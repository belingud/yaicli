#!/usr/bin/env python3
"""Cold-start benchmark for YAICLI (K08).

Measures the parts of startup a CLI user feels on every invocation:

- ``--version`` / ``--help`` / ``--template``: full process, cold subprocess each run;
- ``import yaicli.entry``: the CLI surface import (must stay free of prompt_toolkit/SDKs);
- REPL readiness proxy: import ``yaicli.cli`` + construct ``CLI`` with an injected client +
  ``prepare_chat_loop()`` (the real first prompt also waits for the user, so this is the
  machine-side cost only);
- one-shot local overhead: spawn a local OpenAI-compatible mock server and measure the
  time from process start to the server receiving the first request (network excluded,
  localhost only).

The script is stdlib-only and works from a source checkout or an installed wheel:

    python scripts/bench.py                  # human-readable table
    python scripts/bench.py --json           # machine-readable
    python scripts/bench.py --gate           # fail (exit 1) when a P50 exceeds its limit

Results are P50 over ``--iterations`` runs. Interpret them as relative numbers on one machine;
CI uses the ``--gate`` limits to catch gross regressions, not as absolute marketing claims.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Generous CI thresholds (P50 ms). Local development can pass stricter ``--max-*`` flags.
GATE_LIMITS = {
    "version": 250.0,
    "help": 900.0,
    "template": 900.0,
    "entry_import": 900.0,
    "repl_ready": 1800.0,
    "oneshot_local": 1800.0,
}

_COMPLETION_RESPONSE = {
    "id": "chatcmpl-bench",
    "object": "chat.completion",
    "created": 0,
    "model": "gpt-bench",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


class _BenchHandler(BaseHTTPRequestHandler):
    """Tiny OpenAI-compatible endpoint that records when the first request arrives."""

    server: "_BenchServer"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.server.first_request_at is None:
            self.server.first_request_at = time.perf_counter()
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        data = json.dumps(_COMPLETION_RESPONSE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # silence the request log
        pass


class _BenchServer(ThreadingHTTPServer):
    daemon_threads = True
    first_request_at = None


def _isolated_env(config_dir: str) -> dict:
    """Environment that never reads/writes the developer's real YAICLI config."""
    env = os.environ.copy()
    env.update(
        {
            "YAI_CONFIG_DIR": config_dir,
            "YAI_PROVIDER": "openai",
            "YAI_API_KEY": "bench-key",
            "YAI_MODEL": "gpt-bench",
            "YAI_ENABLE_FUNCTIONS": "false",
            "YAI_ENABLE_MCP": "false",
            # Keep the benchmark deterministic: no retries/proxies from the host env.
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    env.pop("OPENAI_API_KEY", None)
    return env


def _run(args, *, env, stdin=subprocess.DEVNULL) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        stdin=stdin,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )


def _p50(values) -> float:
    return round(float(statistics.median(values)), 1)


def _bench_flag(flag: str, iterations: int, env: dict) -> float:
    values = []
    for _ in range(iterations):
        started = time.perf_counter()
        _run([sys.executable, "-m", "yaicli", flag], env=env)
        values.append((time.perf_counter() - started) * 1000)
    return _p50(values)


def _bench_python(code: str, iterations: int, env: dict) -> float:
    values = []
    for _ in range(iterations):
        started = time.perf_counter()
        _run([sys.executable, "-c", code], env=env)
        values.append((time.perf_counter() - started) * 1000)
    return _p50(values)


def _bench_oneshot(iterations: int, env: dict) -> float:
    server = _BenchServer(("127.0.0.1", 0), _BenchHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    one_shot_env = dict(env)
    one_shot_env["YAI_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
    values = []
    try:
        for _ in range(iterations):
            server.first_request_at = None
            started = time.perf_counter()
            _run(
                [sys.executable, "-m", "yaicli", "-p", "bench", "--no-stream"],
                env=one_shot_env,
            )
            if server.first_request_at is None:  # pragma: no cover - mock server failed
                raise RuntimeError("one-shot run never reached the mock provider")
            values.append((server.first_request_at - started) * 1000)
    finally:
        server.shutdown()
        server.server_close()
    return _p50(values)


def run_bench(iterations: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="yaicli-bench-") as config_dir:
        env = _isolated_env(config_dir)
        return {
            "version": _bench_flag("--version", iterations, env),
            "help": _bench_flag("--help", iterations, env),
            "template": _bench_flag("--template", iterations, env),
            "entry_import": _bench_python("import yaicli.entry", iterations, env),
            "repl_ready": _bench_python(
                "from unittest.mock import MagicMock\n"
                "from yaicli.cli import CLI\n"
                "cli = CLI(client=MagicMock())\n"
                "cli.prepare_chat_loop()",
                iterations,
                env,
            ),
            "oneshot_local": _bench_oneshot(iterations, env),
        }


def _format_table(results: dict) -> str:
    lines = [f"{'metric':<16}{'P50 (ms)':>10}{'gate (ms)':>12}"]
    lines.append("-" * 38)
    for name, value in results.items():
        lines.append(f"{name:<16}{value:>10.1f}{GATE_LIMITS.get(name, 0):>12.0f}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="YAICLI cold-start benchmark (K08).")
    parser.add_argument("-n", "--iterations", type=int, default=5, help="runs per metric (default 5)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--gate", action="store_true", help="exit 1 when a P50 exceeds its gate limit")
    parser.add_argument("--max-version-ms", type=float, default=None)
    parser.add_argument("--max-help-ms", type=float, default=None)
    parser.add_argument("--max-entry-import-ms", type=float, default=None)
    parser.add_argument("--max-repl-ready-ms", type=float, default=None)
    parser.add_argument("--max-oneshot-local-ms", type=float, default=None)
    args = parser.parse_args(argv)

    results = run_bench(max(1, args.iterations))

    limits = dict(GATE_LIMITS) if args.gate else {}
    overrides = {
        "version": args.max_version_ms,
        "help": args.max_help_ms,
        "entry_import": args.max_entry_import_ms,
        "repl_ready": args.max_repl_ready_ms,
        "oneshot_local": args.max_oneshot_local_ms,
    }
    for name, limit in overrides.items():
        if limit is not None:
            limits[name] = limit

    if args.json:
        print(json.dumps({"results": results, "limits": limits}, indent=2))
    elif limits:
        lines = [f"{'metric':<16}{'P50 (ms)':>10}{'limit (ms)':>12}  status"]
        lines.append("-" * 52)
        for name, value in results.items():
            limit = limits.get(name)
            if limit is None:
                lines.append(f"{name:<16}{value:>10.1f}{'-':>12}  -")
            else:
                status = "ok" if value <= limit else "FAIL"
                lines.append(f"{name:<16}{value:>10.1f}{limit:>12.0f}  {status}")
        print("\n".join(lines))
    else:
        print(_format_table(results))

    failures = [name for name, limit in limits.items() if name in results and results[name] > limit]
    if failures:
        print(f"benchmark gate failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
