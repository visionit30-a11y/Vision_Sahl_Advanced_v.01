"""Blocking dependency gates. Raw scanner output is never a report artifact.

The caller provisions pip-audit from pip-audit.lock.txt with --require-hashes.
Python audits universal uv inventory, isolated build constraints, and scanner tools.
Both modes preserve application lockfiles even when a scanner fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Never

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATHS = ("apps/api/uv.lock", "apps/web/package-lock.json")
PIP_AUDIT_VERSION = "2.10.1"
UV_VERSION = "0.12.10"
NPM_VERSION = "11.11.0"
NAME = re.compile(r"(?:@[a-z0-9._-]+/)?[a-z0-9][a-z0-9._-]{0,100}\Z")
VERSION = re.compile(r"[0-9][a-zA-Z0-9.!+_-]{0,80}\Z")
ADVISORY = re.compile(
    r"(?:GHSA-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}|CVE-\d{4}-\d{4,10}|PYSEC-\d{4}-\d{1,10})\Z"
)
SEVERITIES = ("info", "low", "moderate", "medium", "high", "critical")
REASONS = frozenset(
    {
        "invalid_scanner_result",
        "tool_version_mismatch",
        "unsupported_package_source",
        "duplicate_inventory",
        "incomplete_inventory",
        "invalid_tool_lock",
        "build_inventory_changed",
        "scanner_failed",
        "scanner_status_mismatch",
        "tool_inventory_mismatch",
        "export_failed",
        "lockfiles_changed",
        "invalid_mode",
        "invalid_arguments",
        "gate_failed",
        "scanner_diagnostics",
    }
)


class GateFailure(Exception):
    """Only fixed reason codes cross the gate boundary."""


def ensure(condition: bool, reason: str = "invalid_scanner_result") -> None:
    if not condition:
        raise GateFailure(reason)


def package_pair(name: Any, version: Any) -> tuple[str, str]:
    ensure(isinstance(name, str) and NAME.fullmatch(name) is not None)
    ensure(isinstance(version, str) and VERSION.fullmatch(version) is not None)
    return re.sub(r"[-_.]+", "-", name).lower(), version


def lock_hashes(root: Path) -> dict[str, str]:
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in LOCK_PATHS}


def environment(work: Path) -> dict[str, str]:
    # Public registries need no application, DB, GitHub, proxy, or npm credentials.
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(
        HOME=str(work),
        USERPROFILE=str(work),
        UV_CACHE_DIR=str(work / "uv-cache"),
        PIP_AUDIT_CACHE_DIR=str(work / "pip-audit-cache"),
        UV_PYTHON_DOWNLOADS="never",
        PYTHONIOENCODING="utf-8",
        NO_COLOR="1",
    )
    return env


def execute(args: list[str], cwd: Path, work: Path) -> subprocess.CompletedProcess[str]:
    # No shell, inherited secret variables, raw stdout forwarding, or raw stderr logs.
    return subprocess.run(
        args,
        cwd=cwd,
        env=environment(work),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )


def exact_tool(args: list[str], expected: str, cwd: Path, work: Path) -> None:
    result = execute(args, cwd, work)
    ensure(
        result.returncode == 0 and result.stdout.strip() == expected and not result.stderr.strip(),
        "tool_version_mismatch",
    )


def strict_json(value: str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            ensure(key not in result)
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=unique)


def uv_inventory(root: Path) -> set[tuple[str, str]]:
    lock = tomllib.loads((root / "apps/api/uv.lock").read_text(encoding="utf-8"))
    inventory: set[tuple[str, str]] = set()
    local = []
    for row in lock["package"]:
        source = row["source"]
        if source == {"editable": "."} and row["name"] == "sahl-api":
            local.append(row)
            continue
        ensure(source == {"registry": "https://pypi.org/simple"}, "unsupported_package_source")
        pair = package_pair(row["name"], row["version"])
        ensure(pair not in inventory, "duplicate_inventory")
        inventory.add(pair)
    ensure(len(local) == 1 and bool(inventory), "incomplete_inventory")
    return inventory


def requirements_inventory(path: Path) -> set[tuple[str, str]]:
    inventory: set[tuple[str, str]] = set()
    text = path.read_text(encoding="utf-8").replace("\\\n", " ")
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        match = re.fullmatch(
            r"([a-zA-Z0-9._-]+)==([^\s]+)\s+((?:--hash=sha256:[a-f0-9]{64}\s*)+)", line.strip()
        )
        ensure(match is not None, "invalid_tool_lock")
        assert match is not None
        pair = package_pair(match[1].lower(), match[2])
        ensure(pair not in inventory, "duplicate_inventory")
        inventory.add(pair)
    ensure(bool(inventory), "incomplete_inventory")
    return inventory


def build_inventory(root: Path) -> set[tuple[str, str]]:
    project = tomllib.loads((root / "apps/api/pyproject.toml").read_text(encoding="utf-8"))
    # A new backend/build requirement requires an explicit reviewed inventory update.
    ensure(
        project["build-system"]
        == {"requires": ["setuptools>=68"], "build-backend": "setuptools.build_meta"},
        "build_inventory_changed",
    )
    inventory = requirements_inventory(root / ".github/ci/python-build.lock.txt")
    ensure(inventory == {("setuptools", "84.0.0")}, "build_inventory_changed")
    config = tomllib.loads((root / ".github/ci/uv-build.toml").read_text(encoding="utf-8"))
    ensure(
        config
        == {
            "python-preference": "only-system",
            "python-downloads": "never",
            "extra-build-dependencies": {
                "sahl-api": [f"{name}=={version}" for name, version in sorted(inventory)]
            },
        },
        "build_inventory_changed",
    )
    return inventory


def safe_advisory(value: Any) -> str:
    ensure(isinstance(value, str) and ADVISORY.fullmatch(value) is not None)
    return value


def safe_versions(values: Any) -> list[str]:
    ensure(isinstance(values, list))
    for value in values:
        ensure(isinstance(value, str) and VERSION.fullmatch(value) is not None)
    return values


def python_report(
    result: subprocess.CompletedProcess[str], expected: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    ensure(result.returncode in (0, 1), "scanner_failed")
    ensure(
        re.fullmatch(
            r"(?:No known vulnerabilities found|Found \d+ known vulnerabilit(?:y|ies) "
            r"in \d+ package(?:s)?)?\s*",
            result.stderr,
        )
        is not None,
        "scanner_diagnostics",
    )
    data = strict_json(result.stdout)
    ensure(isinstance(data, dict) and set(data) == {"dependencies", "fixes"})
    ensure(data["fixes"] == [] and isinstance(data["dependencies"], list))
    actual: set[tuple[str, str]] = set()
    findings = []
    for row in data["dependencies"]:
        ensure(isinstance(row, dict) and set(row) == {"name", "version", "vulns"})
        pair = package_pair(row["name"], row["version"])
        ensure(pair not in actual)
        actual.add(pair)
        ensure(isinstance(row["vulns"], list))
        for issue in row["vulns"]:
            ensure(isinstance(issue, dict))
            aliases = issue.get("aliases", [])
            ensure(isinstance(aliases, list))
            findings.append(
                {
                    "package": pair[0],
                    "version": pair[1],
                    "advisory": safe_advisory(issue["id"]),
                    "aliases": [safe_advisory(alias) for alias in aliases],
                    "fix_versions": safe_versions(issue["fix_versions"]),
                    "severity": issue.get("severity")
                    if issue.get("severity") in SEVERITIES
                    else None,
                }
            )
    ensure(actual == expected, "incomplete_inventory")
    ensure((result.returncode == 0) == (not findings), "scanner_status_mismatch")
    return findings


def audit_python(root: Path, work: Path, audit_python: str, uv: str) -> dict[str, Any]:
    uv_version = execute([uv, "--version"], root, work)
    ensure(
        uv_version.returncode == 0
        and not uv_version.stderr.strip()
        and re.fullmatch(
            rf"uv {re.escape(UV_VERSION)}(?: \([a-zA-Z0-9 ._-]+\))?\s*", uv_version.stdout
        )
        is not None,
        "tool_version_mismatch",
    )
    exact_tool(
        [audit_python, "-m", "pip_audit", "--version"], f"pip-audit {PIP_AUDIT_VERSION}", root, work
    )
    exact_tool(
        [audit_python, "-c", "import sys; print('.'.join(map(str, sys.version_info[:2])))"],
        "3.14",
        root,
        work,
    )
    expected = uv_inventory(root)
    build = build_inventory(root)
    scanner_path = root / ".github/ci/pip-audit.lock.txt"
    scanner = requirements_inventory(scanner_path)
    ensure(("pip-audit", PIP_AUDIT_VERSION) in scanner, "tool_version_mismatch")
    # Audit the actual installed scanner environment too, not merely an unused lock.
    installed = execute(
        [
            audit_python,
            "-c",
            "import importlib.metadata as m, json; "
            "print(json.dumps([[d.metadata['Name'],d.version] for d in m.distributions()]))",
        ],
        root,
        work,
    )
    ensure(installed.returncode == 0 and not installed.stderr.strip(), "scanner_failed")
    installed_pairs = {package_pair(n.lower(), v) for n, v in strict_json(installed.stdout)}
    ensure(installed_pairs == scanner, "tool_inventory_mismatch")
    export_dir = work / "python-inventory"
    export_dir.mkdir()
    output = export_dir / "pylock.toml"
    export = execute(
        [
            uv,
            "export",
            "--frozen",
            "--all-groups",
            "--all-extras",
            "--no-emit-project",
            "--format",
            "pylock.toml",
            "--output-file",
            str(output),
        ],
        root / "apps/api",
        work,
    )
    ensure(export.returncode == 0 and output.is_file(), "export_failed")
    ensure(
        re.search(r"warning|error|panic|skip", export.stderr, flags=re.I) is None,
        "scanner_diagnostics",
    )
    pylock = tomllib.loads(output.read_text(encoding="utf-8"))
    exported = [package_pair(p["name"], p["version"]) for p in pylock["packages"]]
    ensure(len(exported) == len(expected) and set(exported) == expected, "incomplete_inventory")
    common = [
        audit_python,
        "-m",
        "pip_audit",
        "--strict",
        "--format",
        "json",
        "--progress-spinner",
        "off",
        "--vulnerability-service",
        "pypi",
    ]
    findings: list[dict[str, Any]] = []
    audited = {}
    for label, arguments, inventory in [
        ("runtime_dev_all_markers", ["--locked", str(export_dir)], expected),
        (
            "build",
            [
                "--require-hashes",
                "--disable-pip",
                "-r",
                str(root / ".github/ci/python-build.lock.txt"),
            ],
            build,
        ),
        (
            "scanner",
            ["--require-hashes", "--disable-pip", "-r", str(scanner_path)],
            scanner,
        ),
    ]:
        found = python_report(execute([*common, *arguments], root, work), inventory)
        findings.extend(found)
        audited[label] = len(inventory)
        if found:
            break  # User policy: stop on the first actual advisory; never upgrade.
    return {
        "tool": "pip-audit",
        "version": PIP_AUDIT_VERSION,
        "audited_packages": audited,
        "findings": findings,
        "status": "FAIL" if findings else "PASS",
    }


def npm_inventory(root: Path) -> dict[str, tuple[str, str]]:
    lock = strict_json((root / "apps/web/package-lock.json").read_text(encoding="utf-8"))
    ensure(lock["lockfileVersion"] == 3 and isinstance(lock["packages"], dict))
    inventory = {}
    for key, value in lock["packages"].items():
        if key == "":
            continue
        ensure("node_modules/" in key and "link" not in value)
        name = key.rsplit("node_modules/", 1)[1]
        pair = package_pair(name, value["version"])
        ensure(isinstance(value.get("integrity"), str), "incomplete_inventory")
        ensure(
            value.get("resolved", "").startswith("https://registry.npmjs.org/"),
            "unsupported_package_source",
        )
        inventory[key] = pair
    ensure(bool(inventory), "incomplete_inventory")
    return inventory


def npm_report(
    result: subprocess.CompletedProcess[str], inventory: dict[str, tuple[str, str]]
) -> list[dict[str, Any]]:
    ensure(result.returncode in (0, 1), "scanner_failed")
    ensure(not result.stderr.strip(), "scanner_diagnostics")
    data = strict_json(result.stdout)
    ensure(isinstance(data, dict) and data.get("auditReportVersion") == 2 and "error" not in data)
    ensure(isinstance(data.get("vulnerabilities"), dict))
    counts = data["metadata"]["vulnerabilities"]
    ensure(set(counts) == {"info", "low", "moderate", "high", "critical", "total"})
    ensure(all(type(v) is int and v >= 0 for v in counts.values()))
    ensure(counts["total"] == sum(v for k, v in counts.items() if k != "total"))
    ensure(data["metadata"]["dependencies"]["total"] == len(inventory), "incomplete_inventory")
    findings = []
    for name, row in data["vulnerabilities"].items():
        ensure(
            isinstance(row, dict) and row.get("name") == name and NAME.fullmatch(name) is not None
        )
        ensure(row.get("severity") in SEVERITIES and isinstance(row.get("nodes"), list))
        ensure(
            bool(row["nodes"]) and all(node in inventory for node in row["nodes"]),
            "incomplete_inventory",
        )
        versions = sorted({inventory[node][1] for node in row["nodes"]})
        ensure(all(inventory[node][0] == re.sub(r"[-_.]+", "-", name) for node in row["nodes"]))
        fix = row.get("fixAvailable")
        fix_versions = []
        if isinstance(fix, dict):
            ensure(isinstance(fix.get("name"), str) and NAME.fullmatch(fix["name"]) is not None)
            fix_versions = safe_versions([fix["version"]])
        else:
            ensure(type(fix) is bool)
        ensure(isinstance(row.get("via"), list) and bool(row["via"]))
        ids = []
        for advisory in row["via"]:
            if isinstance(advisory, str):
                ensure(advisory in data["vulnerabilities"])
                continue
            ensure(isinstance(advisory, dict))
            url = advisory.get("url", "")
            ensure(isinstance(url, str) and url.startswith("https://github.com/advisories/"))
            ids.append(safe_advisory(url.removeprefix("https://github.com/advisories/")))
        findings.append(
            {
                "package": name,
                "versions": versions,
                "advisories": ids,
                "severity": row["severity"],
                "fix_versions": fix_versions,
                "fix_available": bool(fix),
            }
        )
    ensure(counts["total"] == len(findings), "scanner_status_mismatch")
    ensure((result.returncode == 0) == (not findings), "scanner_status_mismatch")
    return findings


def audit_npm(root: Path, work: Path, node: str, npm: str) -> dict[str, Any]:
    npm_command = [node, npm] if npm.endswith(".js") else [npm]
    exact_tool([*npm_command, "--version"], NPM_VERSION, root, work)
    node_version = execute([node, "--version"], root, work)
    ensure(
        node_version.returncode == 0
        and not node_version.stderr.strip()
        and re.fullmatch(r"v24\.\d+\.\d+\s*", node_version.stdout) is not None,
        "tool_version_mismatch",
    )
    inventory = npm_inventory(root)
    snapshot = work / "npm-inventory"
    snapshot.mkdir()
    for name in ("package.json", "package-lock.json"):
        shutil.copyfile(root / "apps/web" / name, snapshot / name)
    before = hashlib.sha256((snapshot / "package-lock.json").read_bytes()).hexdigest()
    userconfig, globalconfig = work / "npm-userconfig", work / "npm-globalconfig"
    userconfig.touch()
    globalconfig.touch()
    result = execute(
        [
            *npm_command,
            "audit",
            "--json",
            "--package-lock-only",
            "--audit-level=low",
            "--include=dev",
            "--include=optional",
            "--include=peer",
            "--registry=https://registry.npmjs.org",
            "--userconfig",
            str(userconfig),
            "--globalconfig",
            str(globalconfig),
        ],
        snapshot,
        work,
    )
    ensure(
        hashlib.sha256((snapshot / "package-lock.json").read_bytes()).hexdigest() == before,
        "lockfiles_changed",
    )
    findings = npm_report(result, inventory)
    return {
        "tool": "npm audit",
        "version": NPM_VERSION,
        "audited_nodes": len(inventory),
        "findings": findings,
        "status": "FAIL" if findings else "PASS",
    }


def run(
    mode: str, output_dir: Path, audit_python: str, uv: str, node: str, npm: str, root: Path = ROOT
) -> int:
    summary: dict[str, Any] = {"gate": mode, "status": "FAIL", "reason": "gate_failed"}
    before: dict[str, str] | None = None
    try:
        before = lock_hashes(root)
        output_dir = output_dir.resolve()
        ensure(sys.version_info[:2] == (3, 14), "tool_version_mismatch")
        ensure(mode in ("python", "npm"), "invalid_mode")
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="audit-", dir=output_dir) as temporary:
            work = Path(temporary)
            summary = (
                audit_python_fn(root, work, audit_python, uv)
                if mode == "python"
                else audit_npm(root, work, node, npm)
            )
    except GateFailure as error:
        reason = str(error) if str(error) in REASONS else "gate_failed"
        summary = {"gate": mode, "status": "FAIL", "reason": reason}
    except Exception:  # noqa: BLE001 - fail closed without exception payloads.
        # Exception strings may contain request headers, raw JSON, DSNs, or SQL.
        summary = {"gate": mode, "status": "FAIL", "reason": "gate_failed"}
    finally:
        try:
            unchanged = before is not None and lock_hashes(root) == before
        except OSError:
            unchanged = False
        if not unchanged:
            summary = {"gate": mode, "status": "FAIL", "reason": "lockfiles_changed"}
        summary["project_lockfiles_unchanged"] = unchanged
    payload = json.dumps(summary, sort_keys=True)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"dependency-{mode}.json").write_text(payload + "\n", encoding="utf-8")
    except OSError:
        print('{"status":"FAIL","reason":"report_failed"}')
        return 1
    print(payload)
    return 0 if summary["status"] == "PASS" else 1


# Retain a stable, testable callable independently from the CLI parameter name.
audit_python_fn = audit_python


class ClosedParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise GateFailure("invalid_arguments")


def main(argv: list[str] | None = None) -> int:
    parser = ClosedParser(description=__doc__)
    parser.add_argument("mode", choices=("python", "npm"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--audit-python", default=os.environ.get("SECURITY_AUDIT_PYTHON", "python"))
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--node", default="node")
    parser.add_argument("--npm", default="npm")
    try:
        args = parser.parse_args(argv)
    except GateFailure:
        print('{"status":"FAIL","reason":"invalid_arguments"}')
        return 1
    return run(args.mode, args.output_dir, args.audit_python, args.uv, args.node, args.npm)


if __name__ == "__main__":
    sys.exit(main())
