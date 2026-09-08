"""`packages/core` imports nothing outside the standard library, pydantic
(including pydantic-settings), or itself. `sqlmodel` is the import this test
watches hardest for -- it looks like pydantic and the persistence adapter
lives on it."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

CORE_SRC = Path(__file__).resolve().parents[1] / "src" / "interviewer_core"

ALLOWED_TOP_LEVEL = {"pydantic", "pydantic_settings", "pydantic_core", "interviewer_core"}
ALLOWED_TOP_LEVEL |= set(sys.stdlib_module_names)


def _iter_python_files() -> list[Path]:
    return sorted(CORE_SRC.rglob("*.py"))


def _imported_top_level_names(tree: ast.AST) -> list[tuple[str, int]]:
    names: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import, necessarily within interviewer_core
            if node.module:
                names.append((node.module.split(".")[0], node.lineno))
    return names


def test_core_imports_nothing_outside_stdlib_pydantic_or_itself() -> None:
    offenders: list[str] = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name, lineno in _imported_top_level_names(tree):
            if name not in ALLOWED_TOP_LEVEL:
                offenders.append(
                    f"{path.relative_to(CORE_SRC.parent.parent)}:{lineno} imports {name!r}"
                )

    assert not offenders, "packages/core must import only stdlib/pydantic/itself:\n" + "\n".join(
        offenders
    )


def test_sqlmodel_is_explicitly_named_as_the_watched_import() -> None:
    assert "sqlmodel" not in ALLOWED_TOP_LEVEL
    assert "sqlalchemy" not in ALLOWED_TOP_LEVEL
