"""Provider dispatch as data, never a branch (PRD §3.3)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from interviewer_core.errors import ConfigError


@dataclass(frozen=True)
class ProviderSpec:
    kind: str
    name: str
    build: Callable[..., Any]
    rate_per_minute: int = 60
    label: str = ""


_REGISTRY: dict[tuple[str, str], ProviderSpec] = {}


def register(spec: ProviderSpec) -> None:
    """Add `spec`. Refuses a name that already has an owner for its kind."""
    key = (spec.kind, spec.name)
    if key in _REGISTRY:
        raise ConfigError(f"provider {spec.name!r} is already registered for kind {spec.kind!r}")
    _REGISTRY[key] = spec


def require_spec(kind: str, name: str) -> ProviderSpec:
    """Return the registered spec, or raise `ConfigError` naming the slug."""
    key = (kind, name)
    if key not in _REGISTRY:
        known = sorted(n for k, n in _REGISTRY if k == kind)
        raise ConfigError(f"unknown provider {name!r} for kind {kind!r}; known providers: {known}")
    return _REGISTRY[key]


def known_providers(kind: str | None = None) -> list[ProviderSpec]:
    """All registered specs, or only those of `kind` when given."""
    if kind is None:
        return list(_REGISTRY.values())
    return [spec for (k, _n), spec in _REGISTRY.items() if k == kind]


def clear_registry_for_tests() -> dict[tuple[str, str], ProviderSpec]:
    """Empty the registry and return what was in it, for a test to restore."""
    snapshot = dict(_REGISTRY)
    _REGISTRY.clear()
    return snapshot


def restore_registry_for_tests(snapshot: dict[tuple[str, str], ProviderSpec]) -> None:
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)
