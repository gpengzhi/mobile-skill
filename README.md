<div align="center">
  <img src="assets/mobile-skill-banner.png" alt="mobile-skill banner" width="100%">
  <br>
  <br>
  <strong>Screenshot-driven mobile control for multimodal coding agents</strong>
</div>

<br>

`mobile-skill` lets a multimodal coding agent operate a real Android phone. The agent looks at each screenshot; `mobile-skill` handles the connection, the coordinate mapping, and the safety loop that keeps every action accountable to the exact frame the model just saw.

## Install

Tell your agent:

```text
Clone https://github.com/gpengzhi/mobile-skill.git and follow AGENT_INSTALL.md in the repo to install and verify mobile-skill.
```

By hand: [`AGENT_INSTALL.md`](AGENT_INSTALL.md) is the checklist. Requirements: Python 3.11+, `adb`, and an unlocked Android phone with USB debugging enabled.

## Try it

Open Codex or Claude Code with a multimodal model, then describe the task in natural language:

```text
Use mobile-skill to open Settings on my connected phone and tell me what screen is visible. Do not change any settings.
```

Or hand it a full goal:

```text
Use mobile-skill to open the calculator, calculate 128 × 64, and report the result.
```

Codex users prefix the skill name with `$`: `Use $mobile-skill to ...`.

## Why it feels different

- **A lease on reality, not a screenshot cache.** Coordinate actions must cite the observation they came from; anything older is rejected as `stale_observation`.
- **No blind retries.** When an action succeeds but the follow-up capture fails, the error reports `action_applied: true`, so the agent never repeats a side-effecting action.
- **Human takeover built in.** Passwords, OTPs, payments, and permission dialogs pause the session via `request-help`. `mobile-skill` never types a PIN.
- **Device-independent coordinates.** The same `0..999` space works across screen sizes.

## Limits

- **Needs a model that really sees images.** Text-only models get screenshots as links, not pixels. `msk doctor` reports `vision: unverified` because only a real task can prove image understanding.
- **One Android phone over USB.** No multi-device selection, Wi-Fi adb, or iOS.
- **Login walls stop the loop.** Apps that require login on launch — common in China — trigger human takeover by design.
- **Animation is judged, not detected.** Conservative per-action settle delays plus the model re-observing transitional frames; a decelerating fling can still look still in a single frame.
- **No OCR, accessibility trees, or selectors.** Precision is bounded by the model's vision — no structured fallback.

## Learn more

- Skill instructions: [`skill/SKILL.md`](skill/SKILL.md)
- Project scope: [`docs/project-plan.md`](docs/project-plan.md)
