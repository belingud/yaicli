import os
import unittest
from unittest.mock import MagicMock, patch

import click
import pytest  # Import pytest

from yaicli.cli import CHAT_MODE, CLI, EXEC_MODE, TEMP_MODE


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

    @patch("openai.OpenAI")
    def test_simple_prompt(self, mock_openai_client):
        """Test basic prompt mode (ai xxx)"""
        # Mock OpenAI client and response
        mock_client = MagicMock()
        mock_openai_client.return_value = mock_client

        # Mock the return value of completions.create method
        mock_chat_completion = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Test response"
        mock_choice.message = mock_message
        mock_chat_completion.choices = [mock_choice]

        # Set up mock objects returned by the API client
        mock_client.chat.completions.create.return_value = mock_chat_completion

        # Directly mock api_client.completion method to return test response
        original_completion = self.cli.api_client.completion
        self.cli.api_client.completion = MagicMock(return_value=("Test response", None))

        try:
            # Run CLI with a simple prompt
            self.cli.run(chat=False, shell=False, input="Hello AI")

            # Verify API was called through our mocked completion method
            self.cli.api_client.completion.assert_called_once()

            # Verify mode was set correctly
            self.assertEqual(self.cli.current_mode, TEMP_MODE)
        finally:
            # Restore original method
            self.cli.api_client.completion = original_completion

    @patch("openai.OpenAI")
    @patch("yaicli.cli.CLI._confirm_and_execute")
    def test_shell_mode(self, mock_execute, mock_openai_client):
        """Test shell command mode (ai --shell xxx)"""
        # Mock OpenAI client and response
        mock_client = MagicMock()
        mock_openai_client.return_value = mock_client

        # Mock the return value of completions.create method
        mock_chat_completion = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "ls -la"
        mock_choice.message = mock_message
        mock_chat_completion.choices = [mock_choice]

        # Set up mock objects returned by the API client
        mock_client.chat.completions.create.return_value = mock_chat_completion

        # Directly mock api_client.completion method to return test response
        original_completion = self.cli.api_client.completion
        self.cli.api_client.completion = MagicMock(return_value=("ls -la", None))

        try:
            # Run CLI in shell mode
            self.cli.run(chat=False, shell=True, input="List files")

            # Verify API was called
            self.cli.api_client.completion.assert_called_once()

            # Verify mode was set correctly
            self.assertEqual(self.cli.current_mode, EXEC_MODE)

            # Verify shell execution was attempted
            mock_execute.assert_called_once()
        finally:
            # Restore original method
            self.cli.api_client.completion = original_completion

    def test_chat_mode(self):
        """Test chat mode (ai --chat)"""
        # Set up chat mode
        self.cli.current_mode = CHAT_MODE

        # Ensure streaming is disabled for this test
        original_stream_setting = self.cli.config["STREAM"]
        self.cli.config["STREAM"] = False

        # Create a test message
        test_message = "Hello AI"

        # Mock the API client's completion method
        original_completion = self.cli.api_client.completion
        mock_completion = MagicMock(return_value=("Hello, how can I help?", None))
        self.cli.api_client.completion = mock_completion

        try:
            # Directly call the method that processes user input
            self.cli._handle_llm_response(test_message)

            # Verify API client's completion method was called with correct parameters
            mock_completion.assert_called_once()
            messages_arg = mock_completion.call_args[0][0]
            self.assertEqual(messages_arg[-1]["content"], test_message)

            # Verify the response was added to history
            self.assertEqual(len(self.cli.history), 2)  # User message and assistant response
            self.assertEqual(self.cli.history[0]["role"], "user")
            self.assertEqual(self.cli.history[0]["content"], test_message)
            self.assertEqual(self.cli.history[1]["role"], "assistant")
            self.assertEqual(self.cli.history[1]["content"], "Hello, how can I help?")
        finally:
            # Restore original methods and settings
            self.cli.api_client.completion = original_completion
            self.cli.config["STREAM"] = original_stream_setting

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
                self.cli.run(chat=False, shell=False, input="Error Prompt")

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
            self.cli.run(chat=False, shell=False, input="Hello AI")

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
                self.cli.run(chat=False, shell=False, input="Error Prompt")

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

    @patch("openai.OpenAI")
    def test_prompt_toolkit_input(self, mock_openai_client):
        """Test prompt_toolkit input handling"""
        # Mock OpenAI client
        mock_client = MagicMock()
        mock_openai_client.return_value = mock_client

        # Create CLI instance
        cli = CLI(verbose=False)
        cli.console = MagicMock()

        # Directly mock _process_user_input instead of modifying api_client underlying implementation
        cli._process_user_input = MagicMock(return_value=True)

        # Instead of using prompt_toolkit's pipe input which causes EOFError,
        # we'll directly mock the session.prompt method
        cli.session = MagicMock()
        cli.session.prompt.side_effect = ["Hello AI", "/exit"]

        # Set up for chat mode
        cli.current_mode = CHAT_MODE
        cli.prepare_chat_loop = MagicMock()  # Prevent actual setup

        # Run the REPL loop
        cli._run_repl()

        # Verify input was processed
        cli._process_user_input.assert_called_with("Hello AI")


if __name__ == "__main__":
    unittest.main()
