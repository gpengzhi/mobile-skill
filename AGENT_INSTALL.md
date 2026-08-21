# AGENT_INSTALL.md — installing mobile-skill

Instructions for a coding agent (Codex or Claude Code) installing mobile-skill on the user's machine. Follow the steps in order, run the checks yourself, and report the final `doctor` status to the user. Do not skip the verification step.

## Prerequisites

- macOS or Linux with `git` and Python 3.11+ (`python3 --version`)
- `adb` from Android platform-tools on `PATH` (`command -v adb`); if missing, install platform-tools first
- An Android phone connected over USB, unlocked, with USB debugging enabled

## Install

Run from the repo root (clone it first if you have not):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./msk install codex          # or claude-code
```

The `msk` launcher prefers `.venv` automatically, so the dependency keeps working from any shell — no activation needed. Installation symlinks the launcher to `~/.local/bin/msk` and the skill into the agent's skill directory; keep the checkout in place (updates apply on `git pull`).

If `command -v msk` fails afterwards, `~/.local/bin` is not on `PATH` — either add it or keep invoking `./msk` from the repo.

## Verify

```bash
./msk --json doctor --agent codex
```

Success criteria:

- `checks.python`, `checks.adb`, `checks.pillow`, `checks.screenshot` → `ready`
- `checks.device` → `ready` and `status` → `ready`
- `checks.<agent>.skill` → `ready` (restart the agent CLI so it picks up the skill)
- `vision: unverified` is expected — static checks cannot prove the model sees images; the first real task does

If `checks.device` is `missing` or reports `unauthorized`, the user must act on the phone:

```bash
./msk --json onboard --timeout 60
```

Tell the user to unlock the phone and accept the USB debugging dialog; `onboard` restarts the adb server and waits until the device is ready. Rerun `doctor` afterwards.

## Report to the user

State which checks passed or failed, and whether the phone needed authorization. On success, the user can start a first task — for example: "Use mobile-skill to open Settings and tell me what screen is visible."
