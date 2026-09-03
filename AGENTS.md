# DOBEDUB STUDIO v4 Agent Guide

## Scope

This repository contains the DOBEDUB Studio v4 frontend, FastAPI backend,
workflow definitions, database migrations, and deployment documentation.
Treat existing uncommitted changes as user work unless the current request
explicitly covers them.

## Superpowers Workflow

Use the installed Superpowers skills for repository work:

1. Start feature, UX, and behavior changes with `brainstorming`.
2. Record approved multi-step designs in `docs/superpowers/specs/`.
3. Record implementation plans in `docs/superpowers/plans/` before substantial
   implementation work.
4. Use `test-driven-development`: add a focused failing test before production
   behavior changes, then make it pass with the smallest scoped edit.
5. Before reporting completion, use `verification-before-completion` and run
   `./scripts/verify.sh` when the full suite is appropriate.

The Superpowers plugin is installed per Codex user environment; it is not
vendored into this repository. New contributors must install or enable the
plugin in Codex separately.

## Project Commands

```bash
# Build the React bundle served by FastAPI.
npm run build

# Start the stable local application address.
npm start

# Run the repository verification suite.
./scripts/verify.sh
```

The local app normally runs at `http://127.0.0.1:8790/studio/access/login`.
Use an unused port only when another local server is intentionally running.

## Engineering Constraints

- Preserve workflow JSON and `.paramconfig.json` compatibility unless the task
  explicitly changes the workflow contract.
- Keep RunPod submissions reproducible: preserve input asset IDs, prompt text,
  workflow settings, and submission snapshots.
- For database schema changes, add an Alembic migration. Do not mutate
  production RDS data in application code.
- Keep secrets out of source control and documentation examples.
- Build frontend changes with `npm run build`; compile backend changes with
  `python3 -m compileall -q backend/app`.
- Do not commit, push, or deploy unless the user explicitly asks.
