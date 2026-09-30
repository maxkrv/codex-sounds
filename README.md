# Codex Sounds

A local Codex plugin that plays a random completion sound when a turn finishes and a random question sound when Codex requests input through a supported hook. Get notified when a Codex task is complete or when Codex needs your input.

## Requirements

- Python 3.9 or newer and the Codex CLI on `PATH`.
- macOS: built-in `afplay`.
- Windows: Python's built-in `winsound` and the `py` launcher.
- Linux: `paplay` or `aplay` on `PATH` and a working audio device.

## Install or update

### Install with a coding agent

Open a Codex chat or another coding agent **on the computer where you use Codex**, then paste this prompt:

```text
Set up Codex Sounds on this computer from https://github.com/maxkrv/codex-notification. Clone the repository (or reuse my existing checkout without discarding changes), read AGENT_SETUP.md and README.md, and follow the agent workflow in AGENT_SETUP.md. Check my OS and prerequisites, inspect scripts/install.py before running it, install the plugin, verify the installation and sound previews, and help me review and trust its hooks in a new Codex CLI chat. Use the --user-hooks fallback only if the bundled hooks are absent. Tell me what succeeded and any step I still need to do. Do not treat an install in a remote environment as an install on my computer.
```

The full agent checklist is in [AGENT_SETUP.md](AGENT_SETUP.md). Hook trust requires your review in `/hooks` before Codex will run the sounds.

### Install manually

From this repository, run:

```sh
python3 scripts/install.py
```

On Windows, use `py -3 scripts/install.py`. The installer copies the plugin to `~/plugins/codex-sounds`, adds it to `~/.agents/plugins/marketplace.json`, installs `codex-sounds@personal` (or the existing personal marketplace name), and creates the per-user settings file if needed. Repeat the command after editing the plugin. Start a new Codex chat after installing or updating. In Codex CLI, run `/hooks` and review and trust the `codex-sounds` hooks. Codex skips non-managed hooks until they are trusted.

On Codex CLI 0.154.0, the plugin installs but its bundled hooks were not discovered. Run `python3 scripts/install.py --user-hooks` to register the same hooks at user scope. This fallback was enabled on the development Mac and appears in `/hooks` as three untrusted user hooks. Check for bundled plugin hooks before enabling the fallback on newer Codex builds; having both sources active can play a sound twice.

The plugin is installed at user scope, so it applies across local Codex projects. It does not replace other Codex notification commands or built-in notification settings. If you hear two sounds, check the desktop or terminal's built-in notification sound settings and `/hooks` for duplicate hook sources.

## Customize sounds

Find your settings file with:

```sh
python3 plugins/codex-sounds/hooks/play_sound.py --config-path
```

Put WAV files directly in `completion/` and `question/` beside the settings file. For example, on macOS these folders are `~/Library/Application Support/Codex Sounds/completion/` and `~/Library/Application Support/Codex Sounds/question/`. Each event picks a WAV at random from its folder; the same file may play twice in a row. Non-WAV files and nested folders are ignored. An empty folder uses the bundled sound.

The installer creates both folders. When updating an existing installation, it copies a valid custom WAV from each single-file setting into the corresponding folder and clears that setting. It leaves the original files in place and does not add duplicate copies on later updates.

To use one specific sound instead, edit either setting below. A valid single-file path overrides its folder. Paths must be absolute; `~` is also accepted. `null` enables random folder selection.

```json
{
  "completion_sound": null,
  "input_sound": null
}
```

Preview a random choice from each folder with:

```sh
python3 plugins/codex-sounds/hooks/play_sound.py --preview completion
python3 plugins/codex-sounds/hooks/play_sound.py --preview input
```

Invalid single-file settings fall back to the folder. Empty or unreadable folders use the bundled WAVs. Unreadable settings are ignored, so folder selection still works. If an audio player is unavailable, the hook reports the problem but does not block Codex.

## Event coverage

The `Stop` hook plays the completion sound. `PermissionRequest` plays the input sound before a supported approval prompt. A `PreToolUse` hook also matches `request_user_input` and `request_user_input_async` when those local function tools use Codex's standard hook path. Codex currently does not expose a dedicated hook for every clarification question, so some question prompts will not play the input sound. Plain-text questions in a final reply play the completion sound. Approval requests that do not trigger `PermissionRequest` are likewise outside this plugin's coverage.

These hooks only observe events and play local audio. They do not approve, deny, block, or rewrite Codex actions. All three run asynchronously so playback does not hold up a turn or prompt.

## Verify

```sh
python3 -m unittest discover -s tests -v
codex plugin marketplace list
```

You can validate the compatibility manifest with the validator bundled in Codex's Plugin Creator skill; it needs PyYAML in the Python environment used to run it. Verify live event playback after trusting the hooks. The question-tool hook can only be verified in a Codex host that exposes those tool calls to lifecycle hooks.
