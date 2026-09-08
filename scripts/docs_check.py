#!/usr/bin/env python3
"""Verify documentation the way `make check` verifies code.

Fails, naming the offender, when:
  - a package or app directory has no CONTEXT.md
  - a CONTEXT.md is missing one of the six template headings
  - a path inside a code span in a README.md/CONTEXT.md does not exist on disk
  - a registered provider slug, or an `.env.example` key, is missing from the
    README configuration table (skipped while that table still carries the
    `<!-- filled in T10 -->` placeholder -- see docs/adr/0001)
  - a Mermaid block does not look like it would parse

Exit code is non-zero on any failure; every failure is printed, not just the
first, so one run tells you everything that is wrong.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_HEADINGS = [
    "**Responsibility**",
    "**Public surface**",
    "**Depends on**",
    "**Invariants**",
    "**Where to change what**",
    "**Traps**",
]

MERMAID_DIAGRAM_TYPES = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "stateDiagram-v2",
    "stateDiagram",
    "erDiagram",
    "classDiagram",
    "gantt",
    "pie",
    "journey",
)

DEFERRED_TO_T10_MARKER = "<!-- filled in T10 -->"

CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
MERMAID_BLOCK_RE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


def module_directories() -> list[Path]:
    dirs: list[Path] = []
    for parent in ("packages", "apps"):
        base = ROOT / parent
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                dirs.append(child)
    return dirs


def check_context_files(errors: list[str]) -> None:
    for module_dir in module_directories():
        context_file = module_dir / "CONTEXT.md"
        rel = module_dir.relative_to(ROOT)
        if not context_file.is_file():
            errors.append(f"missing CONTEXT.md in {rel}")
            continue
        text = context_file.read_text(encoding="utf-8")
        for heading in REQUIRED_HEADINGS:
            if heading not in text:
                errors.append(f"{rel}/CONTEXT.md is missing the {heading} heading")


def top_level_entries() -> set[str]:
    return {p.name for p in ROOT.iterdir() if not p.name.startswith(".git")}


def looks_like_a_path(span: str, known_roots: set[str]) -> bool:
    if "/" not in span:
        return False
    if "://" in span:
        return False
    if any(ch in span for ch in "<>$\"'{}()="):
        return False
    if " " in span:
        return False
    if span.startswith("-") or span.startswith("."):
        return False
    if span.startswith("/"):
        return False  # an HTTP route or an absolute path -- not a repo path
    first_segment = span.split("/", 1)[0]
    return first_segment in known_roots


def resolve_candidate(span: str) -> Path:
    candidate = span
    if candidate.endswith("/**"):
        candidate = candidate[: -len("/**")]
    elif candidate.endswith("**"):
        candidate = candidate[: -len("**")]
    if candidate.endswith("/"):
        candidate = candidate[:-1]
    return ROOT / candidate


def check_paths_in_doc(doc: Path, errors: list[str], known_roots: set[str]) -> None:
    text = doc.read_text(encoding="utf-8")
    rel_doc = doc.relative_to(ROOT)
    for span in CODE_SPAN_RE.findall(text):
        if not looks_like_a_path(span, known_roots):
            continue
        candidate = resolve_candidate(span)
        if not candidate.exists():
            errors.append(f"{rel_doc} references a path that does not exist: `{span}`")


def check_mermaid_blocks(doc: Path, errors: list[str]) -> None:
    text = doc.read_text(encoding="utf-8")
    rel_doc = doc.relative_to(ROOT)
    for body in MERMAID_BLOCK_RE.findall(text):
        stripped = body.strip()
        if not stripped:
            errors.append(f"{rel_doc} has an empty mermaid block")
            continue
        first_line = stripped.splitlines()[0].strip()
        if not first_line.startswith(MERMAID_DIAGRAM_TYPES):
            errors.append(
                f"{rel_doc} has a mermaid block that does not open with a known "
                f"diagram type: {first_line!r}"
            )
            continue
        if stripped.count("[") != stripped.count("]"):
            errors.append(f"{rel_doc} has a mermaid block with unbalanced [ ]")
        if stripped.count("(") != stripped.count(")"):
            errors.append(f"{rel_doc} has a mermaid block with unbalanced ( )")


def known_provider_slugs() -> list[str]:
    try:
        import interviewer_adapters  # noqa: F401  (side effect: registers providers)
        from interviewer_core.registry import known_providers
    except ImportError:
        return []
    try:
        return [spec.name for spec in known_providers()]
    except Exception:
        return []


def env_example_keys() -> list[str]:
    env_file = ROOT / ".env.example"
    if not env_file.is_file():
        return []
    keys = []
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.append(line.split("=", 1)[0])
    return keys


def check_configuration_table(errors: list[str]) -> None:
    readme = ROOT / "README.md"
    if not readme.is_file():
        errors.append("README.md is missing")
        return
    text = readme.read_text(encoding="utf-8")
    if DEFERRED_TO_T10_MARKER in text:
        return  # configuration table not filled in yet -- T10's job

    missing_slugs = [slug for slug in known_provider_slugs() if slug not in text]
    for slug in missing_slugs:
        errors.append(f"README.md configuration table is missing provider slug: {slug}")

    missing_keys = [key for key in env_example_keys() if key not in text]
    for key in missing_keys:
        errors.append(f"README.md configuration table is missing env var: {key}")


def main() -> int:
    errors: list[str] = []

    check_context_files(errors)

    docs = list(ROOT.glob("**/CONTEXT.md")) + list(ROOT.glob("**/README.md"))
    ignored_dirs = {".git", ".venv", "tasks", "node_modules"}
    docs = [d for d in docs if not ignored_dirs & set(d.parts)]
    known_roots = top_level_entries()
    for doc in docs:
        check_paths_in_doc(doc, errors, known_roots)
        check_mermaid_blocks(doc, errors)

    check_configuration_table(errors)

    if errors:
        print(f"docs-check: {len(errors)} problem(s) found\n")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("docs-check: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
