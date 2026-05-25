# Web Control Panel — Issues

10 vertical-slice issues bẻ từ [PRD.md](../PRD.md) qua `/to-issues` skill.

## Dependency graph

```
0001 (Skeleton)
  └── 0002 (Auth)
        ├── 0003 (Admin user CRUD)        — AFK, parallel với 0004 + 0005
        ├── 0004 (User profile + Telegram service)
        │     └── ─┐
        ├── 0005 (Process CRUD, list mode only)
        │     └── ─┤
        │         0006 (Worker end-to-end)
        │               ├── 0007 (CMC Top N + resolver)
        │               ├── 0008 (Signal history UI)
        │               └── 0009 (One-shot "Quét ngay")
        │                     └── 0010 (Tailscale + systemd deployment)  ← HITL
```

## Order suggestion

Critical path (longest chain): 0001 → 0002 → 0005 → 0006 → 0009 → 0010.

Parallel possible after 0002 finishes:
- 0003 (Admin CRUD)
- 0004 (User profile + Telegram service)
- 0005 (Process CRUD)

Parallel possible after 0006 finishes:
- 0007 (CMC Top N)
- 0008 (Signal history UI)
- 0009 (One-shot)

## Triage labels

- **ready-for-agent** (9 issues): 0001-0009 — AFK agent có thể pickup và merge.
- **ready-for-human** (1 issue): 0010 — HITL, cần operator có VPS access.

## How to consume

Mỗi issue file là 1 contract cho 1 PR. Theo CLAUDE.md flow:

```
1. Pick 1 issue file (theo dependency order).
2. /grill-with-docs với issue body để align (optional).
3. /tdd cho deep modules.
4. Implement vertical slice.
5. PR với link tới issue file path trong description.
6. Khi merge: cập nhật issue `status: done` (hoặc delete file + add row vào CHANGELOG).
```

Recommend `/tdd` cho 0002, 0004, 0005, 0006, 0007, 0008, 0009 (logic-heavy slices có deep modules).
Skip TDD ép buộc cho 0001 (pure infra) và 0010 (deployment scripts).
