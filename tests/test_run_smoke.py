import os
import unittest
from unittest.mock import MagicMock, patch

import click
import pytest  # Import pytest

from yaicli.cli import CHAT_MODE, CLI, EXEC_MODE, TEMP_MODE


class MockResponse:
    """Mock HTTP response"""

    def __init__(self, json_data, status_code=200, stream=False):
        self.json_data = json_data
        self.status_code = status_code
        self._stream = stream

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception(f"HTTP Error: {self.status_code}")

    def iter_lines(self):
        if not self._stream:
            return []
        # Simulate streaming response format
        yield b'data: {"choices": [{"delta": {"content": "Hello"}}]}'
        yield b'data: {"choices": [{"delta": {"content": " World"}}]}'
        yield b"data: [DONE]"


class TestRunSmoke(unittest.TestCase):
    """Smoke tests for yaicli.py"""

    def setUp(self):
        # Set up environment for tests
        os.environ["YAI_API_KEY"] = "test_api_key"
        os.environ["YAI_STREAM"] = "false"  # Disable streaming for easier testing

        # Create CLI instance with test configuration
        self.cli = CLI(verbose=False)

        # Mock console AFTER CLI initialization
        self.cli.console = MagicMock()
        # Ensure the printer instance uses the mocked console as well
        self.cli.printer.console = self.cli.console

    def tearDown(self):
        # Clean up environment after tests
        if "YAI_API_KEY" in os.environ:
            del os.environ["YAI_API_KEY"]
        if "YAI_STREAM" in os.environ:
            del os.environ["YAI_STREAM"]

    @patch("httpx.Client.post")
    def test_simple_prompt(self, mock_post):
        """Test basic prompt mode (ai xxx)"""
        # Setup mock response
        mock_response = MockResponse({"choices": [{"message": {"content": "Test response"}}]})
        mock_post.return_value = mock_response

        # Run CLI with a simple prompt
        self.cli.run(chat=False, shell=False, prompt="Hello AI")

        # Verify API was called with correct parameters
        mock_post.assert_called_once()
        call_args = mock_post.call_args[1]
        self.assertEqual(call_args["json"]["messages"][-1]["content"], "Hello AI")

        # Verify mode was set correctly
        self.assertEqual(self.cli.current_mode, TEMP_MODE)

    @patch("httpx.Client.post")
    @patch("yaicli.cli.CLI._confirm_and_execute")
    def test_shell_mode(self, mock_execute, mock_post):
        """Test shell command mode (ai --shell xxx)"""
        # Setup mock response
        mock_response = MockResponse({"choices": [{"message": {"content": "ls -la"}}]})
        mock_post.return_value = mock_response

        # Run CLI in shell mode
        self.cli.run(chat=False, shell=True, prompt="List files")

        # Verify API was called with correct parameters
        mock_post.assert_called_once()
        call_args = mock_post.call_args[1]
        self.assertEqual(call_args["json"]["messages"][-1]["content"], "List files")

        # Verify mode was set correctly
        self.assertEqual(self.cli.current_mode, EXEC_MODE)

        # Verify shell execution was attempted
        mock_execute.assert_called_once()

    @patch("httpx.Client.post")
    @patch("prompt_toolkit.PromptSession.prompt")
    def test_chat_mode(self, mock_prompt, mock_post):
        """Test chat mode (ai --chat)"""
        # Setup mock responses
        mock_response = MockResponse({"choices": [{"message": {"content": "Hello, how can I help?"}}]})
        mock_post.return_value = mock_response

        # Setup mock prompt inputs (first a message, then exit command)
        mock_prompt.side_effect = ["Hello AI", "/exit"]

        # Run CLI in chat mode
        self.cli.run(chat=True, shell=False, prompt="")

        # Verify mode was set correctly
        self.assertEqual(self.cli.current_mode, CHAT_MODE)

        # Verify API was called with correct parameters
        mock_post.assert_called_once()
        call_args = mock_post.call_args[1]
        self.assertEqual(call_args["json"]["messages"][-1]["content"], "Hello AI")

    def test_error_handling(self):
        """Test error handling in API calls (non-streaming)"""
        # Ensure streaming is off for this test
        self.cli.config["STREAM"] = False

        # Mock api_client.completion to raise an error
        with patch.object(
            self.cli.api_client, "completion", side_effect=Exception("Simulated API Error")
        ) as mock_get_completion:
            # Check that typer.Exit is called (which raises click.exceptions.Exit)
            with pytest.raises(click.exceptions.Exit) as e:
                self.cli.run(chat=False, shell=False, prompt="Error Prompt")

            # Verify exit code is 1
            self.assertEqual(e.value.exit_code, 1)

            # Verify get_completion was called
            mock_get_completion.assert_called_once()
            messages_arg = mock_get_completion.call_args[0][0]
            self.assertEqual(messages_arg[-1]["content"], "Error Prompt")

            # Verify error message was printed
            self.cli.console.print.assert_any_call("[red]Error processing LLM response: Simulated API Error[/red]")  # type: ignore

    def test_streaming_response(self):
        """Test streaming response handling"""
        # Enable streaming for this test
        self.cli.config["STREAM"] = True

        # Mock the stream_completion method to yield the processed event format
        def mock_stream_generator():
            yield {"type": "content", "chunk": "Hello", "message": None}  # Add type/message keys
            yield {"type": "content", "chunk": " World", "message": None}
            # Simulate a final chunk (often has null chunk or different type)
            yield {"type": "finish", "chunk": None, "message": None, "reason": "stop"}

        # Patch api_client.stream_completion
        with patch.object(
            self.cli.api_client, "stream_completion", return_value=mock_stream_generator()
        ) as mock_stream:
            # Run CLI with a simple prompt
            self.cli.run(chat=False, shell=False, prompt="Hello AI")

            # Verify stream_completion was called
            mock_stream.assert_called_once()
            messages_arg = mock_stream.call_args[0][0]
            self.assertEqual(messages_arg[-1]["content"], "Hello AI")

        # Verify content was processed and stored in history
        self.assertEqual(len(self.cli.history), 2)  # User message and assistant response
        self.assertEqual(self.cli.history[1]["content"], "Hello World")

    def test_streaming_response_error(self):
        """Test streaming response handling when stream processing fails (e.g., exception in generator)"""
        # Enable streaming for this test
        self.cli.config["STREAM"] = True

        # Mock stream_completion to yield correct format then raise an error
        def mock_stream_generator_error():
            yield {"type": "content", "chunk": "Partial", "message": None}  # Add type/message keys
            raise Exception("Simulated stream error")

        # Patch api_client.stream_completion
        with patch.object(
            self.cli.api_client, "stream_completion", return_value=mock_stream_generator_error()
        ) as mock_stream:
            # _handle_llm_response receives None.
            # _run_once receives None and calls typer.Exit(code=1).
            with pytest.raises(click.exceptions.Exit) as e:
                self.cli.run(chat=False, shell=False, prompt="Error Prompt")

            # Verify exit code
            self.assertEqual(e.value.exit_code, 1)

            # Verify stream_completion was called
            mock_stream.assert_called_once()
            messages_arg = mock_stream.call_args[0][0]
            self.assertEqual(messages_arg[-1]["content"], "Error Prompt")

            # Verify error message was printed by the exception handler in display_stream
            error_msg = "An error occurred during stream display: Simulated stream error"
            error_style = "red"

            found_call = False
            for call_item in self.cli.console.print.call_args_list:  # type: ignore
                args = call_item.args
                kwargs = call_item.kwargs
                if args and args[0] == error_msg and kwargs.get("style") == error_style:
                    found_call = True
                    break

            self.assertTrue(
                found_call, f"Expected console print call with '{error_msg}' and style='{error_style}' not found."
            )


class TestPromptToolkitIntegration(unittest.TestCase):
    """Tests for prompt_toolkit integration"""

    def setUp(self):
        # Set up environment for tests
        os.environ["YAI_API_KEY"] = "test_api_key"
        os.environ["YAI_STREAM"] = "false"  # Disable streaming for easier testing

    def tearDown(self):
        # Clean up environment after tests
        if "YAI_API_KEY" in os.environ:
            del os.environ["YAI_API_KEY"]
        if "YAI_STREAM" in os.environ:
            del os.environ["YAI_STREAM"]

    @patch("httpx.Client.post")
    def test_prompt_toolkit_input(self, mock_post):
        """Test prompt_toolkit input handling"""
        # Setup mock response
        mock_response = MockResponse({"choices": [{"message": {"content": "Test response"}}]})
        mock_post.return_value = mock_response

        # Create CLI instance
        cli = CLI(verbose=False)
        cli.console = MagicMock()

        # Instead of using prompt_toolkit's pipe input which causes EOFError,
        # we'll directly mock the session.prompt method
        cli.session = MagicMock()
        cli.session.prompt.side_effect = ["Hello AI", "/exit"]

        # Set up for chat mode
        cli.current_mode = CHAT_MODE
        cli.prepare_chat_loop = MagicMock()  # Prevent actual setup

        # Mock _process_user_input to avoid actual API calls
        with patch.object(cli, "_process_user_input", return_value=True) as mock_process:
            # Run the REPL loop with a patch to exit after processing one input
            cli._run_repl()

            # Verify input was processed
            mock_process.assert_called_with("Hello AI")


if __name__ == "__main__":
    unittest.main()
