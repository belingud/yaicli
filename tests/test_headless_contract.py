"""v0.19 K04 headless / scripting contract tests.

Locks the frozen contract:

- flags: -p/--print, --output-format {text,json,stream-json}, -q/--quiet,
  --max-turns, -y/--yes, --allowed-tools, --cwd, --fail-on-tool-denied;
- stdout carries only results/events (no "Assistant:", no boxes, no warnings),
  diagnostics go to stderr, text output ends with exactly one newline;
- ``--output-format json`` emits one object
  {content, tool_calls, usage, model, provider, error, exit_code};
- ``--output-format stream-json`` emits NDJSON events
  (turn_start/text_delta/tool_call/tool_result/usage/done);
- CLI state attributes (interactive, exit_code, had_error, interrupted,
  depth_limit_reached, tool_denied) map to the documented exit codes
  (0/1/2/3/130/141), and ``-y``/``--allowed-tools`` are kept on the CLI for K06.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.entry import app
from yaicli.schemas import ChatMessage, LLMResponse, ToolCall

runner = CliRunner()

BOX_CHARS = "╭╮╰╯│─┌┐└┘"


def make_client(chunks, hook=None):
    """A mocked LLMClient whose completion_with_tools() yields ``chunks``."""
    client = MagicMock()
    items = list(chunks)

    def completion(messages, **kwargs):
        if hook is not None:
            hook(messages)
        return iter(items)

    client.completion_with_tools = MagicMock(side_effect=completion)
    return client


def make_streaming_client(generator):
    client = MagicMock()
    client.completion_with_tools = MagicMock(side_effect=lambda messages, **kwargs: generator())
    return client


@pytest.fixture
def mock_llm_client():
    """Patch the client class used by CLI._create_client()."""
    with patch("yaicli.cli.LLMClient") as mock_cls:
        client = make_client([LLMResponse(content="hello")])
        mock_cls.return_value = client
        yield client


def invoke_real_cli(client, args):
    """Invoke the Typer app with the real CLI but a mocked LLM client."""
    with patch("yaicli.cli.LLMClient", return_value=client):
        return runner.invoke(app, args)


class TestJsonOutput:
    def test_json_is_one_valid_object(self, mock_llm_client):
        mock_llm_client.completion_with_tools = MagicMock(
            side_effect=lambda messages, **kwargs: iter([LLMResponse(content="hello "), LLMResponse(content="world")])
        )
        result = invoke_real_cli(mock_llm_client, ["-p", "--output-format", "json", "hi"])

        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert set(payload) == {
            "content",
            "tool_calls",
            "usage",
            "model",
            "provider",
            "error",
            "exit_code",
        }
        assert payload["content"] == "hello world"
        assert payload["tool_calls"] == []
        assert payload["usage"] == {"prompt_tokens": 0, "completion_tokens": 0}
        assert payload["error"] is None
        assert payload["exit_code"] == 0

    def test_json_stdout_has_no_decorations(self, mock_llm_client):
        result = invoke_real_cli(mock_llm_client, ["-p", "--output-format", "json", "hi"])

        assert result.exit_code == 0
        assert "Assistant:" not in result.stdout
        assert not any(char in result.stdout for char in BOX_CHARS)
        assert "Warning:" not in result.stdout
        # Exactly one JSON document (plus the trailing newline).
        assert result.stdout.count("\n") == 1
        json.loads(result.stdout)

    def test_json_reports_tool_calls_from_messages(self, mock_llm_client):
        tool_call = ToolCall(id="c1", name="fs_read_file", arguments='{"path": "a.txt"}')

        def hook(messages):
            messages.append(ChatMessage(role="assistant", content="", tool_calls=[tool_call]))
            messages.append(ChatMessage(role="tool", content="file body", name="fs_read_file", tool_call_id="c1"))

        mock_llm_client.completion_with_tools = MagicMock(
            side_effect=lambda messages, **kwargs: (hook(messages), iter([LLMResponse(content="done")]))[1]
        )
        result = invoke_real_cli(mock_llm_client, ["-p", "--output-format", "json", "read a.txt"])

        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["tool_calls"] == [
            {"name": "fs_read_file", "arguments": {"path": "a.txt"}, "result": "file body"}
        ]

    def test_json_error_path_keeps_schema(self, mock_llm_client):
        mock_llm_client.completion_with_tools = MagicMock(side_effect=RuntimeError("boom"))

        result = invoke_real_cli(mock_llm_client, ["-p", "--output-format", "json", "hi"])

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["exit_code"] == 1
        assert payload["error"] is not None
        assert payload["error"]["message"]
        assert "Error processing LLM response" in result.stderr


class TestTextOutput:
    def test_non_tty_text_is_plain_with_one_newline(self, mock_llm_client):
        mock_llm_client.completion_with_tools = MagicMock(
            side_effect=lambda messages, **kwargs: iter([LLMResponse(content="hello\nworld\n")])
        )
        result = invoke_real_cli(mock_llm_client, ["-p", "hi"])

        assert result.exit_code == 0, result.stderr
        assert result.stdout == "hello\nworld\n"
        assert "Assistant:" not in result.stdout
        assert not any(char in result.stdout for char in BOX_CHARS)

    def test_quiet_prints_content_only(self, mock_llm_client):
        mock_llm_client.completion_with_tools = MagicMock(
            side_effect=lambda messages, **kwargs: iter([LLMResponse(content="the answer")])
        )
        result = invoke_real_cli(mock_llm_client, ["-q", "hi"])

        assert result.exit_code == 0, result.stderr
        assert result.stdout == "the answer\n"
        assert "Assistant:" not in result.stdout

    def test_quiet_stderr_still_gets_errors(self, mock_llm_client):
        mock_llm_client.completion_with_tools = MagicMock(side_effect=RuntimeError("boom"))
        result = invoke_real_cli(mock_llm_client, ["-q", "hi"])

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Error processing LLM response" in result.stderr


class TestStreamJson:
    def test_stream_json_emits_ndjson_events(self, mock_llm_client):
        mock_llm_client.completion_with_tools = MagicMock(
            side_effect=lambda messages, **kwargs: iter([LLMResponse(content="hel"), LLMResponse(content="lo")])
        )
        result = invoke_real_cli(mock_llm_client, ["-p", "--output-format", "stream-json", "hi"])

        assert result.exit_code == 0, result.stderr
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        types = [event["type"] for event in events]
        assert types[0] == "turn_start"
        assert "text_delta" in types
        assert types[-1] == "done"
        assert events[-1]["exit_code"] == 0
        deltas = "".join(event.get("delta", "") for event in events if event["type"] == "text_delta")
        assert deltas == "hello"
        # Every line is a JSON object and nothing else is printed to stdout.
        assert all(isinstance(event, dict) for event in events)


class TestExitCodes:
    def test_one_shot_error_exits_1(self, mock_llm_client):
        mock_llm_client.completion_with_tools = MagicMock(side_effect=RuntimeError("boom"))
        result = invoke_real_cli(mock_llm_client, ["-p", "hi"])

        assert result.exit_code == 1
        assert "Traceback" not in result.output

    def test_interrupted_cli_state_maps_to_130(self):
        mock_instance = MagicMock()
        mock_instance.exit_code = None  # force the documented attribute mapping
        mock_instance.interrupted = True
        mock_instance.had_error = False
        mock_instance.tool_denied = False
        mock_instance.fail_on_tool_denied = False
        mock_instance.depth_limit_reached = False
        mock_instance.evaluate_role_name = MagicMock(return_value="DEFAULT")

        with patch("yaicli.cli.CLI", return_value=mock_instance):
            result = runner.invoke(app, ["-p", "hi"])

        assert result.exit_code == 130

    def test_generation_keyboard_interrupt_exits_130(self):
        def generator():
            yield LLMResponse(content="partial")
            raise KeyboardInterrupt

        client = make_streaming_client(generator)
        result = invoke_real_cli(client, ["-p", "hi"])

        assert result.exit_code == 130
        assert "Interrupted." in result.stderr
        assert "Traceback" not in result.output

    def test_broken_pipe_error_exits_141(self):
        mock_instance = MagicMock()
        mock_instance.run.side_effect = BrokenPipeError()
        mock_instance.evaluate_role_name = MagicMock(return_value="DEFAULT")

        with patch("yaicli.cli.CLI", return_value=mock_instance):
            result = runner.invoke(app, ["-p", "hi"])

        assert result.exit_code == 141
        assert "Traceback" not in result.output

    def test_depth_limit_reached_maps_to_error(self):
        mock_instance = MagicMock()
        mock_instance.exit_code = None
        mock_instance.interrupted = False
        mock_instance.had_error = False
        mock_instance.tool_denied = False
        mock_instance.fail_on_tool_denied = False
        mock_instance.depth_limit_reached = True

        with patch("yaicli.cli.CLI", return_value=mock_instance):
            result = runner.invoke(app, ["-p", "hi"])

        assert result.exit_code == 1

    def test_fail_on_tool_denied_exits_3(self):
        tool_call = ToolCall(id="c1", name="execute_shell_command", arguments='{"shell_command": "rm -rf /"}')

        def hook(messages):
            messages.append(ChatMessage(role="assistant", content="", tool_calls=[tool_call]))
            messages.append(
                ChatMessage(
                    role="tool",
                    content='{"error": "tool_denied", "reason": "non-interactive run"}',
                    name="execute_shell_command",
                    tool_call_id="c1",
                )
            )

        client = make_client([LLMResponse(content="I could not run that.")], hook=hook)

        denied = invoke_real_cli(client, ["-p", "--fail-on-tool-denied", "--output-format", "json", "do it"])
        assert denied.exit_code == 3
        assert json.loads(denied.stdout)["exit_code"] == 3

        allowed = invoke_real_cli(client, ["-p", "--output-format", "json", "do it"])
        assert allowed.exit_code == 0
        assert json.loads(allowed.stdout)["exit_code"] == 0

    def test_invalid_output_format_is_usage_error(self):
        result = runner.invoke(app, ["--output-format", "bogus", "hi"])
        assert result.exit_code == 2
        assert "bogus" in result.stderr

    def test_help_pipe_does_not_fail(self, tmp_path):
        """`ai --help | head -1` must exit 0 or 141 (never 1)."""
        repo_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("YAI_API_KEY", None)
        env.update(
            {
                "HOME": str(tmp_path / "home"),
                "YAI_CONFIG_DIR": str(tmp_path / "config"),
                "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
                "XDG_STATE_HOME": str(tmp_path / "xdg-state"),
            }
        )
        (tmp_path / "home").mkdir()
        process = subprocess.Popen(
            [sys.executable, "-c", "from yaicli.entry import app; app()", "--help"],
            cwd=str(repo_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            # Read one line then close the pipe, like `head -1` does.
            process.stdout.readline()
            process.stdout.close()
            return_code = process.wait(timeout=120)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=30)

        # 141 = 128 + SIGPIPE as seen by a shell; Popen reports -SIGPIPE directly.
        sigpipe_code = -getattr(signal, "SIGPIPE", 13)
        assert return_code in (0, 141, sigpipe_code), f"unexpected exit code {return_code}"
        assert b"Traceback" not in process.stderr.read()


class TestShellMode:
    def test_shell_non_tty_prints_command_without_executing(self):
        client = make_client([LLMResponse(content="```bash\nls -la\n```")])
        with patch("yaicli.cli.subprocess.call") as mock_call:
            result = invoke_real_cli(client, ["--shell", "list files"])

        assert result.exit_code == 0, result.stderr
        assert result.stdout == "ls -la\n"
        mock_call.assert_not_called()

    def test_shell_non_tty_yes_executes(self):
        client = make_client([LLMResponse(content="ls -la")])
        with patch("yaicli.cli.subprocess.call", return_value=0) as mock_call:
            result = invoke_real_cli(client, ["--shell", "--yes", "list files"])

        assert result.exit_code == 0, result.stderr
        assert result.stdout == "ls -la\n"
        mock_call.assert_called_once_with("ls -la", shell=True)

    def test_shell_non_tty_yes_failure_exits_nonzero(self):
        client = make_client([LLMResponse(content="false")])
        with patch("yaicli.cli.subprocess.call", return_value=3):
            result = invoke_real_cli(client, ["--shell", "-y", "fail"])

        assert result.exit_code == 1
        assert result.stdout == "false\n"


class TestHeadlessFlags:
    def test_print_forces_one_shot_over_chat(self):
        mock_instance = MagicMock()
        mock_instance.exit_code = 0
        mock_instance.evaluate_role_name = MagicMock(return_value="DEFAULT")

        with patch("yaicli.cli.CLI", return_value=mock_instance) as mock_cls:
            result = runner.invoke(app, ["-p", "--chat", "a title"])

        assert result.exit_code == 0
        assert mock_instance.run.call_args.kwargs["chat"] is False
        assert "--chat is ignored" in result.stderr
        assert mock_cls.return_value.configure_headless.called

    def test_yes_and_allowed_tools_are_stored_on_cli(self):
        mock_instance = MagicMock()
        mock_instance.exit_code = 0
        mock_instance.evaluate_role_name = MagicMock(return_value="DEFAULT")

        with patch("yaicli.cli.CLI", return_value=mock_instance):
            result = runner.invoke(app, ["-p", "-y", "--allowed-tools", "fs_read_file, fs_*", "hi"])

        assert result.exit_code == 0
        kwargs = mock_instance.configure_headless.call_args.kwargs
        assert kwargs["yes"] is True
        assert kwargs["allowed_tools"] == ["fs_read_file", "fs_*"]

    def test_max_turns_overrides_config(self):
        old_value = cfg["MAX_TOOL_CALL_DEPTH"]
        mock_instance = MagicMock()
        mock_instance.exit_code = 0
        mock_instance.evaluate_role_name = MagicMock(return_value="DEFAULT")
        try:
            with patch("yaicli.cli.CLI", return_value=mock_instance):
                result = runner.invoke(app, ["-p", "--max-turns", "3", "hi"])
            assert result.exit_code == 0
            assert cfg["MAX_TOOL_CALL_DEPTH"] == 3
            assert mock_instance.configure_headless.call_args.kwargs["max_turns"] == 3
        finally:
            cfg["MAX_TOOL_CALL_DEPTH"] = old_value

    def test_cwd_chdir_and_workspace_root(self, tmp_path):
        old_cwd = os.getcwd()
        old_workspace = cfg.get("WORKSPACE_ROOT", "")
        mock_instance = MagicMock()
        mock_instance.exit_code = 0
        mock_instance.evaluate_role_name = MagicMock(return_value="DEFAULT")
        try:
            with patch("yaicli.cli.CLI", return_value=mock_instance):
                result = runner.invoke(app, ["-p", "--cwd", str(tmp_path), "hi"])
            assert result.exit_code == 0, result.stderr
            assert Path(os.getcwd()).resolve() == tmp_path.resolve()
            assert cfg["WORKSPACE_ROOT"] == str(tmp_path.resolve())
            assert mock_instance.configure_headless.call_args.kwargs["cwd"] == str(tmp_path.resolve())
        finally:
            os.chdir(old_cwd)
            cfg["WORKSPACE_ROOT"] = old_workspace

    def test_cwd_validation_is_usage_error(self):
        missing = "/nonexistent/yaicli-cwd-for-tests"
        with patch("yaicli.cli.CLI") as mock_cls:
            result = runner.invoke(app, ["-p", "--cwd", missing, "hi"])
        assert result.exit_code == 2
        assert "Not a directory" in result.stderr
        mock_cls.assert_not_called()

    def test_structured_output_without_input_is_usage_error(self):
        result = runner.invoke(app, ["--output-format", "json"])
        assert result.exit_code == 2
        assert result.stdout == ""


class TestReplSignals:
    def test_ctrl_c_at_prompt_clears_input_and_continues(self):
        cli = CLI(client=MagicMock())
        cli.console = MagicMock()
        session = MagicMock()
        session.prompt.side_effect = [KeyboardInterrupt(), "/exit"]
        cli.session = session
        with (
            patch.object(CLI, "prepare_chat_loop"),
            patch.object(CLI, "_print_welcome_message"),
        ):
            cli._run_repl()

        assert session.prompt.call_count == 2

    def test_ctrl_d_exits_cleanly(self):
        cli = CLI(client=MagicMock())
        cli.console = MagicMock()
        session = MagicMock()
        session.prompt.side_effect = [EOFError()]
        cli.session = session
        with (
            patch.object(CLI, "prepare_chat_loop"),
            patch.object(CLI, "_print_welcome_message"),
        ):
            cli._run_repl()  # should not raise

        assert session.prompt.call_count == 1

    def test_generation_ctrl_c_keeps_repl_alive(self):
        cli = CLI(client=MagicMock())
        cli.console = MagicMock()
        cli.client.completion_with_tools = MagicMock(side_effect=KeyboardInterrupt)
        session = MagicMock()
        session.prompt.side_effect = ["a question", EOFError()]
        cli.session = session
        with (
            patch.object(CLI, "prepare_chat_loop"),
            patch.object(CLI, "_print_welcome_message"),
        ):
            cli._run_repl()

        assert session.prompt.call_count == 2
        printed = [str(call.args[0]) for call in cli.console.print.call_args_list if call.args]
        assert any("KeyboardInterrupt" in text for text in printed)


class TestPromptSessionLaziness:
    def test_non_interactive_cli_skips_prompt_session(self):
        with patch("yaicli.cli.PromptSession") as mock_session:
            with (
                patch.object(CLI, "_stdin_is_tty", return_value=False),
                patch.object(CLI, "_stdout_is_tty", return_value=False),
            ):
                cli = CLI(client=MagicMock())

        mock_session.assert_not_called()
        assert cli.session is None
        assert cli.interactive is False


class TestTtyBehaviorPreserved:
    def test_tty_one_shot_keeps_rich_label(self):
        """TTY + text output keeps the historical rich experience (Assistant:)."""
        client = make_client([LLMResponse(content="hi")])
        with patch("yaicli.cli.PromptSession"), patch("yaicli.cli.get_console") as console_factory:
            console = MagicMock()
            console_factory.return_value = console
            with (
                patch.object(CLI, "_stdin_is_tty", return_value=True),
                patch.object(CLI, "_stdout_is_tty", return_value=True),
            ):
                cli = CLI(client=client)
                cli.configure_headless()

        assert cli.machine_output is False
        with patch("yaicli.printer.Printer.display_stream", return_value=("hi", "")):
            cli._handle_llm_response("prompt")
        console.print.assert_any_call("Assistant:", style="bold green")
        # The rich path is allowed to build the prompt session.
        assert cli.interactive is True


class TestCliStateContract:
    def test_configure_headless_sets_public_state(self):
        cli = CLI(client=MagicMock())
        try:
            cli.configure_headless(
                print_mode=True,
                output_format="json",
                quiet=True,
                yes=True,
                allowed_tools=["fs_*"],
                fail_on_tool_denied=True,
                max_turns=4,
                cwd="/tmp",
            )
            assert cli.print_mode is True
            assert cli.output_format == "json"
            assert cli.quiet is True
            assert cli.machine_output is True
            assert cli.yes is True
            assert cli.allowed_tools == ["fs_*"]
            assert cli.fail_on_tool_denied is True
            assert cli.max_turns == 4
            assert cli.cwd == "/tmp"
            assert cfg["MAX_TOOL_CALL_DEPTH"] == 4
        finally:
            cfg["MAX_TOOL_CALL_DEPTH"] = 8

    def test_run_sets_exit_code_contract(self):
        client = make_client([LLMResponse(content="answer")])
        cli = CLI(client=client)
        cli.configure_headless(print_mode=True, output_format="json")

        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.run(chat=False, user_input="hi")

        payload = json.loads(buffer.getvalue())
        assert payload["content"] == "answer"
        assert cli.exit_code == 0
        assert cli.had_error is False
        assert cli.interrupted is False
        assert cli.depth_limit_reached is False
        assert cli.tool_denied is False
        assert cli.last_content == "answer"
        assert cli.tool_calls == []

    def test_interrupted_state_contract(self):
        cli = CLI(client=MagicMock())
        cli.interrupted = True
        assert cli._finalize_exit_code() == 130

    def test_tool_denied_state_contract(self):
        cli = CLI(client=MagicMock())
        cli.tool_denied = True
        cli.fail_on_tool_denied = False
        assert cli._finalize_exit_code() == 0
        cli.fail_on_tool_denied = True
        assert cli._finalize_exit_code() == 3


class TestStructuredErrorOutcomes:
    def test_json_interrupt_reports_error_and_code_130(self):
        def generator():
            yield LLMResponse(content="partial")
            raise KeyboardInterrupt

        client = make_streaming_client(generator)
        result = invoke_real_cli(client, ["-p", "--output-format", "json", "hi"])

        assert result.exit_code == 130
        payload = json.loads(result.stdout)
        assert payload["exit_code"] == 130
        assert payload["error"]["kind"] == "interrupted"
        assert "Interrupted." in result.stderr

    def test_json_depth_limit_has_error_payload(self):
        from contextlib import redirect_stdout
        from io import StringIO

        cli = CLI(client=MagicMock())
        cli.configure_headless(print_mode=True, output_format="json")
        cli.depth_limit_reached = True
        buffer = StringIO()
        with redirect_stdout(buffer):
            cli._finalize_headless()
        payload = json.loads(buffer.getvalue())
        assert payload["exit_code"] == 1
        assert payload["error"]["kind"] == "depth_limit"


class _PollutingProvider:
    """Fake provider that writes diagnostics through its own console."""

    def __init__(self):
        self.console = None


class _PollutingClient:
    """Fake LLMClient reproducing provider-side stdout writes (K04 D1/D2)."""

    def __init__(self, *args, **kwargs):
        self.console = None
        self.provider = _PollutingProvider()
        self.interactive = True
        self.approval = None
        self.depth_limit_reached = False
        self.tool_denied = False

    def completion_with_tools(self, messages, **kwargs):
        # Real providers dump the request in --verbose and print API error bodies
        # through ``self.console`` (captured at construction time from get_console()).
        self.provider.console.print("Messages:")
        self.provider.console.print([{"role": "user", "content": "hi"}])
        self.provider.console.print("Error Response: {'error': 'boom'}")
        self.console.print("Skipping disallowed tool calls: x")
        yield LLMResponse(content="answer")


class _NoisyConstructionClient(_PollutingClient):
    """Fake client that prints before the CLI can re-point its console."""

    def __init__(self, *args, **kwargs):
        print("Provider not found, using openai as default")
        super().__init__(*args, **kwargs)


class TestProviderStdoutIsolation:
    def test_json_stdout_clean_with_polluting_provider(self):
        with patch("yaicli.cli.LLMClient", _PollutingClient):
            result = runner.invoke(app, ["-p", "--json", "hi"])

        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)  # exactly one JSON object
        assert payload["content"] == "answer"
        assert "Messages:" not in result.stdout
        assert "Error Response" not in result.stdout
        assert "Skipping disallowed tool calls" not in result.stdout
        # Diagnostics still reach the operator on stderr.
        assert "Error Response: {'error': 'boom'}" in result.stderr
        assert "Skipping disallowed tool calls" in result.stderr

    def test_verbose_json_stdout_stays_single_object(self):
        with patch("yaicli.cli.LLMClient", _PollutingClient):
            result = runner.invoke(app, ["-p", "--json", "--verbose", "hi"])

        assert result.exit_code == 0, result.stderr
        assert result.stdout.count("\n") == 1
        json.loads(result.stdout)
        for noise in ("Messages:", "Error Response", "Loading Configuration:", "Config file path:"):
            assert noise not in result.stdout, f"{noise!r} leaked to stdout"
            assert noise in result.stderr, f"{noise!r} missing from stderr"

    def test_stream_json_stdout_is_ndjson_only(self):
        with patch("yaicli.cli.LLMClient", _PollutingClient):
            result = runner.invoke(app, ["-p", "--output-format", "stream-json", "hi"])

        assert result.exit_code == 0, result.stderr
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        events = [json.loads(line) for line in lines]
        assert events[0]["type"] == "turn_start"
        assert events[-1]["type"] == "done"
        assert "Messages:" not in result.stdout
        assert "Messages:" in result.stderr

    def test_construction_warnings_are_redirected_to_stderr(self):
        with patch("yaicli.cli.LLMClient", _NoisyConstructionClient):
            result = runner.invoke(app, ["-p", "--json", "hi"])

        assert result.exit_code == 0, result.stderr
        json.loads(result.stdout)
        assert "Provider not found" not in result.stdout
        assert "Provider not found" in result.stderr

    def test_client_and_provider_consoles_repointed_in_machine_mode(self):
        client = _PollutingClient()
        cli = CLI(client=client, print_mode=True, output_format="json")
        assert cli.machine_output is True
        assert cli.client.console is cli.console
        assert cli.client.provider.console is cli.console
        assert cli.client.interactive is False


class TestConstructorHeadlessIntent:
    def test_print_mode_constructor_skips_prompt_session_and_uses_stderr(self):
        with (
            patch("yaicli.cli.PromptSession") as mock_session,
            patch("yaicli.cli.get_console") as get_console_mock,
            patch("yaicli.cli.get_error_console") as get_error_console_mock,
            patch.object(CLI, "_stdin_is_tty", return_value=True),
            patch.object(CLI, "_stdout_is_tty", return_value=True),
        ):
            stdout_console = MagicMock()
            stderr_console = MagicMock()
            get_console_mock.return_value = stdout_console
            get_error_console_mock.return_value = stderr_console
            cli = CLI(print_mode=True, output_format="json", client=MagicMock())

        mock_session.assert_not_called()
        assert cli.interactive is False
        assert cli.machine_output is True
        assert cli.session is None
        assert cli.console is stderr_console
        assert cli.printer.console is stderr_console

    def test_quiet_tty_skips_prompt_session_and_uses_stderr(self):
        with (
            patch("yaicli.cli.PromptSession") as mock_session,
            patch("yaicli.cli.get_console"),
            patch("yaicli.cli.get_error_console") as get_error_console_mock,
            patch.object(CLI, "_stdin_is_tty", return_value=True),
            patch.object(CLI, "_stdout_is_tty", return_value=True),
        ):
            stderr_console = MagicMock()
            get_error_console_mock.return_value = stderr_console
            cli = CLI(quiet=True, client=MagicMock())

        mock_session.assert_not_called()
        assert cli.machine_output is True
        assert cli.session is None
        assert cli.console is stderr_console

    def test_plain_tty_still_builds_prompt_session_and_stdout_console(self):
        with (
            patch("yaicli.cli.PromptSession") as mock_session,
            patch("yaicli.cli.get_console") as get_console_mock,
            patch("yaicli.cli.get_error_console") as get_error_console_mock,
            patch.object(CLI, "_stdin_is_tty", return_value=True),
            patch.object(CLI, "_stdout_is_tty", return_value=True),
        ):
            stdout_console = MagicMock()
            get_console_mock.return_value = stdout_console
            cli = CLI(client=MagicMock())

        assert mock_session.call_count == 1
        assert cli.interactive is True
        assert cli.machine_output is False
        assert cli.console is stdout_console
        get_error_console_mock.assert_not_called()
