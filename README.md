<div align="center">
  <img src="assets/mobile-skill-banner.png" alt="mobile-skill" width="100%">
  <br>
  <br>
  <strong>Let AI agent drive a real Android phone.</strong>
</div>

<br>

When an app exposes a deep link, the skill invokes it directly, without GUI navigation. Each successful invocation contributes a reusable pattern to a registry that later sessions inherit. Otherwise, the agent observes each screenshot and issues tap, swipe, or type actions.

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

A single command replaces the sequence *open app → tap search → type → submit*:

```bash
msk --json app open-url "bilibili://search?keyword=Minecraft" --session <id>
```

The registry ships with **25 URL templates across 9 apps**: Bilibili, Zhihu, Kuaishou, Taobao, Xianyu, Amap, Weibo, Alipay, WeChat (see [`registry/deeplinks.json`](registry/deeplinks.json)).

Outside the curated set, each successful invocation contributes a reusable pattern to a local registry that subsequent sessions inherit.

Sensitive actions (payments, messaging, content publication) are refused on the deep-link path and must proceed through the GUI.

## Limits

- Vision-capable models only.
- One Android phone over USB; no iOS, no Wi-Fi ADB.
- No OCR or accessibility trees; targeting precision is bounded by the model's vision.

## More

- [`skill/SKILL.md`](skill/SKILL.md) — the contract the agent follows
- [`docs/project-plan.md`](docs/project-plan.md) — scope, invariants, roadmap
- [`registry/deeplinks.json`](registry/deeplinks.json) — curated deep-link templates (PRs welcome)
