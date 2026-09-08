"""The CI output boundary never emits command bodies, exceptions or secrets."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def gate() -> ModuleType:
    path = ROOT / ".github/ci/security-command.py"
    spec = importlib.util.spec_from_file_location("security_command_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def child(monkeypatch: pytest.MonkeyPatch, gate: ModuleType, payload: bytes, code: int = 0) -> None:
    monkeypatch.setattr(
        gate,
        "execute_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(["withheld"], code, payload, b""),
    )


@pytest.mark.parametrize("code", [0, 1, 137])
def test_raw_output_never_persisted_or_replayed(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    code: int,
) -> None:
    secret = ("synthetic-" + "private-credential-marker").encode()
    child(monkeypatch, gate, b"12 passed\n" + secret, code)
    observed: list[bytes] = []

    def observe(data: bytes, path: Path) -> bool:
        observed.append(data)
        return True

    monkeypatch.setattr(gate, "scan_output", observe)
    result, report = gate.run_gate("pytest", ["python", "-m", "pytest"], tmp_path, 30)
    assert result == (0 if code == 0 else 1)
    assert observed and secret in observed[0]
    saved = (tmp_path / "pytest.json").read_bytes()
    assert secret not in saved
    assert report["counts"] == {"passed": 12}
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("payload", [b"1 skipped", b"2 xfailed", b"1 xpassed", b"2 pending"])
def test_skipped_proofs_cannot_pass(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: bytes
) -> None:
    child(monkeypatch, gate, payload)
    monkeypatch.setattr(gate, "scan_output", lambda *args: True)
    result, report = gate.run_gate("pytest", ["pytest"], tmp_path, 30)
    assert result == 1
    assert report["reason"] == "incomplete_test_gate"


def test_secret_scanner_failure_blocks_even_passing_command(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    child(monkeypatch, gate, b"9 passed\n")
    monkeypatch.setattr(gate, "scan_output", lambda *args: False)
    result, report = gate.run_gate("pytest", ["pytest"], tmp_path, 30)
    assert result == 1
    assert report["reason"] == "output_security_gate_failed"


@pytest.mark.parametrize("failure", [RuntimeError, subprocess.TimeoutExpired])
def test_exception_messages_are_not_emitted(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: type[Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = "private-" + "exception-canary"

    def fail(*args: Any, **kwargs: Any) -> None:
        if failure is subprocess.TimeoutExpired:
            raise subprocess.TimeoutExpired(marker, 1, output=marker.encode())
        raise failure(marker)

    monkeypatch.setattr(gate, "execute_command", fail)
    result, report = gate.run_gate("pytest", ["pytest"], tmp_path, 1)
    assert result == 1
    assert marker not in json.dumps(report)
    assert marker not in (tmp_path / "pytest.json").read_text()
    assert marker not in capsys.readouterr().out


@pytest.mark.parametrize("args", [[], ["--bad", "secret-canary"], ["--timeout", "secret-canary"]])
def test_argument_errors_do_not_replay_arguments(
    gate: ModuleType, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    assert gate.main(args) == 1
    output = capsys.readouterr()
    assert "secret-canary" not in output.out + output.err
    assert json.loads(output.out)["reason"] == "invalid_configuration"


@pytest.mark.parametrize("timeout", [0, -1, 1201])
def test_invalid_timeout_does_not_execute(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, timeout: int
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("A command was executed with an invalid timeout.")

    monkeypatch.setattr(gate, "execute_command", unexpected)
    result, _ = gate.run_gate("pytest", ["pytest"], tmp_path, timeout)
    assert result == 1


def test_numeric_summary_only(gate: ModuleType) -> None:
    data = b" Test Files 29 passed (29)\n Tests 225 passed (225)\n7 passed (30s)\nsecret"
    assert gate.counters(data) == (
        {"passed": 7, "frontend_tests": 225, "frontend_files": 29},
        False,
    )


def test_no_fake_success_when_evidence_cannot_be_written(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    child(monkeypatch, gate, b"1 passed")
    monkeypatch.setattr(gate, "scan_output", lambda *args: True)
    (tmp_path / "pytest.json").mkdir()
    code, report = gate.run_gate("pytest", ["pytest"], tmp_path, 1)
    assert code == 1
    assert report["reason"] == "evidence_failure"


def test_output_limit_is_closed(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gate, "MAX_OUTPUT_BYTES", 2)
    child(monkeypatch, gate, b"123")
    code, report = gate.run_gate("pytest", ["pytest"], tmp_path, 1)
    assert code == 1
    assert report["reason"] == "output_limit"


@pytest.mark.parametrize("name", ["pytest", "backend-tests", "web-test", "browser-tests"])
def test_success_without_test_count_is_not_proof(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    child(monkeypatch, gate, b"No tests ran")
    monkeypatch.setattr(gate, "scan_output", lambda *args: True)
    code, report = gate.run_gate(name, ["pytest"], tmp_path, 30)
    assert code == 1
    assert report["reason"] == "incomplete_test_gate"


@pytest.mark.parametrize(
    "head", [b"0015_security_event_wiring (head)", b"0016_security_audit_retention"]
)
def test_migration_current_requires_approved_head(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, head: bytes
) -> None:
    child(monkeypatch, gate, head)
    monkeypatch.setattr(gate, "scan_output", lambda *args: True)
    code, report = gate.run_gate("migration-head", ["alembic", "current"], tmp_path, 30)
    assert code == 1
    assert report["reason"] == "incomplete_test_gate"


def test_unknown_gate_name_never_becomes_report_field(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = "private-" + "label-canary"
    assert gate.main(["--log-dir", str(tmp_path), "--name", marker, "--", "python"]) == 1
    output = capsys.readouterr()
    assert marker not in output.out + output.err
    assert list(tmp_path.iterdir()) == []


def test_direct_unknown_label_cannot_write_arbitrary_filename(
    gate: ModuleType, tmp_path: Path
) -> None:
    code, report = gate.run_gate("../private-marker", ["python"], tmp_path, 1)
    assert code == 1
    assert report == {"result": "FAIL", "reason": "invalid_configuration"}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "name,payload",
    [
        ("pytest", b"0 passed"),
        ("backend-tests", b"Tests 9 passed"),
        ("browser-tests", b"Test Files 1 passed\nTests 9 passed"),
        ("web-test", b"Test Files 29 passed\nTests 0 passed"),
        ("web-test", b"Test Files 29 passed"),
        ("web-test", b"7 passed"),
        ("web-test", b"Tests 9 passed"),
        ("pytest", b"1 passed, 1 failed"),
        ("pytest", b"1 passed, 1 error"),
    ],
)
def test_tool_specific_positive_test_counts_required(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    payload: bytes,
) -> None:
    child(monkeypatch, gate, payload)
    monkeypatch.setattr(gate, "scan_output", lambda *args: True)
    code, report = gate.run_gate(name, ["withheld"], tmp_path, 30)
    assert code == 1
    assert report["reason"] == "incomplete_test_gate"


@pytest.mark.parametrize(
    "extra",
    [b"0015_security_event_wiring (head)", b"0015_security_event_wiring", b"another_head (head)"],
)
def test_approved_head_beside_another_revision_is_rejected(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extra: bytes
) -> None:
    child(monkeypatch, gate, b"0016_security_audit_retention (head)\n" + extra)
    monkeypatch.setattr(gate, "scan_output", lambda *args: True)
    code, report = gate.run_gate("migration-head", ["alembic", "current"], tmp_path, 30)
    assert code == 1
    assert report["reason"] == "incomplete_test_gate"


def _process_running(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    else:
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists() and stat.read_text().split(")", 1)[1].split()[0] == "Z":
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True


@pytest.mark.parametrize("parent_exits", [False, True])
def test_real_timeout_reaps_owned_child_and_grandchild_pipes(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, parent_exits: bool
) -> None:
    child_file = tmp_path / "child.pid"
    grandchild_file = tmp_path / "grandchild.pid"
    grandchild = (
        "import os,sys,time; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid())); "
        "print('private-' + 'subprocess-canary', flush=True); time.sleep(120)"
    )
    program = (
        "import os,subprocess,sys,time; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid())); "
        "subprocess.Popen([sys.executable, '-c', sys.argv[3], sys.argv[2]]); "
        + ("time.sleep(0.3)" if parent_exits else "time.sleep(120)")
    )
    scanner_calls: list[bytes] = []

    def scan(payload: bytes, path: Path) -> bool:
        scanner_calls.append(payload)
        return True

    monkeypatch.setattr(gate, "scan_output", scan)
    started = time.monotonic()
    code, report = gate.run_gate(
        "pytest",
        [sys.executable, "-c", program, str(child_file), str(grandchild_file), grandchild],
        tmp_path / "evidence",
        2,
    )
    assert time.monotonic() - started < 15
    assert code == 1
    assert report["reason"] == "execution_failure"
    assert scanner_calls == []
    assert child_file.is_file() and grandchild_file.is_file()
    assert not _process_running(int(child_file.read_text()))
    assert not _process_running(int(grandchild_file.read_text()))
    saved = (tmp_path / "evidence/pytest.json").read_text()
    assert "subprocess-canary" not in saved


def test_real_owned_process_success_preserves_exit_code_and_captured_output(
    gate: ModuleType,
) -> None:
    completed = gate.execute_command(
        [sys.executable, "-c", "import sys; print('3 passed'); sys.exit(7)"], 5
    )
    assert completed.returncode == 7
    assert completed.stdout.strip() == b"3 passed"
    assert completed.stderr == b""
