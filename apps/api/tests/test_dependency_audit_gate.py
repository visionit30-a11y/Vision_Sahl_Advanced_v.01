"""G5 dependency gates fail closed without exposing scanner or exception payloads."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def gate() -> Any:
    path = Path(__file__).resolve().parents[3] / ".github/ci/dependency-audit.py"
    spec = importlib.util.spec_from_file_location("dependency_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    for name in ("apps/api/uv.lock", "apps/web/package-lock.json"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original-lock")
    return tmp_path


def result(data: Any, code: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["scanner"], code, json.dumps(data), stderr)


def python_payload() -> dict[str, Any]:
    return {"dependencies": [{"name": "example", "version": "1.2.3", "vulns": []}], "fixes": []}


def npm_payload() -> dict[str, Any]:
    return {
        "auditReportVersion": 2,
        "vulnerabilities": {},
        "metadata": {
            "dependencies": {"total": 1},
            "vulnerabilities": {
                "info": 0,
                "low": 0,
                "moderate": 0,
                "high": 0,
                "critical": 0,
                "total": 0,
            },
        },
    }


def test_python_complete_inventory_succeeds(gate: Any) -> None:
    assert gate.python_report(result(python_payload()), {("example", "1.2.3")}) == []


@pytest.mark.parametrize(
    "fault", ["skip", "missing", "extra", "duplicate", "version", "fix", "status"]
)
def test_python_rejects_partial_skipped_or_inconsistent_inventory(gate: Any, fault: str) -> None:
    data = python_payload()
    code = 0
    if fault == "skip":
        data["dependencies"][0]["skip_reason"] = "not audited"
    elif fault == "missing":
        data["dependencies"] = []
    elif fault == "extra":
        data["dependencies"].append({"name": "other", "version": "1.0", "vulns": []})
    elif fault == "duplicate":
        data["dependencies"] *= 2
    elif fault == "version":
        data["dependencies"][0]["version"] = "2.0"
    elif fault == "fix":
        data["fixes"] = [{"name": "example"}]
    else:
        code = 1
    with pytest.raises(gate.GateFailure):
        gate.python_report(result(data, code), {("example", "1.2.3")})


def test_python_advisory_is_blocking_and_only_projects_allowed_fields(gate: Any) -> None:
    data = python_payload()
    data["dependencies"][0]["vulns"] = [
        {
            "id": "CVE-2026-12345",
            "aliases": ["PYSEC-2026-123"],
            "fix_versions": ["1.2.4"],
            "description": "CANARY_PRIVATE_PAYLOAD",
            "severity": "high",
        }
    ]
    findings = gate.python_report(result(data, 1), {("example", "1.2.3")})
    assert findings[0]["fix_versions"] == ["1.2.4"]
    assert findings[0]["advisory"] == "CVE-2026-12345"
    assert "CANARY_PRIVATE_PAYLOAD" not in json.dumps(findings)
    with pytest.raises(gate.GateFailure):
        gate.python_report(result(data), {("example", "1.2.3")})


@pytest.mark.parametrize("field", ["id", "aliases", "fix_versions"])
def test_python_untrusted_advisory_metadata_rejected(gate: Any, field: str) -> None:
    issue: dict[str, Any] = {"id": "CVE-2026-12345", "aliases": [], "fix_versions": []}
    issue[field] = "CANARY_PRIVATE_PAYLOAD" if field == "id" else ["CANARY_PRIVATE_PAYLOAD"]
    data = python_payload()
    data["dependencies"][0]["vulns"] = [issue]
    with pytest.raises(gate.GateFailure):
        gate.python_report(result(data, 1), {("example", "1.2.3")})


def test_npm_complete_inventory_succeeds(gate: Any) -> None:
    assert (
        gate.npm_report(result(npm_payload()), {"node_modules/example": ("example", "1.2.3")}) == []
    )


@pytest.mark.parametrize("fault", ["count", "error", "schema", "negative", "total", "status"])
def test_npm_rejects_incomplete_or_malformed_result(gate: Any, fault: str) -> None:
    data = npm_payload()
    code = 0
    if fault == "count":
        data["metadata"]["dependencies"]["total"] = 0
    elif fault == "error":
        data["error"] = {"message": "CANARY_PRIVATE_PAYLOAD"}
    elif fault == "schema":
        data["auditReportVersion"] = 1
    elif fault == "negative":
        data["metadata"]["vulnerabilities"]["high"] = -1
    elif fault == "total":
        data["metadata"]["vulnerabilities"]["total"] = 1
    else:
        code = 1
    with pytest.raises(gate.GateFailure):
        gate.npm_report(result(data, code), {"node_modules/example": ("example", "1.2.3")})


def test_npm_advisory_projects_no_title_or_description(gate: Any) -> None:
    data = npm_payload()
    data["metadata"]["vulnerabilities"].update(high=1, total=1)
    data["vulnerabilities"] = {
        "example": {
            "name": "example",
            "severity": "high",
            "nodes": ["node_modules/example"],
            "fixAvailable": {"name": "example", "version": "1.2.4", "isSemVerMajor": False},
            "via": [
                {
                    "url": "https://github.com/advisories/GHSA-2345-6789-cfgh",
                    "title": "CANARY_PRIVATE_PAYLOAD",
                    "range": "CANARY_PRIVATE_PAYLOAD",
                }
            ],
        }
    }
    findings = gate.npm_report(result(data, 1), {"node_modules/example": ("example", "1.2.3")})
    assert findings[0]["fix_versions"] == ["1.2.4"]
    assert "CANARY_PRIVATE_PAYLOAD" not in json.dumps(findings)


@pytest.mark.parametrize("parser", ["python", "npm"])
def test_scanner_transport_failure_cannot_be_success(gate: Any, parser: str) -> None:
    with pytest.raises(gate.GateFailure):
        if parser == "python":
            gate.python_report(
                result(python_payload(), 2, "CANARY_PRIVATE_PAYLOAD"), {("example", "1.2.3")}
            )
        else:
            gate.npm_report(
                result(npm_payload(), 2, "CANARY_PRIVATE_PAYLOAD"),
                {"node_modules/example": ("example", "1.2.3")},
            )


def test_duplicate_json_keys_rejected(gate: Any) -> None:
    with pytest.raises(gate.GateFailure):
        gate.strict_json('{"dependencies": [], "dependencies": []}')


@pytest.mark.parametrize("failure", ["network", "malformed", "timeout", "missing_tool"])
def test_gate_errors_emit_only_fixed_reason_and_preserve_locks(
    gate: Any,
    repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    marker = "CANARY_PRIVATE_PAYLOAD"
    original = gate.lock_hashes(repository)

    def fail(*args: Any) -> Any:
        if failure == "network":
            raise OSError(marker)
        if failure == "malformed":
            raise ValueError(marker)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(marker, 1, output=marker, stderr=marker)
        raise FileNotFoundError(marker)

    monkeypatch.setattr(gate, "audit_python_fn", fail)
    output = tmp_path / "reports"
    assert gate.run("python", output, "python", "uv", "node", "npm", repository) == 1
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err
    assert marker not in (output / "dependency-python.json").read_text()
    assert gate.lock_hashes(repository) == original
    assert json.loads(captured.out)["reason"] == "gate_failed"


@pytest.mark.parametrize("scanner_fails", [False, True])
def test_lock_mutation_fails_even_if_scanner_passes_or_errors(
    gate: Any,
    repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scanner_fails: bool,
) -> None:
    def mutate(*args: Any) -> dict[str, Any]:
        (repository / "apps/api/uv.lock").write_text("changed")
        if scanner_fails:
            raise RuntimeError("CANARY_PRIVATE_PAYLOAD")
        return {"status": "PASS"}

    monkeypatch.setattr(gate, "audit_python_fn", mutate)
    assert gate.run("python", tmp_path / "reports", "python", "uv", "node", "npm", repository) == 1
    record = json.loads(capsys.readouterr().out)
    assert record["reason"] == "lockfiles_changed"
    assert record["project_lockfiles_unchanged"] is False


def test_runtime_environment_drops_credentials_and_registry_overrides(
    gate: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in [
        "DATABASE_URL",
        "PGPASSWORD",
        "GITHUB_TOKEN",
        "NPM_TOKEN",
        "PIP_INDEX_URL",
        "HTTPS_PROXY",
        "npm_config_omit",
        "UV_INDEX_URL",
    ]:
        monkeypatch.setenv(key, "CANARY_PRIVATE_PAYLOAD")
    env = gate.environment(tmp_path)
    assert "CANARY_PRIVATE_PAYLOAD" not in json.dumps(env)
    assert env["UV_PYTHON_DOWNLOADS"] == "never"


def test_universal_uv_inventory_includes_non_host_marker_packages(gate: Any) -> None:
    inventory = gate.uv_inventory(gate.ROOT)
    assert any(name == "uvloop" for name, _ in inventory)
    assert ("sahl-api", "0.1.0") not in inventory
    assert len(inventory) == 50


def test_build_and_scanner_locks_are_exact_and_hash_pinned(gate: Any) -> None:
    assert gate.build_inventory(gate.ROOT) == {("setuptools", "84.0.0")}
    tools = gate.requirements_inventory(gate.ROOT / ".github/ci/pip-audit.lock.txt")
    assert ("pip-audit", "2.10.1") in tools


@pytest.mark.parametrize(
    "content",
    [
        "example>=1.0\n",
        "example==1.0\n",
        "-r other.txt\n",
        "example==1.0 ; sys_platform=='win32'\n",
    ],
)
def test_tool_lock_rejects_unpinned_unhashed_or_marker_hidden_inventory(
    gate: Any,
    tmp_path: Path,
    content: str,
) -> None:
    path = tmp_path / "tool.lock"
    path.write_text(content)
    with pytest.raises(gate.GateFailure):
        gate.requirements_inventory(path)


def test_build_contract_expansion_requires_inventory_review(
    gate: Any,
    tmp_path: Path,
) -> None:
    path = tmp_path / "apps/api/pyproject.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        '[build-system]\nrequires=["setuptools>=68", "wheel"]\n'
        'build-backend="setuptools.build_meta"\n'
    )
    with pytest.raises(gate.GateFailure, match="build_inventory_changed"):
        gate.build_inventory(tmp_path)


def test_no_automatic_fix_or_ignored_vulnerability_flags(gate: Any) -> None:
    source = Path(gate.__file__).read_text()
    for forbidden in ('"--fix"', '"--ignore-vuln"', '"--skip-editable"', '"--skip-audit"'):
        assert forbidden not in source
    assert '"--frozen"' in source
    assert '"--include=dev"' in source and '"--include=optional"' in source
    assert '"--include=peer"' in source and '"--strict"' in source


@pytest.mark.parametrize("parser", ["python", "npm"])
def test_scanner_diagnostics_fail_closed_even_with_complete_success_json(
    gate: Any, parser: str
) -> None:
    with pytest.raises(gate.GateFailure, match="scanner_diagnostics"):
        if parser == "python":
            gate.python_report(
                result(python_payload(), stderr="WARNING skipped CANARY_PRIVATE_PAYLOAD"),
                {("example", "1.2.3")},
            )
        else:
            gate.npm_report(
                result(npm_payload(), stderr="error CANARY_PRIVATE_PAYLOAD"),
                {"node_modules/example": ("example", "1.2.3")},
            )


def test_cli_invalid_arguments_never_echo_input(
    gate: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gate.main(["python", "--unknown", "CANARY_PRIVATE_PAYLOAD"]) == 1
    output = capsys.readouterr()
    assert "CANARY_PRIVATE_PAYLOAD" not in output.out + output.err
    assert json.loads(output.out)["reason"] == "invalid_arguments"


def test_unrecognized_gate_exception_is_redacted(
    gate: Any,
    repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*args: Any) -> Any:
        raise gate.GateFailure("CANARY_PRIVATE_PAYLOAD")

    monkeypatch.setattr(gate, "audit_python_fn", fail)
    assert gate.run("python", tmp_path / "reports", "python", "uv", "node", "npm", repository) == 1
    output = capsys.readouterr()
    assert "CANARY_PRIVATE_PAYLOAD" not in output.out + output.err
    assert json.loads(output.out)["reason"] == "gate_failed"


@pytest.mark.parametrize("constraint", ["setuptools>=68", "setuptools==83.0.0", "wheel==0.1"])
def test_external_uv_build_pin_must_match_audited_inventory(
    gate: Any,
    tmp_path: Path,
    constraint: str,
) -> None:
    for name in ("apps/api/pyproject.toml", ".github/ci/python-build.lock.txt"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((gate.ROOT / name).read_bytes())
    (tmp_path / ".github/ci/uv-build.toml").write_text(
        'python-preference="only-system"\npython-downloads="never"\n'
        "[extra-build-dependencies]\n"
        f'sahl-api=["{constraint}"]\n'
    )
    with pytest.raises(gate.GateFailure, match="build_inventory_changed"):
        gate.build_inventory(tmp_path)
