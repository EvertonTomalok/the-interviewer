from __future__ import annotations

from collections.abc import Iterator

import pytest

from interviewer_core.errors import ConfigError
from interviewer_core.registry import (
    ProviderSpec,
    clear_registry_for_tests,
    known_providers,
    register,
    require_spec,
    restore_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    snapshot = clear_registry_for_tests()
    try:
        yield
    finally:
        restore_registry_for_tests(snapshot)


def test_register_then_require_spec_round_trips() -> None:
    spec = ProviderSpec(kind="llm", name="fake", build=lambda *a, **k: "built")
    register(spec)

    assert require_spec("llm", "fake") is spec


def test_duplicate_registration_is_refused() -> None:
    register(ProviderSpec(kind="llm", name="fake", build=lambda *a, **k: None))

    with pytest.raises(ConfigError, match="fake"):
        register(ProviderSpec(kind="llm", name="fake", build=lambda *a, **k: None))


def test_unknown_slug_names_itself_and_the_known_ones() -> None:
    register(ProviderSpec(kind="llm", name="openrouter", build=lambda *a, **k: None))

    with pytest.raises(ConfigError, match="typo-slug") as exc_info:
        require_spec("llm", "typo-slug")
    assert "openrouter" in str(exc_info.value)


def test_a_provider_registered_only_in_a_test_is_built_with_no_factory_change() -> None:
    register(ProviderSpec(kind="llm", name="test-only", build=lambda *a, **k: "built-by-test"))

    spec = require_spec("llm", "test-only")

    assert spec.build() == "built-by-test"


def test_known_providers_filters_by_kind() -> None:
    register(ProviderSpec(kind="llm", name="a", build=lambda *a, **k: None))
    register(ProviderSpec(kind="stt", name="b", build=lambda *a, **k: None))

    assert [s.name for s in known_providers("llm")] == ["a"]
    assert {s.name for s in known_providers()} == {"a", "b"}
