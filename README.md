<div align="center">
  <img src="assets/mobile-skill-banner.png" alt="mobile-skill" width="100%">
  <br>
  <br>
  <strong>Let AI agent drive a real Android phone.</strong>
</div>

<br>

When an app exposes a deep link, the skill warps straight in — and remembers what worked, so it gets sharper the more you use it. For everything else, the agent sees each screenshot and taps, swipes, types the way a person would.

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

## Deep Links & Learning

One command instead of *open app → tap search → type → submit*:

```bash
msk --json app open-url "bilibili://search?keyword=Minecraft" --session <id>
```

**25 URL templates across 9 apps** — Bilibili, Zhihu, Kuaishou, Taobao, Xianyu, Amap, Weibo, Alipay, WeChat — ship in [`registry/deeplinks.json`](registry/deeplinks.json).

For anything else, `msk` learns as it goes. Every URL that works this session becomes shared knowledge for the next — automatically.

Sensitive actions — spending money, sending messages, posting content — never warp. They stay in the visible tap-by-tap flow.

## Limits

- Vision-capable models only.
- One phone over USB — no iOS, no Wi-Fi ADB.
- No OCR or accessibility trees — precision is bounded by the model's eyes.

## More

- [`skill/SKILL.md`](skill/SKILL.md) — the contract the agent follows
- [`docs/project-plan.md`](docs/project-plan.md) — scope, invariants, roadmap
- [`registry/deeplinks.json`](registry/deeplinks.json) — curated deep-link templates (PRs welcome)
