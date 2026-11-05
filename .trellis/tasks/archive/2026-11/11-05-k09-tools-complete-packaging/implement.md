# K09 implementation plan

## Change boundary

- Behaviour gap: base install carried `anthropic[bedrock,vertex]` (cloud SDK closure) while every
  builtin tool dependency must stay in base. Only the cloud closure moves to extras.
- Files: `pyproject.toml` (+`uv.lock`), `yaicli/llms/provider.py` (missing-SDK hint),
  `yaicli/llms/providers/anthropic_provider.py` (fast-fail cloud extra + api_key fix),
  `tests/test_packaging.py`, provider tests, README/docs install matrix, packaging spec.

## Steps

- [x] `pyproject.toml`: base `anthropic[bedrock,vertex]` -> `anthropic`; add `bedrock`/`vertex` extras;
      add `anthropic[bedrock,vertex]` to `[all]`; keep ddgs/trafilatura/fastmcp in base; `uv lock`.
- [x] `ProviderFactory.create_provider`: `_OPTIONAL_PROVIDER_EXTRAS` map; ImportError ->
      `AgentError(kind=CONFIG)` with `pip install "yaicli[<extra>]"` for optional providers.
- [x] Anthropic cloud providers: fast-fail ImportError for missing `boto3`/`google.auth` with the
      extra name; drop the shared `api_key` from Bedrock/Vertex client params (SDK rejects it).
- [x] `tests/test_packaging.py`: Python-3.10-compatible pyproject parser + policy assertions
      (tool deps in base, no cloud extras in base, `bedrock`/`vertex`/`all` defined).
- [x] Docs: README, `docs/install.md`, `docs/providers/overview.md`, `docs/providers/anthropic.md`,
      `docs/advanced/upgrade.md` (v0.20 migration note); `.trellis/spec/repo/build-and-release.md`.
- [x] Build wheel + inspect METADATA; fresh venv base-wheel smoke: 12 builtin tool modules import,
      fastmcp/trafilatura/ddgs present, boto3/google.auth absent, `ai --list-functions` shows builtin
      tools, missing-extra runs print the actionable `pip install "yaicli[bedrock|vertex]"` hint.
- [x] Verify: full pytest (1924 passed), ruff, `mkdocs build --strict`; commit.

## Verification notes

- Wheel METADATA base: `anthropic>=0.57.1` plain; `ddgs`, `trafilatura`, `fastmcp` retained.
  Extras: `bedrock = anthropic[bedrock]`, `vertex = anthropic[vertex]`, `all` keeps
  `anthropic[bedrock,vertex]`.
- Fresh venv from the built wheel: all 12 builtin tool modules + `fastmcp`/`trafilatura`/`ddgs` import;
  `boto3`/`google.auth` not installed; `ai --list-functions` lists 12 builtin tools.
- Missing extra end-to-end: `YAI_PROVIDER=anthropic-bedrock|anthropic-vertex` prints the
  `pip install "yaicli[bedrock|vertex]"` hint and exits 1 (no traceback).
