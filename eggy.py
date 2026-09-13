"""Eggy - a simple Windows countdown timer.

Type a duration (e.g. "10s", "5m30s", "1 hour 12 m") and press Enter.
The window counts down and plays sounds/default.wav when time is up.
"""

import json
import math
import os
import re
import time
import tkinter as tk
from pathlib import Path
import winsound

APP_TITLE = "Eggy"
SOUND_FILE = Path(__file__).resolve().parent / "sounds" / "default.wav"
ICON_FILE = Path(__file__).resolve().parent / "eggy.ico"


def settings_path():
    """Per-user settings file: %APPDATA%\\Eggy\\settings.json."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / APP_TITLE / "settings.json"


class Settings:
    """Last-used timer text, persisted so re-running is just Enter."""

    def __init__(self):
        self.last_timer = ""
        try:
            data = json.loads(settings_path().read_text(encoding="utf-8"))
            if isinstance(data.get("last_timer"), str):
                self.last_timer = data["last_timer"]
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            path = settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"last_timer": self.last_timer}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass


# Input mappings: anything the user might type for a unit -> canonical unit.
# Edit this table to accept additional spellings.
UNIT_ALIASES = {
    "s": "seconds", "sec": "seconds", "secs": "seconds",
    "second": "seconds", "seconds": "seconds",
    "m": "minutes", "min": "minutes", "mins": "minutes", "mn": "minutes",
    "mns": "minutes", "minute": "minutes", "minutes": "minutes",
    "h": "hours", "hr": "hours", "hrs": "hours",
    "hour": "hours", "hours": "hours",
}

UNIT_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600}
UNIT_LETTERS = {"seconds": "s", "minutes": "m", "hours": "h"}

# A number, optionally followed by a run of letters (unit), anywhere in the
# string; tokens may be separated by whitespace only.
_TOKEN_RE = re.compile(r"(\d+)\s*([A-Za-z]*)")
_UNIT_ORDER = ["seconds", "minutes", "hours"]


def parse_duration(text):
    """Parse user input into (total_seconds, largest_unit).

    Returns None if the input is not a valid duration. A bare number with no
    unit counts as seconds.
    """
    total = 0
    largest = None
    pos = 0
    matched = False
    for match in _TOKEN_RE.finditer(text):
        if text[pos:match.start()].strip():
            return None  # junk between tokens
        pos = match.end()
        matched = True
        number = int(match.group(1))
        word = match.group(2).lower()
        if word:
            unit = UNIT_ALIASES.get(word)
            if unit is None:
                return None  # unknown unit letters
        else:
            unit = "seconds"
        total += number * UNIT_SECONDS[unit]
        if largest is None or _UNIT_ORDER.index(unit) > _UNIT_ORDER.index(largest):
            largest = unit
    if not matched or text[pos:].strip():
        return None
    return total, largest


def format_remaining(seconds, largest_unit):
    """Format remaining seconds for display, e.g. '1 h 11 m 59 s'.

    Only shows units down to the largest unit the user entered.
    """
    parts = []
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    values = {"hours": hours, "minutes": minutes, "seconds": secs}
    for unit in reversed(_UNIT_ORDER):
        if _UNIT_ORDER.index(unit) > _UNIT_ORDER.index(largest_unit):
            continue
        parts.append(f"{values[unit]} {UNIT_LETTERS[unit]}")
    return " ".join(parts)


class EggyApp:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        try:
            root.iconbitmap(str(ICON_FILE))
        except tk.TclError:
            pass  # missing or invalid icon: keep the default
        root.configure(bg="#6f6f6f")
        root.geometry("440x220")
        root.minsize(300, 140)

        self.entry = tk.Entry(
            root,
            font=("Segoe UI", 32, "bold"),
            justify="center",
            fg="black",
            bg="white",
            insertwidth=2,
            relief="flat",
        )
        self.entry.pack(fill="both", expand=True, padx=12, pady=12)
        self.entry.focus_set()

        self.end_time = None
        self.largest_unit = None
        self.last_shown = None
        self.tick_job = None
        self.flash_job = None
        self.settings = Settings()

        self.entry.bind("<Return>", self.on_enter)
        root.bind("<Escape>", lambda _e: root.destroy())

        if self.settings.last_timer:
            self.entry.insert(0, self.settings.last_timer)
            self.entry.select_range(0, "end")

    def on_enter(self, _event):
        self.cancel_timer()
        text = self.entry.get()
        parsed = parse_duration(text)
        if parsed is None:
            if text.strip():
                self.flash_invalid()
            return
        self.settings.last_timer = text
        self.settings.save()
        total, self.largest_unit = parsed
        self.end_time = time.time() + total
        self.last_shown = None
        self.tick()

    def tick(self):
        if self.end_time is None:
            return
        remaining = max(0, math.ceil(self.end_time - time.time()))
        if remaining != self.last_shown:
            self.last_shown = remaining
            self.entry.config(fg="black")
            self.entry.delete(0, "end")
            self.entry.insert(0, format_remaining(remaining, self.largest_unit))
        if remaining > 0:
            self.tick_job = self.root.after(100, self.tick)
        else:
            self.end_time = None
            self.tick_job = None
            self.play_sound()
            self.restore_last_timer()

    def restore_last_timer(self):
        """Put the previous timer text back so re-running is just Enter."""
        self.entry.config(fg="black")
        self.entry.delete(0, "end")
        if self.settings.last_timer:
            self.entry.insert(0, self.settings.last_timer)
            self.entry.select_range(0, "end")

    def cancel_timer(self):
        self.end_time = None
        if self.tick_job is not None:
            self.root.after_cancel(self.tick_job)
            self.tick_job = None
        winsound.PlaySound(None, winsound.SND_PURGE)
        if self.flash_job is not None:
            self.root.after_cancel(self.flash_job)
            self.flash_job = None

    def flash_invalid(self):
        self.flash_count = 0
        self.flash_step()

    def flash_step(self):
        self.entry.config(fg="red" if self.flash_count % 2 == 0 else "black")
        self.flash_count += 1
        if self.flash_count < 6:
            self.flash_job = self.root.after(150, self.flash_step)
        else:
            self.flash_job = None
            self.entry.config(fg="black")

    @staticmethod
    def play_sound():
        try:
            if SOUND_FILE.is_file():
                winsound.PlaySound(str(SOUND_FILE),
                                   winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
        except RuntimeError:
            pass
        winsound.MessageBeep(winsound.MB_ICONASTERISK)


def main():
    root = tk.Tk()
    EggyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
