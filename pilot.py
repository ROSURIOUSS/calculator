"""Experimental, screen-based Satisfactory desktop pilot.

This script runs on the player's own Windows PC. It does not read or modify save files.
It sends screenshots to a configurable OpenAI-compatible vision endpoint and can optionally
apply a tightly limited keyboard/mouse action to the currently focused game window.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pyautogui
import pygetwindow
import requests
from PIL import Image
import mss


ROOT = Path(__file__).resolve().parent
GOAL_FILE = ROOT / "pilot" / "goal.txt"
DEFAULT_API_BASE = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "qwen2.5vl:7b"
MAX_ACTION_SECONDS = 1.25
MAX_MOUSE_DELTA = 300
ALLOWED_KEYS = {
    "w", "a", "s", "d", "space", "shift", "e", "q", "tab", "r", "c", "v", "x",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "left", "right", "up", "down",
}

SYSTEM_PROMPT = """You are a cautious screen-control agent for the single-player factory game Satisfactory.
The player is already in an existing save. The user's mission is provided in each request.
You see only the current screenshot and a short history; you have no game API and cannot inspect save files.

Safety rules:
- Never dismantle, delete, overwrite, or intentionally damage existing buildings or items.
- Avoid cliffs, jumping into unknown areas, combat, and long blind movement.
- Use only normal gameplay and visible UI. Do not attempt console commands, OS shortcuts, or file actions.
- Take small steps. If you cannot confidently identify the current screen or next safe action, set request_human=true and do nothing.
- Do not claim completion unless a visible in-game message confirms it.
- When a decision could irreversibly spend a rare item or change a large part of the base, request human input.

Return exactly one JSON object with these fields:
{
  "observation": "one short sentence describing what is visible",
  "reason": "brief reason for the next action",
  "keys": [],
  "hold_seconds": 0.0,
  "mouse_dx": 0,
  "mouse_dy": 0,
  "click": "none",
  "task_complete": false,
  "request_human": false
}

Allowed keys: w, a, s, d, space, shift, e, q, tab, r, c, v, x, 1-0, left, right, up, down. The dismantle key is intentionally blocked.
Allowed click values: none, left, right. Use no more than two keys at once. Keep hold_seconds at or below 1.25.
Mouse deltas should be small (within +/-300 pixels). If unsure, return empty keys, zero mouse movement, click none, and request_human=true.
"""


def load_goal() -> str:
    try:
        text = GOAL_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        text = "Safely inspect the current existing save and make cautious progress toward the next visible HUB or Space Elevator milestone. Preserve the base and stop for human input if uncertain."
    return text or "Safely inspect the current existing save. Preserve the base and stop for human input if uncertain."


def active_window_title() -> str:
    try:
        return pygetwindow.getActiveWindowTitle() or ""
    except Exception:
        return ""


def ensure_game_focus(allow_any_window: bool) -> None:
    title = active_window_title()
    if allow_any_window:
        if not title:
            raise RuntimeError("Не удалось определить активное окно. Открой игру и повтори запуск.")
        print(f"Активное окно: {title}")
        return
    if "satisfactory" not in title.lower():
        shown_title = title if title else "(название не определено)"
        raise RuntimeError(
            f"Активное окно — «{shown_title}», а не Satisfactory. "
            "Переключись в игру. Для нестандартного заголовка есть явный флаг --allow-any-window."
        )


def capture_screen(monitor_number: int, max_dimension: int = 1280) -> bytes:
    with mss.mss() as screen:
        if monitor_number < 1 or monitor_number >= len(screen.monitors):
            available = max(0, len(screen.monitors) - 1)
            raise RuntimeError(f"Монитор {monitor_number} не найден. Доступные номера: 1–{available}.")
        frame = screen.grab(screen.monitors[monitor_number])
        image = Image.frombytes("RGB", frame.size, frame.rgb)
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82, optimize=True)
        return buffer.getvalue()


def endpoint_url(base: str) -> str:
    base = base.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def extract_content(response_json: dict[str, Any]) -> str:
    try:
        content = response_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Vision API вернул неожиданный формат ответа.") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "\n".join(part for part in text_parts if part)
    raise RuntimeError("Vision API не вернул текстовое решение.")


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Модель не вернула JSON. В режиме live действие не выполнено.")
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ответ модели содержит некорректный JSON. Действие не выполнено.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Ожидался JSON-объект. Действие не выполнено.")
    return parsed


def call_vision_model(
    image_bytes: bytes,
    goal: str,
    history: list[str],
    *,
    api_base: str,
    model: str,
    api_key: str | None,
    timeout: float,
) -> dict[str, Any]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    history_text = "\n".join(f"- {line}" for line in history[-4:]) or "(пока нет)"
    user_text = (
        f"МИССИЯ ПОЛЬЗОВАТЕЛЯ:\n{goal}\n\n"
        f"КРАТКАЯ ИСТОРИЯ:\n{history_text}\n\n"
        "Оцени только то, что видно на текущем скриншоте. Выбери не более одного короткого, безопасного следующего действия. "
        "Верни JSON по схеме из системного сообщения."
    )
    body = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                ],
            },
        ],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.post(endpoint_url(api_base), headers=headers, json=body, timeout=timeout)
        if response.status_code == 400 and "response_format" in body:
            # Some otherwise compatible local servers do not implement the JSON response hint.
            body.pop("response_format")
            response = requests.post(endpoint_url(api_base), headers=headers, json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Не удалось обратиться к vision API ({api_base}). Проверь, запущена ли модель и верны ли настройки.\n{exc}"
        ) from exc
    if response.status_code >= 400:
        detail = response.text[:800]
        raise RuntimeError(f"Vision API ответил HTTP {response.status_code}: {detail}")
    try:
        response_json = response.json()
    except requests.JSONDecodeError as exc:
        raise RuntimeError("Vision API вернул не JSON.") from exc
    return parse_json_object(extract_content(response_json))


def validate_action(raw: dict[str, Any]) -> dict[str, Any]:
    keys_raw = raw.get("keys", [])
    if not isinstance(keys_raw, list) or len(keys_raw) > 2:
        raise RuntimeError("Небезопасный ответ модели: keys должен содержать не более двух клавиш.")
    keys: list[str] = []
    for key in keys_raw:
        if not isinstance(key, str) or key.lower() not in ALLOWED_KEYS:
            raise RuntimeError(f"Небезопасный ответ модели: клавиша {key!r} запрещена. Действие не выполнено.")
        normalized = key.lower()
        if normalized not in keys:
            keys.append(normalized)

    try:
        hold_seconds = float(raw.get("hold_seconds", 0))
        mouse_dx = int(raw.get("mouse_dx", 0))
        mouse_dy = int(raw.get("mouse_dy", 0))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Ответ модели содержит неверные числовые параметры. Действие не выполнено.") from exc
    if not (0 <= hold_seconds <= MAX_ACTION_SECONDS):
        raise RuntimeError(f"Модель запросила действие дольше {MAX_ACTION_SECONDS} с. Действие не выполнено.")
    if abs(mouse_dx) > MAX_MOUSE_DELTA or abs(mouse_dy) > MAX_MOUSE_DELTA:
        raise RuntimeError(f"Смещение мыши превышает безопасный лимит ±{MAX_MOUSE_DELTA} px. Действие не выполнено.")

    click = raw.get("click", "none")
    if not isinstance(click, str) or click not in {"none", "left", "right"}:
        raise RuntimeError("Недопустимый тип клика. Действие не выполнено.")

    observation = str(raw.get("observation", "Экран получен."))[:350]
    reason = str(raw.get("reason", ""))[:350]
    task_complete = raw.get("task_complete", False) is True
    request_human = raw.get("request_human", False) is True
    return {
        "observation": observation,
        "reason": reason,
        "keys": keys,
        "hold_seconds": hold_seconds,
        "mouse_dx": mouse_dx,
        "mouse_dy": mouse_dy,
        "click": click,
        "task_complete": task_complete,
        "request_human": request_human,
    }


def stop_listener(stop_event: threading.Event) -> Any:
    try:
        from pynput import keyboard
    except Exception as exc:  # pragma: no cover - machine-specific hook
        raise RuntimeError(f"Не удалось включить аварийную клавишу F8/Esc: {exc}") from exc

    def on_press(key: Any) -> None:
        if key in (keyboard.Key.f8, keyboard.Key.esc):
            stop_event.set()

    listener = keyboard.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()
    return listener


def watch_stop_file(stop_event: threading.Event, stop_path: Path) -> None:
    while not stop_event.wait(0.15):
        try:
            if stop_path.is_file():
                stop_event.set()
                return
        except OSError:
            continue


def perform_action(action: dict[str, Any], stop_event: threading.Event) -> None:
    # PyAutoGUI's own failsafe is also enabled: move the mouse to the upper-left corner to abort.
    keys = action["keys"]
    pressed: list[str] = []
    try:
        for key in keys:
            if stop_event.is_set():
                return
            pyautogui.keyDown(key)
            pressed.append(key)
        if action["mouse_dx"] or action["mouse_dy"]:
            move_duration = min(max(action["hold_seconds"], 0.08), 0.25)
            pyautogui.moveRel(action["mouse_dx"], action["mouse_dy"], duration=move_duration)
        remaining = max(0, action["hold_seconds"] - (0.25 if action["mouse_dx"] or action["mouse_dy"] else 0))
        deadline = time.monotonic() + remaining
        while remaining > 0 and not stop_event.is_set():
            time.sleep(min(0.05, remaining))
            remaining = deadline - time.monotonic()
    finally:
        for key in reversed(pressed):
            try:
                pyautogui.keyUp(key)
            except Exception:
                pass
    if not stop_event.is_set() and action["click"] != "none":
        pyautogui.click(button=action["click"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Экспериментальный vision-автопилот Satisfactory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="разрешить ограниченные нажатия клавиш/мыши после подтверждения")
    mode.add_argument("--dry-run", action="store_true", help="только анализировать экран, не отправляя игровые действия (режим по умолчанию)")
    parser.add_argument("--confirmed-live", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--max-steps", type=int, default=10, help="максимальное число циклов (1–500, по умолчанию 10)")
    parser.add_argument("--monitor", type=int, default=1, help="номер монитора для скриншотов, начиная с 1")
    parser.add_argument("--goal", type=str, default=None, help="переопределить миссию из pilot/goal.txt")
    parser.add_argument("--allow-any-window", action="store_true", help="разрешить активное окно, название которого не содержит Satisfactory")
    parser.add_argument("--timeout", type=float, default=90, help="таймаут запроса к vision API в секундах")
    parser.add_argument("--api-base", type=str, default=os.getenv("VISION_API_BASE", DEFAULT_API_BASE), help="OpenAI-compatible API base URL")
    parser.add_argument("--model", type=str, default=os.getenv("VISION_MODEL", DEFAULT_MODEL), help="vision-модель")
    args = parser.parse_args()
    if not 1 <= args.max_steps <= 500:
        parser.error("--max-steps должен быть от 1 до 500")
    if args.timeout <= 0:
        parser.error("--timeout должен быть больше нуля")
    if args.monitor < 1:
        parser.error("--monitor должен быть не меньше 1")
    return args


def main() -> int:
    args = parse_args()
    live = args.live
    goal = args.goal.strip() if args.goal else load_goal()
    if not goal:
        print("Миссия пустая. Укажи --goal или заполни pilot/goal.txt.", file=sys.stderr)
        return 2

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.15

    if live:
        print("\nВНИМАНИЕ: агент сможет нажимать клавиши и мышь в активном окне.")
        print("Сохранись вручную. F8 или Esc остановят цикл; угол экрана тоже является аварийной остановкой.")
        if not args.confirmed_live:
            try:
                confirmation = input('Чтобы продолжить, введи ровно "RUN LIVE": ').strip()
            except (EOFError, KeyboardInterrupt):
                return 130
            if confirmation != "RUN LIVE":
                print("Запуск отменён.")
                return 0
    print("Переключись обратно в Satisfactory. Начало через 5 секунд...")
    for countdown in range(5, 0, -1):
        print(f"  {countdown}…")
        time.sleep(1)

    try:
        ensure_game_focus(args.allow_any_window)
    except RuntimeError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2

    print(f"Режим: {'LIVE' if live else 'DRY-RUN'} | модель: {args.model} | максимум шагов: {args.max_steps}")
    print(f"API: {args.api_base} | миссия: {goal}")
    print("Агент не управляет игрой вне активного окна. Для отмены в консоли нажми Ctrl+C.\n")

    stop_event = threading.Event()
    stop_file = os.getenv("FICSIT_STOP_FILE")
    if stop_file:
        stop_watcher = threading.Thread(target=watch_stop_file, args=(stop_event, Path(stop_file)), daemon=True)
        stop_watcher.start()
    listener = None
    if live:
        try:
            listener = stop_listener(stop_event)
        except RuntimeError as exc:
            print(f"ОШИБКА: {exc}", file=sys.stderr)
            return 2

    history: list[str] = []
    try:
        for step in range(1, args.max_steps + 1):
            if stop_event.is_set():
                print("Получен запрос на остановку (F8/Esc или кнопка программы).")
                break
            try:
                ensure_game_focus(args.allow_any_window)
                screenshot = capture_screen(args.monitor)
                decision_raw = call_vision_model(
                    screenshot,
                    goal,
                    history,
                    api_base=args.api_base,
                    model=args.model,
                    api_key=os.getenv("VISION_API_KEY"),
                    timeout=args.timeout,
                )
                decision = validate_action(decision_raw)
            except pyautogui.FailSafeException:
                print("Аварийная остановка PyAutoGUI: курсор в левом верхнем углу.")
                break
            except (RuntimeError, requests.RequestException) as exc:
                print(f"ОШИБКА: {exc}", file=sys.stderr)
                return 1

            if stop_event.is_set():
                print("Остановка запрошена во время анализа; действие не будет применено.")
                break

            print(f"[{step}/{args.max_steps}] Экран: {decision['observation']}")
            if decision["reason"]:
                print(f"  Решение: {decision['reason']}")
            action_summary = (
                f"клавиши={decision['keys'] or '—'}, hold={decision['hold_seconds']:.2f}s, "
                f"мышь=({decision['mouse_dx']},{decision['mouse_dy']}), клик={decision['click']}"
            )
            print(f"  Действие: {action_summary}")

            history.append(f"Шаг {step}: {decision['observation']} Решение: {decision['reason']} Действие: {action_summary}")
            if decision["request_human"]:
                print("Агент просит вмешательство игрока. Цикл остановлен; действие не применялось.")
                break
            if decision["task_complete"]:
                print("Модель считает миссию выполненной; проверь результат в игре.")
                break

            if live:
                # Re-check foreground immediately before injecting input.
                try:
                    ensure_game_focus(args.allow_any_window)
                    perform_action(decision, stop_event)
                except pyautogui.FailSafeException:
                    print("Аварийная остановка PyAutoGUI: курсор в левом верхнем углу.")
                    break
                except RuntimeError as exc:
                    print(f"Остановка перед вводом: {exc}", file=sys.stderr)
                    break
            else:
                print("  DRY-RUN: игровой ввод не отправлен.")

            if step < args.max_steps and not stop_event.is_set():
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("Остановка: Ctrl+C.")
    finally:
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass
    print("Автопилот завершил работу.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
