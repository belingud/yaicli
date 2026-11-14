"""A provider response with no model payload must be an error, not a silent success.

Regression for the "wrong BASE_URL shows no error" report: pointing ``BASE_URL`` at a
web page (for example ``https://host/`` without the ``/v1`` API path) can answer
HTTP 200 with HTML. The OpenAI SDK's SSE parser then yields no chunks at all, so
before this fix the CLI printed nothing, reported ``error: null`` and exited 0.

The client now raises ``ErrorKind.EMPTY_RESPONSE`` and both the REPL and the
headless output surface an actionable message (naming BASE_URL / ``/v1``).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.entry import app
from yaicli.errors import AgentError, ErrorKind
from yaicli.llms.client import LLMClient
from yaicli.llms.provider import Provider
from yaicli.schemas import ChatMessage, LLMResponse

runner = CliRunner()

HTML_BODY = b"<html><body><h1>Welcome</h1><p>not an API</p></body></html>"


class _EmptyProvider(Provider):
    """Provider double that yields exactly the given responses."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.config = {"ENABLE_FUNCTIONS": False, "ENABLE_MCP": False}

    def completion(self, messages, stream=False, tool_policy=None):
        for response in self.responses:
            yield response

    def detect_tool_role(self):
        return "tool"


@pytest.fixture
def base_config():
    return {
        "API_KEY": "fake_api_key",
        "BASE_URL": "https://fake-api.openai.com/v1",
        "MODEL": "gpt-test",
        "TEMPERATURE": 0.7,
        "TOP_P": 1.0,
        "MAX_TOKENS": 1000,
        "TIMEOUT": 10,
        "PROVIDER": "openai",
        "ENABLE_FUNCTIONS": False,
        "ENABLE_MCP": False,
        "MAX_TOOL_CALL_DEPTH": 3,
        "TOOL_CONFIRM": False,
    }


@pytest.fixture
def html_base_url(monkeypatch):
    """A local endpoint that answers every POST with a 200 HTML page."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(HTML_BODY)))
            self.end_headers()
            self.wfile.write(HTML_BODY)

        def log_message(self, *args):  # pragma: no cover - silence access log
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def _patch_cfg(monkeypatch, base_url: str) -> None:
    """Point the process config singleton at the local HTML endpoint."""
    monkeypatch.setitem(cfg, "PROVIDER", "openai")
    monkeypatch.setitem(cfg, "BASE_URL", base_url)
    monkeypatch.setitem(cfg, "API_KEY", "test-key")
    monkeypatch.setitem(cfg, "MODEL", "gpt-test")
    monkeypatch.setitem(cfg, "ENABLE_FUNCTIONS", False)
    monkeypatch.setitem(cfg, "ENABLE_MCP", False)
    monkeypatch.setitem(cfg, "STREAM", True)
    monkeypatch.setitem(cfg, "RETRY_MAX", 0)
    monkeypatch.setitem(cfg, "TOOL_CONFIRM", False)


class TestClientEmptyResponse:
    """The client classifies an empty provider round instead of returning silently."""

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_no_chunks_raises_empty_response(self, mock_factory, base_config):
        mock_factory.return_value = _EmptyProvider([])
        client = LLMClient(provider_name="openai", config=base_config)

        with pytest.raises(AgentError) as info:
            list(client.completion_with_tools([ChatMessage(role="user", content="hi")], stream=True))

        assert info.value.kind is ErrorKind.EMPTY_RESPONSE
        assert "BASE_URL" in info.value.message
        assert "/v1" in info.value.message

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_finish_reason_is_reported(self, mock_factory, base_config):
        mock_factory.return_value = _EmptyProvider([LLMResponse(content="", finish_reason="content_filter")])
        client = LLMClient(provider_name="openai", config=base_config)

        with pytest.raises(AgentError) as info:
            list(client.completion_with_tools([ChatMessage(role="user", content="hi")], stream=True))

        assert info.value.kind is ErrorKind.EMPTY_RESPONSE
        assert "content_filter" in info.value.message

    @patch("yaicli.llms.provider.ProviderFactory.create_provider")
    def test_non_empty_content_still_works(self, mock_factory, base_config):
        mock_factory.return_value = _EmptyProvider([LLMResponse(content="hello")])
        client = LLMClient(provider_name="openai", config=base_config)

        chunks = list(client.completion_with_tools([ChatMessage(role="user", content="hi")], stream=True))

        assert any(getattr(chunk, "content", "") == "hello" for chunk in chunks)


class TestHeadlessEmptyResponse:
    """``-p`` must fail with exit 1 and a structured error instead of exiting 0."""

    def test_json_reports_empty_response(self, html_base_url, monkeypatch):
        _patch_cfg(monkeypatch, html_base_url)

        result = runner.invoke(app, ["-p", "--output-format", "json", "hi"])

        assert result.exit_code == 1, result.stderr
        payload = json.loads(result.stdout)
        assert payload["content"] == ""
        assert payload["error"]["kind"] == "empty_response"
        assert "BASE_URL" in payload["error"]["message"]
        assert payload["exit_code"] == 1

    def test_text_reports_error_on_stderr(self, html_base_url, monkeypatch):
        _patch_cfg(monkeypatch, html_base_url)

        result = runner.invoke(app, ["-p", "hi"])

        assert result.exit_code == 1
        assert "empty response" in result.stderr.lower()
        assert "BASE_URL" in result.stderr


class TestReplEmptyResponse:
    """The interactive REPL prints the classified error instead of silently looping."""

    def test_repl_prints_classified_error(self, html_base_url, monkeypatch):
        _patch_cfg(monkeypatch, html_base_url)

        stream = StringIO()
        cli = CLI(verbose=False)
        cli.interactive = True
        cli.machine_output = False
        cli.console = Console(file=stream, width=120)
        cli.printer = cli._make_printer()
        monkeypatch.setattr(CLI, "_start_generation_watcher", lambda self: None)

        cli._process_user_input("hi")

        output = stream.getvalue()
        assert cli.had_error is True
        assert "Error processing LLM response" in output
        assert "empty response" in output.lower()
        assert "BASE_URL" in output
