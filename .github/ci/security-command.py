"""Run a blocking CI command without persisting or replaying its raw output."""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Never

MAX_OUTPUT_BYTES = 16 * 1024 * 1024
GATE_NAMES = frozenset(
    {
        "security-tool-lint",
        "security-tool-format",
        "security-tool-types",
        "pytest",
        "ruff",
        "ruff-format",
        "mypy",
        "migration-upgrade",
        "migration-downgrade",
        "migration-reupgrade",
        "migration-check",
        "migration-head",
        "backend-tests",
        "database-cleanup",
        "browser-migration",
        "web-lint",
        "web-typecheck",
        "prettier",
        "web-test",
        "browser-tests",
        "web-build",
    }
)


def _windows_kernel() -> Any:
    if sys.platform == "win32":
        return ctypes.WinDLL("kernel32", use_last_error=True)
    else:
        raise RuntimeError("unsupported_process_owner")


class _WindowsJob:
    """One unnamed job owns only this command and its descendants, before execution."""

    def __init__(self) -> None:
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t),
                ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "read_operations",
                    "write_operations",
                    "other_operations",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", IoCounters),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t),
            ]

        self.kernel = _windows_kernel()
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                wintypes.BOOL,
            ),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Thread32First": ([wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
            "Thread32Next": ([wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes = arguments
            function.restype = result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise RuntimeError("owned_process_setup_failed")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        if not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError("owned_process_setup_failed")

    def assign_and_resume(self, process: subprocess.Popen[bytes]) -> None:
        from ctypes import wintypes

        class ThreadEntry(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD),
                ("usage", wintypes.DWORD),
                ("thread_id", wintypes.DWORD),
                ("process_id", wintypes.DWORD),
                ("base_priority", wintypes.LONG),
                ("delta_priority", wintypes.LONG),
                ("flags", wintypes.DWORD),
            ]

        # Popen holds the process handle and its main thread is still suspended:
        # this PID cannot be reused and no descendant can run before job assignment.
        handle = self.kernel.OpenProcess(0x0101, False, process.pid)
        if not handle:
            raise RuntimeError("owned_process_setup_failed")
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, handle):
                raise RuntimeError("owned_process_setup_failed")
        finally:
            self.kernel.CloseHandle(handle)
        snapshot = self.kernel.CreateToolhelp32Snapshot(0x00000004, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise RuntimeError("owned_process_setup_failed")
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            present = self.kernel.Thread32First(snapshot, ctypes.byref(entry))
            while present:
                if entry.process_id == process.pid:
                    thread = self.kernel.OpenThread(0x0002, False, entry.thread_id)
                    if not thread:
                        raise RuntimeError("owned_process_setup_failed")
                    try:
                        if self.kernel.ResumeThread(thread) != 1:
                            raise RuntimeError("owned_process_setup_failed")
                        return
                    finally:
                        self.kernel.CloseHandle(thread)
                present = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise RuntimeError("owned_process_setup_failed")
        finally:
            self.kernel.CloseHandle(snapshot)

    def terminate(self) -> None:
        if self.handle and not self.kernel.TerminateJobObject(self.handle, 1):
            raise RuntimeError("owned_process_cleanup_failed")

    def close(self) -> None:
        if self.handle:
            try:
                self.terminate()
            finally:
                self.kernel.CloseHandle(self.handle)
                self.handle = None


def _signal_owned_group(process: subprocess.Popen[bytes], signum: int) -> None:
    try:
        if sys.platform != "win32":
            os.killpg(process.pid, signum)
        else:
            raise RuntimeError("unsupported_process_owner")
    except ProcessLookupError:
        return


def execute_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[bytes]:
    """Bound the complete owned process tree, including inherited stdout/stderr pipes."""
    job: _WindowsJob | None = None
    process: subprocess.Popen[bytes] | None = None
    try:
        if os.name == "nt":
            job = _WindowsJob()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
            creationflags=(0x00000004 | 0x00000200 | 0x08000000) if os.name == "nt" else 0,
        )  # Windows: CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW.
        if job is not None:
            job.assign_and_resume(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if job is not None:
                job.terminate()
            else:
                _signal_owned_group(process, signal.SIGTERM)
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                if job is not None:
                    job.terminate()
                else:
                    _signal_owned_group(process, 9)  # POSIX SIGKILL; Windows uses its owned job.
                process.communicate(timeout=3)
            raise subprocess.TimeoutExpired("withheld", timeout) from None
        return subprocess.CompletedProcess(["withheld"], process.returncode, stdout, stderr)
    finally:
        try:
            if job is not None:
                job.close()
            elif process is not None:
                _signal_owned_group(process, 9)  # POSIX SIGKILL; Windows uses its owned job.
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()  # The retained Popen handle refers only to our own child.
                process.wait(timeout=3)


def scan_output(payload: bytes, tool_dir: Path) -> bool:
    spec = importlib.util.spec_from_file_location(
        "sahl_ci_gitleaks", Path(__file__).with_name("gitleaks-gate.py")
    )
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return bool(module.scan_stdin(payload, tool_dir))


def counters(payload: bytes) -> tuple[dict[str, int], bool]:
    """Project integers only; untrusted text never becomes a report field."""
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", payload.decode("utf-8", errors="replace"))
    result: dict[str, int] = {}
    incomplete = False
    patterns = {
        "passed": r"(?:^|\n)\s*(?:=+\s*)?(\d+) passed\b",
        "frontend_tests": r"(?:^|\n)\s*Tests\s+(\d+) passed\b",
        "frontend_files": r"(?:^|\n)\s*Test Files\s+(\d+) passed\b",
    }
    for key, pattern in patterns.items():
        values = re.findall(pattern, text)
        if values:
            result[key] = int(values[-1])
    for line in text.splitlines():
        if re.search(r"\b[1-9]\d* (?:skipped|xfailed|xpassed|todo|pending|failed|errors?)\b", line):
            incomplete = True
    return result, incomplete


def run_gate(
    name: str, command: list[str], log_dir: Path, timeout: int
) -> tuple[int, dict[str, Any]]:
    if name not in GATE_NAMES:
        return 1, {"result": "FAIL", "reason": "invalid_configuration"}
    report: dict[str, Any] = {"gate": name, "result": "FAIL", "reason": "command_failed"}
    try:
        if name not in GATE_NAMES or not command or not 1 <= timeout <= 1200:
            raise ValueError
        if log_dir.is_symlink():
            raise ValueError
        log_dir.mkdir(parents=True, exist_ok=True)
        tool_dir = log_dir.parent / "security-scanner-cache"
        completed = execute_command(command, timeout)
        payload = completed.stdout + b"\n" + completed.stderr
        if len(payload) > MAX_OUTPUT_BYTES:
            report["reason"] = "output_limit"
        elif not scan_output(payload, tool_dir):
            report["reason"] = "output_security_gate_failed"
        else:
            counts, incomplete = counters(payload)
            report["counts"] = counts
            required_counts = {
                "pytest": ("passed",),
                "backend-tests": ("passed",),
                "browser-tests": ("passed",),
                "web-test": ("frontend_tests", "frontend_files"),
            }
            if name in required_counts:
                incomplete = incomplete or any(
                    counts.get(counter, 0) <= 0 for counter in required_counts[name]
                )
            if name == "migration-head":
                # Alembic current writes revisions to stdout; additional heads/revisions,
                # blank output and a stale version all invalidate this proof.
                incomplete = (
                    incomplete
                    or completed.stdout.strip() != b"0016_security_audit_retention (head)"
                )
            if incomplete:
                report["reason"] = "incomplete_test_gate"
            elif completed.returncode == 0:
                report = {"gate": name, "result": "PASS", "counts": counts}
        code = 0 if report["result"] == "PASS" else 1
    except Exception:  # noqa: BLE001 -- final CI emission boundary must hide every exception
        # Even TimeoutExpired includes captured stdout and argv. Never format it.
        code = 1
        report = {"gate": name, "result": "FAIL", "reason": "execution_failure"}
    try:
        (log_dir / f"{name}.json").write_text(
            json.dumps(report, sort_keys=True) + "\n", encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 -- final CI emission boundary must hide every exception
        return 1, {"gate": name, "result": "FAIL", "reason": "evidence_failure"}
    return code, report


class ClosedParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ValueError


def main(argv: list[str] | None = None) -> int:
    try:
        parser = ClosedParser(description=__doc__)
        parser.add_argument("--log-dir", type=Path, required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--timeout", type=int, default=900)
        parser.add_argument("command", nargs=argparse.REMAINDER)
        args = parser.parse_args(argv)
        if args.name not in GATE_NAMES:
            raise ValueError
        command = args.command
        if command and command[0] == "--":
            command = command[1:]
        code, report = run_gate(args.name, command, args.log_dir, args.timeout)
    except Exception:  # noqa: BLE001 -- final CI emission boundary must hide every exception
        code, report = 1, {"result": "FAIL", "reason": "invalid_configuration"}
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
