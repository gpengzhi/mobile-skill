<div align="center">
  <img src="assets/mobile-skill-banner.png" alt="mobile-skill banner" width="100%">
  <br>
  <br>
  <strong>Screenshot-driven mobile control for multimodal coding agents</strong>
  <br>
  <sub>Give multimodal coding agents a reliable interface for real mobile devices.</sub>
</div>

<br>

`mobile-skill` is a lightweight skill that enables multimodal coding agents to control real mobile devices through screenshots and verified actions.

The multimodal model interprets screenshots and verifies outcomes, while `mobile-skill` handles device connectivity, screenshot capture, normalized coordinate mapping, and atomic actions.

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

If the phone is not detected or shows as unauthorized, run `./msk onboard` and accept the USB debugging dialog on the phone.

## Try it

Open Codex or Claude Code with a multimodal model that can inspect images, then describe the mobile task in natural language.

For Codex:

```text
Use $mobile-skill to open Settings on my connected phone and tell me what screen is visible. Do not change any settings.
```

For Claude Code:

```text
Use mobile-skill to open Settings on my connected phone and tell me what screen is visible. Do not change any settings.
```

The agent will run the screenshot → inspect → action → verify loop for you. You can also give it a complete task, for example:

```text
Use mobile-skill to open the calculator, calculate 128 × 64, and report the result.
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
