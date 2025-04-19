import json
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import httpx
import jmespath
from rich.console import Console

from yaicli.const import (
    DEFAULT_BASE_URL,
    DEFAULT_COMPLETION_PATH,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    DEFAULT_TOP_P,
    EventTypeEnum,
)


def parse_stream_line(line: Union[bytes, str], console: Console, verbose: bool) -> Optional[dict]:
    """(Helper Function) Parse a single line from the SSE stream response."""
    line_str: str
    if isinstance(line, bytes):
        try:
            line_str = line.decode("utf-8")
        except UnicodeDecodeError:
            if verbose:
                console.print(f"Warning: Could not decode stream line bytes: {line!r}", style="yellow")
            return None
    elif isinstance(line, str):
        line_str = line
    else:
        # Handle unexpected line types
        if verbose:
            console.print(f"Warning: Received unexpected line type: {type(line)}", style="yellow")
        return None

    line_str = line_str.strip()
    if not line_str or not line_str.startswith("data: "):
        return None

    data_part = line_str[6:]
    if data_part.lower() == "[done]":
        return {"done": True}  # Use a specific dictionary to signal DONE

    try:
        json_data = json.loads(data_part)
        if not isinstance(json_data, dict) or "choices" not in json_data:
            if verbose:
                console.print(f"Warning: Invalid stream data format (missing 'choices'): {data_part}", style="yellow")
            return None
        return json_data
    except json.JSONDecodeError:
        console.print("Error decoding response JSON", style="red")
        if verbose:
            console.print(f"Invalid JSON data: {data_part}", style="red")
        return None


class ApiClient:
    """Handles communication with the LLM API."""

    def __init__(self, config: Dict[str, Any], console: Console, verbose: bool, client: Optional[httpx.Client] = None):
        """Initialize the API client with configuration."""
        self.config = config
        self.console = console
        self.verbose = verbose
        self.base_url = str(config.get("BASE_URL", DEFAULT_BASE_URL))
        self.completion_path = str(config.get("COMPLETION_PATH", DEFAULT_COMPLETION_PATH))
        self.api_key = str(config.get("API_KEY", ""))
        self.model = str(config.get("MODEL", DEFAULT_MODEL))
        self.timeout = self.config.get("TIMEOUT", DEFAULT_TIMEOUT)
        self.client = client or httpx.Client(timeout=self.config.get("TIMEOUT", DEFAULT_TIMEOUT))

    def _prepare_request_body(self, messages: List[Dict[str, str]], stream: bool) -> Dict[str, Any]:
        """Prepare the common request body for API calls."""
        return {
            "messages": messages,
            "model": self.model,
            "stream": stream,
            "temperature": self.config.get("TEMPERATURE", DEFAULT_TEMPERATURE),
            "top_p": self.config.get("TOP_P", DEFAULT_TOP_P),
            "max_tokens": self.config.get("MAX_TOKENS", DEFAULT_MAX_TOKENS),
        }

    def _handle_api_error(self, e: httpx.HTTPError) -> None:
        """Handle and print HTTP errors consistently."""
        if isinstance(e, httpx.TimeoutException):
            self.console.print(f"Error: API request timed out after {self.timeout} seconds. {e}", style="red")
        elif isinstance(e, httpx.HTTPStatusError):
            self.console.print(f"Error calling API: {e.response.status_code} {e.response.reason_phrase}", style="red")
            if self.verbose:
                self.console.print(f"Response Text: {e.response.text}")
        elif isinstance(e, httpx.RequestError):
            api_url = self.get_completion_url()
            self.console.print(f"Error: Could not connect to API endpoint '{api_url}'. {e}", style="red")
        else:
            self.console.print(f"An unexpected HTTP error occurred: {e}", style="red")

    def get_completion_url(self) -> str:
        """Get the full completion URL."""
        base_url = self.base_url.rstrip("/")
        completion_path = self.completion_path.lstrip("/")
        return f"{base_url}/{completion_path}"

    def get_headers(self) -> Dict[str, str]:
        """Get the request headers."""
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _process_completion_response(self, response_json: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """Process the JSON response from a non-streamed completion request."""
        answer_path = self.config["ANSWER_PATH"]
        message_path = answer_path.rsplit(".", 1)[0]

        # Extract content and reasoning using JMESPath
        content = jmespath.search(answer_path, response_json)
        message = jmespath.search(message_path, response_json)
        reasoning = self._get_reasoning_content(
            message
        )  # Reuse reasoning extraction if applicable to the whole message

        # Process string content and extract reasoning from <think> tags if present
        if isinstance(content, str):
            content = content.lstrip()
            if content.startswith("<think>"):
                think_end = content.find("</think>")
                if think_end != -1:
                    # Extract reasoning from <think> tag only if not already found via message path
                    if reasoning is None:
                        reasoning = content[7:think_end].strip()  # Start after <think>
                    # Remove the <think> block from the main content
                    content = content[think_end + 8 :].strip()  # Start after </think>
            # If it doesn't start with <think>, or if </think> wasn't found, return content as is
            return content, reasoning
        elif content:
            self.console.print(
                f"Warning: Unexpected content type from API: {type(content)}. Path: {answer_path}", style="yellow"
            )
            # Attempt to convert unexpected content to string, return existing reasoning
            return str(content), reasoning
        else:
            self.console.print(f"Warning: Could not extract content using JMESPath '{answer_path}'.", style="yellow")
            if self.verbose:
                self.console.print(f"API Response: {response_json}")
            return None, reasoning

    def completion(self, messages: List[Dict[str, str]]) -> Tuple[Optional[str], Optional[str]]:
        """Get a complete non-streamed response from the API."""
        url = self.get_completion_url()
        body = self._prepare_request_body(messages, stream=False)
        headers = self.get_headers()

        try:
            response = self.client.post(url, json=body, headers=headers)
            response.raise_for_status()
            response_json = response.json()
            # Delegate processing to the helper method
            return self._process_completion_response(response_json)

        except httpx.HTTPError as e:
            self._handle_api_error(e)
            return None, None

    def _handle_http_error(self, e: httpx.HTTPStatusError) -> Dict[str, Any]:
        """Handle HTTP errors during streaming and return an error event.

        Args:
            e: The HTTP status error that occurred

        Returns:
            An error event dictionary to be yielded to the client
        """
        error_body = e.response.read()
        self._handle_api_error(e)

        try:
            error_json = json.loads(error_body)
            error_message = error_json.get("error", {}).get("message")
        except (json.JSONDecodeError, AttributeError):
            error_message = None

        if not error_message:
            error_message = error_body.decode() if error_body else str(e)

        return {"type": EventTypeEnum.ERROR, "message": error_message}

    def _process_stream_chunk(
        self, parsed_data: Dict[str, Any], in_reasoning: bool
    ) -> Iterator[Tuple[Dict[str, Any], bool]]:
        """Process a single chunk from the stream and yield events with updated reasoning state.

        Args:
            parsed_data: The parsed JSON data from a stream line
            in_reasoning: Whether we're currently in a reasoning state

        Yields:
            A tuple containing:
                - An event dictionary to yield to the client
                - The updated reasoning state
        """
        # Handle stream errors
        if "error" in parsed_data:
            error_msg = parsed_data["error"].get("message", "Unknown error in stream data")
            self.console.print(f"Error in stream data: {error_msg}", style="red")
            yield {"type": EventTypeEnum.ERROR, "message": error_msg}, in_reasoning
            return

        # Get and validate the choice
        choices = parsed_data.get("choices", [])
        if not choices or not isinstance(choices, list):
            if self.verbose:
                self.console.print(f"Skipping stream chunk with no choices: {parsed_data}", style="dim")
            return

        choice = choices[0]
        if not isinstance(choice, dict):
            if self.verbose:
                self.console.print(f"Skipping stream chunk with invalid choice structure: {choice}", style="dim")
            return

        # Get content from delta
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            if self.verbose:
                self.console.print(f"Skipping stream chunk with invalid delta structure: {delta}", style="dim")
            return

        # Process content
        reason = self._get_reasoning_content(delta)
        content_chunk = delta.get("content", "")
        finish_reason = choice.get("finish_reason")

        # Yield events based on content type
        if reason is not None:
            in_reasoning = True
            yield {"type": EventTypeEnum.REASONING, "chunk": reason}, in_reasoning
        elif in_reasoning and content_chunk and isinstance(content_chunk, str):
            # Signal the end of reasoning before yielding content
            in_reasoning = False
            yield {"type": EventTypeEnum.REASONING_END, "chunk": ""}, in_reasoning
            yield {"type": EventTypeEnum.CONTENT, "chunk": content_chunk}, in_reasoning
        elif content_chunk and isinstance(content_chunk, str):
            yield {"type": EventTypeEnum.CONTENT, "chunk": content_chunk}, in_reasoning

        if finish_reason:
            yield {"type": EventTypeEnum.FINISH, "reason": finish_reason}, in_reasoning

    def stream_completion(self, messages: List[Dict[str, str]]) -> Iterator[Dict[str, Any]]:
        """Connect to the API and yield parsed stream events.

        This method handles the streaming API connection and processes the response,
        yielding events that can be consumed by the client. It handles various types
        of content including regular content and reasoning content.

        Args:
            messages: The list of message dictionaries to send to the API

        Yields:
            Event dictionaries with the following structure:
                - type: The event type (from EventTypeEnum)
                - chunk/message/reason: The content of the event
        """
        url = self.get_completion_url()
        body = self._prepare_request_body(messages, stream=True)
        headers = self.get_headers()
        in_reasoning = False

        try:
            with self.client.stream("POST", url, json=body, headers=headers) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    yield self._handle_http_error(e)
                    return

                # Process the stream line by line
                for line in response.iter_lines():
                    parsed_data = parse_stream_line(line, self.console, self.verbose)
                    if parsed_data is None:
                        continue
                    if parsed_data.get("done"):
                        break

                    # Process chunks and yield events
                    for event, updated_state in self._process_stream_chunk(parsed_data, in_reasoning):
                        in_reasoning = updated_state
                        # event: {type: str, Optional[chunk]: str, Optional[message]: str, Optional[reason]: str}
                        yield event

        except httpx.HTTPError as e:
            self._handle_api_error(e)
            yield {"type": EventTypeEnum.ERROR, "message": str(e)}
        except Exception as e:
            self.console.print(f"An unexpected error occurred during streaming: {e}", style="red")
            if self.verbose:
                import traceback

                traceback.print_exc()
            yield {"type": EventTypeEnum.ERROR, "message": f"Unexpected stream error: {e}"}

    def _get_reasoning_content(self, delta: dict) -> Optional[str]:
        """Extract reasoning content from delta if available based on specific keys.

        This method checks for various keys that might contain reasoning content
        in different API implementations.

        Args:
            delta: The delta dictionary from the API response

        Returns:
            The reasoning content string if found, None otherwise
        """
        if not delta:
            return None
        # reasoning_content: deepseek/infi-ai
        # reasoning: openrouter
        # <think> block implementation not in here
        for key in ("reasoning_content", "reasoning", "metadata"):
            # Check if the key exists and its value is a non-empty string
            value = delta.get(key)
            if isinstance(value, str) and value:
                return value

        return None  # Return None if no relevant key with a string value is found
