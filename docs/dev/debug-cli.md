# CLI Debugging

Practical recipes for debugging YAICLI when working from a source checkout.

## Run the code you are editing

The package does not need to be installed. From the repository root:

```bash
# point imports at this checkout and keep user state out of your real HOME
PYTHONPATH=. HOME=/tmp/yaicli-dev COLUMNS=120 python -m yaicli.entry "hello"
```

`python -m yaicli.entry` is the same Typer app as the `ai` console script. A throwaway `HOME`
gives you a fresh config file, roles/functions directories and chat storage, so experiments
cannot corrupt your real `~/.config/yaicli`.

## Verbose mode

```bash
ai --verbose "hello"
```

`--verbose` prints the loaded configuration (API key masked), the current role, provider
messages/tools for each request, and tracebacks for handled errors. Do not paste verbose output
into bug reports without checking it: only `API_KEY` is masked, other credentials in
`EXTRA_HEADERS`/provider-specific keys are not.

## Common failures

| Symptom | Likely cause / fix |
| --- | --- |
| `Unknown provider: <name>` | The `PROVIDER` value is not a `ProviderFactory.providers_map` key. Run `ai --list-providers`. |
| `API_KEY is required` | No key in `API_KEY`, `YAI_API_KEY`, or the provider-specific fallback. |
| `ModelAPIError` / HTTP 4xx | Check model name, base URL, and provider credentials with `--verbose`. |
| Config traceback / non-zero exit | Malformed `config.ini` (missing `[core]`, duplicate section). Inspect `ai --template` for the expected format. |
| Functions behave like an old version | Built-in definitions are copied to `~/.config/yaicli/functions/`; run `ai --reinstall-functions`. |
| Markup/render crash | Untrusted strings must go through `yaicli/console.py` helpers (`safe_text`, `untrusted_text`, `print_untrusted`). |
| Process exits `0` after an error message | Should not happen — handled failures exit `1` (`entry.py`); file a bug with the command and exit code. |

## Exit codes

`0` on success, `1` on handled failures (config/provider/API/no-input). In `--chat` mode an
error in one turn keeps the REPL alive; the exit code reflects leaving the REPL. See
[Exit codes](../usage/cli.md#exit-codes).

## Isolate components

- **Config**: import `yaicli.config.cfg` and print it; the singleton is built at import time.
- **Provider only**: instantiate the provider with a dict config and a mocked `CLIENT_CLS`, then
  call `_handle_normal_response()` / `_handle_stream_response()` with constructed
  `ChatCompletion` / `ChatCompletionChunk` objects (see `tests/llms/`).
- **Tool only**: call `execute_tool_call(ToolCall(...))` with `yaicli.tools.cfg` patched and
  `get_function`/`get_mcp` mocked (`tests/tools/`).
- **CLI/REPL**: inject a mock client via `CLI(client=...)`; `tests/conftest.py` provides
  `patched_config_path`, `setup_test_environment`, `cli`, `mock_console`.

## Tests

```bash
uv run pytest tests/test_entry.py tests/test_cli.py -q   # CLI behaviour
uv run pytest -k "markup or confirmation" -q            # safety paths
```

Use `pytest -x --pdb` to drop into the debugger on the first failure, and
`ruff check yaicli tests` before pushing.

## Where to put temporary output

Use the project console (`get_console()`) or `print()` in `entry.py` only; remove debug output
before committing. `tests/` never call real APIs — keep it that way when adding diagnostics.
