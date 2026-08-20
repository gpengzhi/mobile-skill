# mobile-skill

Minimal screenshot-driven GUI control for a real Android phone.

`mobile-skill` gives Codex or Claude Code a small atomic CLI:

```text
observe screenshot → inspect image → run one action → observe again
```

It intentionally does not use OCR, UI trees, accessibility trees, Deep Links, generated control scripts, a daemon, or a phone-side companion App.

Naming is consistent across interfaces: the project and Agent Skill are `mobile-skill`, the CLI command is `msk`, and the Python package is `mobile_skill`.

## Requirements

- Python 3.11+
- Android platform-tools (`adb`)
- One unlocked Android phone with USB debugging authorized
- Codex CLI or Claude Code

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Install

Run from this source checkout:

```bash
./msk install codex
./msk --json doctor --agent codex
```

Or for Claude Code:

```bash
./msk install claude-code
./msk --json doctor --agent claude-code
```

The installer creates symlinks to this checkout. Moving or deleting the checkout breaks those links.

## Required Loop

```bash
msk --json session start
msk --json observe --session <id>
# Open the returned image path with view_image or Read.
msk --json tap X Y --session <id> --observation <obs-id> --observe-after
msk --json session stop <id>
```

The model must open the exact returned image before choosing coordinates. Every successful action invalidates the previous observation.

## Actions

```bash
msk --json tap X Y --session <id> --observation <obs-id>
msk --json double-tap X Y --session <id> --observation <obs-id>
msk --json long-press X Y --session <id> --observation <obs-id>
msk --json swipe X1 Y1 X2 Y2 --session <id> --observation <obs-id>
msk --json type "text" --session <id>
msk --json press return --session <id>
msk --json home --session <id>
msk --json back --session <id>
msk --json app-switcher --session <id>
msk --json app open com.android.settings --session <id>
msk --json wait --duration 500 --session <id>
```

Add `--observe-after` to an action to receive the next screenshot in the same response. Use `--settle-ms` only when the default wait is unsuitable.

## Human Takeover

Passwords, OTPs, PINs, biometrics, payments, private information, and permission decisions belong to the user:

```bash
msk --json request-help --session <id> \
  --reason login_required \
  --message "Please finish signing in on the phone."

msk --json session resume <id>
```

Always observe a fresh image after resuming.

## State and Cleanup

Sessions and screenshots are stored under `~/.local/state/mobile-skill` by default. Stopped Sessions are retained for seven days.

```bash
msk --json session list
msk --json cleanup --dry-run
msk --json cleanup
```

Use `MOBILE_SKILL_HOME` to move state and `MOBILE_SKILL_RETENTION_DAYS` to change retention.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
./msk --json version
```

Current focus and scope are recorded in `docs/project-plan.md`.
