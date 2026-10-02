#!/usr/bin/env python3
"""Play a short local sound for supported Codex hook events."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import random
import shutil
import sqlite3
import subprocess
import sys
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
QUESTION_TOOLS = {"request_user_input", "request_user_input_async"}
SOUND_NAMES = {"completion": "completion.wav", "input": "input.wav"}
SETTING_NAMES = {"completion": "completion_sound", "input": "input_sound"}
FOLDER_NAMES = {"completion": "completion", "input": "question"}


def config_path(system: str | None = None, environ: dict[str, str] | None = None,
                home: Path | None = None) -> Path:
    """Return the conventional per-user settings location for this OS."""
    system = system or platform.system()
    environ = environ if environ is not None else os.environ
    home = home or Path.home()
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Codex Sounds" / "settings.json"
    if system == "Windows":
        base = Path(environ.get("APPDATA") or home / "AppData" / "Roaming")
        return base / "Codex Sounds" / "settings.json"
    xdg = environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".config"
    return base / "codex-sounds" / "settings.json"


def event_kind(payload: dict[str, Any]) -> str | None:
    event = payload.get("hook_event_name")
    if event == "Stop":
        return "completion"
    if event == "PermissionRequest":
        return "input"
    if event == "PreToolUse" and payload.get("tool_name") in QUESTION_TOOLS:
        return "input"
    return None


def read_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("settings must be a JSON object")
        return value
    except (OSError, ValueError) as exc:
        print(f"Codex Sounds: cannot read {path}: {exc}; using defaults", file=sys.stderr)
        return {}


def sound_path(kind: str, settings: dict[str, Any], root: Path = PLUGIN_ROOT,
               settings_path: Path | None = None, exclude: Path | None = None) -> Path:
    default = root / "assets" / SOUND_NAMES[kind]
    configured = settings.get(SETTING_NAMES[kind])
    if configured is not None and configured != "":
        if isinstance(configured, str):
            candidate = Path(configured).expanduser()
            if candidate.is_absolute() and candidate.suffix.lower() == ".wav" and candidate.is_file():
                return candidate
        print(f"Codex Sounds: invalid {SETTING_NAMES[kind]} path {configured!r}; checking sound folder",
              file=sys.stderr)

    folder = (settings_path or config_path()).parent / FOLDER_NAMES[kind]
    try:
        choices = sorted(path for path in folder.iterdir()
                         if path.suffix.lower() == ".wav" and path.is_file())
    except FileNotFoundError:
        choices = []
    except OSError as exc:
        print(f"Codex Sounds: cannot read {folder}: {exc}; using default", file=sys.stderr)
        choices = []
    if len(choices) > 1 and exclude in choices:
        choices.remove(exclude)
    return random.choice(choices) if choices else default


def linux_player(which=shutil.which) -> str:
    for name in ("paplay", "aplay"):
        player = which(name)
        if player:
            return player
    raise RuntimeError("install PulseAudio's paplay or ALSA's aplay to play WAV files")


def play(path: Path, system: str | None = None) -> None:
    system = system or platform.system()
    if system == "Windows":
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_SYNC)
        return
    if system == "Darwin":
        executable = shutil.which("afplay")
        if not executable:
            raise RuntimeError("afplay is unavailable")
    elif system == "Linux":
        executable = linux_player()
    else:
        raise RuntimeError(f"unsupported operating system: {system}")
    subprocess.run([executable, str(path)], check=True, timeout=30,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def play_choice(path: Path) -> bool:
    try:
        play(path)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Codex Sounds: could not play {path}: {exc}", file=sys.stderr)
        return False
    return True


def play_with_history(kind: str, settings: dict[str, Any], settings_path: Path) -> bool:
    """Serialize selection and playback, remembering only successful plays."""
    database = None
    played = False
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(settings_path.with_name("history.sqlite3"), timeout=25)
        database.execute("BEGIN IMMEDIATE")
        database.execute("CREATE TABLE IF NOT EXISTS last_played "
                         "(kind TEXT PRIMARY KEY, path TEXT NOT NULL)")
        row = database.execute("SELECT path FROM last_played WHERE kind = ?", (kind,)).fetchone()
        exclude = Path(row[0]) if row else None
        selected = sound_path(kind, settings, settings_path=settings_path, exclude=exclude)
        if not play_choice(selected):
            database.rollback()
            return False
        played = True
        database.execute("INSERT INTO last_played (kind, path) VALUES (?, ?) "
                         "ON CONFLICT(kind) DO UPDATE SET path = excluded.path", (kind, str(selected)))
        database.commit()
        return True
    except (sqlite3.Error, OSError) as exc:
        if played:
            print(f"Codex Sounds: could not save sound history: {exc}", file=sys.stderr)
            return True
        print(f"Codex Sounds: cannot use sound history: {exc}; using random selection",
              file=sys.stderr)
        return play_choice(sound_path(kind, settings, settings_path=settings_path))
    finally:
        if database is not None:
            database.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--hook", action="store_true", help="read a Codex hook event from stdin")
    choice.add_argument("--preview", choices=SOUND_NAMES, help="play one configured sound")
    choice.add_argument("--config-path", action="store_true", help="print the user settings path")
    args = parser.parse_args(argv)
    if args.config_path:
        print(config_path())
        return 0
    if args.hook:
        try:
            payload = json.load(sys.stdin)
            kind = event_kind(payload) if isinstance(payload, dict) else None
        except ValueError as exc:
            print(f"Codex Sounds: invalid hook input: {exc}", file=sys.stderr)
            return 0
        if kind is None:
            return 0
    else:
        kind = args.preview
    settings_path = config_path()
    succeeded = play_with_history(kind, read_settings(settings_path), settings_path)
    return 0 if succeeded or args.hook else 1


if __name__ == "__main__":
    raise SystemExit(main())
