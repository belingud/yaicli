import json
from enum import StrEnum
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import httpx
import jmespath
from rich.console import Console


class EventTypeEnum(StrEnum):
    """Enumeration of possible event types from the SSE stream."""

    ERROR = "error"
    REASONING = "reasoning"
    REASONING_END = "reasoning_end"
    CONTENT = "content"
    FINISH = "finish"


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

    def __init__(self, config: Dict[str, Any], console: Console, verbose: bool):
        self.config = config
        self.console = console
        self.verbose = verbose
        self.base_url = str(config.get("BASE_URL", "")).rstrip("/")
        self.completion_path = str(config.get("COMPLETION_PATH", "")).lstrip("/")
        self.api_key = str(config.get("API_KEY", ""))
        self.model = str(config.get("MODEL", "gpt-4o"))

    def _prepare_request_body(self, messages: List[Dict[str, str]], stream: bool) -> Dict[str, Any]:
        """Prepare the common request body for API calls."""
        return {
            "messages": messages,
            "model": self.model,
            "stream": stream,
            "temperature": self.config.get("TEMPERATURE", 0.7),
            "top_p": self.config.get("TOP_P", 1.0),
            "max_tokens": self.config.get("MAX_TOKENS", 1024),
        }

    def _handle_api_error(self, e: httpx.HTTPError) -> None:
        """Handle and print HTTP errors consistently."""
        if isinstance(e, httpx.TimeoutException):
            self.console.print(f"Error: API request timed out after 120 seconds. {e}", style="red")
        elif isinstance(e, httpx.HTTPStatusError):
            self.console.print(f"Error calling API: {e.response.status_code} {e.response.reason_phrase}", style="red")
            if self.verbose:
                try:
                    error_details = e.response.json()
                    self.console.print(f"Response Body: {json.dumps(error_details, indent=2)}")
                except json.JSONDecodeError:
                    self.console.print(f"Response Text: {e.response.text}")
        elif isinstance(e, httpx.RequestError):
            api_url = f"{self.base_url}/{self.completion_path}"
            self.console.print(f"Error: Could not connect to API endpoint '{api_url}'. {e}", style="red")
        else:
            self.console.print(f"An unexpected HTTP error occurred: {e}", style="red")

    def get_completion(self, messages: List[Dict[str, str]]) -> Tuple[Optional[str], Optional[str]]:
        """Get a complete non-streamed response from the API."""
        url = f"{self.base_url}/{self.completion_path}"
        body = self._prepare_request_body(messages, stream=False)
        answer_path = self.config.get("ANSWER_PATH", "choices[0].message.content")
        message_path = self.config.get("MESSAGE_PATH", "choices[0].message")

        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    url,
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                )
            response.raise_for_status()
            response_json = response.json()

            # Use jmespath to extract content
            content = jmespath.search(answer_path, response_json)
            message = jmespath.search(message_path, response_json)
            reasoning = self._get_reasoning_content(message)
            
            if isinstance(content, str):
                think_start = content.find("<think>")
                if think_start != -1:
                    think_end = content.find("</think>", think_start)
                    if think_end != -1:
                        if reasoning is None:
                            reasoning = content[think_start + 7:think_end].strip()
                        content = content[:think_start] + content[think_end + 8:].strip()
                return content, reasoning
            elif content:
                self.console.print(
                    f"Warning: Unexpected content type from API: {type(content)}. Path: {answer_path}", style="yellow"
                )
                return str(content), reasoning  # Attempt to return string representation
            else:
                self.console.print(
                    f"Warning: Could not extract content using JMESPath '{answer_path}'.", style="yellow"
                )
                if self.verbose:
                    self.console.print(f"API Response: {response_json}")
                return None, reasoning

        except httpx.HTTPError as e:
            self._handle_api_error(e)
            return None, None
        except Exception as e:
            self.console.print(f"An unexpected error occurred during non-streamed API call: {e}", style="red")
            if self.verbose:
                import traceback

                traceback.print_exc()
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
            return {
                "type": EventTypeEnum.ERROR,
                "message": error_json.get("error", {}).get("message", error_body.decode()),
            }
        except json.JSONDecodeError:
            return {"type": EventTypeEnum.ERROR, "message": error_body.decode() if error_body else str(e)}

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

        # Validate choices structure
        choices = parsed_data.get("choices")
        if not choices or not isinstance(choices, list) or len(choices) == 0:
            if self.verbose:
                self.console.print(f"Skipping stream chunk with no choices: {parsed_data}", style="dim")
            return

        # Get the first choice
        choice = choices[0]
        if not isinstance(choice, dict):
            if self.verbose:
                self.console.print(f"Skipping stream chunk with invalid choice structure: {choice}", style="dim")
            return

        # Get delta from choice
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            if self.verbose:
                self.console.print(f"Skipping stream chunk with invalid delta structure: {delta}", style="dim")
            return

        # Extract content from delta
        reason = self._get_reasoning_content(delta)
        content_chunk = delta.get("content", "")
        finish_reason = choice.get("finish_reason")

        # Generate and yield events based on content
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
        url = f"{self.base_url}/{self.completion_path}"
        body = self._prepare_request_body(messages, stream=True)
        in_reasoning = False

        try:
            with httpx.Client(timeout=120.0) as client:
                with client.stream(
                    "POST", url, json=body, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=120.0
                ) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        error_event = self._handle_http_error(e)
                        yield error_event
                        return

                    # Process each line in the stream
                    for line in response.iter_lines():
                        parsed_data = parse_stream_line(line, self.console, self.verbose)

                        if parsed_data is None:
                            continue
                        if parsed_data.get("done"):
                            break

                        # Process the chunk and yield events in real-time
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
        """Extract reasoning content from delta if available.

        This method checks for various keys that might contain reasoning content
        in different API implementations.

        Args:
            delta: The delta dictionary from the API response

        Returns:
            The reasoning content string if found, None otherwise
        """
        # reasoning_content: deepseek/infi-ai
        # reasoning: openrouter
        # <think> block implementation
        
        # 检查特定的键中是否包含思考内容
        for k in ("reasoning_content", "reasoning", "metadata"):
            if k in delta and isinstance(delta[k], str):
                return delta[k]
        
        # 检查内容中是否包含<think>标签
        if "content" in delta and isinstance(delta["content"], str):
            content = delta["content"]
            # 检测<think>...</think>格式的思考内容
            think_start = content.find("<think>")
            if think_start != -1:
                think_end = content.find("</think>", think_start)
                if think_end != -1:
                    # 提取<think>标签之间的内容
                    return content[think_start + 7:think_end].strip()
        
        return None
