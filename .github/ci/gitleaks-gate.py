"""Pinned, fail-closed secret scanning; raw scanner output is never published."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Never

ROOT = Path(__file__).resolve().parents[2]
VERSION = "8.30.1"
ARCHIVES = {
    "Windows": (
        "gitleaks_8.30.1_windows_x64.zip",
        "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e",
        "gitleaks.exe",
    ),
    "Linux": (
        "gitleaks_8.30.1_linux_x64.tar.gz",
        "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
        "gitleaks",
    ),
}
CONFIG = {"extend": {"useDefault": True}}
LOCKS = ("apps/api/uv.lock", "apps/web/package-lock.json")


class GateFailure(Exception):
    """Closed failure; callers must not emit the underlying diagnostic."""


def _plain_path(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    for item in (absolute, *absolute.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise GateFailure
    return absolute.resolve()


def _environment() -> dict[str, str]:
    # Public binary/local Git scans need no application, DB or GitHub credentials.
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return environment


def _run(
    arguments: list[str], *, payload: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        input=payload,
        cwd=ROOT,
        env=_environment(),
        capture_output=True,
        check=False,
        timeout=600,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _git(*arguments: str) -> bytes:
    result = _run(["git", *arguments])
    if result.returncode or result.stderr:
        raise GateFailure
    return result.stdout


def _verify_contract() -> None:
    import tomllib

    if tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8")) != CONFIG:
        raise GateFailure
    exceptions = json.loads((ROOT / ".github/security-exceptions.json").read_text())
    if exceptions != {"schema_version": 1, "exceptions": []}:
        # No exception has been approved. Adding one requires a reviewed contract change.
        raise GateFailure
    if (ROOT / ".gitleaksignore").exists():
        raise GateFailure


def _prepare(output_dir: Path) -> tuple[Path, Path]:
    _verify_contract()
    output = _plain_path(output_dir)
    if output == ROOT or ROOT.is_relative_to(output):
        raise GateFailure
    output.mkdir(parents=True, exist_ok=True)
    tools = _plain_path(output / "tools")
    tools.mkdir(exist_ok=True)
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise GateFailure
    name, checksum, executable = ARCHIVES[platform.system()]
    archive_path = _plain_path(tools / name)
    if not archive_path.exists():
        url = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/{name}"
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = response.read(64 * 1024 * 1024 + 1)
        if len(payload) > 64 * 1024 * 1024:
            raise GateFailure
        if hashlib.sha256(payload).hexdigest() != checksum:
            raise GateFailure
        archive_path.write_bytes(payload)
    payload = archive_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != checksum:
        raise GateFailure
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            binary = archive.read(executable)
    else:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            member = archive.getmember(executable)
            if not member.isfile() or member.size > 64 * 1024 * 1024:
                raise GateFailure
            stream = archive.extractfile(member)
            if stream is None:
                raise GateFailure
            binary = stream.read()
    target = _plain_path(tools / executable)
    if target.exists():
        if (
            not target.is_file()
            or target.stat().st_nlink != 1
            or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(binary).digest()
        ):
            raise GateFailure
    else:
        with target.open("xb") as destination:
            destination.write(binary)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    version = _run([str(target), "version"])
    if version.returncode or version.stderr or version.stdout.strip() != VERSION.encode():
        raise GateFailure
    return target, output


def _scan(binary: Path, output: Path, arguments: list[str], payload: bytes | None = None) -> int:
    result = _run(
        [
            str(binary),
            *arguments,
            "--config",
            str(ROOT / ".gitleaks.toml"),
            "--redact=100",
            "--exit-code=1",
            "--ignore-gitleaks-allow",
            "--no-banner",
            "--no-color",
            "--log-level=warn",
            "--max-decode-depth=5",
            "--report-format=json",
            "--report-path",
            "-",
        ],
        payload=payload,
    )
    # Report JSON stays in captured memory, because even a redacted report may
    # contain sensitive Match/context. Never replay scanner stdout or diagnostics.
    # Warnings (including partial/skipped scans) fail closed.
    if result.returncode not in {0, 1} or result.stderr or len(result.stdout) > 32 * 1024 * 1024:
        raise GateFailure
    findings: Any = json.loads(result.stdout)
    if not isinstance(findings, list):
        raise GateFailure
    for item in findings:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("RuleID"), str)
            or not re.fullmatch(r"[a-z0-9_-]{1,100}", item["RuleID"])
            or not isinstance(item.get("File"), str)
            or type(item.get("StartLine")) is not int
            or item["StartLine"] < 1
            or item.get("Secret") not in {"REDACTED", ""}
        ):
            raise GateFailure
    if (result.returncode == 0) != (len(findings) == 0):
        raise GateFailure
    return len(findings)


def scan_stdin(payload: bytes, output_dir: Path) -> bool:
    """Scan captured command output in memory; publish no output or raw report."""
    try:
        if not isinstance(payload, bytes) or not payload or b"\x00" in payload:
            return False
        payload.decode("utf-8", errors="strict")
        binary, _output = _prepare(output_dir)
        # Stdin output remains in memory throughout: even a redacted JSON report could
        # contain an unredacted Match/context, so this mode never requests a report file.
        result = _run(
            [
                str(binary),
                "stdin",
                "--config",
                str(ROOT / ".gitleaks.toml"),
                "--redact=100",
                "--exit-code=1",
                "--ignore-gitleaks-allow",
                "--no-banner",
                "--no-color",
                "--log-level=warn",
                "--max-decode-depth=5",
            ],
            payload=payload,
        )
        return result.returncode == 0 and not result.stdout and not result.stderr
    except Exception:  # noqa: BLE001 - no raw scanner/download diagnostics leave this boundary
        return False


def _forbidden(path: PurePosixPath) -> bool:
    name = path.name.lower()
    return (
        ((name == ".env" or name.startswith(".env.")) and name != ".env.example")
        or path.suffix.lower() in {".pem", ".key", ".pfx", ".p12"}
        or name in {".gitleaksignore", "id_rsa", "id_ed25519", "credentials.json"}
    )


def _source(binary: Path, output: Path) -> tuple[int, int]:
    if _git("rev-parse", "--is-shallow-repository").strip() != b"false":
        raise GateFailure
    entries = _git("ls-files", "--stage", "-z").split(b"\x00")
    files: list[Path] = []
    for entry in filter(None, entries):
        metadata, raw_name = entry.split(b"\t", 1)
        mode, _object_id, stage = metadata.split()
        name = PurePosixPath(raw_name.decode("utf-8"))
        if mode not in {b"100644", b"100755"} or stage != b"0":
            raise GateFailure
        if name.is_absolute() or ".." in name.parts or _forbidden(name):
            raise GateFailure
        target = _plain_path(ROOT / str(name))
        if not target.is_relative_to(ROOT) or not target.is_file():
            raise GateFailure
        files.append(target)
    if not files:
        raise GateFailure
    # Reject prohibited tracked filenames throughout history, even when deleted at HEAD.
    names = _git("log", "--all", "--full-history", "-m", "--format=", "--name-only", "-z")
    for raw_name in names.split(b"\x00"):
        historical_name = raw_name.strip(b"\r\n")
        if historical_name and _forbidden(PurePosixPath(historical_name.decode("utf-8"))):
            raise GateFailure
    # Include merge-versus-each-parent patches: a merge-only secret removed later
    # must still be inspected, even when neither parent's patch introduced it.
    findings = _scan(binary, output, ["git", str(ROOT), "--log-opts=--all --full-history -m"])
    with tempfile.TemporaryDirectory(prefix="tracked-", dir=output) as temporary:
        snapshot = Path(temporary)
        for source in files:
            destination = snapshot / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        findings += _scan(binary, output, ["dir", str(snapshot)])
    return findings, len(files)


def _artifacts(binary: Path, output: Path, scan_path: Path) -> tuple[int, int]:
    target = _plain_path(scan_path)
    approved = [_plain_path(ROOT / "_logs/security-artifacts")]
    if os.environ.get("RUNNER_TEMP"):
        approved.append(_plain_path(Path(os.environ["RUNNER_TEMP"]) / "security-logs"))
    if (
        not target.is_dir()
        or not any(target.is_relative_to(item) for item in approved)
        or output.is_relative_to(target)
        or target.is_relative_to(output)
    ):
        raise GateFailure
    files = []
    for item in target.rglob("*"):
        checked = _plain_path(item)
        if checked.is_dir():
            continue
        if not checked.is_file() or checked.stat().st_nlink != 1:
            raise GateFailure
        # Only text artifacts are approved; archives, traces and binary dumps must not be uploaded.
        data = checked.read_bytes()
        if b"\x00" in data:
            raise GateFailure
        data.decode("utf-8", errors="strict")
        if _forbidden(PurePosixPath(checked.name)):
            raise GateFailure
        files.append(checked)
    if not files or not any(item.stat().st_size for item in files):
        raise GateFailure
    return _scan(binary, output, ["dir", str(target)]), len(files)


def _lock_hashes() -> tuple[str, ...]:
    return tuple(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in LOCKS)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise GateFailure


def main(argv: list[str] | None = None) -> int:
    summary: dict[str, Any] = {"tool": "gitleaks", "version": VERSION, "result": "FAIL"}
    try:
        parser = _Parser(add_help=False)
        parser.add_argument("mode", choices=("source", "artifacts"))
        parser.add_argument("--output-dir", type=Path, required=True)
        parser.add_argument("--scan-path", type=Path)
        args = parser.parse_args(argv)
        if (args.mode == "artifacts") != (args.scan_path is not None):
            raise GateFailure
        before = _lock_hashes()
        binary, output = _prepare(args.output_dir)
        if args.mode == "source":
            findings, file_count = _source(binary, output)
        else:
            findings, file_count = _artifacts(binary, output, args.scan_path)
        if _lock_hashes() != before:
            raise GateFailure
        summary.update(findings=findings, scanned_files=file_count, lockfiles_unchanged=True)
        if findings == 0:
            summary["result"] = "PASS"
    except Exception:  # noqa: BLE001 - never expose exception text, scanner output or report content
        summary = {"tool": "gitleaks", "version": VERSION, "result": "FAIL"}
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
