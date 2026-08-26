# mobile-skill project plan

## Goal

Provide reliable screenshot-driven Android GUI navigation for local coding Agents.

## Supported today

- USB ADB device discovery, validation, and first-run onboarding (`msk onboard`)
- Screenshot capture, JPEG compression, and normalized `0..999` coordinate mapping
- Tap, double-tap, long-press, swipe, wait, text input, key presses, app launch
- Model-declared bounded action sequences with a five-action limit, terminal-action ordering, partial-failure reporting, and optional final observation
- Installed-app inventory (`msk apps list`) as a text-based fallback when a package name is unknown
- Session lease with observation-staleness protection, pause/resume, human takeover, and idle-timeout cleanup
- Skill installation from a source checkout for registered harnesses — Claude Code, Codex, Cursor, OpenClaw, CodeBuddy, WorkBuddy, Pi, Hermes, Kimi Code (`msk install --list`) — plus `msk install --home <dir>` for any agent with the same `<home>/skills/<name>/SKILL.md` convention
- Automatic cleanup of stopped/idle sessions and orphaned screenshots
- Deep-link discovery and invocation: `msk app schemes` (dumpsys-based), `msk app registry` (curated + learned templates), `msk app open-url` (pre-checked via `pm resolve-activity`, sensitive URLs blocked, post-invocation landing verified against foreground activity). Self-evolution: successful invocations are normalized to structural templates (`bilibili://space/{...}`, never concrete URLs) and accumulated in `~/.local/state/mobile-skill/learned_deeplinks.json` with `invocations` / `verified` / `hijacked` counters that `msk app registry` overlays onto curated entries.
- Automated test suite covering coordinate mapping, IME dispatch, cleanup, observation staleness, deep-link normalization/invariants/learning, session lifecycle, and CLI dispatch — pytest-based, no real-device required (`pip install -r requirements-dev.txt && pytest`).

## Not supported

- iPhone (deferred until the Android side is proven)
- Wi-Fi ADB, simultaneous multi-device orchestration
- OCR, UI trees, accessibility trees, element selectors
- Daemon mode, remote devices, multi-Agent scheduling
- Automatic handling of login, secrets, permissions, or payments

## Invariants

1. One CLI command performs one observation, one atomic action, or one bounded sequence of up to five actions.
2. Coordinate actions require the latest viewed observation.
3. Every successful action invalidates that observation.
4. Action results are verified with a new screenshot.
5. Uncertain side-effecting actions are never retried blindly.
6. User-only decisions always use human takeover.

## Architecture

```text
Codex / Claude Code
        ↓
      msk CLI
        ↓
Session + observation state (~/.local/state/mobile-skill/)
        ↓
      Android ADB
        ↓
   Real Android phone
```

## Next priorities

1. **Evaluation matrix.** ~20 representative tasks × 2–3 frontier models × configurations (476px vision, 768px vision, accessibility-tree channel where applicable). The data decides whether a structured-sensing fallback belongs in the primary path, and whether a text-only mode is viable enough to broaden model support.
2. **Raise the model image width from 476 to 768** and expose it as configuration once the eval baseline exists.
3. **Bounded composite actions** (`scroll-until` with a swipe cap) once the eval identifies where composite steps outperform single-atomic-step chains.
4. **Wi-Fi ADB pairing and multi-device selection.**
