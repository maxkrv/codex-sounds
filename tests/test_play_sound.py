from __future__ import annotations

from contextlib import closing
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
import wave


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-sounds"
SPEC = importlib.util.spec_from_file_location("play_sound", PLUGIN / "hooks" / "play_sound.py")
assert SPEC is not None and SPEC.loader is not None
sound = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sound)


class EventTests(unittest.TestCase):
    def test_supported_events(self):
        cases = [
            ({"hook_event_name": "Stop"}, "completion"),
            ({"hook_event_name": "PermissionRequest"}, "input"),
            ({"hook_event_name": "PreToolUse", "tool_name": "request_user_input"}, "input"),
            ({"hook_event_name": "PreToolUse", "tool_name": "request_user_input_async"}, "input"),
            ({"hook_event_name": "PreToolUse", "tool_name": "Bash"}, None),
            ({"hook_event_name": "SessionEnd"}, None),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(sound.event_kind(payload), expected)

    def test_hook_input_is_silent_for_unrelated_event(self):
        with mock.patch("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash"}))), \
             mock.patch.object(sound, "play") as play:
            self.assertEqual(sound.main(["--hook"]), 0)
            play.assert_not_called()

    def test_hook_routes_to_selected_sound(self):
        payload = {"hook_event_name": "PermissionRequest"}
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                 mock.patch.object(sound, "play") as play, \
                 mock.patch.object(sound, "config_path", return_value=Path(directory) / "settings.json"), \
                 mock.patch.object(sound, "read_settings", return_value={}):
                self.assertEqual(sound.main(["--hook"]), 0)
                play.assert_called_once_with(PLUGIN / "assets" / "input.wav")


class SettingsTests(unittest.TestCase):
    def test_platform_settings_paths(self):
        home = Path("/home/example")
        self.assertEqual(sound.config_path("Darwin", {}, home), home / "Library/Application Support/Codex Sounds/settings.json")
        self.assertEqual(sound.config_path("Windows", {"APPDATA": "C:/Users/example/AppData/Roaming"}, home),
                         Path("C:/Users/example/AppData/Roaming/Codex Sounds/settings.json"))
        self.assertEqual(sound.config_path("Linux", {"XDG_CONFIG_HOME": "/tmp/config"}, home),
                         Path("/tmp/config/codex-sounds/settings.json"))

    def test_custom_and_invalid_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            custom = Path(directory) / "custom.wav"
            custom.write_bytes(b"RIFF")
            self.assertEqual(sound.sound_path("completion", {"completion_sound": str(custom)},
                                              settings_path=settings_path), custom)
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(sound.sound_path("completion", {"completion_sound": "relative.wav"},
                                                  settings_path=settings_path),
                                 PLUGIN / "assets" / "completion.wav")
                self.assertEqual(sound.sound_path("input", {"input_sound": str(custom.with_suffix('.mp3'))},
                                                  settings_path=settings_path),
                                 PLUGIN / "assets" / "input.wav")

    def test_random_choice_uses_matching_folder_and_wav_files_only(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            completion = base / "completion"
            question = base / "question"
            completion.mkdir()
            question.mkdir()
            first = completion / "a.wav"
            second = completion / "b.WAV"
            asked = question / "asked.wav"
            for path in (first, second, asked, completion / "ignore.mp3"):
                path.write_bytes(b"sound")
            (completion / "nested").mkdir()
            (completion / "nested" / "nested.wav").write_bytes(b"sound")
            (completion / "directory.wav").mkdir()
            settings_path = base / "settings.json"
            with mock.patch.object(sound.random, "choice", side_effect=lambda files: files[-1]) as choice:
                self.assertEqual(sound.sound_path("completion", {}, settings_path=settings_path), second)
                self.assertEqual(choice.call_args.args[0], [first, second])
                self.assertEqual(sound.sound_path("input", {}, settings_path=settings_path), asked)

    def test_single_file_override_wins_over_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            folder = base / "completion"
            folder.mkdir()
            (folder / "pooled.wav").write_bytes(b"sound")
            override = base / "override.wav"
            override.write_bytes(b"sound")
            with mock.patch.object(sound.random, "choice") as choice:
                self.assertEqual(sound.sound_path("completion", {"completion_sound": str(override)},
                                                  settings_path=base / "settings.json"), override)
                choice.assert_not_called()

    def test_empty_folder_uses_bundled_sound(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "question").mkdir()
            self.assertEqual(sound.sound_path("input", {}, settings_path=Path(directory) / "settings.json"),
                             PLUGIN / "assets" / "input.wav")

    def test_bad_settings_use_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "settings.json"
            file.write_text("not json", encoding="utf-8")
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(sound.read_settings(file), {})


class HistoryTests(unittest.TestCase):
    def make_pool(self, base, folder, names):
        pool = base / folder
        pool.mkdir()
        paths = [pool / name for name in names]
        for path in paths:
            path.write_bytes(b"sound")
        return paths

    def test_last_successful_choice_persists_without_forcing_a_full_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first, second, _ = self.make_pool(base, "completion", ["a.wav", "b.wav", "c.wav"])
            settings_path = base / "settings.json"
            with mock.patch.object(sound.random, "choice", side_effect=lambda files: files[0]), \
                 mock.patch.object(sound, "play") as play:
                for _ in range(3):
                    self.assertTrue(sound.play_with_history("completion", {}, settings_path))
            self.assertEqual([call.args[0] for call in play.call_args_list], [first, second, first])
            with closing(sqlite3.connect(base / "history.sqlite3")) as database:
                self.assertEqual(database.execute("SELECT path FROM last_played WHERE kind = 'completion'").fetchone(),
                                 (str(first),))

    def test_completion_and_input_have_independent_history(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            completion = self.make_pool(base, "completion", ["a.wav", "b.wav"])
            question = self.make_pool(base, "question", ["a.wav", "b.wav"])
            with mock.patch.object(sound.random, "choice", side_effect=lambda files: files[0]), \
                 mock.patch.object(sound, "play") as play:
                for kind in ("completion", "input", "completion", "input"):
                    self.assertTrue(sound.play_with_history(kind, {}, base / "settings.json"))
            self.assertEqual([call.args[0] for call in play.call_args_list],
                             [completion[0], question[0], completion[1], question[1]])

    def test_previews_share_history_with_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first, second = self.make_pool(base, "completion", ["a.wav", "b.wav"])
            with mock.patch.object(sound, "config_path", return_value=base / "settings.json"), \
                 mock.patch.object(sound.random, "choice", side_effect=lambda files: files[0]), \
                 mock.patch.object(sound, "play") as play:
                self.assertEqual(sound.main(["--preview", "completion"]), 0)
                self.assertTrue(sound.play_with_history("completion", {}, base / "settings.json"))
            self.assertEqual([call.args[0] for call in play.call_args_list], [first, second])

    def test_failed_playback_does_not_update_history(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first, _ = self.make_pool(base, "completion", ["a.wav", "b.wav"])
            with mock.patch.object(sound.random, "choice", side_effect=lambda files: files[0]), \
                 mock.patch.object(sound, "play", side_effect=[RuntimeError("bad audio"), None]) as play, \
                 mock.patch("sys.stderr", new_callable=io.StringIO):
                self.assertFalse(sound.play_with_history("completion", {}, base / "settings.json"))
                self.assertTrue(sound.play_with_history("completion", {}, base / "settings.json"))
            self.assertEqual([call.args[0] for call in play.call_args_list], [first, first])

    def test_single_file_repeats_and_override_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first, second = self.make_pool(base, "completion", ["a.wav", "b.wav"])
            settings_path = base / "settings.json"
            with mock.patch.object(sound.random, "choice", side_effect=lambda files: files[0]), \
                 mock.patch.object(sound, "play") as play:
                for _ in range(2):
                    self.assertTrue(sound.play_with_history("completion", {"completion_sound": str(first)},
                                                            settings_path))
                self.assertTrue(sound.play_with_history("completion", {}, settings_path))
            self.assertEqual([call.args[0] for call in play.call_args_list], [first, first, second])

            single, = self.make_pool(base, "question", ["only.wav"])
            with mock.patch.object(sound, "play") as play:
                for _ in range(2):
                    self.assertTrue(sound.play_with_history("input", {}, settings_path))
            self.assertEqual([call.args[0] for call in play.call_args_list], [single, single])

    def test_unavailable_history_falls_back_to_random_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first, _ = self.make_pool(base, "completion", ["a.wav", "b.wav"])
            with mock.patch.object(sound.sqlite3, "connect", side_effect=sqlite3.OperationalError("unavailable")), \
                 mock.patch.object(sound.random, "choice", side_effect=lambda files: files[0]), \
                 mock.patch.object(sound, "play") as play, \
                 mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertTrue(sound.play_with_history("completion", {}, base / "settings.json"))
            play.assert_called_once_with(first)
            self.assertIn("cannot use sound history", stderr.getvalue())

    def test_history_write_failure_does_not_play_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first, _ = self.make_pool(base, "completion", ["a.wav", "b.wav"])
            with closing(sqlite3.connect(base / "history.sqlite3")) as database:
                database.execute("CREATE TABLE last_played (kind TEXT PRIMARY KEY, path TEXT NOT NULL)")
                database.execute("CREATE TRIGGER reject_history BEFORE INSERT ON last_played "
                                 "BEGIN SELECT RAISE(FAIL, 'history is unavailable'); END")
                database.commit()
            with mock.patch.object(sound.random, "choice", side_effect=lambda files: files[0]), \
                 mock.patch.object(sound, "play") as play, \
                 mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertTrue(sound.play_with_history("completion", {}, base / "settings.json"))
            play.assert_called_once_with(first)
            self.assertIn("could not save sound history", stderr.getvalue())

    def test_overlapping_hooks_wait_for_successful_playback(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first, second = self.make_pool(base, "completion", ["a.wav", "b.wav"])
            started = threading.Event()
            release = threading.Event()
            second_play = threading.Event()
            calls = []
            results = []
            errors = []

            def fake_play(path):
                calls.append(path)
                if len(calls) == 1:
                    started.set()
                    if not release.wait(5):
                        raise RuntimeError("test timed out")
                else:
                    second_play.set()

            def run():
                try:
                    results.append(sound.play_with_history("completion", {}, base / "settings.json"))
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(sound.random, "choice", side_effect=lambda files: files[0]), \
                 mock.patch.object(sound, "play", side_effect=fake_play):
                first_thread = threading.Thread(target=run)
                second_thread = threading.Thread(target=run)
                first_thread.start()
                try:
                    self.assertTrue(started.wait(5))
                    second_thread.start()
                    self.assertFalse(second_play.wait(0.1))
                finally:
                    release.set()
                    first_thread.join(5)
                    if second_thread.ident is not None:
                        second_thread.join(5)
            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results, [True, True])
            self.assertEqual(calls, [first, second])


class PlaybackTests(unittest.TestCase):
    def test_linux_player_fallback(self):
        self.assertEqual(sound.linux_player(lambda name: "/bin/aplay" if name == "aplay" else None), "/bin/aplay")
        with self.assertRaises(RuntimeError):
            sound.linux_player(lambda name: None)

    def test_macos_player_uses_argument_list(self):
        target = PLUGIN / "assets" / "completion.wav"
        with mock.patch.object(sound.shutil, "which", return_value="/usr/bin/afplay"), \
             mock.patch.object(sound.subprocess, "run") as run:
            sound.play(target, "Darwin")
            self.assertEqual(run.call_args.args[0], ["/usr/bin/afplay", str(target)])

    def test_windows_player_uses_winsound(self):
        target = PLUGIN / "assets" / "input.wav"
        fake = SimpleNamespace(SND_FILENAME=1, SND_SYNC=2, PlaySound=mock.Mock())
        with mock.patch.dict(sys.modules, {"winsound": fake}):
            sound.play(target, "Windows")
        fake.PlaySound.assert_called_once_with(str(target), 3)

    def test_default_assets_are_valid_wav(self):
        for filename in sound.SOUND_NAMES.values():
            with self.subTest(filename=filename), wave.open(str(PLUGIN / "assets" / filename), "rb") as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertGreater(wav.getnframes(), 0)


if __name__ == "__main__":
    unittest.main()
