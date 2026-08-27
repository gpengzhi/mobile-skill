# AGENT_INSTALL.md — installing mobile-skill

Instructions for a coding agent installing mobile-skill on the user's machine. Follow the steps in order, run the checks yourself, and report the final `doctor` status to the user. Do not skip the verification step.

Registered harnesses: `claude-code`, `codex`, `cursor`, `openclaw`, `codebuddy`, `workbuddy`, `pi`, `hermes`, `kimi-code`. Any other agent with a `<home>/skills/<name>/SKILL.md` convention installs manually via `--home` (see below).

## Prerequisites

- macOS or Linux with `git` and Python 3.11+ (`python3 --version`)
- `adb` from Android platform-tools on `PATH` (`command -v adb`); if missing, install platform-tools first
- An Android phone connected over USB, unlocked, with USB debugging enabled

## Install

Run from the repo root (clone it first if you have not):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./msk install <your-harness>   # e.g. codex, claude-code, cursor, kimi-code
```

The `msk` launcher prefers `.venv` automatically, so the dependency keeps working from any shell — no activation needed. Installation symlinks the launcher to `~/.local/bin/msk` and the skill into the agent's skill directory; keep the checkout in place (updates apply on `git pull`).

If `command -v msk` fails afterwards, `~/.local/bin` is not on `PATH` — either add it or keep invoking `./msk` from the repo.

### Other agents

Registered harnesses print with `./msk --json install --list`. For a shell-capable agent whose `skills/` directory is not in the table, install manually:

```bash
./msk install --home <agent-home-dir>
```

This drops the skill at `<agent-home-dir>/skills/mobile-skill/`. The launcher symlink is still placed at `~/.local/bin/msk`. Afterwards restart that agent's CLI and run `./msk doctor` to confirm the environment is healthy — the agent-specific `--agent` check only fires for names registered in the table.

## Verify

```bash
./msk --json doctor --agent <your-harness>
```

Success criteria:

- `checks.python`, `checks.adb`, `checks.pillow`, `checks.screenshot` → `ready`
- `checks.device` → `ready` and `status` → `ready`
- `checks.input.unicode` → `ready`; if it reports `unavailable`, run `./msk --json setup-ime` (downloads and installs the pinned helper IME, needs network and "Install via USB"), then rerun `doctor`
- `checks.<agent>.skill` → `ready` (restart the agent CLI so it picks up the skill)
- `vision: unverified` is expected — static checks cannot prove the model sees images; the first real task does

If `checks.device` is `missing` or reports `unauthorized`, the user must act on the phone:

```bash
./msk --json onboard --timeout 60
```

Tell the user to unlock the phone and accept the USB debugging dialog; `onboard` restarts the adb server and waits until the device is ready. Rerun `doctor` afterwards.

## Report to the user

State which checks passed or failed, and whether the phone needed authorization. On success, the user can start a first task — for example: "Use mobile-skill to open Settings and tell me what screen is visible."

## Developer notes

Contributors can install the dev extras and run the pytest suite (no device required):

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```
