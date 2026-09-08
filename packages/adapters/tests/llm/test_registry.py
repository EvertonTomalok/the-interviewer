from __future__ import annotations

import pytest

import interviewer_adapters  # noqa: F401  -- import registers openrouter/openai_compat/fake
from interviewer_core.config import Settings
from interviewer_core.errors import ConfigError
from interviewer_core.ports.llm import LLMAnswer, LLMPort, LLMUsage
from interviewer_core.registry import (
    ProviderSpec,
    clear_registry_for_tests,
    known_providers,
    require_spec,
    restore_registry_for_tests,
)


def _settings() -> Settings:
    return Settings(database_url="postgresql+asyncpg://x/db", redis_url="redis://localhost:6379/0")


def test_openrouter_openai_compat_and_fake_are_registered() -> None:
    names = {spec.name for spec in known_providers("llm")}

    assert {"openrouter", "openai_compat", "fake"} <= names


def test_unknown_llm_slug_raises_config_error_naming_it() -> None:
    with pytest.raises(ConfigError, match="typo-provider"):
        require_spec("llm", "typo-provider")


def test_registry_proof_a_test_registered_provider_is_built_by_the_factory_untouched() -> None:
    """A provider registered *inside this test* is built the same way a real
    one is -- through `require_spec(...).build(settings)`, with no change
    anywhere in this module or in `interviewer_core.registry`. If this
    needed an edit elsewhere, dispatch would not be data yet.
    """

    class _ProbeLLM:
        model = "probe"

        async def complete(
            self, messages: object, *, temperature: float, max_tokens: int
        ) -> LLMAnswer:
            return LLMAnswer(text="probed", usage=LLMUsage(prompt_tokens=0, completion_tokens=0))

    def _build_probe(settings: Settings) -> LLMPort:
        return _ProbeLLM()

    snapshot = clear_registry_for_tests()
    probe = ProviderSpec(kind="llm", name="__test_probe__", build=_build_probe)
    restore_registry_for_tests({**snapshot, ("llm", "__test_probe__"): probe})
    try:
        spec = require_spec("llm", "__test_probe__")
        built = spec.build(_settings())

        assert isinstance(built, _ProbeLLM)
    finally:
        restore_registry_for_tests(snapshot)
