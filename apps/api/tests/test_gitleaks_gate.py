"""G5 secret gates fail closed and never publish scanner-controlled secret context."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    path = Path(__file__).resolve().parents[3] / ".github/ci/gitleaks-gate.py"
    spec = importlib.util.spec_from_file_location("gitleaks_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".github").mkdir()
    (repository / ".gitleaks.toml").write_text("[extend]\nuseDefault = true\n")
    (repository / ".github/security-exceptions.json").write_text(
        '{"schema_version": 1, "exceptions": []}'
    )
    for lock in module.LOCKS:
        target = repository / lock
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("locked")
    monkeypatch.setattr(module, "ROOT", repository)
    return module


def _report_run(
    monkeypatch: pytest.MonkeyPatch,
    gate: Any,
    report: object,
    *,
    code: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    raw: bool = False,
) -> list[list[str]]:
    calls = []

    def execute(args: list[str], *, payload: bytes | None = None) -> object:
        calls.append(args)
        assert args[args.index("--report-path") + 1] == "-"
        report_bytes = (str(report) if raw else json.dumps(report)).encode()
        return subprocess.CompletedProcess(args, code, stdout or report_bytes, stderr)

    monkeypatch.setattr(gate, "_run", execute)
    return calls


def test_clean_scan_requires_pinned_rules_redaction_and_no_inline_suppression(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _report_run(monkeypatch, gate, [])
    assert gate._scan(Path("scanner"), tmp_path, ["stdin"], b"safe log") == 0
    assert "--ignore-gitleaks-allow" in calls[0]
    assert "--redact=100" in calls[0]
    assert "--max-decode-depth=5" in calls[0]
    assert "--log-level=warn" in calls[0]
    assert not list(tmp_path.glob("scan-*/redacted.json"))


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_scanner_diagnostics_never_become_success_or_escape(
    gate: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    channel: str,
) -> None:
    marker = uuid.uuid4().hex.encode()
    _report_run(
        monkeypatch,
        gate,
        [],
        stdout=b"skipped " + marker if channel == "stdout" else b"",
        stderr=b"skipped " + marker if channel == "stderr" else b"",
    )
    with pytest.raises((gate.GateFailure, json.JSONDecodeError)):
        gate._scan(Path("scanner"), tmp_path, ["stdin"], marker)
    assert capsys.readouterr() == ("", "")
    assert not list(tmp_path.glob("scan-*/redacted.json"))


@pytest.mark.parametrize(
    "report,code,raw",
    [({}, 0, False), (None, 0, False), ([], 1, False), ([], 2, False), ("{broken", 0, True)],
)
def test_malformed_incomplete_or_tool_failure_is_not_success(
    gate: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    report: object,
    code: int,
    raw: bool,
) -> None:
    _report_run(monkeypatch, gate, report, code=code, raw=raw)
    with pytest.raises((gate.GateFailure, json.JSONDecodeError)):
        gate._scan(Path("scanner"), tmp_path, ["stdin"], b"safe log")


@pytest.mark.parametrize("change", ["unredacted", "invalid_rule", "invalid_line", "invalid_file"])
def test_malformed_finding_fails_closed(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: str
) -> None:
    record: dict[str, object] = {
        "RuleID": "generic-api-key",
        "File": "safe.txt",
        "StartLine": 1,
        "Secret": "REDACTED",
    }
    key, value = {
        "unredacted": ("Secret", uuid.uuid4().hex),
        "invalid_rule": ("RuleID", "not\na\nrule"),
        "invalid_line": ("StartLine", True),
        "invalid_file": ("File", {}),
    }[change]
    record[key] = value
    _report_run(monkeypatch, gate, [record], code=1)
    with pytest.raises(gate.GateFailure):
        gate._scan(Path("scanner"), tmp_path, ["stdin"], b"safe log")


def test_secret_in_match_path_nested_fields_is_never_emitted_or_persisted(
    gate: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = uuid.uuid4().hex
    record = {
        "RuleID": "generic-api-key",
        "File": marker,
        "StartLine": 1,
        "Secret": "REDACTED",
        "Match": marker,
        "Extra": {"nested": marker},
    }
    _report_run(monkeypatch, gate, [record], code=1)
    assert gate._scan(Path("scanner"), tmp_path, ["stdin"], marker.encode()) == 1
    assert capsys.readouterr() == ("", "")
    assert not list(tmp_path.glob("scan-*/redacted.json"))


def test_download_or_scan_exception_message_is_closed(
    gate: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = uuid.uuid4().hex

    def unavailable(*args: object) -> None:
        raise RuntimeError(marker)

    monkeypatch.setattr(gate, "_prepare", unavailable)
    assert gate.scan_stdin(marker.encode(), tmp_path) is False
    assert gate.main(["source", "--output-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err
    assert json.loads(captured.out) == {"tool": "gitleaks", "version": "8.30.1", "result": "FAIL"}


@pytest.mark.parametrize("payload", [b"", b"binary\x00dump", b"\xff"])
def test_unscannable_log_input_never_soft_passes(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: bytes
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(gate, "_prepare", lambda *args: calls.append(args))
    assert gate.scan_stdin(payload, tmp_path) is False
    assert calls == []


@pytest.mark.parametrize(
    "code,stdout,stderr,expected",
    [
        (0, b"", b"", True),
        (1, b"", b"", False),
        (2, b"", b"", False),
        (0, b"secret-context", b"", False),
        (0, b"", b"skipped-file", False),
    ],
)
def test_captured_log_gate_uses_actual_stdin_without_report_files(
    gate: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    code: int,
    stdout: bytes,
    stderr: bytes,
    expected: bool,
) -> None:
    calls = []
    monkeypatch.setattr(gate, "_prepare", lambda *args: (Path("scanner"), tmp_path))

    def run(args: list[str], *, payload: bytes | None = None) -> object:
        calls.append((args, payload))
        return subprocess.CompletedProcess(args, code, stdout, stderr)

    monkeypatch.setattr(gate, "_run", run)
    assert gate.scan_stdin(b"captured log", tmp_path) is expected
    assert calls[0][0][:2] == ["scanner", "stdin"]
    assert calls[0][1] == b"captured log"
    assert not any("report" in arg for arg in calls[0][0])
    assert not list(tmp_path.glob("scan-*"))


@pytest.mark.parametrize("setting", ["inline_config", "exception", "ignore_file"])
def test_unapproved_configuration_or_exception_is_rejected(gate: Any, setting: str) -> None:
    if setting == "inline_config":
        (gate.ROOT / ".gitleaks.toml").write_text(
            "[extend]\nuseDefault=true\n[allowlist]\npaths=[]"
        )
    elif setting == "exception":
        (gate.ROOT / ".github/security-exceptions.json").write_text(
            '{"schema_version":1,"exceptions":[{"rule":"*"}]}'
        )
    else:
        (gate.ROOT / ".gitleaksignore").touch()
    with pytest.raises(gate.GateFailure):
        gate._verify_contract()


def test_ambient_scanner_overrides_are_removed(gate: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLEAKS_CONFIG", "different.toml")
    monkeypatch.setenv("GITLEAKS_CONFIG_TOML", "bypass")
    monkeypatch.setenv("GITLEAKS_LICENSE", "private")
    assert not any(name.startswith("GITLEAKS_") for name in gate._environment())


@pytest.mark.parametrize("name", [".env", "nested/.env.production", "nested/a.pem", "nested/a.key"])
def test_nested_committed_credential_files_are_rejected(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    monkeypatch.setattr(
        gate,
        "_git",
        lambda *args: (
            b"false\n"
            if args[0] == "rev-parse"
            else b"100644 0000000000000000000000000000000000000000 0\t" + name.encode() + b"\x00"
        ),
    )
    with pytest.raises(gate.GateFailure):
        gate._source(Path("scanner"), tmp_path)


@pytest.mark.parametrize("mode", [b"120000", b"160000"])
def test_symlink_and_submodule_scopes_are_rejected(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: bytes
) -> None:
    monkeypatch.setattr(
        gate,
        "_git",
        lambda *args: (
            b"false\n"
            if args[0] == "rev-parse"
            else mode + b" 0000000000000000000000000000000000000000 0\toutside\x00"
        ),
    )
    with pytest.raises(gate.GateFailure):
        gate._source(Path("scanner"), tmp_path)


def test_shallow_checkout_is_rejected(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gate, "_git", lambda *args: b"true\n")
    with pytest.raises(gate.GateFailure):
        gate._source(Path("scanner"), tmp_path)


def test_source_snapshot_reads_current_tracked_content_and_ignores_untracked_reports(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tracked = gate.ROOT / "app.py"
    tracked.write_text("current uncommitted content")
    (gate.ROOT / "owner-report.txt").write_text("untracked private report")
    (gate.ROOT / ".env").write_text("untracked credential file")

    def git(*args: str) -> bytes:
        if args[0] == "rev-parse":
            return b"false\n"
        if args[0] == "ls-files":
            return b"100644 0000000000000000000000000000000000000000 0\tapp.py\x00"
        return b"app.py\x00"

    scopes = []

    def scan(binary: Path, output: Path, args: list[str]) -> int:
        scopes.append(args[0])
        if args[0] == "dir":
            snapshot = Path(args[1])
            assert (snapshot / "app.py").read_text() == "current uncommitted content"
            assert not (snapshot / "owner-report.txt").exists()
            assert not (snapshot / ".env").exists()
        else:
            assert args == ["git", str(gate.ROOT), "--log-opts=--all --full-history -m"]
        return 0

    monkeypatch.setattr(gate, "_git", git)
    monkeypatch.setattr(gate, "_scan", scan)
    assert gate._source(Path("scanner"), tmp_path) == (0, 1)
    assert scopes == ["git", "dir"]


def test_deleted_historical_env_file_is_rejected(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (gate.ROOT / "app.py").write_text("safe")

    def git(*args: str) -> bytes:
        if args[0] == "rev-parse":
            return b"false\n"
        if args[0] == "ls-files":
            return b"100644 0000000000000000000000000000000000000000 0\tapp.py\x00"
        return b"\nnested/.env\x00"

    monkeypatch.setattr(gate, "_git", git)
    with pytest.raises(gate.GateFailure):
        gate._source(Path("scanner"), tmp_path)


@pytest.mark.parametrize("failure", ["empty", "binary", "outside", "tool_overlap"])
def test_artifact_scope_rejects_empty_binary_unapproved_and_self_scan(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    target = gate.ROOT / "_logs/security-artifacts"
    target.mkdir(parents=True)
    output = tmp_path / "scanner-output"
    output.mkdir()
    if failure == "binary":
        (target / "dump.log").write_bytes(b"text\x00binary")
    elif failure == "outside":
        target = tmp_path / "unapproved"
        target.mkdir()
        (target / "safe.log").write_text("safe")
    elif failure == "tool_overlap":
        output = target / "scanner-output"
        output.mkdir()
    with pytest.raises(gate.GateFailure):
        gate._artifacts(Path("scanner"), output, target)


def test_approved_runner_artifacts_are_scanned(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = tmp_path / "runner"
    target = runner / "security-logs"
    target.mkdir(parents=True)
    (target / "safe.json").write_text('{"result":"PASS"}')
    monkeypatch.setenv("RUNNER_TEMP", str(runner))
    calls = []

    def scan(*args: object) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(gate, "_scan", scan)
    assert gate._artifacts(Path("scanner"), runner / "gitleaks-final", target) == (0, 1)
    assert calls[0][2] == ["dir", str(target)]


def test_symlink_component_is_rejected(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    unsafe = tmp_path / "linked"
    monkeypatch.setattr(Path, "is_symlink", lambda item: item == unsafe)
    with pytest.raises(gate.GateFailure):
        gate._plain_path(unsafe / "nested")


def test_modified_lockfile_never_passes(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gate, "_prepare", lambda *args: (Path("scanner"), tmp_path))

    def source(*args: object) -> tuple[int, int]:
        (gate.ROOT / gate.LOCKS[0]).write_text("modified")
        return 0, 1

    monkeypatch.setattr(gate, "_source", source)
    assert gate.main(["source", "--output-dir", str(tmp_path)]) == 1


def test_cli_arguments_and_findings_use_only_closed_projection(
    gate: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = uuid.uuid4().hex
    assert gate.main([marker]) == 1
    monkeypatch.setattr(gate, "_prepare", lambda *args: (Path("scanner"), tmp_path))
    monkeypatch.setattr(gate, "_source", lambda *args: (2, 3))
    assert gate.main(["source", "--output-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err
    assert captured.err == ""
    assert json.loads(captured.out.splitlines()[-1]) == {
        "tool": "gitleaks",
        "version": "8.30.1",
        "result": "FAIL",
        "findings": 2,
        "scanned_files": 3,
        "lockfiles_unchanged": True,
    }


def test_corrupt_cached_archive_is_never_executed(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "gate-output"
    tools = output / "tools"
    tools.mkdir(parents=True)
    monkeypatch.setattr(gate.platform, "system", lambda: "Windows")
    monkeypatch.setattr(gate.platform, "machine", lambda: "AMD64")
    (tools / gate.ARCHIVES["Windows"][0]).write_bytes(b"corrupted tool archive")
    calls: list[object] = []
    monkeypatch.setattr(gate, "_run", lambda *args: calls.append(args))
    with pytest.raises(gate.GateFailure):
        gate._prepare(output)
    assert calls == []


def test_runner_temp_outside_approved_security_logs_is_rejected(
    gate: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = tmp_path / "runner"
    unapproved = runner / "maintenance-files"
    unapproved.mkdir(parents=True)
    (unapproved / "private.txt").write_text("not approved for this scan")
    monkeypatch.setenv("RUNNER_TEMP", str(runner))
    with pytest.raises(gate.GateFailure):
        gate._artifacts(Path("scanner"), runner / "gitleaks-final", unapproved)


def test_scanner_process_does_not_receive_application_credentials(
    gate: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("DATABASE_URL", "AUTH_HMAC_KEY", "GITHUB_TOKEN", "GIT_CONFIG_COUNT", "HTTP_PROXY"):
        monkeypatch.setenv(name, "generated-private-marker")
    environment = gate._environment()
    for name in ("DATABASE_URL", "AUTH_HMAC_KEY", "GITHUB_TOKEN", "GIT_CONFIG_COUNT", "HTTP_PROXY"):
        assert name not in environment
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
