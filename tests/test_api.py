import pytest
from unittest.mock import MagicMock, patch
from yaicli.api import ApiClient, parse_stream_line
import httpx


# Basic config fixture for testing
@pytest.fixture
def base_config():
    return {
        "BASE_URL": "http://test.com/v1/",
        "COMPLETION_PATH": "/chat/completions",
        "API_KEY": "test_key",
        "MODEL": "test_model",
        "TEMPERATURE": 0.8,
        "TOP_P": 0.9,
        "MAX_TOKENS": 500,
        "CODE_THEME": "native",
    }


# Mock console fixture
@pytest.fixture
def mock_console():
    return MagicMock()


class TestApiClientInit:
    def test_init_basic(self, base_config, mock_console):
        """Test basic initialization with standard config."""
        client = ApiClient(base_config, mock_console, verbose=False)
        assert client.base_url == "http://test.com/v1"  # Trailing slash removed
        assert client.completion_path == "chat/completions"  # Leading slash removed
        assert client.api_key == "test_key"
        assert client.model == "test_model"
        assert client.console == mock_console
        assert client.verbose is False

    def test_init_url_variations(self, base_config, mock_console):
        """Test URL handling with different slash combinations."""
        config_no_slash = base_config.copy()
        config_no_slash["BASE_URL"] = "http://test.com/v1"
        config_no_slash["COMPLETION_PATH"] = "chat/completions"
        client = ApiClient(config_no_slash, mock_console, verbose=False)
        assert client.base_url == "http://test.com/v1"
        assert client.completion_path == "chat/completions"

        config_extra_slash = base_config.copy()
        config_extra_slash["BASE_URL"] = "http://test.com/v1//"
        config_extra_slash["COMPLETION_PATH"] = "//chat/completions"
        client = ApiClient(config_extra_slash, mock_console, verbose=False)
        assert client.base_url == "http://test.com/v1"  # Handles multiple trailing slashes
        assert client.completion_path == "chat/completions"  # Handles multiple leading slashes

    def test_init_defaults(self, mock_console):
        """Test initialization with minimal config, relying on defaults."""
        minimal_config = {"API_KEY": "minimal_key"}
        client = ApiClient(minimal_config, mock_console, verbose=True)
        assert client.base_url == ""  # Default BASE_URL is empty string
        assert client.completion_path == ""  # Default COMPLETION_PATH is empty string
        assert client.api_key == "minimal_key"
        assert client.model == "gpt-4o"  # Default model
        assert client.verbose is True


class TestApiClientPrepareRequestBody:
    def test_prepare_body_basic(self, base_config, mock_console):
        """Test preparing request body for non-streaming."""
        client = ApiClient(base_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Hello"}]
        body = client._prepare_request_body(messages, stream=False)
        expected_body = {
            "messages": messages,
            "model": "test_model",
            "stream": False,
            "temperature": 0.8,
            "top_p": 0.9,
            "max_tokens": 500,
        }
        assert body == expected_body

    def test_prepare_body_streaming(self, base_config, mock_console):
        """Test preparing request body for streaming."""
        client = ApiClient(base_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Stream test"}]
        body = client._prepare_request_body(messages, stream=True)
        expected_body = {
            "messages": messages,
            "model": "test_model",
            "stream": True,
            "temperature": 0.8,
            "top_p": 0.9,
            "max_tokens": 500,
        }
        assert body == expected_body

    def test_prepare_body_config_defaults(self, mock_console):
        """Test request body uses defaults if config values are missing."""
        minimal_config = {"API_KEY": "key", "MODEL": "default_model"}
        client = ApiClient(minimal_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Test"}]
        body = client._prepare_request_body(messages, stream=False)
        expected_body = {
            "messages": messages,
            "model": "default_model",
            "stream": False,
            "temperature": 0.7,  # Default value
            "top_p": 1.0,  # Default value
            "max_tokens": 1024,  # Default value
        }
        assert body == expected_body


# --- Placeholder for next test classes ---
class TestApiClientHandleApiError:
    @pytest.mark.parametrize(
        "error_type, status_code, reason, response_body, expected_log_part",
        [
            (httpx.TimeoutException, None, None, None, "timed out"),
            (httpx.HTTPStatusError, 401, b"Unauthorized", b'{"error": "Invalid key"}', "401 Unauthorized"),
            (httpx.HTTPStatusError, 404, b"Not Found", b"Endpoint not found", "404 Not Found"),
            (httpx.HTTPStatusError, 500, b"Internal Server Error", b"Internal error", "500 Internal Server Error"),
            (httpx.RequestError, None, None, None, "Could not connect"),
            (httpx.UnsupportedProtocol, None, None, None, "Could not connect"),
            (httpx.HTTPError, None, None, None, "unexpected HTTP error"),
        ],
    )
    def test_handle_errors(
        self, base_config, mock_console, error_type, status_code, reason, response_body, expected_log_part
    ):
        """Test handling of various httpx errors."""
        client = ApiClient(base_config, mock_console, verbose=False)

        # Construct mock request and response if needed
        mock_request = httpx.Request("POST", "http://test.com/v1/chat/completions")
        mock_response = None
        if status_code:
            mock_response = httpx.Response(status_code, request=mock_request, content=response_body)

        # Instantiate the specific error
        if error_type == httpx.HTTPStatusError:
            error_instance = error_type("Error message", request=mock_request, response=mock_response)
        elif error_type == httpx.RequestError:
            error_instance = error_type("Connection failed", request=mock_request)
        elif error_type == httpx.HTTPError:  # Base HTTPError takes no request kwarg
            error_instance = error_type("Generic error")
        else:  # TimeoutException etc.
            error_instance = error_type("Generic error", request=mock_request)

        # Call the handler
        client._handle_api_error(error_instance)

        # Verify console.print was called
        mock_console.print.assert_called()
        # Check if the expected error message part was in the printed output
        found_match = False
        for call_args in mock_console.print.call_args_list:
            args, kwargs = call_args
            if args and expected_log_part in args[0]:
                found_match = True
                # Optionally check style='red'
                assert kwargs.get("style") == "red"
                break
        assert found_match, (
            f"Expected log containing '{expected_log_part}' not found in {mock_console.print.call_args_list}"
        )

    def test_handle_status_error_verbose(self, base_config, mock_console):
        """Test verbose logging for HTTPStatusError with JSON body."""
        client = ApiClient(base_config, mock_console, verbose=True)  # Enable verbose
        mock_request = httpx.Request("POST", "http://test.com/v1/chat/completions")
        response_json = {"error": {"message": "Invalid API key", "code": 123}}
        mock_response = httpx.Response(401, request=mock_request, json=response_json)
        error_instance = httpx.HTTPStatusError("Unauthorized", request=mock_request, response=mock_response)

        client._handle_api_error(error_instance)

        # Verify the main error and the verbose JSON body were printed
        calls = mock_console.print.call_args_list
        assert any("401 Unauthorized" in call.args[0] for call in calls if call.args)
        assert any("Response Body:" in call.args[0] for call in calls if call.args)
        assert any("Invalid API key" in call.args[0] for call in calls if call.args)

    def test_handle_status_error_verbose_no_json(self, base_config, mock_console):
        """Test verbose logging for HTTPStatusError with non-JSON body."""
        client = ApiClient(base_config, mock_console, verbose=True)  # Enable verbose
        mock_request = httpx.Request("POST", "http://test.com/v1/chat/completions")
        mock_response = httpx.Response(503, request=mock_request, content=b"Service Unavailable")
        error_instance = httpx.HTTPStatusError("Service Unavailable", request=mock_request, response=mock_response)

        client._handle_api_error(error_instance)

        # Verify the main error and the verbose text body were printed
        calls = mock_console.print.call_args_list
        assert any("503 Service Unavailable" in call.args[0] for call in calls if call.args)
        assert any("Response Text: Service Unavailable" in call.args[0] for call in calls if call.args)


class TestApiClientGetCompletion:
    @pytest.fixture
    def mock_httpx_client(self):
        """Fixture to mock httpx.Client and its post method."""
        with patch("httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client_instance
            yield mock_client_instance  # Yield the instance used inside 'with' block

    def test_get_completion_success(self, base_config, mock_console, mock_httpx_client):
        """Test successful non-streaming completion."""
        client = ApiClient(base_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Translate Hello"}]
        api_response_json = {"choices": [{"message": {"role": "assistant", "content": "Hola"}}]}
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = api_response_json
        # Ensure raise_for_status doesn't raise an error for 200
        mock_response.raise_for_status.return_value = None
        mock_httpx_client.post.return_value = mock_response

        result = client.get_completion(messages)

        # Verify httpx client call
        expected_url = "http://test.com/v1/chat/completions"
        expected_body = client._prepare_request_body(messages, stream=False)
        expected_headers = {"Authorization": "Bearer test_key", "Content-Type": "application/json"}
        mock_httpx_client.post.assert_called_once_with(expected_url, json=expected_body, headers=expected_headers)
        mock_response.raise_for_status.assert_called_once()
        assert result == "Hola"
        mock_console.print.assert_not_called()  # No warnings or errors should be printed

    def test_get_completion_api_error(self, base_config, mock_console, mock_httpx_client):
        """Test handling of API error during non-streaming completion."""
        client = ApiClient(base_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Error test"}]

        # Simulate an HTTPStatusError during response.raise_for_status()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 403
        mock_response.request = httpx.Request("POST", "http://test.com/v1/chat/completions")
        mock_response.reason_phrase = b"Forbidden"
        mock_response.content = b'{"error": "Permission denied"}'
        error_instance = httpx.HTTPStatusError("Forbidden", request=mock_response.request, response=mock_response)
        mock_response.raise_for_status.side_effect = error_instance
        mock_httpx_client.post.return_value = mock_response

        # Mock the error handler to check if it was called
        with patch.object(client, "_handle_api_error") as mock_error_handler:
            result = client.get_completion(messages)

            assert result is None
            mock_error_handler.assert_called_once_with(error_instance)

    def test_get_completion_jmespath_missing(self, base_config, mock_console, mock_httpx_client):
        """Test when JMESPath expression doesn't find the content."""
        client = ApiClient(base_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Missing path"}]
        # Response missing the expected structure
        api_response_json = {"choices": [{"wrong_key": "value"}]}
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = api_response_json
        mock_response.raise_for_status.return_value = None
        mock_httpx_client.post.return_value = mock_response

        result = client.get_completion(messages)

        assert result is None
        # Verify warning message was printed
        mock_console.print.assert_any_call(
            "Warning: Could not extract content using JMESPath 'choices[0].message.content'.", style="yellow"
        )

    def test_get_completion_jmespath_wrong_type(self, base_config, mock_console, mock_httpx_client):
        """Test when JMESPath finds content but it's not a string."""
        client = ApiClient(base_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Wrong type"}]
        # Content is a list, not a string
        api_response_json = {"choices": [{"message": {"content": ["Hola"]}}]}
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = api_response_json
        mock_response.raise_for_status.return_value = None
        mock_httpx_client.post.return_value = mock_response

        result = client.get_completion(messages)

        assert result == "['Hola']"  # Should return string representation
        mock_console.print.assert_any_call(
            "Warning: Unexpected content type from API: <class 'list'>. Path: choices[0].message.content",
            style="yellow",
        )

    def test_get_completion_jmespath_error(self, base_config, mock_console, mock_httpx_client):
        """Test handling of error during JMESPath evaluation."""
        client = ApiClient(base_config, mock_console, verbose=True)  # Use verbose
        messages = [{"role": "user", "content": "JMESPath Error"}]
        api_response_json = {"choices": [{"message": {"content": "Data"}}]}
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = api_response_json
        mock_response.raise_for_status.return_value = None
        mock_httpx_client.post.return_value = mock_response

        # Simulate JMESPath error
        jmespath_error = ValueError("Simulated JMESPath error")
        with patch("jmespath.search", side_effect=jmespath_error) as mock_jmespath_search:
            result = client.get_completion(messages)

            assert result is None
            mock_jmespath_search.assert_called_once_with("choices[0].message.content", api_response_json)
            # Verify error message was printed
            mock_console.print.assert_any_call(
                f"[red]Error processing API response with JMESPath 'choices[0].message.content': {jmespath_error}[/red]"
            )

    def test_get_completion_custom_jmespath(self, base_config, mock_console, mock_httpx_client):
        """Test using a custom JMESPath expression from config."""
        custom_config = base_config.copy()
        custom_config["ANSWER_PATH"] = "result.text"  # Custom path
        client = ApiClient(custom_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Custom path test"}]
        api_response_json = {"result": {"text": "Custom Success"}}
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = api_response_json
        mock_response.raise_for_status.return_value = None
        mock_httpx_client.post.return_value = mock_response

        with patch("jmespath.search") as mock_jmespath_search:
            # Set the return value for the specific call we expect
            mock_jmespath_search.return_value = "Custom Success"
            result = client.get_completion(messages)

            assert result == "Custom Success"
            mock_jmespath_search.assert_called_once_with("result.text", api_response_json)
            mock_console.print.assert_not_called()


class TestApiClientStreamCompletion:
    @pytest.fixture
    def mock_httpx_stream(self):
        """Fixture to mock httpx.Client and its stream context manager."""
        with patch("httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_stream_cm = MagicMock()  # Mock for the context manager returned by stream()
            mock_response = MagicMock(spec=httpx.Response)

            # Configure the context manager's __enter__ to return the mock response
            mock_stream_cm.__enter__.return_value = mock_response
            # Configure the Client instance's stream method to return the context manager mock
            mock_client_instance.stream.return_value = mock_stream_cm
            # Configure the Client class's __enter__ to return the client instance
            mock_client_class.return_value.__enter__.return_value = mock_client_instance

            # Yield both the response mock (for setting iter_lines) and the client mock (for checking calls)
            yield mock_response, mock_client_instance

    def test_stream_completion_success(self, base_config, mock_console, mock_httpx_stream):
        """Test successful streaming completion yielding content and finish events."""
        mock_response, mock_client_instance = mock_httpx_stream
        client = ApiClient(base_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Stream test"}]

        # Simulate SSE stream lines
        sse_lines = [
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            b'data: {"choices":[{"delta":{"content":" World"}}]}',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',  # Finish reason in delta
            b"data: [DONE]",
        ]
        mock_response.iter_lines.return_value = sse_lines
        mock_response.raise_for_status.return_value = None  # Simulate successful status

        # Call the method and collect results
        stream_results = list(client.stream_completion(messages))

        # Verify httpx client call
        expected_url = "http://test.com/v1/chat/completions"
        expected_body = client._prepare_request_body(messages, stream=True)
        expected_headers = {"Authorization": "Bearer test_key"}
        mock_client_instance.stream.assert_called_once_with(
            "POST", expected_url, json=expected_body, headers=expected_headers, timeout=120.0
        )
        mock_response.raise_for_status.assert_called_once()

        # Verify yielded events
        expected_results = [
            {"type": "content", "chunk": "Hello"},
            {"type": "content", "chunk": " World"},
            {"type": "finish", "reason": "stop"},
        ]
        assert stream_results == expected_results
        mock_console.print.assert_not_called()  # No errors or warnings

    def test_stream_completion_with_reasoning(self, base_config, mock_console, mock_httpx_stream):
        """Test streaming completion including reasoning chunks."""
        mock_response, mock_client_instance = mock_httpx_stream
        client = ApiClient(base_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Reasoning test"}]

        sse_lines = [
            b'data: {"choices":[{"delta":{"reasoning_content":"Thinking..."}}]}',  # Reasoning chunk
            b'data: {"choices":[{"delta":{"content":"Okay"}}]}',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            b"data: [DONE]",
        ]
        mock_response.iter_lines.return_value = sse_lines
        mock_response.raise_for_status.return_value = None

        stream_results = list(client.stream_completion(messages))

        expected_results = [
            {"type": "reasoning", "chunk": "Thinking..."},
            {"type": "content", "chunk": "Okay"},
            {"type": "finish", "reason": "stop"},
        ]
        assert stream_results == expected_results
        mock_console.print.assert_not_called()

    def test_stream_completion_api_error_before_stream(self, base_config, mock_console, mock_httpx_stream):
        """Test API error that occurs before stream iteration (e.g., 401)."""
        mock_response, mock_client_instance = mock_httpx_stream
        client = ApiClient(base_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "API Error test"}]

        # Simulate HTTPStatusError on raise_for_status
        error_request = httpx.Request("POST", "http://test.com/v1/chat/completions")
        error_response_content = b'{"error": {"message": "Invalid Key"}}'
        error_response = httpx.Response(401, request=error_request, content=error_response_content)
        error_instance = httpx.HTTPStatusError("Unauthorized", request=error_request, response=error_response)
        mock_response.raise_for_status.side_effect = error_instance
        # Make read() return the content for error reporting in stream_completion
        mock_response.read = MagicMock(return_value=error_response_content)

        # Mock the main error handler to verify it's called
        with patch.object(client, "_handle_api_error") as mock_error_handler:
            stream_results = list(client.stream_completion(messages))

            # Verify error handler call
            mock_error_handler.assert_called_once_with(error_instance)
            # Verify the yielded error event
            expected_results = [{"type": "error", "message": "Invalid Key"}]
            assert stream_results == expected_results

    def test_stream_completion_parse_error(self, base_config, mock_console, mock_httpx_stream):
        """Test handling of invalid data within the stream."""
        mock_response, mock_client_instance = mock_httpx_stream
        client = ApiClient(base_config, mock_console, verbose=True)  # Use verbose
        messages = [{"role": "user", "content": "Parse error test"}]

        sse_lines = [
            b'data: {"choices":[{"delta":{"content":"Good"}}]}',
            b"data: {invalid json}",  # Invalid line
            b'data: {"choices":[{"delta":{"content":" End"}}]}',
            b"data: [DONE]",
        ]
        mock_response.iter_lines.return_value = sse_lines
        mock_response.raise_for_status.return_value = None

        stream_results = list(client.stream_completion(messages))

        # Should yield the valid content and skip the invalid line
        expected_results = [
            {"type": "content", "chunk": "Good"},
            {"type": "content", "chunk": " End"},
        ]
        assert stream_results == expected_results
        # Verify warning/error was printed for the invalid line by parse_stream_line
        mock_console.print.assert_any_call("Error decoding response JSON", style="red")
        # Check verbose output too
        assert any(
            "Invalid JSON data: {invalid json}" in call.args[0]
            for call in mock_console.print.call_args_list
            if call.args
        )

    def test_stream_completion_network_error(self, base_config, mock_console, mock_httpx_stream):
        """Test handling of network error during streaming."""
        mock_response, mock_client_instance = mock_httpx_stream
        client = ApiClient(base_config, mock_console, verbose=False)
        messages = [{"role": "user", "content": "Network error"}]

        # Simulate network error during iteration
        network_error = httpx.ReadTimeout("Timeout reading stream", request=MagicMock())
        mock_response.iter_lines.side_effect = network_error
        mock_response.raise_for_status.return_value = None

        # Mock the main error handler
        with patch.object(client, "_handle_api_error") as mock_error_handler:
            stream_results = list(client.stream_completion(messages))

            # Verify error handler was called
            mock_error_handler.assert_called_once_with(network_error)
            # Verify the yielded error event
            expected_results = [{"type": "error", "message": str(network_error)}]
            assert stream_results == expected_results

    def test_stream_completion_unexpected_error(self, base_config, mock_console, mock_httpx_stream):
        """Test handling of unexpected Python error during streaming."""
        mock_response, mock_client_instance = mock_httpx_stream
        client = ApiClient(base_config, mock_console, verbose=True)  # Use verbose
        messages = [{"role": "user", "content": "Unexpected error"}]

        # Simulate unexpected error
        unexpected_error = TypeError("Something went wrong")
        mock_response.iter_lines.side_effect = unexpected_error
        mock_response.raise_for_status.return_value = None

        stream_results = list(client.stream_completion(messages))

        # Verify yielded error
        expected_results = [{"type": "error", "message": f"Unexpected stream error: {unexpected_error}"}]
        assert stream_results == expected_results
        # Verify error message was printed
        mock_console.print.assert_any_call(
            f"[red]An unexpected error occurred during streaming: {unexpected_error}[/red]"
        )


class TestParseStreamLine:
    @pytest.mark.parametrize(
        "line_input, expected_output",
        [
            (b'data: {"choices":[{"delta":{"content":"Hi"}}]}', {"choices": [{"delta": {"content": "Hi"}}]}),
            ('data: {"choices":[{"delta":{"content":"Hi"}}]}', {"choices": [{"delta": {"content": "Hi"}}]}),
            (b"data: [DONE]", {"done": True}),
            ("data: [DONE]", {"done": True}),
            (b"\n", None),  # Empty line
            (b"event: message", None),  # Non-data line
            (b"data: not json", None),  # Invalid JSON
            (b'data: {"no_choices": true}', None),  # Missing 'choices' key
            (b'data: "just a string"', None),  # Not a dictionary
            (b" ", None),  # Whitespace only
            (b"", None),  # Empty bytes
        ],
    )
    def test_parse_valid_and_invalid_lines(self, mock_console, line_input, expected_output):
        """Test parsing various valid and invalid SSE lines."""
        result = parse_stream_line(line_input, mock_console, verbose=False)
        assert result == expected_output
        # Check for warnings/errors printed on invalid lines
        if (
            expected_output is None and line_input and line_input.strip().startswith(b"data: not json")
        ):  # Check specific case
            mock_console.print.assert_called()

    def test_parse_line_verbose_warnings(self, mock_console):
        """Test verbose warnings for specific invalid formats."""
        # Invalid JSON
        parse_stream_line(b"data: {invalid}", mock_console, verbose=True)
        mock_console.print.assert_any_call("Error decoding response JSON", style="red")
        mock_console.print.assert_any_call("Invalid JSON data: {invalid}", style="red")
        mock_console.reset_mock()

        # Missing 'choices'
        parse_stream_line(b'data: {"key":"value"}', mock_console, verbose=True)
        mock_console.print.assert_any_call(
            'Warning: Invalid stream data format (missing \'choices\'): {"key":"value"}', style="yellow"
        )
        mock_console.reset_mock()

        # UTF-8 Decode Error
        invalid_utf8 = b"data: \xff\xfe\x9c\x00"
        parse_stream_line(invalid_utf8, mock_console, verbose=True)
        mock_console.print.assert_any_call(
            f"Warning: Could not decode stream line bytes: {invalid_utf8!r}", style="yellow"
        )
        mock_console.reset_mock()

        # Unexpected type
        parse_stream_line(123, mock_console, verbose=True)  # type: ignore # Intentionally passing wrong type
        mock_console.print.assert_any_call("Warning: Received unexpected line type: <class 'int'>", style="yellow")
