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
from collections import deque
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
You see only the current screenshot, a short action history, and optionally recent physical inputs from the player while Satisfactory was focused. You have no game API and cannot inspect save files. Treat player inputs as context, not as instructions to repeat blindly.

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


def is_satisfactory_window_title(title: str) -> bool:
    normalized = title.lower()
    return "satisfactory" in normalized and "ficsit ops" not in normalized


def ensure_game_focus(allow_any_window: bool) -> None:
    title = active_window_title()
    if allow_any_window:
        if not title:
            raise RuntimeError("Не удалось определить активное окно. Открой игру и повтори запуск.")
        print(f"Активное окно: {title}")
        return
    if not is_satisfactory_window_title(title):
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
    user_inputs: list[str] | None = None,
    api_base: str,
    model: str,
    api_key: str | None,
    timeout: float,
) -> dict[str, Any]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    history_text = "\n".join(f"- {line}" for line in history[-4:]) or "(пока нет)"
    input_text = ", ".join(user_inputs) if user_inputs else "(нажатий не было/сбор выключен)"
    user_text = (
        f"МИССИЯ ПОЛЬЗОВАТЕЛЯ:\n{goal}\n\n"
        f"КРАТКАЯ ИСТОРИЯ:\n{history_text}\n\n"
        f"ПОСЛЕДНИЕ НАЖАТИЯ ИГРОКА В АКТИВНОМ ОКНЕ ИГРЫ (только контекст):\n{input_text}\n\n"
        "Оцени только текущий скриншот и последние нажатия. Выбери не более одного короткого, безопасного следующего действия. "
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

    def post_with_retry(payload: dict[str, Any]) -> requests.Response:
        url = endpoint_url(api_base)
        transient_statuses = {429, 500, 502, 503, 504}
        last_exception: requests.RequestException | None = None
        for attempt in range(3):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            except requests.RequestException as exc:
                last_exception = exc
                if attempt == 2:
                    break
                delay = 2 ** attempt
                print(f"Сеть/API временно недоступны; повтор через {delay} с.")
                time.sleep(delay)
                continue
            if response.status_code not in transient_statuses or attempt == 2:
                return response
            try:
                delay = min(10.0, max(1.0, float(response.headers.get("Retry-After", 2 ** attempt))))
            except (TypeError, ValueError):
                delay = float(2 ** attempt)
            print(f"Vision API временно перегружен (HTTP {response.status_code}); повтор через {delay:g} с.")
            time.sleep(delay)
        if last_exception is not None:
            raise RuntimeError(
                f"Не удалось обратиться к vision API ({api_base}) после повторов.\n{last_exception}"
            ) from last_exception
        raise RuntimeError("Vision API не ответил после повторных попыток.")

    response = post_with_retry(body)
    if response.status_code == 400 and "response_format" in body:
        # Some otherwise compatible endpoints do not implement the JSON response hint.
        body.pop("response_format")
        response = post_with_retry(body)
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


class GameInputCapture:
    """Observe physical keyboard/mouse input only while Satisfactory is foreground."""

    def __init__(
        self,
        stop_event: threading.Event,
        *,
        enabled: bool,
        emergency_stop: bool,
    ) -> None:
        self.stop_event = stop_event
        self.enabled = enabled
        self.emergency_stop = emergency_stop
        self.events: deque[str] = deque()
        self.pressed: set[Any] = set()
        self.lock = threading.Lock()
        self.keyboard_listener: Any = None
        self.mouse_listener: Any = None
        try:
            from pynput import keyboard, mouse
        except Exception as exc:  # pragma: no cover - machine-specific hook
            raise RuntimeError(f"Не удалось включить монитор клавиш/аварийную остановку: {exc}") from exc
        self.keyboard = keyboard
        self.mouse = mouse

    def _target_is_active(self) -> bool:
        return is_satisfactory_window_title(active_window_title())

    def _key_label(self, key: Any) -> str:
        special = {
            self.keyboard.Key.space: "Space",
            self.keyboard.Key.enter: "Enter",
            self.keyboard.Key.esc: "Esc",
            self.keyboard.Key.tab: "Tab",
            self.keyboard.Key.shift: "Shift",
            self.keyboard.Key.shift_l: "Left Shift",
            self.keyboard.Key.shift_r: "Right Shift",
            self.keyboard.Key.ctrl: "Ctrl",
            self.keyboard.Key.ctrl_l: "Left Ctrl",
            self.keyboard.Key.ctrl_r: "Right Ctrl",
            self.keyboard.Key.alt: "Alt",
            self.keyboard.Key.alt_l: "Left Alt",
            self.keyboard.Key.alt_r: "Right Alt",
            self.keyboard.Key.backspace: "Backspace",
            self.keyboard.Key.delete: "Delete",
            self.keyboard.Key.up: "Up",
            self.keyboard.Key.down: "Down",
            self.keyboard.Key.left: "Left",
            self.keyboard.Key.right: "Right",
            self.keyboard.Key.f8: "F8",
        }
        if key in special:
            return special[key]
        char = getattr(key, "char", None)
        if char:
            return char.upper()
        return str(key).replace("Key.", "").upper()

    def _record(self, label: str) -> None:
        with self.lock:
            self.events.append(label)

    def _keyboard_event_filter(self, _message: Any, data: Any) -> bool:
        # Ignore SendInput/PyAutoGUI-generated events so only physical player input is recorded.
        return not bool(getattr(data, "flags", 0) & 0x12)  # LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED

    def _mouse_event_filter(self, _message: Any, data: Any) -> bool:
        return not bool(getattr(data, "flags", 0) & 0x03)  # LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED

    def start(self) -> None:
        keyboard_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            keyboard_kwargs["win32_event_filter"] = self._keyboard_event_filter
        self.keyboard_listener = self.keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            **keyboard_kwargs,
        )
        self.keyboard_listener.daemon = True
        self.keyboard_listener.start()
        if self.enabled:
            mouse_kwargs: dict[str, Any] = {}
            if os.name == "nt":
                mouse_kwargs["win32_event_filter"] = self._mouse_event_filter
            self.mouse_listener = self.mouse.Listener(on_click=self._on_click, **mouse_kwargs)
            self.mouse_listener.daemon = True
            self.mouse_listener.start()

    def _on_press(self, key: Any) -> None:
        if self.emergency_stop and key in (self.keyboard.Key.f8, self.keyboard.Key.esc):
            self.stop_event.set()
            return
        if not self.enabled or not self._target_is_active():
            return
        with self.lock:
            if key in self.pressed:
                return
            self.pressed.add(key)
        self._record(f"Key {self._key_label(key)}")

    def _on_release(self, key: Any) -> None:
        with self.lock:
            self.pressed.discard(key)

    def _on_click(self, _x: int, _y: int, button: Any, pressed: bool) -> None:
        if pressed and self.enabled and self._target_is_active():
            self._record(f"Mouse {getattr(button, 'name', str(button))}")

    def drain(self) -> list[str]:
        with self.lock:
            events = list(self.events)
            self.events.clear()
        return events

    def stop(self) -> None:
        for listener in (self.keyboard_listener, self.mouse_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass


def watch_stop_file(stop_event: threading.Event, stop_path: Path) -> None:
    while not stop_event.wait(0.15):
        try:
            if stop_path.is_file():
                stop_event.set()
                return
        except OSError:
            continue


_WIN32_INPUT_CACHE: tuple[Any, ...] | None = None


def _win32_input_api() -> tuple[Any, ...]:
    global _WIN32_INPUT_CACHE
    if _WIN32_INPUT_CACHE is not None:
        return _WIN32_INPUT_CACHE
    if os.name != "nt":
        raise RuntimeError("Низкоуровневый игровой ввод доступен только в Windows.")

    import ctypes
    from ctypes import wintypes

    pointer_size = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", pointer_size),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD), ("dwExtraInfo", pointer_size),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    _WIN32_INPUT_CACHE = (ctypes, wintypes, user32, INPUT, KEYBDINPUT, MOUSEINPUT)
    return _WIN32_INPUT_CACHE


def _send_win32_inputs(inputs: list[Any]) -> None:
    ctypes, _wintypes, user32, input_type, _key_type, _mouse_type = _win32_input_api()
    array_type = input_type * len(inputs)
    array = array_type(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(input_type))
    if sent != len(inputs):
        error = ctypes.get_last_error()
        detail = ctypes.FormatError(error).strip() if error else "Windows отклонила ввод"
        raise RuntimeError(
            f"Windows не передала ввод в игру ({detail}). Если Satisfactory запущена от администратора, "
            "запусти FicsitOps на том же уровне прав."
        )


def _virtual_key_code(key: str) -> int:
    named = {
        "space": 0x20, "shift": 0xA0, "tab": 0x09,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    }
    if key in named:
        return named[key]
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    raise RuntimeError(f"Неизвестная Windows-клавиша: {key}")


def _send_game_key(key: str, pressed: bool) -> None:
    if os.name != "nt":
        (pyautogui.keyDown if pressed else pyautogui.keyUp)(key)
        return
    ctypes, wintypes, user32, input_type, key_type, _mouse_type = _win32_input_api()
    vk = _virtual_key_code(key)
    scan = user32.MapVirtualKeyW(vk, 0)
    if not scan:
        raise RuntimeError(f"Не удалось определить scan code для клавиши {key}.")
    flags = 0x0008  # KEYEVENTF_SCANCODE
    if not pressed:
        flags |= 0x0002  # KEYEVENTF_KEYUP
    if key in {"left", "right", "up", "down"}:
        flags |= 0x0001  # KEYEVENTF_EXTENDEDKEY
    event = input_type()
    event.type = 1  # INPUT_KEYBOARD
    event.ki = key_type(0, scan, flags, 0, 0)
    _send_win32_inputs([event])


def _send_game_mouse_move(dx: int, dy: int) -> None:
    if os.name != "nt":
        pyautogui.moveRel(dx, dy, duration=0.1)
        return
    _ctypes, _wintypes, _user32, input_type, _key_type, mouse_type = _win32_input_api()
    event = input_type()
    event.type = 0  # INPUT_MOUSE
    event.mi = mouse_type(dx, dy, 0, 0x0001, 0, 0)  # MOUSEEVENTF_MOVE, relative
    _send_win32_inputs([event])


def _send_game_click(button: str) -> None:
    if os.name != "nt":
        pyautogui.click(button=button)
        return
    down_up = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010)}[button]
    _ctypes, _wintypes, _user32, input_type, _key_type, mouse_type = _win32_input_api()
    events = []
    for flags in down_up:
        event = input_type()
        event.type = 0
        event.mi = mouse_type(0, 0, 0, flags, 0, 0)
        events.append(event)
    _send_win32_inputs(events)


def _check_mouse_failsafe() -> None:
    try:
        x, y = pyautogui.position()
    except pyautogui.FailSafeException:
        raise
    except Exception:
        return
    if x <= 1 and y <= 1:
        raise pyautogui.FailSafeException("Cursor reached the upper-left corner.")


def _ensure_action_window_active(allow_any_window: bool) -> None:
    title = active_window_title()
    if allow_any_window and title:
        return
    if not allow_any_window and is_satisfactory_window_title(title):
        return
    shown_title = title or "(название не определено)"
    raise RuntimeError(f"Игровое окно потеряло фокус (активно: «{shown_title}»); действие отменено.")


def perform_action(
    action: dict[str, Any],
    stop_event: threading.Event,
    allow_any_window: bool = False,
) -> None:
    keys = action["keys"]
    pressed: list[str] = []
    try:
        for key in keys:
            if stop_event.is_set():
                return
            _ensure_action_window_active(allow_any_window)
            _check_mouse_failsafe()
            _send_game_key(key, True)
            pressed.append(key)
        if action["mouse_dx"] or action["mouse_dy"]:
            _ensure_action_window_active(allow_any_window)
            _check_mouse_failsafe()
            _send_game_mouse_move(action["mouse_dx"], action["mouse_dy"])
        hold_seconds = max(action["hold_seconds"], 0.08 if keys else 0.0)
        deadline = time.monotonic() + hold_seconds
        while time.monotonic() < deadline and not stop_event.is_set():
            _ensure_action_window_active(allow_any_window)
            _check_mouse_failsafe()
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    finally:
        for key in reversed(pressed):
            try:
                _send_game_key(key, False)
            except Exception:
                pass
    if not stop_event.is_set() and action["click"] != "none":
        _ensure_action_window_active(allow_any_window)
        _check_mouse_failsafe()
        _send_game_click(action["click"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Экспериментальный vision-автопилот Satisfactory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="разрешить ограниченные нажатия клавиш/мыши после подтверждения")
    mode.add_argument("--dry-run", action="store_true", help="только анализировать экран, не отправляя игровые действия (режим по умолчанию)")
    parser.add_argument("--confirmed-live", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--watch-user-input", action="store_true", help="передавать модели последние нажатия клавиш/клики игрока в окне игры")
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
    if args.watch_user_input:
        print("Сбор включён: события клавиш и кликов передаются vision-модели только при активном окне Satisfactory.")
    print("Агент не управляет игрой вне активного окна. Для отмены в консоли нажми Ctrl+C.\n")

    stop_event = threading.Event()
    stop_file = os.getenv("FICSIT_STOP_FILE")
    if stop_file:
        stop_watcher = threading.Thread(target=watch_stop_file, args=(stop_event, Path(stop_file)), daemon=True)
        stop_watcher.start()
    input_capture: GameInputCapture | None = None
    if live or args.watch_user_input:
        try:
            input_capture = GameInputCapture(
                stop_event,
                enabled=args.watch_user_input,
                emergency_stop=live,
            )
            input_capture.start()
        except Exception as exc:
            if input_capture is not None:
                input_capture.stop()
            print(f"ОШИБКА: не удалось включить монитор ввода/аварийную остановку: {exc}", file=sys.stderr)
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
                user_inputs = input_capture.drain() if input_capture and args.watch_user_input else []
                if user_inputs:
                    print(f"  Контекст игрока: модели передаётся {len(user_inputs)} событий клавиатуры/мыши.")
                decision_raw = call_vision_model(
                    screenshot,
                    goal,
                    history,
                    user_inputs=user_inputs,
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
                    perform_action(decision, stop_event, args.allow_any_window)
                    if not stop_event.is_set() and (
                        decision["keys"] or decision["mouse_dx"] or decision["mouse_dy"] or decision["click"] != "none"
                    ):
                        backend = "Windows SendInput" if os.name == "nt" else "PyAutoGUI"
                        print(f"  Ввод отправлен через {backend}.")
                    elif not stop_event.is_set():
                        print("  Игровой ввод не запрошен моделью.")
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
        if input_capture is not None:
            input_capture.stop()
    print("Автопилот завершил работу.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
