"""Mechanically enforces the architecture's framework-independence claim.

Uses AST inspection rather than string grepping, so a forbidden import
disguised as a comment or a string literal doesn't produce a false
positive, and an actual `import sqlalchemy` can't be missed by a
too-narrow grep pattern.
"""

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
CORE_DIR = APP_ROOT / "core"

FORBIDDEN_CORE_IMPORTS = {"sqlalchemy", "fastapi", "celery", "redis"}


def _top_level_module(dotted_name: str) -> str:
    return dotted_name.split(".")[0]


def _imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(_top_level_module(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(_top_level_module(node.module))
    return modules


def _core_python_files() -> list[Path]:
    return sorted(CORE_DIR.rglob("*.py"))


@pytest.mark.parametrize("path", _core_python_files(), ids=lambda p: p.name)
def test_core_module_has_no_framework_imports(path: Path) -> None:
    imports = _imported_top_level_modules(path)
    forbidden = imports & FORBIDDEN_CORE_IMPORTS
    assert not forbidden, (
        f"{path.relative_to(APP_ROOT)} imports forbidden module(s) {forbidden} — "
        "app/core must stay usable without FastAPI, SQLAlchemy, Celery, or Redis"
    )


def _files_importing_app_submodule(root: Path, submodule: str) -> list[tuple[Path, str]]:
    """(file, imported module) pairs where a file under `root` imports app.<submodule>."""
    hits: list[tuple[Path, str]] = []
    if not root.exists():
        return hits

    target_prefix = f"app.{submodule}"
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == target_prefix or node.module.startswith(f"{target_prefix}."):
                    hits.append((path, node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == target_prefix or alias.name.startswith(f"{target_prefix}."):
                        hits.append((path, alias.name))
    return hits


def test_api_does_not_import_worker() -> None:
    """The API and the Celery worker must stay cleanly separable, talking
    only through PostgreSQL and the broker — this is what lets the
    production worker move to its own process/host later with zero
    application-code changes. Neither app/api nor app/worker exists yet
    (that's M3+); this test is a structural no-op today and activates
    automatically the moment those packages are created.
    """
    hits = _files_importing_app_submodule(APP_ROOT / "api", "worker")
    assert not hits, f"app/api must not import app/worker: {hits}"


def test_worker_does_not_import_api() -> None:
    hits = _files_importing_app_submodule(APP_ROOT / "worker", "api")
    assert not hits, f"app/worker must not import app/api: {hits}"
