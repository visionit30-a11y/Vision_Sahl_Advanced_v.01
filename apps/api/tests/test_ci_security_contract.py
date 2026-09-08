"""G5 workflow guards reject silent gaps in the blocking security proof."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
ACTION_PINS = {
    "actions/checkout": "11bd71901bbe5b1630ceea73d27597364c9af683",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/setup-node": "49933ea5288caeca8642d1e84afbd3f7d6820020",
    "astral-sh/setup-uv": "c771a70e6277c0a99b617c7a806ffedaca235ff9",
}


def _content() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _jobs(content: str) -> dict[str, str]:
    jobs = re.split(r"(?m)^  ([a-z][a-z-]*):\n", content.split("\njobs:\n", 1)[1])
    return dict(zip(jobs[1::2], jobs[2::2], strict=True))


def _assert_no_soft_pass(content: str) -> None:
    assert "continue-on-error" not in content
    assert "|| true" not in content
    assert "pull_request_target" not in content
    assert not re.search(r"(?m)^\s+(?:paths|paths-ignore|branches-ignore):", content)
    # No job/step condition may silently bypass a required gate. Cleanup and
    # artifact verification deliberately run after failures as well.
    conditions = re.findall(r"(?m)^\s+if:\s*(.+)$", content)
    assert all(value == "always()" for value in conditions)
    for command in ("npm audit fix", "--ignore-vuln", "--ignore-gitleaks-allow=false"):
        assert command not in content


def test_ci_security_gates_have_no_soft_pass_or_conditional_exclusions() -> None:
    _assert_no_soft_pass(_content())


@pytest.mark.parametrize(
    "weakening",
    [
        "        continue-on-error: true\n",
        "        if: github.event_name == 'push'\n",
        "        run: python audit.py || true\n",
        "    paths-ignore: ['apps/api/**']\n",
        "        run: npm audit fix\n",
    ],
)
def test_workflow_guard_detects_security_gate_weakening(weakening: str) -> None:
    with pytest.raises(AssertionError):
        _assert_no_soft_pass(_content() + weakening)


def test_ci_actions_are_verified_immutable_pins_and_read_only() -> None:
    content = _content()
    assert "permissions:\n  contents: read\n" in content
    assert not re.search(r"(?m)^\s+(?:contents|actions|packages|id-token): write", content)
    actions = re.findall(r"(?m)^\s+- uses: ([^@\s]+)@([^\s]+)", content)
    assert actions
    for action, commit in actions:
        assert action in ACTION_PINS
        assert commit == ACTION_PINS[action]
    for job in _jobs(content).values():
        assert re.search(r"(?m)^    timeout-minutes: [1-9][0-9]?\s*$", job)
        checkouts = re.findall(
            r"(?ms)^      - uses: actions/checkout@[^\n]+\n(.*?)(?=^      - |\Z)", job
        )
        assert len(checkouts) == 1
        assert "persist-credentials: false" in checkouts[0]


def test_current_branch_and_all_promotions_trigger_the_security_workflow() -> None:
    content = _content()
    assert 'branches: [main, develop, "feature/**", "codex/**"]' in content
    assert "pull_request:\n    branches: [main, develop]" in content


def test_secret_gate_scans_full_history_and_current_tracked_source() -> None:
    secrets = _jobs(_content())["secrets"]
    assert "fetch-depth: 0" in secrets
    assert "gitleaks-gate.py source" in secrets
    assert "--output-dir" in secrets


def test_python_audit_is_separate_hash_locked_and_covers_build_inventory() -> None:
    jobs = _jobs(_content())
    audit = jobs["python-audit"]
    assert "uv venv --python python" in audit
    assert "uv pip sync" in audit
    assert "--require-hashes .github/ci/pip-audit.lock.txt" in audit
    assert "dependency-audit.py python" in audit
    assert "--audit-python" in audit
    assert 'version: "0.12.10"' in audit
    for name in ("api", "web"):
        sync_commands = re.findall(r"(?m)^\s+run: (uv sync .+)$", jobs[name])
        assert sync_commands
        for command in sync_commands:
            assert "--frozen" in command
            assert "--config-file ../../.github/ci/uv-build.toml" in command
            assert "--build-constraint " not in command


def test_npm_audit_uses_checksum_pinned_tool_without_project_lock_writes() -> None:
    jobs = _jobs(_content())
    assert "dependency-audit.py npm" in jobs["npm-audit"]
    for name in ("web", "npm-audit"):
        job = jobs[name]
        assert "node-version-file: apps/web/.nvmrc" in job
        assert "npm-11.11.0.tgz" in job
        assert "hashlib.sha512(archive).digest()" in job
        assert '--prefix "$RUNNER_TEMP/pinned-npm" --no-package-lock --ignore-scripts' in job
        assert "npm audit fix" not in job
    assert "npm ci --no-audit --no-fund" in jobs["web"]


def test_full_tests_quality_and_migration_output_use_closed_capture_boundary() -> None:
    content = _content()
    wrapped = re.findall(r"security-command\.py .*?--name ([a-z-]+) --", content)
    required = {
        "ruff",
        "ruff-format",
        "mypy",
        "security-tool-lint",
        "security-tool-format",
        "security-tool-types",
        "backend-tests",
        "migration-upgrade",
        "migration-downgrade",
        "migration-reupgrade",
        "migration-check",
        "migration-head",
        "database-cleanup",
        "browser-migration",
        "web-lint",
        "web-typecheck",
        "prettier",
        "web-test",
        "browser-tests",
        "web-build",
    }
    assert required <= set(wrapped)
    assert "pytest --strict-security-gates --tb=short" in content
    assert "alembic downgrade base" in content
    assert "alembic check" in content
    assert "npm run format:check" in content
    assert "bash ../../.github/ci/run-browser-gate.sh" in content
    assert "--maxfail" not in content
    assert "--lf" not in content


@pytest.mark.parametrize("job_name", ["api", "web"])
def test_artifact_scans_remain_blocking_after_a_test_failure(job_name: str) -> None:
    job = _jobs(_content())[job_name]
    assert re.search(
        r"name: Scan approved [^\n]+\n        if: always\(\)\n"
        r"        run: python .*gitleaks-gate\.py artifacts",
        job,
    )
    assert '--scan-path "$RUNNER_TEMP/security-logs"' in job
    assert "upload-artifact" not in job
    if job_name == "web":
        assert '"security-logs/production-dist"' in job
        assert '".js", ".css", ".html", ".json", ".map", ".txt"' in job
        assert "artifact.is_symlink()" in job
        assert "cp -R dist" not in job
        assert (
            'cp test-results/.last-run.json "$RUNNER_TEMP/security-logs/browser-status.json"' in job
        )
        assert "cp -R test-results" not in job
