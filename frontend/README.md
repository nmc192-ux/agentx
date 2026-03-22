# ⚠️ Deprecated — Use `ui/` Instead

This directory (`frontend/`) is **no longer maintained**.

All pages, components, and library code have been consolidated into the `ui/` directory as part of **Sprint 3, Step 3.1 (Frontend Consolidation)**.

## What to Use

```bash
# Active frontend
cd ../ui
npm install
npm run dev
```

## What Was Migrated

See [`../MIGRATION.md`](../MIGRATION.md) for a complete list of:
- Pages merged into `ui/`
- Components merged into `ui/`
- API methods added to `ui/lib/api.ts`
- Items intentionally dropped and why

## Key Differences

| `frontend/` (this dir) | `ui/` (active) |
|------------------------|----------------|
| NextAuth sessions | localStorage JWT |
| `TwitterShell` layout | `AppShell` layout |
| Zustand global store | Local `useState` |
| No DevPanel | DevPanel overlay (dev mode) |
| No WebSocket integration | Live WebSocket feed + agent graph |

## Do Not

- Add new features here
- Fix bugs here
- Deploy this directory

All development goes into `ui/`.
