"""Model context-window resolution and per-request input budget.

This module is the single source of truth for "how large is the model's context
window" and "how much of it may a request use". It is a stdlib-only leaf module
(imported on the request path and by :mod:`yaicli.tokens`), so it must never
import rich/typer/provider SDKs or the ``cfg`` singleton.

Resolution is layered and short-circuits on the first hit (v0.23 K22):

1. ``user``      — ``MODEL_CONTEXT_WINDOWS`` config (highest priority);
2. ``learned``   — the real limit parsed from a provider context-length error;
3. ``metadata``  — provider-advertised values via the ``Provider.model_limits()``
   hook (OpenRouter / Gemini / Ollama), fetched lazily and cached;
4. ``catalog``   — the bundled snapshot ``data/model_limits.json``;
5. ``heuristic`` — provider-scoped family prefixes (longest prefix wins);
6. ``default``   — :data:`DEFAULT_CONTEXT_WINDOW` with ``source="default"``.

Every result carries a ``source`` so the CLI can show where the number came
from; callers must treat ``source == "default"`` as "unknown model". The
Ollama ``NUM_CTX`` option is deliberately ignored (user decision): only the
model metadata (``/api/show``) or an explicit config override is authoritative.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

#: Fallback window for a model missing from every source.
DEFAULT_CONTEXT_WINDOW: int = 128_000
#: Local Ollama servers default to a small window unless metadata says otherwise.
OLLAMA_DEFAULT_CONTEXT_WINDOW: int = 8_192
#: Extra headroom kept below ``window - MAX_TOKENS`` for tokenizer/request drift.
DEFAULT_SAFETY_TOKENS: int = 1_024
#: How long a provider-metadata result stays valid.
METADATA_TTL_SECONDS: int = 7 * 24 * 3600
#: How long a limit learned from a provider error stays valid.
LEARNED_TTL_SECONDS: int = 30 * 24 * 3600
#: Timeout for one provider metadata probe (seconds).
METADATA_TIMEOUT_SECONDS: float = 2.0
#: How long a failed/empty metadata probe is remembered in-process, so every
#: request round does not re-probe an offline or metadata-less provider.
METADATA_MISS_TTL_SECONDS: int = 5 * 60
#: On-disk cache schema version.
CACHE_VERSION: int = 1

#: ``[1m]`` suffix variants advertise a 1,000,000-token window.
ONE_MILLION_CONTEXT_WINDOW: int = 1_000_000

#: Sources in priority order (also used by tests).
LIMIT_SOURCES: Tuple[str, ...] = ("user", "learned", "metadata", "catalog", "heuristic", "default")


@dataclass(frozen=True)
class ModelLimits:
    """Resolved context limits for one model/provider pair.

    ``window`` is the total context window (input + output). ``max_input`` is a
    separate input-only cap when the provider documents one (Gemini); ``max_output``
    is informational and used by ``/context`` display. ``source`` says which layer
    produced the value; ``detail`` is a short human-readable origin string.
    """

    window: Optional[int] = None
    max_input: Optional[int] = None
    max_output: Optional[int] = None
    source: str = "default"
    detail: str = ""

    @property
    def known(self) -> bool:
        """True when at least one real limit was found (not the fallback)."""
        return self.source != "default"

    def window_for_budget(self) -> int:
        """Return the effective cap used for the input budget."""
        caps = [value for value in (self.window, self.max_input) if value and value > 0]
        return min(caps) if caps else DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
#: Vendor prefixes commonly found in OpenRouter/Bedrock/Vertex-style model ids.
_VENDOR_PREFIXES: Tuple[str, ...] = (
    "openrouter/",
    "anthropic/",
    "openai/",
    "google/",
    "mistralai/",
    "meta-llama/",
    "qwen/",
    "deepseek/",
    "moonshotai/",
    "x-ai/",
    "cohere/",
    "nvidia/",
)
_DATE_SUFFIX_RE = re.compile(r"[-@]\d{8}$")
_ROUTER_VARIANT_RE = re.compile(r":(?:free|batch|extended|nitro|online)$")


def _is_1m_variant(model: str) -> bool:
    """True when the raw model id carries the ``[1m]`` extended-context marker."""
    return "[1m]" in str(model or "").lower()


def normalize_model_name(model: Any) -> str:
    """Normalize a provider-specific model id to a comparison key.

    Lower-cases, strips up to two vendor prefixes (``openrouter/anthropic/...``),
    removes ``-YYYYMMDD``/``@YYYYMMDD`` suffixes, OpenRouter variant suffixes and
    the ``[1m]`` marker. Returns ``""`` for empty input.
    """
    text = str(model or "").strip().lower()
    if not text:
        return ""
    text = text.replace("[1m]", "")
    for _ in range(2):
        for prefix in _VENDOR_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :]
                break
        else:
            break
    text = _DATE_SUFFIX_RE.sub("", text)
    text = _ROUTER_VARIANT_RE.sub("", text)
    return text.strip()


# ---------------------------------------------------------------------------
# User config layer
# ---------------------------------------------------------------------------
def _positive_int(value: Any) -> Optional[int]:
    """Coerce a config/catalog value to a positive int, or ``None``."""
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
    return number if number > 0 else None


def _limits_from_value(value: Any) -> Optional[ModelLimits]:
    """Parse one ``MODEL_CONTEXT_WINDOWS`` value (int or object)."""
    if isinstance(value, Mapping):
        window = _positive_int(value.get("window"))
        max_input = _positive_int(value.get("max_input"))
        max_output = _positive_int(value.get("max_output"))
        if not (window or max_input):
            return None
        return ModelLimits(
            window=window,
            max_input=max_input,
            max_output=max_output,
            source="user",
            detail="MODEL_CONTEXT_WINDOWS",
        )
    window = _positive_int(value)
    if window is None:
        return None
    return ModelLimits(window=window, source="user", detail="MODEL_CONTEXT_WINDOWS")


def parse_user_windows(value: Any) -> Dict[str, ModelLimits]:
    """Normalize ``MODEL_CONTEXT_WINDOWS`` into a lookup map.

    Accepted keys: ``model``, ``provider:model`` and ``provider/model``. A bare
    model key is also registered so a user can override one model globally. JSON
    strings are tolerated for tests/legacy config values; the config layer itself
    converts the value to ``dict`` already.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except ValueError:
            return {}
    if not isinstance(value, Mapping):
        return {}
    resolved: Dict[str, ModelLimits] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip().lower()
        if not key:
            continue
        limits = _limits_from_value(raw_value)
        if limits is None:
            continue
        slash = key.find("/")
        colon = key.find(":")
        if slash != -1 and (colon == -1 or slash < colon):
            provider, _, rest = key.partition("/")
        elif colon != -1:
            provider, _, rest = key.partition(":")
        else:
            provider, rest = "", key
        provider = provider.strip().lower()
        normalized = normalize_model_name(rest)
        if not normalized:
            continue
        if provider:
            resolved[f"{provider}:{normalized}"] = limits
        else:
            resolved[normalized] = limits
    return resolved


def _from_user(config: Optional[Mapping[str, Any]], provider: str, model: str) -> Optional[ModelLimits]:
    if not config or not hasattr(config, "get"):
        return None
    try:
        mapping = parse_user_windows(config.get("MODEL_CONTEXT_WINDOWS"))
    except Exception:  # pragma: no cover - defensive: config mapping must never break a request
        return None
    if not mapping:
        return None
    normalized = normalize_model_name(model)
    for candidate in (f"{provider}:{normalized}", normalized):
        limits = mapping.get(candidate)
        if limits is not None:
            return limits
    return None


# ---------------------------------------------------------------------------
# Heuristic family table (last static fallback before the default)
# ---------------------------------------------------------------------------
#: ``(provider, model_prefix, window)``. ``provider=""`` applies to every provider;
#: a non-empty provider entry only applies to that provider. Matching is
#: longest-prefix-wins. Keep longer/more specific prefixes above shorter ones.
HEURISTIC_CONTEXT_WINDOWS: Tuple[Tuple[str, str, int], ...] = (
    ("", "gpt-4.1", 1_047_576),
    ("", "gpt-4-32k", 32_768),
    ("", "gpt-4o", 128_000),
    ("", "gpt-4-turbo", 128_000),
    ("", "gpt-4", 8_192),
    ("", "gpt-5", 400_000),
    ("", "gpt-3.5", 16_385),
    ("", "o1-mini", 128_000),
    ("", "o1", 200_000),
    ("", "o3", 200_000),
    ("", "o4", 200_000),
    ("", "claude", 200_000),
    ("", "gemini", 1_048_576),
    ("", "deepseek", 128_000),
    ("", "moonshot", 131_072),
    ("", "kimi", 131_072),
    ("", "qwen", 131_072),
    ("", "glm", 128_000),
    ("", "chatglm", 128_000),
    ("", "grok", 131_072),
    ("", "mistral", 128_000),
    ("", "mixtral", 32_768),
    ("", "command", 128_000),
    ("", "cohere", 128_000),
    ("", "minimax", 245_760),
    ("ollama", "llama", OLLAMA_DEFAULT_CONTEXT_WINDOW),
)


def _from_heuristic(provider: str, model: str, normalized: str) -> Optional[ModelLimits]:
    """Resolve the family-prefix layer (provider-scoped, longest prefix wins)."""
    if _is_1m_variant(model):
        return ModelLimits(
            window=ONE_MILLION_CONTEXT_WINDOW,
            source="heuristic",
            detail="[1m] extended context",
        )
    best: Optional[Tuple[int, int]] = None
    for entry_provider, prefix, window in HEURISTIC_CONTEXT_WINDOWS:
        if entry_provider and entry_provider != provider:
            continue
        # Ollama models are served with a small runtime window by default; do not
        # let generic vendor prefixes (qwen/mistral/...) imply a huge window.
        if provider == "ollama" and not entry_provider:
            continue
        if normalized.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), window)
    if best is not None:
        return ModelLimits(window=best[1], source="heuristic", detail="family prefix")
    if provider == "ollama":
        return ModelLimits(
            window=OLLAMA_DEFAULT_CONTEXT_WINDOW,
            source="heuristic",
            detail="ollama default",
        )
    return None


# ---------------------------------------------------------------------------
# Bundled catalog layer
# ---------------------------------------------------------------------------
_CATALOG_FILE = "data/model_limits.json"
_catalog_cache: Optional[Dict[str, Any]] = None


def catalog_path():
    """Return the bundled catalog path (resolved next to this module)."""
    from pathlib import Path

    return Path(__file__).resolve().parent / _CATALOG_FILE


def load_catalog() -> Dict[str, Any]:
    """Load and memoize the bundled catalog; a missing/corrupt file yields ``{}``."""
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    catalog: Dict[str, Any] = {}
    try:
        with open(catalog_path(), "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            catalog = loaded
    except (OSError, ValueError):
        catalog = {}
    _catalog_cache = catalog
    return catalog


def catalog_generated_at() -> str:
    """Return the catalog snapshot date (``""`` when unavailable)."""
    generated = load_catalog().get("generated_at")
    return str(generated) if generated else ""


def _catalog_limits(entry: Any) -> Optional[ModelLimits]:
    if not isinstance(entry, Mapping):
        return None
    window = _positive_int(entry.get("window"))
    max_input = _positive_int(entry.get("max_input"))
    max_output = _positive_int(entry.get("max_output"))
    if not (window or max_input):
        return None
    generated = catalog_generated_at()
    return ModelLimits(
        window=window,
        max_input=max_input,
        max_output=max_output,
        source="catalog",
        detail=f"catalog {generated}".strip(),
    )


def _from_catalog(provider: str, normalized: str) -> Optional[ModelLimits]:
    catalog = load_catalog()
    if not catalog or not normalized:
        return None
    providers = catalog.get("providers")
    if isinstance(providers, Mapping):
        provider_map = providers.get(provider)
        if isinstance(provider_map, Mapping):
            limits = _catalog_limits(provider_map.get(normalized))
            if limits is not None:
                return limits
    # Cloud model ids in the global map are meaningless for a local server: an
    # Ollama deployment serves these names with its own (small) runtime window,
    # so only provider-specific ``providers["ollama"]`` entries apply there.
    if provider != "ollama":
        exact = catalog.get("exact")
        if isinstance(exact, Mapping):
            global_map = exact.get("*")
            if isinstance(global_map, Mapping):
                return _catalog_limits(global_map.get(normalized))
    return None


# ---------------------------------------------------------------------------
# Cache (memory + on-disk, best effort)
# ---------------------------------------------------------------------------
_MEMORY: Dict[str, Tuple[ModelLimits, float]] = {}
_METADATA_MISSES: Dict[str, float] = {}
_DISK: Dict[str, Dict[str, Any]] = {}
_DISK_LOADED = False

#: Public test hook: when set, overrides the cache path (see ``cache_path()``).
CACHE_PATH_OVERRIDE = None


def cache_path():
    """Resolve the on-disk cache path (``<config-dir>/cache/model_limits.json``)."""
    if CACHE_PATH_OVERRIDE is not None:
        from pathlib import Path

        return Path(CACHE_PATH_OVERRIDE)
    from .const import MODEL_LIMITS_CACHE_PATH

    return MODEL_LIMITS_CACHE_PATH


def _cache_enabled(config: Optional[Mapping[str, Any]]) -> bool:
    if config is None or not hasattr(config, "get"):
        return True
    try:
        return bool(config.get("ENABLE_MODEL_LIMITS_CACHE", True))
    except Exception:  # pragma: no cover - defensive
        return True


def _metadata_enabled(config: Optional[Mapping[str, Any]]) -> bool:
    if config is None or not hasattr(config, "get"):
        return True
    try:
        return bool(config.get("ENABLE_MODEL_METADATA", True))
    except Exception:  # pragma: no cover - defensive
        return True


def _cache_key(provider: str, base_url: str, normalized: str) -> str:
    return f"{provider}|{base_url}|{normalized}"


def _load_disk(config: Optional[Mapping[str, Any]]) -> None:
    global _DISK_LOADED, _DISK
    if _DISK_LOADED or not _cache_enabled(config):
        return
    _DISK_LOADED = True
    try:
        with open(cache_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        entries = data.get("entries") if isinstance(data, dict) else None
        if isinstance(entries, dict):
            _DISK = entries
    except (OSError, ValueError):
        _DISK = {}


def _save_disk(config: Optional[Mapping[str, Any]]) -> None:
    if not _cache_enabled(config):
        return
    try:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": CACHE_VERSION, "entries": _DISK}
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        tmp.replace(path)
        try:
            import os

            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - platform dependent
            pass
    except OSError:  # pragma: no cover - read-only HOME / disk errors
        pass


def _remember(key: str, limits: ModelLimits, ttl: int, config: Optional[Mapping[str, Any]]) -> None:
    _MEMORY[key] = (limits, time.time() + ttl)
    if not _cache_enabled(config):
        return
    _load_disk(config)
    _DISK[key] = {
        "window": limits.window,
        "max_input": limits.max_input,
        "max_output": limits.max_output,
        "source": limits.source,
        "detail": limits.detail,
        "saved_at": int(time.time()),
        "ttl": int(ttl),
    }
    _save_disk(config)


def _cached(key: str, config: Optional[Mapping[str, Any]]) -> Optional[ModelLimits]:
    now = time.time()
    hit = _MEMORY.get(key)
    if hit is not None:
        limits, expires = hit
        if expires > now:
            return limits
        _MEMORY.pop(key, None)
    if not _cache_enabled(config):
        return None
    _load_disk(config)
    entry = _DISK.get(key)
    if not isinstance(entry, Mapping):
        return None
    saved_at = _positive_int(entry.get("saved_at")) or 0
    ttl = _positive_int(entry.get("ttl")) or 0
    if ttl and saved_at + ttl <= now:
        _DISK.pop(key, None)
        return None
    window = _positive_int(entry.get("window"))
    max_input = _positive_int(entry.get("max_input"))
    max_output = _positive_int(entry.get("max_output"))
    if not (window or max_input):
        return None
    source = str(entry.get("source") or "")
    if source not in ("metadata", "learned"):
        return None
    return ModelLimits(
        window=window,
        max_input=max_input,
        max_output=max_output,
        source=source,
        detail=str(entry.get("detail") or ""),
    )


def _metadata_miss_expired(key: str) -> bool:
    """True when the key has no live negative-cache entry (probe allowed)."""
    expires = _METADATA_MISSES.get(key)
    if expires is None:
        return True
    if expires > time.time():
        return False
    _METADATA_MISSES.pop(key, None)
    return True


def clear_limit_cache() -> None:
    """Clear every cache layer (tests / explicit refresh)."""
    global _MEMORY, _METADATA_MISSES, _DISK, _DISK_LOADED, _catalog_cache
    _MEMORY = {}
    _METADATA_MISSES = {}
    _DISK = {}
    _DISK_LOADED = False
    _catalog_cache = None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def get_context_limits(
    provider: Optional[str],
    model: Optional[str],
    config: Optional[Mapping[str, Any]] = None,
    *,
    base_url: str = "",
    fetcher: Optional[Callable[[str], Optional[ModelLimits]]] = None,
) -> ModelLimits:
    """Resolve :class:`ModelLimits` through the layered pipeline.

    ``fetcher`` is the provider metadata hook (``provider.model_limits``); it is
    called at most once per cache miss, must be time-bounded by the provider and
    is always wrapped so a failing probe falls through to the static layers.
    """
    provider_name = str(provider or "").strip().lower()
    raw_model = str(model or "").strip()
    normalized = normalize_model_name(raw_model)
    if not normalized:
        return ModelLimits(window=DEFAULT_CONTEXT_WINDOW, source="default", detail="assumed for unknown model")

    # 1. user configuration
    limits = _from_user(config, provider_name, raw_model)
    if limits is not None:
        return limits

    key = _cache_key(provider_name, str(base_url or ""), normalized)

    # 2. learned limits from provider errors
    cached = _cached(key, config)
    if cached is not None and cached.source == "learned":
        return cached

    # 3. provider metadata (memory/disk cache first, then the hook)
    if cached is not None and cached.source == "metadata":
        return cached
    if fetcher is not None and _metadata_enabled(config) and _metadata_miss_expired(key):
        fetched: Optional[ModelLimits] = None
        try:
            fetched = fetcher(raw_model)
        except Exception:  # pragma: no cover - provider probes must never break a request
            fetched = None
        if isinstance(fetched, ModelLimits) and (fetched.window or fetched.max_input):
            resolved = replace(
                fetched,
                source="metadata",
                detail=fetched.detail or "provider metadata",
            )
            _METADATA_MISSES.pop(key, None)
            _remember(key, resolved, METADATA_TTL_SECONDS, config)
            return resolved
        # Remember the empty/failed probe briefly: a metadata-less or offline
        # provider must not cost a 2 s probe on every request round.
        _METADATA_MISSES[key] = time.time() + METADATA_MISS_TTL_SECONDS

    # 4. bundled catalog
    limits = _from_catalog(provider_name, normalized)
    if limits is not None:
        return limits

    # 5. heuristic family prefixes
    limits = _from_heuristic(provider_name, raw_model, normalized)
    if limits is not None:
        return limits

    # 6. conservative default (caller warns once)
    return ModelLimits(window=DEFAULT_CONTEXT_WINDOW, source="default", detail="assumed for unknown model")


def record_learned_limit(
    provider: Optional[str],
    model: Optional[str],
    base_url: str,
    window: Optional[int],
    max_output: Optional[int] = None,
    *,
    config: Optional[Mapping[str, Any]] = None,
) -> Optional[ModelLimits]:
    """Record a real limit learned from a provider context-length error."""
    provider_name = str(provider or "").strip().lower()
    normalized = normalize_model_name(model)
    size = _positive_int(window)
    if not normalized or size is None:
        return None
    limits = ModelLimits(
        window=size,
        max_output=_positive_int(max_output),
        source="learned",
        detail="learned from provider error",
    )
    _remember(_cache_key(provider_name, str(base_url or ""), normalized), limits, LEARNED_TTL_SECONDS, config)
    return limits


def context_input_budget(
    limits: ModelLimits,
    *,
    max_tokens: Optional[int] = None,
    safety_tokens: int = DEFAULT_SAFETY_TOKENS,
    override: Optional[int] = None,
) -> int:
    """Return the number of input tokens a request may use.

    ``override > 0`` (``CONTEXT_BUDGET_TOKENS``) wins verbatim for compatibility.
    Otherwise the budget is ``min(window, max_input) - requested_output - safety``.
    """
    forced = _positive_int(override)
    if forced is not None:
        return forced
    cap = limits.window_for_budget()
    reserve = max(0, _positive_int(max_tokens) or 0) + max(0, _positive_int(safety_tokens) or 0)
    return max(1, cap - reserve)


def limits_from_dict(payload: Mapping[str, Any]) -> Optional[ModelLimits]:
    """Build :class:`ModelLimits` from a provider hook's plain mapping (test helper)."""
    if not isinstance(payload, Mapping):
        return None
    window = _positive_int(payload.get("window"))
    max_input = _positive_int(payload.get("max_input"))
    max_output = _positive_int(payload.get("max_output"))
    if not (window or max_input):
        return None
    return ModelLimits(
        window=window,
        max_input=max_input,
        max_output=max_output,
        source=str(payload.get("source") or "metadata"),
        detail=str(payload.get("detail") or ""),
    )


__all__ = [
    "DEFAULT_CONTEXT_WINDOW",
    "OLLAMA_DEFAULT_CONTEXT_WINDOW",
    "DEFAULT_SAFETY_TOKENS",
    "METADATA_TTL_SECONDS",
    "LEARNED_TTL_SECONDS",
    "METADATA_TIMEOUT_SECONDS",
    "ONE_MILLION_CONTEXT_WINDOW",
    "LIMIT_SOURCES",
    "HEURISTIC_CONTEXT_WINDOWS",
    "ModelLimits",
    "normalize_model_name",
    "parse_user_windows",
    "load_catalog",
    "catalog_path",
    "catalog_generated_at",
    "cache_path",
    "get_context_limits",
    "record_learned_limit",
    "context_input_budget",
    "limits_from_dict",
    "clear_limit_cache",
]
