# Phase 2E — G6 final review

Date: 2026-09-08. Branch: `codex/phase-2e-security-hardening`.
Baseline: `phase-2d-baseline` / `1677d114c5736c4032b862ddf0b58517490d1317`.
Reviewed G5 HEAD: `1bad2208347933f42f837c977d92fb601ee3aa45`.
Migration head: `0016_security_audit_retention`.

## Item-by-item evidence

The numbered acceptance matrix remains authoritative. G6 reuses the owner's accepted full
local proof; documentation-only changes do not justify rerunning the same local suites.
GitHub must run the full workflow against the final pushed HEAD independently.

| Criteria | Evidence reviewed | Result |
| --- | --- | --- |
| 1, 4, 5, 7, 8 | G2 typed catalog, DB validation, append-only ACL, rollback and isolation proofs | PASS |
| 2, 3, 5, 6 | G3 auth/role/denial wiring, trusted IDs and mandatory atomic events | PASS |
| 9, 10, 11, 12, 13 | G3 HTTP validation, exception chains, SQL parameter and real Uvicorn emission canaries | PASS |
| 14 | G4 real PostgreSQL cutoff, exactly-at-cutoff retention, SKIP LOCKED, bounded batches, audit rollback | PASS |
| 15 | G4 exact maintenance grants, safe runner output and isolated DB logging; operational boundaries below | PASS within authorized environment |
| 16, 17, 18 | G5 full-history/source/artifact Gitleaks and frozen dependency inventories, fail-closed scanner tests | PASS locally |
| 19 | Workflow contracts verified; actual GitHub branch protection missing at initial G6 read | PENDING external configuration/CI |
| 20, 21 | G5 full suite and real browser/database proof, strict no-skip gates | PASS locally |
| 22 | Baseline-to-HEAD path review, approved changes and excluded reports; final remote HEAD/CI/PR | PENDING remote proof |

## Accepted local evidence

- Backend: 996 passed, no SKIP/XFAIL/XPASS.
- Frontend: 225 passed across 29 files.
- Playwright Chromium: 7/7 passed through frontend5187, actual FastAPI8010 and disposable PostgreSQL17.
- Gitleaks8.30.1: history/merge diffs, 453 tracked files and 26 approved text artifacts passed.
- pip-audit2.10.1: 50 project +1 build +28 scanner entries, zero advisories.
- npm audit11.11.0: 350 lock nodes, zero advisories.
- Ruff/Mypy/ESLint/TypeScript/Prettier/build/Alembic/round-trip/RLS/ownership/catalog/cleanup: PASS.
- G4 retention regressions included in the full Backend count; no double-counting earlier targeted runs.
- Sanitized local evidence: ignored `_logs/phase2e-g5-final-results.json` and G2–G5 reports.

## Operational boundary (criterion15)

The authorized implementation and isolated proof are complete. No production deployment,
scheduler, maintenance LOGIN/credential, purge, proxy change or backup configuration is authorized.
The dedicated maintenance capability remains NOLOGIN, owns nothing, and receives only auth schema
USAGE and exact EXECUTE on `auth.prune_security_events(integer)`; runtime cannot execute it.

Before any future deployment, the operator must separately approve the maintenance identity and
bounded schedule, verify actual PostgreSQL/proxy logs do not retain sensitive parameters/bodies,
validate backup/replica/export retention and the proposed 30-day backup limit, and prove purge
completion before restored data serves traffic. Application TTL alone cannot prove deletion from
backups or unreviewed logging systems. These are deployment prerequisites, not claims made by this PR.
The approved runbook is [G4 retention](phase-2e-g4-retention.md); ADR-0025 retains the production boundary.

## Scope and Git

Baseline comparison contains only approved Phase2E audit/redaction, narrow auth coordination,
retention, scanner/CI, tests and documentation. G3's internal password orchestration and four
specific database functions were expressly approved; no new auth HTTP endpoints or redesign.
Role audit observes mutations under existing RLS; no policy/FORCE RLS/TenantContext/RBAC redesign.
Frontend, Design System, UI settings, BRD/SRS and project dependency lockfiles are unchanged.
No Business Modules, Phase3, SIEM, production deployment or retention execution on dev/production.

`docs/TECHNICAL_PROJECT_HANDOVER_REPORT.md` and the owner's Arabic report directory remain
untracked and excluded. No merge, tag, branch deletion or history rewrite is authorized in G6.

## GitHub acceptance

Initial public API check: main and develop both at the approved baseline, `protected=false`,
with no repository rulesets. Workflow YAML alone is not represented as enforced branch protection.
The proposed exact required checks are API, Web, No committed secrets, Python dependency audit,
and npm dependency audit, with strict up-to-date checks. The owner explicitly approved these exact required checks with strict updating in G6.
Application is blocked because Git Credential Manager currently supplies no GitHub credential;
the available browser is also signed out. Public reads succeeded and confirmed neither branch
was modified. No token was printed, persisted to a file or included in Git configuration.
Reauthenticate locally before applying the approved settings, pushing or creating the PR.

Final source run and PR links/results must be recorded after successful execution. Source and
PR-triggered runs are distinct; neither constitutes a future merge-commit CI result.

## References

- [Acceptance matrix](phase-2e-exit-criteria.md)
- [Audit contract](adr/ADR-0025-security-audit-and-hardening.md)
- [G2 proof](phase-2e-g2-verification.md)
- [G3 proof](phase-2e-g3-verification.md)
- [G4 proof](phase-2e-g4-retention.md)
- [G5 proof](phase-2e-g5-verification.md)

The G6 local change is documentation only. No new security functions or local full-suite rerun.
