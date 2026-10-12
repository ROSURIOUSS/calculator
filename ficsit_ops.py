"""Windows desktop control panel for the external Satisfactory helper.

Packaged with PyInstaller, this opens as a standalone GUI. The worker mode runs the
screen-based pilot in a child process; no game mod or save-file access is used.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

APP_NAME = "FICSIT Ops"
DEFAULT_API_BASE = os.getenv("VISION_API_BASE", "http://127.0.0.1:11434/v1")
DEFAULT_MODEL = os.getenv("VISION_MODEL", "qwen2.5vl:7b")


def resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative_path


def user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    folder = base / "FicsitOps"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def run_worker() -> int:
    """Internal mode used when the packaged application starts its agent worker."""
    args = sys.argv[1:]
    try:
        args.remove("--worker")
    except ValueError:
        pass
    log_path = Path(os.getenv("FICSIT_LOG_FILE", user_data_dir() / "agent.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = log_handle
    sys.stderr = log_handle
    sys.argv = [str(Path(__file__).resolve().parent / "pilot.py"), *args]
    from pilot import main as pilot_main

    return pilot_main()


class FicsitOpsApp:
    BG = "#0b100e"
    PANEL = "#131a16"
    PANEL_DARK = "#101713"
    BORDER = "#2a362e"
    TEXT = "#edf3ee"
    MUTED = "#a0aca3"
    GREEN = "#a4ff5f"
    AMBER = "#f3c66a"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config_dir = user_data_dir()
        self.settings_file = self.config_dir / "settings.json"
        self.log_file = self.config_dir / "agent.log"
        self.stop_file = self.config_dir / "stop.request"
        self.settings = self._load_settings()
        self.process: subprocess.Popen[bytes] | None = None
        self.log_offset = 0
        self.close_when_stopped = False
        self.form_widgets: list[tk.Widget] = []

        root.title(f"{APP_NAME} — внешний помощник")
        root.geometry("850x820")
        root.minsize(680, 650)
        root.configure(bg=self.BG)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._configure_styles()
        self._build_ui()
        self._load_form_values()
        self._update_mode_label()
        self._poll_worker()

    def _load_settings(self) -> dict[str, Any]:
        try:
            return json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_settings(self) -> None:
        data = {
            "api_base": self.api_base_var.get().strip(),
            "model": self.model_var.get().strip(),
            "max_steps": self.max_steps_var.get().strip(),
            "watch_user_input": self.watch_user_input_var.get(),
            "goal": self.goal_text.get("1.0", "end-1c").strip(),
        }
        try:
            self.settings_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self._append_log(f"Не удалось сохранить настройки: {exc}\n")

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=self.PANEL, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=self.BG, foreground=self.MUTED, font=("Segoe UI", 9))
        style.configure("PanelMuted.TLabel", background=self.PANEL, foreground=self.MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI", 20, "bold"))
        style.configure("Brand.TLabel", background=self.BG, foreground=self.GREEN, font=("Segoe UI", 10, "bold"))
        style.configure("Section.TLabel", background=self.PANEL, foreground=self.GREEN, font=("Segoe UI", 10, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=(11, 8))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 9), background=self.GREEN, foreground="#14200f")
        style.map("Accent.TButton", background=[("active", "#b5ff7c"), ("disabled", "#53604f")], foreground=[("disabled", "#c1c9bf")])
        style.configure("Stop.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 9), background="#4b2823", foreground="#ffd7ce")
        style.map("Stop.TButton", background=[("active", "#68352d"), ("disabled", "#35211e")])
        style.configure("TRadiobutton", background=self.PANEL, foreground=self.TEXT, font=("Segoe UI", 10))
        style.map("TRadiobutton", background=[("active", self.PANEL)], foreground=[("active", self.GREEN)])
        style.configure("TCheckbutton", background=self.PANEL, foreground=self.TEXT, font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", self.PANEL)], foreground=[("active", self.GREEN), ("disabled", self.MUTED)])
        style.configure("TEntry", fieldbackground=self.PANEL_DARK, foreground=self.TEXT, insertcolor=self.TEXT, padding=7)
        style.configure("TSpinbox", fieldbackground=self.PANEL_DARK, foreground=self.TEXT, padding=6)

    def _panel(self, parent: tk.Widget, *, padding: int = 16) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=padding)
        frame.pack(fill="x", pady=(0, 10))
        return frame

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(20, 17, 20, 15))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="FICSIT OPS", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(header, text="Satisfactory — внешний помощник", style="Title.TLabel").pack(anchor="w", pady=(3, 2))
        ttk.Label(header, text="Отдельная Windows-программа • не модифицирует игру и не меняет сохранения", style="Muted.TLabel").pack(anchor="w")

        settings = self._panel(outer)
        ttk.Label(settings, text="VISION-МОДЕЛЬ", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.api_base_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self._field(settings, "API endpoint", self.api_base_var, row=1, column=0, width=50)
        self._field(settings, "Модель", self.model_var, row=1, column=1, width=26)
        self._field(settings, "API key (необязательно)", self.api_key_var, row=2, column=0, width=50, show="•", allow_copy=False, paste_button=True)
        ttk.Label(settings, text="Вставка: Ctrl+V или кнопка «Вставить». API key не сохраняется в настройках.", style="PanelMuted.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 3))
        ttk.Label(settings, text="Для Gemini нужны ключ из AI Studio и точный API model ID; «Авто / Gemini 3 models» — не ID модели. Удалённый API получит скриншоты игры.", style="PanelMuted.TLabel", wraplength=740).grid(row=4, column=0, columnspan=2, sticky="w")
        settings.columnconfigure(0, weight=3)
        settings.columnconfigure(1, weight=2)

        mission_panel = self._panel(outer)
        mission_header = ttk.Frame(mission_panel, style="Panel.TFrame")
        mission_header.pack(fill="x")
        ttk.Label(mission_header, text="МИССИЯ", style="Section.TLabel").pack(side="left")
        ttk.Label(mission_header, text="Можно вставить план из калькулятора", style="PanelMuted.TLabel").pack(side="right")
        self.goal_text = tk.Text(
            mission_panel, height=5, wrap="word", undo=True,
            bg=self.PANEL_DARK, fg=self.TEXT, insertbackground=self.TEXT,
            selectbackground="#456238", relief="flat", borderwidth=1,
            highlightthickness=1, highlightbackground=self.BORDER, highlightcolor=self.GREEN,
            font=("Segoe UI", 10), padx=9, pady=8,
        )
        self.goal_text.pack(fill="x", pady=(9, 0))
        self.form_widgets.append(self.goal_text)
        self._attach_clipboard(self.goal_text, allow_copy=True)

        options = self._panel(outer)
        ttk.Label(options, text="РЕЖИМ РАБОТЫ", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 9))
        self.mode_var = tk.StringVar(value="dry-run")
        mode_row = ttk.Frame(options, style="Panel.TFrame")
        mode_row.grid(row=1, column=0, sticky="w")
        self.mode_buttons = [
            ttk.Radiobutton(mode_row, text="Проверка — только анализ экрана", variable=self.mode_var, value="dry-run", command=self._update_mode_label),
            ttk.Radiobutton(mode_row, text="Управление клавишами и мышью", variable=self.mode_var, value="live", command=self._update_mode_label),
        ]
        self.mode_buttons[0].pack(side="left", padx=(0, 18))
        self.mode_buttons[1].pack(side="left")

        steps_row = ttk.Frame(options, style="Panel.TFrame")
        steps_row.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(steps_row, text="Лимит циклов", style="PanelMuted.TLabel").pack(side="left", padx=(0, 8))
        self.max_steps_var = tk.StringVar(value="10")
        self.max_steps_spin = ttk.Spinbox(steps_row, from_=1, to=500, increment=1, width=6, textvariable=self.max_steps_var)
        self.max_steps_spin.pack(side="left")
        self.form_widgets.append(self.max_steps_spin)
        self.form_widgets.extend(self.mode_buttons)
        self.watch_user_input_var = tk.BooleanVar(value=False)
        self.watch_user_input_check = ttk.Checkbutton(
            options,
            text="Передавать vision-модели мои клавиши и клики (только при активной Satisfactory)",
            variable=self.watch_user_input_var,
        )
        self.watch_user_input_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.form_widgets.append(self.watch_user_input_check)
        ttk.Label(
            options,
            text="События не записываются в журнал. Отключай опцию перед вводом в игровой чат или секретов.",
            style="PanelMuted.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(3, 0))
        options.columnconfigure(0, weight=1)
        options.columnconfigure(1, weight=0)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(0, 9))
        self.start_button = ttk.Button(buttons, text="Запустить проверку", style="Accent.TButton", command=self._start_worker)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="Остановить", style="Stop.TButton", command=self._request_stop, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        self.planner_button = ttk.Button(buttons, text="Открыть планировщик фабрики", command=self._open_planner)
        self.planner_button.pack(side="right")

        status_panel = ttk.Frame(outer, style="Panel.TFrame", padding=(12, 9))
        status_panel.pack(fill="x", pady=(0, 8))
        self.status_dot = tk.Canvas(status_panel, width=12, height=12, bg=self.PANEL, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 8))
        self.status_dot.create_oval(2, 2, 10, 10, fill="#718078", outline="")
        self.status_var = tk.StringVar(value="Готово. Открой игру на нужном сохранении.")
        self.status_label = ttk.Label(status_panel, textvariable=self.status_var, style="Panel.TLabel")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.status_panel = status_panel

        log_panel = ttk.Frame(outer, style="Panel.TFrame", padding=12)
        log_panel.pack(fill="both", expand=True)
        ttk.Label(log_panel, text="ЖУРНАЛ РАБОТЫ", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        log_frame = tk.Frame(log_panel, bg=self.PANEL_DARK, highlightbackground=self.BORDER, highlightthickness=1)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            log_frame, height=7, wrap="word", state="disabled", bg=self.PANEL_DARK,
            fg="#d0d9d1", insertbackground=self.TEXT, relief="flat", borderwidth=0,
            font=("Consolas", 9), padx=9, pady=8,
        )
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        ttk.Label(outer, text="F8 / Esc — аварийная остановка live-режима. В любом режиме используй кнопку «Остановить»; при live оставайся рядом.", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

    def _field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, *, row: int, column: int, width: int, show: str | None = None, allow_copy: bool = True, paste_button: bool = False) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0), pady=(0, 8))
        ttk.Label(frame, text=label, style="PanelMuted.TLabel").pack(anchor="w", pady=(0, 5))
        entry_row = ttk.Frame(frame, style="Panel.TFrame")
        entry_row.pack(fill="x")
        entry = ttk.Entry(entry_row, textvariable=variable, width=width, show=show or "")
        entry.pack(side="left", fill="x", expand=True)
        if paste_button:
            ttk.Button(entry_row, text="Вставить", command=lambda: self._paste_clipboard(entry)).pack(side="left", padx=(6, 0))
        self.form_widgets.append(entry)
        self._attach_clipboard(entry, allow_copy=allow_copy)

    def _attach_clipboard(self, widget: tk.Widget, *, allow_copy: bool = True) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Вставить", command=lambda: self._paste_clipboard(widget))
        if allow_copy:
            menu.add_command(label="Копировать", command=lambda: self._copy_clipboard(widget))
        menu.add_command(label="Выделить всё", command=lambda: self._select_all(widget))

        def show_menu(event: tk.Event) -> str:
            widget.focus_set()
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return "break"

        def paste_key(event: tk.Event) -> str:
            self._paste_clipboard(widget)
            return "break"

        widget.bind("<Button-3>", show_menu, add="+")
        widget.bind("<Control-v>", paste_key, add="+")
        widget.bind("<Control-V>", paste_key, add="+")
        widget.bind("<Shift-Insert>", paste_key, add="+")
        if not allow_copy:
            widget.bind("<Control-c>", lambda _event: "break", add="+")
            widget.bind("<Control-C>", lambda _event: "break", add="+")

    def _paste_clipboard(self, widget: tk.Widget) -> None:
        try:
            text = widget.clipboard_get()
        except tk.TclError:
            self.status_var.set("Буфер обмена пуст или недоступен.")
            return
        if isinstance(widget, tk.Text):
            if widget.cget("state") == "disabled":
                return
            try:
                widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            widget.insert("insert", text)
        else:
            try:
                if widget.cget("state") in {"disabled", "readonly"}:
                    return
            except tk.TclError:
                pass
            try:
                widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            widget.insert("insert", text.replace("\r", "").replace("\n", ""))
        widget.focus_set()

    def _copy_clipboard(self, widget: tk.Widget) -> None:
        try:
            if isinstance(widget, tk.Text):
                text = widget.get("sel.first", "sel.last")
            else:
                text = widget.selection_get()
        except tk.TclError:
            return
        widget.clipboard_clear()
        widget.clipboard_append(text)

    def _select_all(self, widget: tk.Widget) -> None:
        widget.focus_set()
        if isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end-1c")
        else:
            widget.selection_range(0, "end")
            widget.icursor("end")

    def _load_form_values(self) -> None:
        default_goal_path = resource_path("pilot/goal.txt")
        try:
            default_goal = default_goal_path.read_text(encoding="utf-8").strip()
        except OSError:
            default_goal = "Осмотри текущее сохранение Satisfactory и действуй осторожно. Не разбирай существующие здания; если следующий шаг неочевиден, остановись и попроси игрока вмешаться."
        self.api_base_var.set(str(self.settings.get("api_base", DEFAULT_API_BASE)))
        self.model_var.set(str(self.settings.get("model", DEFAULT_MODEL)))
        self.api_key_var.set(os.getenv("VISION_API_KEY", ""))
        self.max_steps_var.set(str(self.settings.get("max_steps", "10")))
        self.watch_user_input_var.set(bool(self.settings.get("watch_user_input", False)))
        self.goal_text.insert("1.0", str(self.settings.get("goal", default_goal)))

    def _update_mode_label(self) -> None:
        live = self.mode_var.get() == "live"
        self.start_button.configure(text="Запустить управление" if live else "Запустить проверку")

    def _worker_command(self, worker_args: list[str]) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--worker", *worker_args]
        return [sys.executable, str(Path(__file__).resolve()), "--worker", *worker_args]

    def _start_worker(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        goal = self.goal_text.get("1.0", "end-1c").strip()
        if not goal:
            messagebox.showwarning(APP_NAME, "Сначала укажи цель для автопилота.", parent=self.root)
            self.goal_text.focus_set()
            return
        try:
            max_steps = int(self.max_steps_var.get())
            if not 1 <= max_steps <= 500:
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_NAME, "Лимит циклов должен быть числом от 1 до 500.", parent=self.root)
            return

        live = self.mode_var.get() == "live"
        if live:
            confirmation_text = "Автопилот сможет нажимать клавиши и мышь в активном окне игры.\n\n"
            if self.watch_user_input_var.get():
                confirmation_text += "События клавиатуры и кнопок мыши в игре будут передаваться выбранной vision-модели для контекста.\n\n"
            confirmation_text += "Сначала сохранись, открой Satisfactory и оставайся рядом. Продолжить?"
            confirmed = messagebox.askyesno(
                "Подтверди управление",
                confirmation_text,
                icon="warning", parent=self.root,
            )
            if not confirmed:
                return

        self._save_settings()
        self.log_file.write_text("", encoding="utf-8")
        self.log_offset = 0
        try:
            self.stop_file.unlink(missing_ok=True)
        except OSError:
            pass
        worker_args = ["--live" if live else "--dry-run", "--max-steps", str(max_steps), "--goal", goal]
        if self.watch_user_input_var.get():
            worker_args.append("--watch-user-input")
        worker_args += ["--api-base", self.api_base_var.get().strip() or DEFAULT_API_BASE]
        worker_args += ["--model", self.model_var.get().strip() or DEFAULT_MODEL]
        if live:
            worker_args.append("--confirmed-live")
        env = os.environ.copy()
        env["VISION_API_BASE"] = self.api_base_var.get().strip() or DEFAULT_API_BASE
        env["VISION_MODEL"] = self.model_var.get().strip() or DEFAULT_MODEL
        if self.api_key_var.get().strip():
            env["VISION_API_KEY"] = self.api_key_var.get().strip()
        else:
            env.pop("VISION_API_KEY", None)
        env["FICSIT_LOG_FILE"] = str(self.log_file)
        env["FICSIT_STOP_FILE"] = str(self.stop_file)
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = subprocess.Popen(
                self._worker_command(worker_args),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env, creationflags=create_no_window,
            )
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Не удалось запустить автопилот:\n{exc}", parent=self.root)
            self.process = None
            return

        status = "Запущена проверка экрана…" if not live else "Live-режим включён — управление активно."
        if self.watch_user_input_var.get():
            status += " Сбор клавиш/кликов активен только в игре."
        self.status_var.set(status)
        self._set_status_color(self.GREEN if live else self.AMBER)
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.mode_widgets_state("disabled")
        self.root.after(150, self._poll_worker)

    def mode_widgets_state(self, state: str) -> None:
        for widget in self.form_widgets:
            widget.configure(state=state)

    def _request_stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        try:
            self.stop_file.touch()
        except OSError as exc:
            self._append_log(f"Не удалось отправить запрос остановки: {exc}\n")
        self.status_var.set("Остановка после текущего запроса к модели…")
        self._set_status_color(self.AMBER)
        self.stop_button.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 500:
            self.log_text.delete("1.0", f"{line_count - 400}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _read_worker_log(self) -> None:
        try:
            with self.log_file.open("r", encoding="utf-8", errors="replace") as log:
                log.seek(self.log_offset)
                new_text = log.read()
                self.log_offset = log.tell()
        except OSError:
            return
        if new_text:
            self._append_log(new_text)

    def _poll_worker(self) -> None:
        self._read_worker_log()
        process = self.process
        if process is not None and process.poll() is None:
            self.root.after(300, self._poll_worker)
            return
        if process is not None:
            code = process.returncode
            self.status_var.set("Работа завершена." if code == 0 else f"Автопилот завершился с кодом {code}. Смотри журнал.")
            self._set_status_color(self.GREEN if code == 0 else self.AMBER)
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.mode_widgets_state("normal")
            self.process = None
        if self.close_when_stopped:
            self.root.destroy()

    def _set_status_color(self, color: str) -> None:
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 2, 10, 10, fill=color, outline="")

    def _open_planner(self) -> None:
        target_dir = self.config_dir / "planner"
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in ("index.html", "app.js", "styles.css"):
            source = resource_path(name)
            if not source.is_file():
                messagebox.showerror(APP_NAME, f"Файл планировщика не найден: {source}", parent=self.root)
                return
            try:
                shutil.copy2(source, target_dir / name)
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"Не удалось подготовить планировщик:\n{exc}", parent=self.root)
                return
        webbrowser.open((target_dir / "index.html").as_uri())

    def _on_close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            close = messagebox.askyesno(
                APP_NAME,
                "Автопилот ещё работает. Запросить остановку и закрыть окно после текущего запроса к модели?",
                icon="warning", parent=self.root,
            )
            if not close:
                return
            self.close_when_stopped = True
            self._request_stop()
            return
        self._save_settings()
        self.root.destroy()


def main() -> int:
    if "--worker" in sys.argv[1:]:
        return run_worker()
    root = tk.Tk()
    FicsitOpsApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
