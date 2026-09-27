from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installer", ROOT / "scripts" / "install.py")
assert SPEC is not None and SPEC.loader is not None
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class UserHookFallbackTests(unittest.TestCase):
    def test_merges_without_duplicate_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".codex" / "hooks.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}]}}))
            destination = home / "plugins" / "codex-sounds"
            installer.install_user_hooks(destination, home)
            installer.install_user_hooks(destination, home)
            data = json.loads(path.read_text())
            self.assertEqual(len(data["hooks"]["Stop"]), 2)
            self.assertEqual(data["hooks"]["Stop"][0]["hooks"][0]["command"], "echo existing")
            self.assertEqual(len(data["hooks"]["PermissionRequest"]), 1)
            self.assertEqual(len(data["hooks"]["PreToolUse"]), 1)


class SoundFolderMigrationTests(unittest.TestCase):
    def test_creates_folders_and_migrates_existing_sounds_once(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            settings_path = base / "settings.json"
            completion = base / "old-completion.wav"
            question = base / "old-question.wav"
            completion.write_bytes(b"complete")
            question.write_bytes(b"question")
            settings_path.write_text(json.dumps({"completion_sound": str(completion),
                                                 "input_sound": str(question), "other": "keep"}))
            runner = installer.load_runner()

            installer.prepare_sound_folders(settings_path, runner)
            self.assertEqual((base / "completion" / completion.name).read_bytes(), b"complete")
            self.assertEqual((base / "question" / question.name).read_bytes(), b"question")
            self.assertEqual(completion.read_bytes(), b"complete")
            self.assertEqual(question.read_bytes(), b"question")
            self.assertEqual(json.loads(settings_path.read_text()),
                             {"completion_sound": None, "input_sound": None, "other": "keep"})

            installer.prepare_sound_folders(settings_path, runner)
            self.assertEqual([p.name for p in (base / "completion").iterdir()], [completion.name])
            self.assertEqual([p.name for p in (base / "question").iterdir()], [question.name])

    def test_name_collision_preserves_both_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "sound.wav"
            source.write_bytes(b"new")
            folder = base / "completion"
            folder.mkdir()
            (folder / "sound.wav").write_bytes(b"old")
            settings_path = base / "settings.json"
            settings_path.write_text(json.dumps({"completion_sound": str(source)}))

            installer.prepare_sound_folders(settings_path, installer.load_runner())
            self.assertEqual((folder / "sound.wav").read_bytes(), b"old")
            self.assertEqual((folder / "sound-2.wav").read_bytes(), b"new")
            self.assertIsNone(json.loads(settings_path.read_text())["completion_sound"])


if __name__ == "__main__":
    unittest.main()
