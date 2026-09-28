# Set up Codex Sounds with an agent

Give the prompt in [README.md](README.md#install-with-a-coding-agent) to a coding agent that can run commands **on the machine where you use Codex**. This plugin plays audio locally; installing it in a remote container will not set up sounds on your computer.

The agent should complete the following workflow. The repository is [maxkrv/codex-notification](https://github.com/maxkrv/codex-notification).

## Agent workflow

1. Check the operating system and that `git`, the Codex CLI, and Python 3.9 or newer are available. On macOS, confirm `afplay`; on Linux, confirm `paplay` or `aplay` and an audio device; on Windows, confirm the `py` launcher. If a prerequisite is missing, report the exact blocker and help the user install it using the platform's normal method before continuing.
2. Clone the repository into a new local directory, or reuse an existing checkout of this repository without discarding local changes. Read `README.md`, `AGENT_SETUP.md`, and `scripts/install.py` from that checkout before running the installer. Use the checked-out script, not a command piped from the internet.
3. Run the installer from the repository root:

   ```sh
   python3 scripts/install.py
   ```

   On Windows, use `py -3 scripts/install.py`. The script copies `plugins/codex-sounds` to the user's `~/plugins/codex-sounds`, updates `~/.agents/plugins/marketplace.json`, creates the per-user sound settings and folders, and calls `codex plugin add` for the personal marketplace. Preserve the user's other marketplace entries and sound files.
4. Check the installer exit status and output. Confirm `codex plugin marketplace list` shows the personal marketplace and that the installer-reported settings file and installed plugin directory exist. If installation failed, diagnose the reported error and retry only after fixing its cause.
5. Ask the user to start a **new Codex CLI chat**, run `/hooks`, review the `codex-sounds` hook commands, and trust them if they agree. [Codex requires explicit trust for plugin hooks](https://developers.openai.com/plugins/build/plugins#bundle-lifecycle-hooks); installing the plugin alone does not activate them. Do not claim that the hooks are active before this step.
6. If `/hooks` shows no bundled `codex-sounds` hooks, run the installer again with `--user-hooks` (`py -3 scripts/install.py --user-hooks` on Windows). This registers equivalent `Stop`, `PermissionRequest`, and `PreToolUse` hooks in `~/.codex/hooks.json`. Ask the user to review and trust those user hooks in a new CLI chat. If only some bundled hooks appear, diagnose that partial discovery before adding a second source. Enabling both sources may play sounds twice. The fallback was needed with Codex CLI 0.154.0 and may be unnecessary on other versions.
7. Preview both sounds from the repository root, using `py -3` in place of `python3` on Windows:

   ```sh
   python3 plugins/codex-sounds/hooks/play_sound.py --preview completion
   python3 plugins/codex-sounds/hooks/play_sound.py --preview input
   ```

   Ask the user whether they heard them. A preview verifies the audio player and sound files; a real Codex turn and input request verify hook playback after trust. If the preview fails, report the concrete audio or command error.
8. Report the installed plugin path, settings path, whether bundled or user hooks were selected, what was verified, and any remaining user action. Explain that they can add `.wav` files to `completion/` and `question/` beside the settings file, as described in the README.

## Boundaries

- Do not overwrite an unrelated `~/plugins/codex-sounds` directory or replace the user's full marketplace or hooks configuration. The installer checks the plugin name and merges its own entries; stop and explain if it refuses an existing directory or malformed configuration.
- Do not trust hooks on the user's behalf. The user should inspect the command that will run on lifecycle events and make that trust decision in `/hooks`.
- Do not enable the `--user-hooks` fallback before checking whether bundled hooks are discovered.
- If the agent is running somewhere other than the user's local machine, provide these steps for a local agent instead of claiming a successful local install.
