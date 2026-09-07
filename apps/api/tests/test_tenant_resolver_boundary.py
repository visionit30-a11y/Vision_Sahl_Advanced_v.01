"""Keep service-only explicit resolution outside the production HTTP import graph.

Following local imports catches direct imports, aliases and package reexports.
This is an import-boundary check, not an attempt to interpret arbitrary Python.
The behavioural dependency tests separately prove the fail-closed HTTP default.
"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

APP_DIRECTORY = Path(__file__).resolve().parents[1] / "app"


def application_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in APP_DIRECTORY.rglob("*.py"):
        parts = list(path.relative_to(APP_DIRECTORY.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = path
    return modules


def imported_modules(module: str, path: Path) -> set[str]:
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    imports: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = resolve_name("." * node.level + base, package)
            imports.add(base)
            imports.update(f"{base}.{alias.name}" for alias in node.names)
    # Importing a child also executes its package initializers.
    return {
        ".".join(name.split(".")[:length])
        for name in imports
        for length in range(1, len(name.split(".")) + 1)
    }


def test_production_http_cannot_import_explicit_resolution_even_through_reexports() -> None:
    modules = application_modules()
    roots = {"app.main", "app.tenancy", "app.tenancy.resolution"} | {
        name for name in modules if name == "app.api" or name.startswith("app.api.")
    }
    pending = [(name, [name]) for name in sorted(roots)]
    visited: set[str] = set()
    while pending:
        name, chain = pending.pop()
        assert name != "app.tenancy.explicit", "Explicit resolver reached HTTP: " + " -> ".join(
            chain
        )
        if name in visited or name not in modules:
            continue
        visited.add(name)
        pending.extend(
            (dependency, [*chain, dependency])
            for dependency in imported_modules(name, modules[name])
            if dependency in modules
        )
