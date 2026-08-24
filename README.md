<div align="center">
  <img src="assets/mobile-skill-banner.png" alt="mobile-skill" width="100%">
  <br>
  <br>
  <strong>Let AI agent drive a real Android phone.</strong>
</div>

<br>

The agent sees each screenshot and taps, swipes, types, or opens any app — GUI the way a person would.

When an app exposes a deep link, `msk` warps straight in; every successful jump becomes a URL template the next agent inherits, so the skill gets sharper the more it is used.

## Install

Paste into your agent, or open [`AGENT_INSTALL.md`](AGENT_INSTALL.md) yourself:

```text
Clone https://github.com/gpengzhi/mobile-skill.git and follow AGENT_INSTALL.md.
```

Needs Python 3.11+, `adb`, and an unlocked Android phone with USB debugging on.

## Use

Describe the goal in plain language.

```text
Use mobile-skill to open Bilibili, search for Minecraft, sort results by view count, and filter to the past week. Pick a video, like it, save it. Open its comments, sort by time, like the top one, and reply 'haha' with a smiley emoji.
```

## Deep links + learning

One command instead of *open app → tap search → type → submit*:

```bash
msk --json app open-url "bilibili://search?keyword=Minecraft" --session <id>
```

Ships with **9 curated apps × 25 URL templates** — Bilibili, Zhihu, Kuaishou, Taobao, Xianyu, Amap, Weibo, Alipay, WeChat — recorded in [`registry/deeplinks.json`](registry/deeplinks.json).

For URLs outside the curated set, agents try a plausible URL. If `pm resolve-activity` accepts it *and* the target app foregrounds after invocation, `msk` records the **structural template** (`bilibili://space/12345678` → `bilibili://space/{...}`, never the concrete URL) into a per-user learned registry that the next session inherits. `msk app registry` returns curated + learned in one view, with invocation counts and same-package-landing verification. URLs with `pay` / `transfer` / `send` / `publish` / `share` in them are blocked unless they match a curated template exactly.

## Limits

- Vision-capable models only.
- One phone over USB — no iOS, no Wi-Fi ADB.
- No OCR or accessibility trees — precision is bounded by the model's eyes.

## More

- [`skill/SKILL.md`](skill/SKILL.md) — the contract the agent follows
- [`docs/project-plan.md`](docs/project-plan.md) — scope, invariants, roadmap
- [`registry/deeplinks.json`](registry/deeplinks.json) — curated deep-link templates (PRs welcome)
