#!/usr/bin/env python3
"""Install or refresh Codex Sounds in the personal Codex marketplace."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import filecmp
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "plugins" / "codex-sounds"
NAME = "codex-sounds"


def load_runner():
    module_path = SOURCE / "hooks" / "play_sound.py"
    spec = importlib.util.spec_from_file_location("codex_sounds_runner", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def prepare_sound_folders(settings_path: Path, runner) -> None:
    """Create sound pools and migrate valid single-file choices into them."""
    folders = {kind: settings_path.parent / name
               for kind, name in runner.FOLDER_NAMES.items()}
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Could not migrate sound settings in {settings_path}: {exc}", file=sys.stderr)
        return
    if not isinstance(settings, dict):
        print(f"Could not migrate sound settings in {settings_path}: expected a JSON object",
              file=sys.stderr)
        return

    changed = False
    for kind, key in runner.SETTING_NAMES.items():
        configured = settings.get(key)
        if not isinstance(configured, str) or not configured:
            continue
        source = Path(configured).expanduser()
        if not source.is_absolute() or source.suffix.lower() != ".wav" or not source.is_file():
            continue
        folder = folders[kind]
        destination = folder / source.name
        number = 2
        while destination.exists() and (not destination.is_file()
                                        or not filecmp.cmp(source, destination, shallow=False)):
            destination = folder / f"{source.stem}-{number}{source.suffix}"
            number += 1
        if not destination.exists():
            shutil.copy2(source, destination)
        settings[key] = None
        changed = True
    if changed:
        write_json(settings_path, settings)


def install_user_hooks(destination: Path, home: Path) -> Path:
    """Add a user-scoped fallback for hosts that do not load plugin hooks."""
    path = home / ".codex" / "hooks.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
            raise RuntimeError(f"Invalid hooks file: {path}")
    else:
        data = {"description": "User lifecycle hooks", "hooks": {}}
    script = destination / "hooks" / "play_sound.py"
    unix_command = f"python3 {shlex.quote(str(script))} --hook"
    windows_command = f'py -3 "{script}" --hook'
    template = {"type": "command", "command": unix_command,
                "commandWindows": windows_command, "async": True, "timeout": 30}
    marker = f"{NAME}/hooks/play_sound.py"
    for event, matcher in (("Stop", None), ("PermissionRequest", None),
                           ("PreToolUse", "^(request_user_input|request_user_input_async)$")):
        groups = data["hooks"].setdefault(event, [])
        if not isinstance(groups, list):
            raise RuntimeError(f"Invalid {event} hooks in {path}")
        retained = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                retained.append(group)
                continue
            handlers = [handler for handler in group["hooks"]
                        if not (isinstance(handler, dict)
                                and isinstance(handler.get("command"), str)
                                and marker in handler["command"].replace("\\", "/"))]
            if handlers:
                retained.append({**group, "hooks": handlers})
        group = {"hooks": [template.copy()]}
        if matcher is not None:
            group["matcher"] = matcher
        retained.append(group)
        data["hooks"][event] = retained
    write_json(path, data)
    return path


def install(user_hooks: bool = False) -> None:
    home = Path.home()
    destination = home / "plugins" / NAME
    marketplace = home / ".agents" / "plugins" / "marketplace.json"
    if destination.exists():
        manifest = destination / "plugin.json"
        if not manifest.exists():
            manifest = destination / ".codex-plugin" / "plugin.json"
        try:
            existing = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Refusing to replace unrecognized {destination}: {exc}") from exc
        if existing.get("name") != NAME:
            raise RuntimeError(f"Refusing to replace unrecognized {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # Codex caches installed plugin versions. A local build suffix makes updates visible.
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    for relative in ("plugin.json", ".codex-plugin/plugin.json"):
        path = destination / relative
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["version"] = manifest["version"].split("+")[0] + f"+codex.local-{suffix}"
        write_json(path, manifest)

    if marketplace.exists():
        catalog = json.loads(marketplace.read_text(encoding="utf-8"))
        if not isinstance(catalog, dict) or not isinstance(catalog.get("plugins"), list):
            raise RuntimeError(f"Invalid marketplace: {marketplace}")
    else:
        catalog = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
    market_name = catalog.get("name")
    if not isinstance(market_name, str) or not market_name:
        raise RuntimeError(f"Invalid marketplace name: {marketplace}")
    entry = {
        "name": NAME,
        "source": {"source": "local", "path": f"./plugins/{NAME}"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }
    for index, item in enumerate(catalog["plugins"]):
        if isinstance(item, dict) and item.get("name") == NAME:
            catalog["plugins"][index] = entry
            break
    else:
        catalog["plugins"].append(entry)
    write_json(marketplace, catalog)

    runner = load_runner()
    settings_path = runner.config_path()
    if not settings_path.exists():
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / "settings.example.json", settings_path)
    prepare_sound_folders(settings_path, runner)

    hooks_path = install_user_hooks(destination, home) if user_hooks else None

    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("Codex CLI was not found on PATH; install the plugin from the personal marketplace in the app")
    subprocess.run([codex, "plugin", "add", f"{NAME}@{market_name}"], check=True)
    print(f"Settings: {settings_path}")
    if hooks_path:
        print(f"User hook fallback: {hooks_path}")
    print("Review and trust the plugin's hooks with /hooks in a new Codex CLI session.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-hooks", action="store_true",
                        help="also register user hooks for hosts that do not discover plugin hooks")
    args = parser.parse_args()
    try:
        install(user_hooks=args.user_hooks)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Install failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
