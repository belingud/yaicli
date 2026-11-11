"""Tests for the v0.23 K22 model context-window resolver (``yaicli.model_limits``).

Covers: name normalization, user-config parsing, the six-layer precedence chain,
heuristic longest-prefix matching (including the Ollama local-window rule), the
bundled catalog, the memory/disk cache (TTL + disable switch), learned limits and
the ``context_input_budget`` formula. No network and no real ``~/.config`` writes.
"""

import json
import time
from pathlib import Path

import pytest

from yaicli import model_limits as ml
from yaicli.model_limits import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_SAFETY_TOKENS,
    OLLAMA_DEFAULT_CONTEXT_WINDOW,
    ModelLimits,
    catalog_generated_at,
    context_input_budget,
    get_context_limits,
    limits_from_dict,
    normalize_model_name,
    parse_user_windows,
)

DATA_FILE = Path(ml.__file__).resolve().parent / "data" / "model_limits.json"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path):
    """Point the disk cache at a tmp path and reset the module caches."""
    ml.clear_limit_cache()
    previous = ml.CACHE_PATH_OVERRIDE
    ml.CACHE_PATH_OVERRIDE = tmp_path / "cache" / "model_limits.json"
    try:
        yield
    finally:
        ml.CACHE_PATH_OVERRIDE = previous
        ml.clear_limit_cache()


def _config(**overrides):
    config = {"ENABLE_MODEL_METADATA": True, "ENABLE_MODEL_LIMITS_CACHE": True}
    config.update(overrides)
    return config


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
class TestNormalize:
    def test_strips_vendor_prefixes(self):
        assert normalize_model_name("openrouter/anthropic/claude-sonnet-5.5") == "claude-sonnet-5.5"
        assert normalize_model_name("anthropic/claude-sonnet-4") == "claude-sonnet-4"
        assert normalize_model_name("openai/gpt-4o") == "gpt-4o"
        assert normalize_model_name("google/gemini-2.5-pro") == "gemini-2.5-pro"
        assert normalize_model_name("meta-llama/llama-3.3-70b-instruct") == "llama-3.3-70b-instruct"

    def test_strips_dates_and_router_variants(self):
        assert normalize_model_name("claude-sonnet-4-5@20250929") == "claude-sonnet-4-5"
        assert normalize_model_name("gpt-4o-2024-08-06") == "gpt-4o-2024-08-06"
        assert normalize_model_name("deepseek/deepseek-chat:free") == "deepseek-chat"
        assert normalize_model_name("anthropic/claude-sonnet-5.5:batch") == "claude-sonnet-5.5"

    def test_removes_1m_marker(self):
        assert normalize_model_name("claude-opus-4-6[1m]") == "claude-opus-4-6"
        assert normalize_model_name("my[1M]model") == "mymodel"

    def test_empty(self):
        assert normalize_model_name(None) == ""
        assert normalize_model_name("   ") == ""


# ---------------------------------------------------------------------------
# User config layer
# ---------------------------------------------------------------------------
class TestUserWindows:
    def test_parses_int_and_object_values(self):
        parsed = parse_user_windows(
            {
                "gpt-4o": 111111,
                "openrouter:claude-sonnet-5.5": {"window": 1000000, "max_output": 128000},
                "ollama/qwen2.5:7b": {"window": 32768},
                "invalid": "not-a-number",
                "zero": 0,
            }
        )
        assert parsed["gpt-4o"].window == 111111
        assert parsed["openrouter:claude-sonnet-5.5"].window == 1000000
        assert parsed["openrouter:claude-sonnet-5.5"].max_output == 128000
        assert parsed["ollama:qwen2.5:7b"].window == 32768
        assert "invalid" not in parsed
        assert "zero" not in parsed

    def test_parses_json_string(self):
        parsed = parse_user_windows('{"gpt-4o": 99999}')
        assert parsed["gpt-4o"].window == 99999

    def test_user_config_wins_over_catalog(self):
        config = _config(MODEL_CONTEXT_WINDOWS={"gpt-4o": 222222})
        limits = get_context_limits("openai", "gpt-4o", config)
        assert limits.window == 222222
        assert limits.source == "user"
        assert limits.detail == "MODEL_CONTEXT_WINDOWS"

    def test_provider_scoped_key_does_not_leak(self):
        config = _config(MODEL_CONTEXT_WINDOWS={"openrouter:claude-sonnet-5.5": 500000})
        scoped = get_context_limits("openrouter", "claude-sonnet-5.5", config)
        assert scoped.window == 500000 and scoped.source == "user"
        unscoped = get_context_limits("anthropic", "claude-sonnet-5.5", config)
        assert unscoped.source != "user"

    def test_provider_slash_key_with_colon_tag(self):
        config = _config(MODEL_CONTEXT_WINDOWS={"ollama/qwen2.5:7b": 32768})
        limits = get_context_limits("ollama", "qwen2.5:7b", config)
        assert limits.window == 32768 and limits.source == "user"

    def test_bare_model_key_applies_everywhere(self):
        config = _config(MODEL_CONTEXT_WINDOWS={"custom-model": 4096})
        assert get_context_limits("openai", "custom-model", config).window == 4096
        assert get_context_limits("deepseek", "custom-model", config).window == 4096


# ---------------------------------------------------------------------------
# Heuristic layer
# ---------------------------------------------------------------------------
class TestHeuristic:
    @pytest.mark.parametrize(
        "provider,model,window",
        [
            ("openai", "gpt-4o", 128000),
            ("openai", "gpt-4.1", 1047576),
            ("openai", "gpt-5.2", 400000),
            ("openai", "gpt-4-32k", 32768),  # must beat the shorter "gpt-4" prefix
            ("openai", "gpt-4", 8192),
            ("openai", "o1-mini", 128000),  # must beat the shorter "o1" prefix
            ("openai", "o1", 200000),
            ("anthropic", "claude-sonnet-4", 200000),
            ("gemini", "gemini-2.5-pro", 1048576),
            ("deepseek", "deepseek-chat", 128000),
            ("ollama", "llama3:8b", OLLAMA_DEFAULT_CONTEXT_WINDOW),
        ],
    )
    def test_family_prefixes(self, provider, model, window):
        # Heuristic layer only: no config, no fetcher; catalog may also know the
        # model, so accept either heuristic or catalog as long as the window matches.
        limits = get_context_limits(provider, model, None)
        assert limits.window == window
        assert limits.source in ("heuristic", "catalog")

    def test_ollama_does_not_use_generic_vendor_prefix(self):
        # qwen2.5 is normally 131k in the cloud, but a local Ollama server gets a
        # small default window unless metadata/config says otherwise.
        limits = get_context_limits("ollama", "qwen2.5:7b", None)
        assert limits.window == OLLAMA_DEFAULT_CONTEXT_WINDOW
        assert limits.source == "heuristic"

    def test_ollama_does_not_use_cloud_catalog(self):
        limits = get_context_limits("ollama", "gpt-4o", None)
        assert limits.window == OLLAMA_DEFAULT_CONTEXT_WINDOW

    def test_unknown_model_falls_back_to_default(self):
        limits = get_context_limits("custom-provider", "my-model-v9", None)
        assert limits.window == DEFAULT_CONTEXT_WINDOW
        assert limits.source == "default"
        assert "unknown" in limits.detail

    def test_1m_variant_maps_to_one_million(self):
        limits = get_context_limits("custom-provider", "some-model[1m]", None)
        assert limits.window == ml.ONE_MILLION_CONTEXT_WINDOW
        assert limits.source == "heuristic"


# ---------------------------------------------------------------------------
# Catalog layer
# ---------------------------------------------------------------------------
class TestCatalog:
    def test_catalog_data_file_is_valid(self):
        payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert payload["generated_at"]
        assert isinstance(payload["exact"]["*"], dict) and payload["exact"]["*"]
        assert catalog_generated_at() == payload["generated_at"]
        for entry in payload["exact"]["*"].values():
            assert isinstance(entry["window"], int) and entry["window"] > 0

    def test_openrouter_scope_from_catalog(self):
        limits = get_context_limits("openrouter", "anthropic/claude-sonnet-5.5", None)
        assert limits.window == 1_000_000
        assert limits.source == "catalog"
        assert limits.detail.startswith("catalog ")

    def test_exact_entries_from_curated_catalog(self):
        limits = get_context_limits("deepseek", "deepseek-chat", None)
        assert limits.window == 128_000
        assert limits.max_output == 8192
        assert limits.source == "catalog"

    def test_catalog_takes_precedence_over_heuristic(self):
        limits = get_context_limits("openai", "gpt-4-32k", None)
        assert limits.window == 32768
        assert limits.source == "catalog"


# ---------------------------------------------------------------------------
# Metadata layer
# ---------------------------------------------------------------------------
class TestMetadata:
    def test_fetcher_used_and_cached(self):
        calls = []

        def fetcher(model):
            calls.append(model)
            return ModelLimits(window=777_000, max_output=12_345, detail="test /models")

        config = _config()
        limits = get_context_limits("custom", "my-model", config, base_url="http://x", fetcher=fetcher)
        assert limits.window == 777_000
        assert limits.source == "metadata"
        assert limits.detail == "test /models"
        again = get_context_limits("custom", "my-model", config, base_url="http://x", fetcher=fetcher)
        assert again.window == 777_000
        assert calls == ["my-model"]

    def test_metadata_disabled_skips_fetcher(self):
        calls = []

        def fetcher(model):
            calls.append(model)
            return ModelLimits(window=777_000)

        config = _config(ENABLE_MODEL_METADATA=False)
        limits = get_context_limits("custom", "my-model", config, fetcher=fetcher)
        assert calls == []
        assert limits.source != "metadata"

    def test_fetcher_failure_falls_through(self):
        def fetcher(model):
            raise RuntimeError("probe failed")

        limits = get_context_limits("openai", "gpt-4o", _config(), fetcher=fetcher)
        assert limits.window == 128_000
        assert limits.source == "catalog"

    def test_metadata_persists_across_sessions(self):
        def fetcher(model):
            raise AssertionError("disk cache should have been used")

        first = get_context_limits(
            "custom",
            "persisted-model",
            _config(),
            base_url="http://x",
            fetcher=lambda model: ModelLimits(window=300_000),
        )
        assert first.source == "metadata"
        ml._MEMORY.clear()  # simulate a new process/session
        second = get_context_limits("custom", "persisted-model", _config(), base_url="http://x", fetcher=fetcher)
        assert second.window == 300_000
        assert second.source == "metadata"

    def test_metadata_ttl_expires(self, monkeypatch):
        monkeypatch.setattr(ml, "METADATA_TTL_SECONDS", 10)
        get_context_limits(
            "custom",
            "expiring-model",
            _config(),
            base_url="http://x",
            fetcher=lambda model: ModelLimits(window=300_000),
        )
        # Age the on-disk entry beyond its TTL.
        key = next(iter(ml._DISK))
        ml._DISK[key]["saved_at"] = int(time.time()) - 11
        ml._MEMORY.clear()
        limits = get_context_limits("custom", "expiring-model", _config(), base_url="http://x", fetcher=None)
        assert limits.source == "default"

    def test_cache_can_be_disabled(self, tmp_path):
        config = _config(ENABLE_MODEL_LIMITS_CACHE=False)
        get_context_limits(
            "custom",
            "nocache-model",
            config,
            base_url="http://x",
            fetcher=lambda model: ModelLimits(window=300_000),
        )
        assert ml._DISK == {}
        assert not ml.cache_path().exists()

    def test_corrupt_cache_file_is_ignored(self):
        path = ml.cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")
        limits = get_context_limits("openai", "gpt-4o", _config())
        assert limits.source == "catalog"

    def test_failed_probe_is_negative_cached(self):
        calls = []

        def fetcher(model):
            calls.append(model)
            return None

        config = _config()
        assert (
            get_context_limits("custom", "offline-model", config, base_url="http://x", fetcher=fetcher).source
            == "default"
        )
        assert (
            get_context_limits("custom", "offline-model", config, base_url="http://x", fetcher=fetcher).source
            == "default"
        )
        assert calls == ["offline-model"]

    def test_negative_cache_expires(self, monkeypatch):
        monkeypatch.setattr(ml, "METADATA_MISS_TTL_SECONDS", 0)
        calls = []

        def fetcher(model):
            calls.append(model)
            return None

        config = _config()
        get_context_limits("custom", "flaky-model", config, base_url="http://x", fetcher=fetcher)
        get_context_limits("custom", "flaky-model", config, base_url="http://x", fetcher=fetcher)
        assert calls == ["flaky-model", "flaky-model"]

    def test_limits_from_dict_helper(self):
        limits = limits_from_dict({"window": 1000, "max_output": 100})
        assert limits is not None and limits.window == 1000
        assert limits_from_dict({"window": 0}) is None


# ---------------------------------------------------------------------------
# Learned layer
# ---------------------------------------------------------------------------
class TestLearned:
    def test_learned_limit_round_trip_and_precedence(self):
        config = _config()
        ml.record_learned_limit("custom", "learned-model", "http://x", 150_000, config=config)
        limits = get_context_limits("custom", "learned-model", config, base_url="http://x")
        assert limits.window == 150_000
        assert limits.source == "learned"

    def test_learned_beats_catalog_but_not_user(self):
        config = _config()
        ml.record_learned_limit("openai", "gpt-4o", "", 200_000, config=config)
        learned = get_context_limits("openai", "gpt-4o", config)
        assert learned.window == 200_000 and learned.source == "learned"
        user = get_context_limits("openai", "gpt-4o", _config(MODEL_CONTEXT_WINDOWS={"gpt-4o": 130_000}))
        assert user.window == 130_000 and user.source == "user"

    def test_learned_persists_across_sessions(self):
        config = _config()
        ml.record_learned_limit("custom", "persisted-learned", "http://x", 42_000, config=config)
        ml._MEMORY.clear()
        limits = get_context_limits("custom", "persisted-learned", config, base_url="http://x")
        assert limits.window == 42_000
        assert limits.source == "learned"

    def test_invalid_learned_value_is_ignored(self):
        assert ml.record_learned_limit("custom", "bad", "", 0) is None
        assert ml.record_learned_limit("custom", "", "", 1000) is None


# ---------------------------------------------------------------------------
# Budget formula
# ---------------------------------------------------------------------------
class TestBudget:
    def test_reserve_is_max_tokens_plus_safety(self):
        limits = ModelLimits(window=128_000)
        budget = context_input_budget(limits, max_tokens=1024, safety_tokens=1024)
        assert budget == 128_000 - 2048

    def test_default_safety(self):
        budget = context_input_budget(ModelLimits(window=100_000), max_tokens=0)
        assert budget == 100_000 - DEFAULT_SAFETY_TOKENS

    def test_override_wins_verbatim(self):
        budget = context_input_budget(ModelLimits(window=128_000), max_tokens=1024, override=5000)
        assert budget == 5000

    def test_max_input_cap_is_used(self):
        limits = ModelLimits(window=1_000_000, max_input=32_768)
        assert context_input_budget(limits, max_tokens=0, safety_tokens=0) == 32_768

    def test_never_below_one(self):
        assert context_input_budget(ModelLimits(window=100), max_tokens=1024, safety_tokens=1024) == 1

    def test_unknown_limits_use_default_window(self):
        budget = context_input_budget(ModelLimits(source="default"), max_tokens=1024, safety_tokens=1024)
        assert budget == DEFAULT_CONTEXT_WINDOW - 2048
