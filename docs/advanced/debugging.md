# Debugging & Logs

How to diagnose problems with YAICLI itself.

## Verbose mode

```bash
ai --verbose "hello"
```

Verbose mode prints the effective configuration, the current role, the provider request
messages/tools, and tracebacks for handled errors. Only `API_KEY` is masked — be careful when
sharing the output because provider-specific credentials may appear.

## Exit codes

Successful runs exit `0`; handled failures exit `1` (configuration errors, provider/API errors,
missing credentials, no input). See [Exit Codes](../usage/cli.md#exit-codes). In `--chat` mode, a
failed turn prints the error and keeps the session alive instead of exiting.

## Isolate the environment

```bash
# fresh config/roles/functions in a temp HOME
HOME=/tmp/yaicli-debug ai --verbose "hello"

# inspect the default config template
ai --template

# print the effective config file path (shown by --verbose)
```

Common causes:

- **Provider errors**: verify `PROVIDER` with `ai --list-providers`, then check `MODEL`,
  `BASE_URL` and the API key.
- **Function changes not taking effect**: built-in function definitions are copied into
  `~/.config/yaicli/functions/`; run `ai --reinstall-functions` after upgrading.
- **Network/proxy**: `HTTPS_PROXY`/`HTTP_PROXY` are honoured by the HTTP stack; an invalid
  `BASE_URL` causes connection errors.
- **MCP**: `~/.config/yaicli/mcp.json` must be valid JSON; run `ai --list-mcp`.

When reporting a bug, include the command, the expected vs actual behaviour, the exit code, and
the relevant (redacted) verbose output.
