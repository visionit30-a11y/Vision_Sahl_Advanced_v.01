# CI enforcement verification (SEC-2E-02)

Verified on 2026-09-21 against `visionit30-a11y/Vision_Sahl_Advanced_v.01`.

## Protected branches

Both `main` and `develop` use legacy branch protection with the same enforced contract:

- pull requests are required before merge;
- one approving review is required;
- required status checks are strict, so the branch must be up to date before merge;
- protection applies to administrators;
- force pushes are disabled;
- branch deletion is disabled;
- no bypass actor is configured.

The exact required checks are:

1. `API (lint, types, tests, database)`
2. `Web (lint, types, tests, real browser, build)`
3. `No committed secrets`
4. `Python dependency audit`
5. `npm dependency audit`

Normal direct-push attempts and `--force-with-lease` attempts against both protected branches were rejected server-side. The attempts did not change either protected branch.

## Blocked-merge proof

Disposable PR [#18](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/pull/18) targeted `develop` and was never merged.

- Commit `b4de06eebc9eaf64790df174dfe6e5c1f5537e75` introduced one temporary verification-only failing API test.
- Actions run [34441194119](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/actions/runs/34441194119) recorded the required API check as `FAILURE`, which left merge blocked.
- Commit `f3d3f18d3987258765132ba160d39a3973cbd343` removed the synthetic test completely. The PR's final file diff was empty.
- The subsequent run proved API, Web, secret scanning, and Python dependency audit successful. The npm audit check exposed the real advisory `GHSA-82fw-gwwq-j7x9`, so GitHub continued to block merge rather than soft-pass it.
- PR #18 was closed without merge and left no verification artifact in `develop` or `main`.

## Green-check proof

PR [#19](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/pull/19) resolves `GHSA-82fw-gwwq-j7x9` by upgrading `vitest` and `@vitest/mocker` to `5.0.0`. At HEAD `734ef4c63067f292be7fdbea27ebc1ed8d0ee782`, both the push and pull-request runs completed all five required checks successfully.

- npm audit reported zero vulnerabilities.
- Vitest passed 29 files and 226 tests.
- Playwright passed all 8 real FastAPI/PostgreSQL browser tests.
- The production frontend build passed.
- GitHub reported the PR conflict-free and mergeable.

The PR remains unmerged. A merge still requires one approval and an up-to-date branch because those controls are enforced independently of check success.

## Result

SEC-2E-02 is verified: failed required checks block merge, successful checks restore technical mergeability, approval and strict-update rules remain enforced, administrators are covered, destructive branch operations are disabled, and the disposable proof did not reach either protected branch.
