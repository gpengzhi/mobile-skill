# mobile-skill project plan

## Goal

Provide reliable screenshot-driven Android GUI navigation for local coding Agents.

## Current Scope

Supported:

- USB ADB device discovery and validation
- Screenshot capture, JPEG compression, and normalized `0..999` coordinate mapping
- Tap, double-tap, long-press, swipe, wait, text input, key presses, and App launch
- Session lease, stale observation protection, pause/resume, and human takeover
- Codex and Claude Code Skill installation from a source checkout
- Automatic cleanup of stopped Sessions and screenshots

Not supported:

- iPhone
- Deep Links
- OCR, UI trees, accessibility trees, or element selectors
- Daemon mode, remote devices, or multi-Agent scheduling
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
Session + observation state
        ↓
      Android ADB
        ↓
   Real Android phone
```

## Next Priorities

1. Test more Android vendors, versions, screen sizes, and orientations.
2. Improve recovery from keyboard, loading, dialog, and navigation failures.
3. Establish repeatable Claude Code visual navigation checks.
4. Add a lightweight device lock only when real concurrency requires it.
