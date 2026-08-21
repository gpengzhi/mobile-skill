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

Tell your agent:

```text
Clone https://github.com/gpengzhi/mobile-skill.git and follow AGENT_INSTALL.md in the repo to install and verify mobile-skill.
```

Installing by hand works the same way: [`AGENT_INSTALL.md`](AGENT_INSTALL.md) is a short, self-contained checklist. Requirements: Python 3.11+, `adb`, and an unlocked Android device with USB debugging enabled.

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
