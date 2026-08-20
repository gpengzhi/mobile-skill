<div align="center">
  <img src="assets/mobile-skill-banner.png" alt="mobile-skill banner" width="100%">
  <br>
  <br>
  <strong>Screenshot-driven GUI control for AI agents</strong>
  <br>
  <sub>Give your coding agent eyes, coordinates, and a real mobile device.</sub>
</div>

<br>

`mobile-skill` is a tiny CLI that lets Codex or Claude Code control a real mobile device by looking at screenshots and performing one verified action at a time.

## Install

Requirements: Python 3.11+, `adb`, and an unlocked Android device with USB debugging enabled.

```bash
git clone https://github.com/gpengzhi/mobile-skill.git
cd mobile-skill

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

./msk install codex
./msk --json doctor --agent codex
```

For Claude Code, use:

```bash
./msk install claude-code
./msk --json doctor --agent claude-code
```

Keep the checkout in place after installation because the installer uses symlinks.

## Try it

```bash
msk --json session start
msk --json observe --session <session-id>
```

Open the returned image, then perform an action using normalized coordinates from `0..999`:

```bash
msk --json tap 500 500 \
  --session <session-id> \
  --observation <observation-id> \
  --observe-after
```

Repeat the observe → inspect → action loop, then stop the session:

```bash
msk --json session stop <session-id>
```

## Why it feels different

- **Visual by default** — act on the screenshot the agent actually inspected.
- **Simple primitives** — tap, swipe, type, press, navigate, and launch apps.
- **Device-independent coordinates** — the same `0..999` coordinate space works across screen sizes.
- **Safe interaction loop** — stale observations are rejected and every action can be verified.

Current backend: Android over USB ADB. The interaction model is designed to support more mobile platforms over time.

## Learn more

- Skill instructions: [`skill/SKILL.md`](skill/SKILL.md)
- Project scope: [`docs/project-plan.md`](docs/project-plan.md)

No OCR, UI trees, accessibility selectors, generated scripts, daemon, or phone-side companion app required.
