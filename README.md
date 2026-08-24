<div align="center">
  <img src="assets/mobile-skill-banner.png" alt="mobile-skill" width="100%">
  <br>
  <br>
  <strong>Give your coding agent a real Android phone.</strong>
</div>

<br>

Every screenshot is a lease: the agent's tap or swipe must cite the exact frame it just looked at, or `msk` rejects it as stale. No blind retries after a shaky capture, no typing PINs — just `adb`, normalized coordinates, and a safety loop that keeps every action accountable to what the model actually saw.

## Install

Paste into your agent, or open [`AGENT_INSTALL.md`](AGENT_INSTALL.md) yourself:

```text
Clone https://github.com/gpengzhi/mobile-skill.git and follow AGENT_INSTALL.md.
```

Needs Python 3.11+, `adb`, and an unlocked Android phone with USB debugging on.

## Use

Describe the goal in plain language. Codex prefixes the skill with `$`.

```text
Use mobile-skill to open Bilibili, search for Minecraft, sort results by view count, and filter to the past week. Pick a video, like it, save it. Open its comments, sort by time, like the top one, and reply 'haha' with a smiley emoji.
```

## Limits

- Vision-capable models only.
- One phone over USB — no iOS, no Wi-Fi ADB.
- No OCR or accessibility trees — precision is bounded by the model's eyes.

## More

- [`skill/SKILL.md`](skill/SKILL.md) — the contract the agent follows
- [`docs/project-plan.md`](docs/project-plan.md) — scope, invariants, roadmap
