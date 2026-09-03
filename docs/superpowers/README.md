# Superpowers Development Guide

This directory keeps the project-level artifacts used with the Superpowers
development workflow. The Superpowers plugin itself is installed in each
developer's Codex environment and is intentionally not copied into this
repository.

## Directory Layout

- `specs/`: approved product, workflow, UX, and architecture designs.
- `plans/`: executable implementation plans derived from an approved spec.

Use ISO dates and a descriptive topic in new filenames, for example:

```text
specs/2026-09-01-task-submission-design.md
plans/2026-09-01-task-submission.md
```

## Working Flow

1. Use `brainstorming` to understand a requested change and obtain approval.
2. For multi-step work, document the approved design in `specs/`.
3. Create the implementation plan in `plans/`.
4. Implement with `test-driven-development` and focused tests.
5. Run `./scripts/verify.sh` before reporting a repository-wide change as
   complete.

## Shared Verification

`scripts/verify.sh` runs the standard local quality gate:

```bash
./scripts/verify.sh
```

It compiles the backend, runs `backend/tests`, builds the frontend, and checks
the working diff for whitespace errors. It does not alter database data, call
RunPod, push Git commits, or deploy to ECS.
