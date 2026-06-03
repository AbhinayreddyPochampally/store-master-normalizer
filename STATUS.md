# Project Status

**Version:** 1.0.0 (see the Versioning section of README.md)
**State:** Production — runnable locally and deployed on Railway.
**Last updated:** 2026-06-03

## Summary

The Store Master Normalizer is complete and in use for eight brands:
Pantaloons, PF (Planet Fashion), Tasva, TCNS, Shantanu and Nikhil, Ownd,
House of Masaba, and Jaypore.

## What works

- Per-brand mapping and the reconciliation cascade (Refresh / Migrated /
  Reactivated / New) with the inactivation pass (closed / bad-email).
- 44-column output schema plus the three engine-derived status columns
  (Data Modified, Deactivated Stores, Reactivated Stores).
- Region as the full uppercase word; Store Zone as the 4-character code.
- Independent verifier (PASS / FAIL).
- Web UI (FastAPI) and command-line entry point.
- Regression test suite — 36 tests passing.

## Run and deploy

- Local: `python -m web.run` (see README.md).
- Hosted: Railway, built from the Dockerfile (see
  docs/04_SLD_System_Level_Design.docx).

## Documentation

Handover documentation is under `docs/`. Version policy is in the
Versioning section of README.md; change history is in CHANGELOG.md.
