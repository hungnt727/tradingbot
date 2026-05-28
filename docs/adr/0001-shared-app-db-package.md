# Shared `app_db/` package for Phase 6 ORM models

**Date:** 2026-05-26
**Status:** accepted
**Context:** Phase 6 Web Control Panel, slice 0 skeleton ([`.scratch/web-control-panel/issues/0001-skeleton.md`](../../.scratch/web-control-panel/issues/0001-skeleton.md))

Phase 6 introduces two services that share one Postgres database (`tradingbot_app`): the FastAPI web app (`web/`) and the Worker daemon (`worker/`). Both read/write the same tables (`users`, `processes`, `signals`). We had to decide where the shared SQLAlchemy `declarative_base()` and ORM models live.

We chose to put them in a neutral top-level package `app_db/` (peer of `web/` and `worker/`), imported by both services and by `migrations_app/env.py` for autogenerate.

## Considered options

- **A. `web/models/`** — models owned by the web service; worker imports `from web.models import ...`. Rejected because it makes `web/` a non-deletable dependency of `worker/` and creates an asymmetric ownership that the PRD explicitly contradicts ("they communicate only through Postgres").
- **B. `app_db/` shared package (chosen)** — schema is shared infrastructure, owned by neither service. Both `web/` and `worker/` import from it as peers.
- **C. Duplicate models in each service** — rejected immediately; double-source-of-truth for schema would diverge.

## Consequences

- `migrations_app/env.py` sets `target_metadata = app_db.base.Base.metadata`.
- New ORM model = add a file under `app_db/models/`, import it into `app_db/models/__init__.py`, run `alembic -c alembic_app.ini revision --autogenerate`.
- Worker and web both pull schema changes by upgrading the same DB — no per-service migration story.
- Mechanical to reverse (mv package + update imports), but touches every web/worker module that does ORM work — moderate cost.
