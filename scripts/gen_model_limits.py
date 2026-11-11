#!/usr/bin/env python3
"""Generate ``yaicli/data/model_limits.json`` from public model catalogs.

The generated file is a *snapshot*: it is committed with the repository and
loaded offline by ``yaicli.model_limits``. This script never performs network
I/O; download the upstream JSON files yourself (or in CI) and pass them in.

Sources (all optional; curated entries are always included):

* OpenRouter  — ``https://openrouter.ai/api/v1/models`` (``context_length``,
  ``top_provider.max_completion_tokens``);
* models.dev  — ``https://models.dev/api.json`` (``providers -> models ->
  limit.context / limit.output``);
* LiteLLM     — ``model_prices_and_context_window.json``
  (``max_input_tokens`` / ``max_output_tokens`` / ``litellm_provider``).

Usage::

    python scripts/gen_model_limits.py \
        --openrouter /tmp/openrouter-models.json \
        --modelsdev /tmp/models-dev.json \
        --litellm /tmp/litellm.json \
        --out yaicli/data/model_limits.json

Only ``provider``-scoped entries are emitted for remote catalogs so that a
window advertised by one provider never silently applies to another deployment.
``exact["*"]`` holds the curated, provider-independent entries (models whose
window is the same everywhere) and is never applied to Ollama.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "yaicli" / "data" / "model_limits.json"

#: Curated cross-provider entries: ``normalized model id -> {"window", "max_output"}``.
#: Only models whose context window is identical across every provider serving them.
CURATED_EXACT: Dict[str, Dict[str, int]] = {
    # OpenAI
    "gpt-4.1": {"window": 1_047_576, "max_output": 32_768},
    "gpt-4.1-mini": {"window": 1_047_576, "max_output": 32_768},
    "gpt-4o": {"window": 128_000, "max_output": 16_384},
    "gpt-4o-mini": {"window": 128_000, "max_output": 16_384},
    "gpt-4-turbo": {"window": 128_000, "max_output": 4_096},
    "gpt-4-32k": {"window": 32_768, "max_output": 8_192},
    "gpt-4": {"window": 8_192, "max_output": 8_192},
    "gpt-3.5-turbo": {"window": 16_385, "max_output": 4_096},
    "gpt-5": {"window": 400_000, "max_output": 128_000},
    "gpt-5-mini": {"window": 400_000, "max_output": 128_000},
    "o1": {"window": 200_000, "max_output": 100_000},
    "o1-mini": {"window": 128_000, "max_output": 65_536},
    "o3": {"window": 200_000, "max_output": 100_000},
    "o3-mini": {"window": 200_000, "max_output": 100_000},
    "o4-mini": {"window": 200_000, "max_output": 100_000},
    # Anthropic
    "claude-3-7-sonnet": {"window": 200_000, "max_output": 64_000},
    "claude-sonnet-4": {"window": 200_000, "max_output": 64_000},
    "claude-opus-4": {"window": 200_000, "max_output": 32_000},
    "claude-3-5-haiku": {"window": 200_000, "max_output": 8_192},
    # Google
    "gemini-2.5-pro": {"window": 1_048_576, "max_output": 65_536},
    "gemini-2.5-flash": {"window": 1_048_576, "max_output": 65_536},
    "gemini-2.0-flash": {"window": 1_048_576, "max_output": 8_192},
    "gemini-1.5-pro": {"window": 2_097_152, "max_output": 8_192},
    # DeepSeek / Moonshot / Qwen / GLM (native provider ids)
    "deepseek-chat": {"window": 128_000, "max_output": 8_192},
    "deepseek-reasoner": {"window": 128_000, "max_output": 65_536},
    "moonshot-v1-8k": {"window": 8_192, "max_output": 8_192},
    "moonshot-v1-32k": {"window": 32_768, "max_output": 32_768},
    "moonshot-v1-128k": {"window": 131_072, "max_output": 131_072},
    "kimi-k2": {"window": 131_072, "max_output": 131_072},
    "qwen-max": {"window": 32_768, "max_output": 8_192},
    "qwen-plus": {"window": 131_072, "max_output": 8_192},
    "qwen-turbo": {"window": 1_000_000, "max_output": 8_192},
    "glm-4": {"window": 128_000, "max_output": 4_096},
    "glm-4-plus": {"window": 128_000, "max_output": 4_096},
    # Others
    "command-r": {"window": 128_000, "max_output": 4_096},
    "mistral-large": {"window": 131_072, "max_output": 8_192},
    "grok-4": {"window": 256_000, "max_output": 64_000},
}

#: models.dev provider id -> yaicli provider key.
_MODELSDEV_PROVIDER_MAP = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "gemini",
    "deepseek": "deepseek",
    "ollama": "ollama",
    "openrouter": "openrouter",
    "groq": "groq",
    "xai": "xai",
    "mistral": "mistral",
    "cohere": "cohere",
    "moonshotai": "moonshot",
    "alibaba": "bailian",
}

#: LiteLLM ``litellm_provider`` -> yaicli provider key.
_LITELLM_PROVIDER_MAP = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "deepseek": "deepseek",
    "ollama": "ollama",
    "openrouter": "openrouter",
    "groq": "groq",
    "xai": "xai",
    "mistral": "mistral",
    "cohere": "cohere",
    "moonshot": "moonshot",
}

#: Vendor prefixes stripped from OpenRouter ids (mirrors yaicli.model_limits).
_VENDOR_PREFIXES = (
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


def normalize_model_name(model: Any) -> str:
    """Mirror of ``yaicli.model_limits.normalize_model_name`` (kept import-free)."""
    import re

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
    text = re.sub(r"[-@]\d{8}$", "", text)
    text = re.sub(r":(?:free|batch|extended|nitro|online)$", "", text)
    return text.strip()


def _positive(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _merge_entry(target: Dict[str, Dict[str, int]], model: Any, window: Any, max_output: Any) -> None:
    """Merge one entry, keeping the larger window for duplicate ids."""
    normalized = normalize_model_name(model)
    size = _positive(window)
    if not normalized or size is None:
        return
    existing = target.get(normalized)
    entry = {"window": size}
    output = _positive(max_output)
    if output:
        entry["max_output"] = output
    if existing is None or entry["window"] > existing["window"]:
        target[normalized] = entry


def load_openrouter(path: Path) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Return ``{"openrouter": {normalized_id: entry}}`` from an OpenRouter dump."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("data") if isinstance(data, dict) else data
    models: Dict[str, Dict[str, int]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        top = row.get("top_provider") or {}
        window = row.get("context_length") or (top.get("context_length") if isinstance(top, dict) else None)
        output = top.get("max_completion_tokens") if isinstance(top, dict) else None
        _merge_entry(models, row.get("id"), window, output)
    return {"openrouter": models}


def load_modelsdev(path: Path) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Return ``{yaicli_provider: {model: entry}}`` from a models.dev dump."""
    data = json.loads(path.read_text(encoding="utf-8"))
    result: Dict[str, Dict[str, Dict[str, int]]] = {}
    if not isinstance(data, dict):
        return result
    for provider, payload in data.items():
        mapped = _MODELSDEV_PROVIDER_MAP.get(str(provider).lower())
        if not mapped or not isinstance(payload, dict):
            continue
        bucket = result.setdefault(mapped, {})
        for model, info in (payload.get("models") or {}).items():
            if not isinstance(info, dict):
                continue
            limit = info.get("limit") or {}
            if not isinstance(limit, dict):
                continue
            _merge_entry(bucket, model, limit.get("context"), limit.get("output"))
    return result


def load_litellm(path: Path) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Return ``{yaicli_provider: {model: entry}}`` from a LiteLLM dump."""
    data = json.loads(path.read_text(encoding="utf-8"))
    result: Dict[str, Dict[str, Dict[str, int]]] = {}
    if not isinstance(data, dict):
        return result
    for model, info in data.items():
        if not isinstance(info, dict):
            continue
        mapped = _LITELLM_PROVIDER_MAP.get(str(info.get("litellm_provider") or "").lower())
        if not mapped:
            continue
        # Drop the provider prefix some LiteLLM keys carry (``openai/gpt-4o``).
        _merge_entry(
            result.setdefault(mapped, {}),
            str(model).split("/")[-1],
            info.get("max_input_tokens") or info.get("max_tokens"),
            info.get("max_output_tokens"),
        )
    return result


def build_catalog(
    *,
    openrouter: Optional[Path] = None,
    modelsdev: Optional[Path] = None,
    litellm: Optional[Path] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge every available source into the catalog payload."""
    providers: Dict[str, Dict[str, Dict[str, int]]] = {}
    for loader, path in (
        (load_openrouter, openrouter),
        (load_modelsdev, modelsdev),
        (load_litellm, litellm),
    ):
        if path is None:
            continue
        for provider, models in loader(path).items():
            bucket = providers.setdefault(provider, {})
            for model, entry in models.items():
                current = bucket.get(model)
                if current is None or entry["window"] > current["window"]:
                    bucket[model] = entry
    return {
        "version": 1,
        "generated_at": generated_at or _dt.date.today().isoformat(),
        "sources": {
            "openrouter": "https://openrouter.ai/api/v1/models",
            "modelsdev": "https://models.dev/api.json",
            "litellm": ("https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"),
            "curated": "yaicli/scripts/gen_model_limits.py",
        },
        "exact": {"*": {model: dict(entry) for model, entry in sorted(CURATED_EXACT.items())}},
        "providers": {
            provider: {model: dict(entry) for model, entry in sorted(models.items())}
            for provider, models in sorted(providers.items())
        },
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openrouter", type=Path, default=None, help="OpenRouter /models JSON dump")
    parser.add_argument("--modelsdev", type=Path, default=None, help="models.dev api.json dump")
    parser.add_argument("--litellm", type=Path, default=None, help="LiteLLM model window JSON dump")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output path")
    parser.add_argument("--date", default=None, help="override generated_at (YYYY-MM-DD)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not any((args.openrouter, args.modelsdev, args.litellm)):
        print("warning: no catalog input given; writing curated-only snapshot", file=sys.stderr)

    catalog = build_catalog(
        openrouter=args.openrouter,
        modelsdev=args.modelsdev,
        litellm=args.litellm,
        generated_at=args.date,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    total = sum(len(models) for models in catalog["providers"].values())
    print(
        f"wrote {args.out} (exact={len(catalog['exact']['*'])}, "
        f"providers={len(catalog['providers'])}, entries={total})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
