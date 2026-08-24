# mobile-skill project plan

## Goal

Provide reliable screenshot-driven Android GUI navigation for local coding Agents.

## Supported today

- USB ADB device discovery, validation, and first-run onboarding (`msk onboard`)
- Screenshot capture, JPEG compression, and normalized `0..999` coordinate mapping
- Tap, double-tap, long-press, swipe, wait, text input, key presses, app launch
- Installed-app inventory (`msk apps list`) as a text-based fallback when a package name is unknown
- Session lease with observation-staleness protection, pause/resume, human takeover, and idle-timeout cleanup
- Skill installation from a source checkout for registered harnesses (Codex and Claude Code today; `msk install --list`) plus a generic `msk install --home <dir>` path for any agent with the same `skills/` convention
- Automatic cleanup of stopped/idle sessions and orphaned screenshots

## Not supported

- iPhone (deferred until the Android side is proven)
- Wi-Fi ADB, multi-device selection
- Deep Links
- OCR, UI trees, accessibility trees, element selectors
- Daemon mode, remote devices, multi-Agent scheduling
- Automatic handling of login, secrets, permissions, or payments

## Invariants

1. One CLI command performs one observation or one atomic action.
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

1. **Automated test suite.** Pure-function tests for coordinate mapping, IME dispatch, cleanup, and observation staleness — locks the harness contract so every change no longer requires a real-device run.
2. **Evaluation matrix.** ~20 representative tasks × 2–3 frontier models × configurations (476px vision, 768px vision, accessibility-tree channel where applicable). The data decides whether a structured-sensing fallback belongs in the primary path, and whether a text-only mode is viable enough to broaden model support.
3. **Raise the model image width from 476 to 768** and expose it as configuration once the eval baseline exists.
4. **Bounded composite actions** (`scroll-until` with a swipe cap) once the eval identifies where composite steps outperform single-atomic-step chains.
5. **Wi-Fi ADB pairing and multi-device selection.**
