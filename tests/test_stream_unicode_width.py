"""Measure real Printer/Live output with an independent terminal-width oracle."""

import re
import threading
from io import StringIO
from types import SimpleNamespace

import pytest
from rich.panel import Panel
from wcwidth import wcswidth

from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.console import YaiConsole
from yaicli.llms.provider import ProviderFactory
from yaicli.printer import Printer
from yaicli.schemas import LLMResponse, RefreshLive, ToolCall, ToolPolicy
from yaicli.tools import output_history
from yaicli.tools.approval import ToolApprovalManager

# Strip control sequences, but retain all padding: an extra trailing space can
# wrap a frame and invalidate Live's cursor-up / erase calculations.
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@pytest.mark.parametrize("width", [60, 200])
@pytest.mark.parametrize("glyph", ["☀️", "❤️", "天", "🙂"], ids=["sun-vs16", "heart-vs16", "cjk", "emoji"])
def test_live_frames_fit_terminal_after_tool_refresh(width: int, glyph: str):
    """VS16 padding must not overflow real Live frames after a tool result.

    Rich 14.0.0 measured a VS16 sun/heart as one cell, padding a 60-column
    frame to 61 terminal cells. The unexpected wrap left old answer lines in
    scrollback, even though the input and returned content were unique. Use
    wcwidth (already required by prompt-toolkit), not Rich's own width helpers.
    """
    output = StringIO()
    console = YaiConsole(
        file=output,
        force_terminal=True,
        color_system=None,
        width=width,
        height=12,
        _environ={"TERM": "xterm-256color"},
    )
    printer = Printer(
        console=console,
        config={"CODE_THEME": "monokai", "SHOW_REASONING": False, "SHOW_THINKING_STATUS": False},
    )
    prefix = "今天杭州天气不错，是个晴天 " + glyph
    tail = "\n\n" + "\n".join(f"第{i:02d}项：温度适宜，空气清新，注意防晒。" for i in range(1, 16))
    expected = prefix + tail
    emitted = []

    def stream():
        yield RefreshLive()
        console.print("@ Function call: get_weather()")
        console.print(Panel("\n".join(f"weather tool row {i}" for i in range(20)), title="Tool result"))
        emitted.append(prefix)
        yield LLMResponse(content=prefix)
        for offset in range(0, len(tail), 3):
            delta = tail[offset : offset + 3]
            emitted.append(delta)
            yield LLMResponse(content=delta)

    content, reasoning = printer.display_stream(stream())
    raw = output.getvalue()
    assert "".join(emitted) == expected
    assert content == expected
    assert content.count(prefix) == 1
    assert reasoning == ""
    assert raw.count("@ Function call: get_weather()") == 1
    assert "\x1b[2K" in raw  # Real Live erases/redraws; do not replace it with a mock.
    lines = _CSI.sub("", raw).splitlines()
    assert sum(line.startswith(prefix) for line in lines) > 1
    measured = [(wcswidth(line), line) for line in lines if line]
    assert all(0 <= cells <= width for cells, _ in measured), [
        (cells, repr(line)) for cells, line in measured if not 0 <= cells <= width
    ][:3]


@pytest.mark.parametrize("width", [60, 200])
def test_threaded_weather_tool_and_debug_preserve_unique_answer(width, tmp_path, monkeypatch):
    """Exercise the real client, tool dispatcher, worker bridge and Live renderer.

    Only the provider and weather function are fake; the keyboard watcher is a
    no-input stub so this test never reads the user's terminal. Debug must use
    the CLI's actual generation lifecycle and a private file, not manual events.
    """
    prefix = "今天杭州天气不错，是个晴天 ☀️"
    tail = "\n\n" + "\n".join(f"第{i:02d}项：温度适宜，空气清新，注意防晒。" for i in range(1, 16))
    expected = prefix + tail
    tool_result = "\n".join(f"weather tool row {i}" for i in range(20))
    debug_path = tmp_path / "debug.log"
    outputs = []
    # Preserve the viewer history owned by other tests.
    monkeypatch.setattr(output_history, "_entries", output_history._entries.copy())
    monkeypatch.setattr(output_history, "_sequence", output_history._sequence)

    for debug_enabled in (False, True):
        if debug_enabled:
            monkeypatch.setenv("YAI_DEBUG_LOG", str(debug_path))
        else:
            monkeypatch.delenv("YAI_DEBUG_LOG", raising=False)
        calls = []
        requests = []
        emitted = []

        def weather(*, city):
            calls.append((city, threading.current_thread().name))
            return tool_result

        class WeatherProvider:
            def resolve_tool_policy(self, policy):
                return policy or ToolPolicy(True, False)

            def detect_tool_role(self):
                return "tool"

            def completion(self, messages, stream=False, tool_policy=None):
                requests.append(list(messages))
                assert stream is True
                if len(requests) == 1:
                    yield LLMResponse(
                        tool_call=ToolCall(id="weather-1", name="get_weather", arguments='{"city":"Hangzhou"}'),
                        finish_reason="tool_calls",
                    )
                else:
                    assert len(requests) == 2
                    emitted.append(prefix)
                    yield LLMResponse(content=prefix)
                    for offset in range(0, len(tail), 3):
                        delta = tail[offset : offset + 3]
                        emitted.append(delta)
                        yield LLMResponse(content=delta)
                    yield LLMResponse(finish_reason="stop")

        output = StringIO()
        console = YaiConsole(
            file=output,
            force_terminal=True,
            color_system=None,
            width=width,
            height=12,
            _environ={"TERM": "xterm-256color"},
        )
        monkeypatch.setattr("yaicli.cli.get_console", lambda: console)
        monkeypatch.setattr("yaicli.cli.get_error_console", lambda: console)
        monkeypatch.setattr(ProviderFactory, "create_provider", lambda *a, **k: WeatherProvider())
        monkeypatch.setattr("yaicli.tools.executor.get_function", lambda name: SimpleNamespace(execute=weather))
        monkeypatch.setattr(
            "yaicli.cli.ToolApprovalManager",
            lambda: ToolApprovalManager(permissions_path=tmp_path / "permissions.json"),
        )
        watcher = SimpleNamespace(take_viewer_request=lambda: False, stop=lambda: "")
        monkeypatch.setattr(CLI, "_start_generation_watcher", lambda self: watcher)
        config = {
            **cfg,
            "PROVIDER": "openai",
            "ENABLED_TOOLS": "get_weather",
            "ENABLE_FUNCTIONS": True,
            "ENABLE_MCP": False,
            "ENABLE_PROJECT_CONTEXT": False,
            "STREAM": True,
            "SHOW_FUNCTION_OUTPUT": True,
            "SHOW_REASONING": False,
            "SHOW_THINKING_STATUS": False,
            "TOOL_CONFIRM": False,
            "TOOL_AUDIT": False,
            "TOOL_POLICY": "standard",
            "MAX_TOOL_CALL_DEPTH": 8,
            "RETRY_ENABLED": False,
            "CHAT_HISTORY_DIR": str(tmp_path / "sessions"),
            "MODEL": "gpt-4o-mini",
            "OS_NAME": "test-os",
            "SHELL_NAME": "test-shell",
        }
        cli = CLI(config=config)
        cli.interactive = True
        cli.machine_output = False
        cli.printer = Printer(console=console, config=cli.config)
        content, messages = cli._handle_llm_response("杭州天气？")

        assert cli.had_error is False, output.getvalue()
        assert len(requests) == 2
        assert calls == [("Hangzhou", "yaicli-stream-bridge")]
        assert "".join(emitted) == expected
        assert content == expected
        assert content.count(prefix) == 1
        results = [message for message in requests[1] if message.role == "tool"]
        assert [(message.tool_call_id, message.content) for message in results] == [("weather-1", tool_result)]
        assert [message.content for message in messages if message.role == "assistant" and message.content] == [
            expected
        ]
        raw = output.getvalue()
        assert raw.count("@Function call: get_weather") == 1
        assert "\x1b[2K" in raw
        lines = _CSI.sub("", raw).splitlines()
        assert sum(line.startswith(prefix) for line in lines) > 1
        assert all(0 <= wcswidth(line) <= width for line in lines)
        outputs.append(raw)
        assert debug_path.exists() is debug_enabled

    assert outputs[0] == outputs[1]
    debug_text = debug_path.read_text()
    assert debug_text.count("generation.begin") == 1
    assert debug_text.count("generation.end") == 1
