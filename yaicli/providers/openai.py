from typing import Any, Dict, Iterator, List, Optional, Tuple

import openai
from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChoiceDelta, Choice
from yaicli.const import EventTypeEnum
from yaicli.providers.base import BaseClient


class OpenAIClient(BaseClient):
    """OpenAI API client implementation using the official OpenAI Python library."""

    def __init__(self, config: Dict[str, Any], console, verbose: bool):
        """Initialize the OpenAI API client with configuration."""
        super().__init__(config, console, verbose)
        self.api_key = config["API_KEY"]
        self.model = config["MODEL"]
        self.base_url = config["BASE_URL"]

        # Initialize the OpenAI client with our custom configuration
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            default_headers={"X-Title": "Yaicli"},
            max_retries=2,  # Add retry logic for resilience
        )

    def _prepare_request_params(self, messages: List[Dict[str, str]], stream: bool) -> Dict[str, Any]:
        """Prepare the common request parameters for OpenAI API calls."""
        return {
            "messages": messages,
            "model": self.model,
            "stream": stream,
            "temperature": self.config["TEMPERATURE"],
            "top_p": self.config["TOP_P"],
            # Openai: This value is now deprecated in favor of max_completion_tokens
            "max_tokens": self.config["MAX_TOKENS"],
            "max_completion_tokens": self.config["MAX_TOKENS"],
        }

    def _process_completion_response(self, conpletion: ChatCompletion) -> Tuple[Optional[str], Optional[str]]:
        """Process the response from a non-streamed OpenAI completion request."""
        try:
            # OpenAI SDK returns structured objects
            content = conpletion.choices[0].message.content
            reasoning = None

            # Check for reasoning in model_extra
            if hasattr(conpletion.choices[0].message, "model_extra") and conpletion.choices[0].message.model_extra:
                extra = conpletion.choices[0].message.model_extra
                if extra and "reasoning" in extra:
                    reasoning = extra["reasoning"]

            # If no reasoning in model_extra, try extracting from <think> tags
            if reasoning is None and isinstance(content, str):
                content = content.lstrip()
                if content.startswith("<think>"):
                    think_end = content.find("</think>")
                    if think_end != -1:
                        reasoning = content[7:think_end].strip()  # Start after <think>
                        # Remove the <think> block from the main content
                        content = content[think_end + 8 :].strip()  # Start after </think>

            return content, reasoning
        except Exception as e:
            self.console.print(f"Error processing OpenAI response: {e}", style="red")
            if self.verbose:
                self.console.print(f"Response: {conpletion}")
            return None, None

    def completion(self, messages: List[Dict[str, str]]) -> Tuple[Optional[str], Optional[str]]:
        """Get a complete non-streamed response from the OpenAI API."""
        params = self._prepare_request_params(messages, stream=False)

        try:
            # Use context manager for proper resource management
            with self.client.with_options(timeout=self.timeout) as client:
                response: ChatCompletion = client.chat.completions.create(**params)
                return self._process_completion_response(response)
        except openai.APIConnectionError as e:
            self.console.print(f"OpenAI connection error: {e}", style="red")
            if self.verbose:
                self.console.print(f"Underlying error: {e.__cause__}")
            return None, None
        except openai.RateLimitError as e:
            self.console.print(f"OpenAI rate limit error (429): {e}", style="red")
            return None, None
        except openai.APIStatusError as e:
            self.console.print(f"OpenAI API error (status {e.status_code}): {e}", style="red")
            if self.verbose:
                self.console.print(f"Response: {e.response}")
            return None, None
        except Exception as e:
            self.console.print(f"Unexpected error during OpenAI completion: {e}", style="red")
            if self.verbose:
                import traceback

                traceback.print_exc()
            return None, None

    def stream_completion(self, messages: List[Dict[str, str]]) -> Iterator[Dict[str, Any]]:
        """Connect to the OpenAI API and yield parsed stream events.

        Args:
            messages: The list of message dictionaries to send to the API

        Yields:
            Event dictionaries with the following structure:
                - type: The event type (from EventTypeEnum)
                - chunk/message/reason: The content of the event
        """
        params: Dict[str, Any] = self._prepare_request_params(messages, stream=True)
        in_reasoning: bool = False

        try:
            # Use context manager to ensure proper cleanup
            with self.client.chat.completions.create(**params) as stream:
                for chunk in stream:
                    choices: List[Choice] = chunk.choices
                    if not choices:
                        # Some APIs may return empty choices upon reaching the end of content.
                        continue
                    choice: Choice = choices[0]
                    delta: ChoiceDelta = choice.delta
                    finish_reason: Optional[str] = choice.finish_reason

                    # Process model_extra for reasoning content
                    if hasattr(delta, "model_extra") and delta.model_extra:
                        reasoning: Optional[str] = self._get_reasoning_content(delta.model_extra)
                        if reasoning:
                            yield {"type": EventTypeEnum.REASONING, "chunk": reasoning}
                            in_reasoning = True
                            continue

                    # Process content delta
                    if hasattr(delta, "content") and delta.content:
                        content_chunk = delta.content
                        if in_reasoning and content_chunk:
                            # Send reasoning end signal before content
                            in_reasoning = False
                            yield {"type": EventTypeEnum.REASONING_END, "chunk": ""}
                            yield {"type": EventTypeEnum.CONTENT, "chunk": content_chunk}
                        elif content_chunk:
                            yield {"type": EventTypeEnum.CONTENT, "chunk": content_chunk}

                    # Process finish reason
                    if finish_reason:
                        # Send reasoning end signal if still in reasoning state
                        if in_reasoning:
                            in_reasoning = False
                            yield {"type": EventTypeEnum.REASONING_END, "chunk": ""}
                        yield {"type": EventTypeEnum.FINISH, "reason": finish_reason}

        except openai.APIConnectionError as e:
            self.console.print(f"OpenAI connection error during streaming: {e}", style="red")
            if self.verbose:
                self.console.print(f"Underlying error: {e.__cause__}")
            yield {"type": EventTypeEnum.ERROR, "message": str(e)}
        except openai.RateLimitError as e:
            self.console.print(f"OpenAI rate limit error (429) during streaming: {e}", style="red")
            yield {"type": EventTypeEnum.ERROR, "message": str(e)}
        except openai.APIStatusError as e:
            self.console.print(f"OpenAI API error (status {e.status_code}) during streaming: {e}", style="red")
            if self.verbose:
                self.console.print(f"Response: {e.response}")
            yield {"type": EventTypeEnum.ERROR, "message": str(e)}
        except Exception as e:
            self.console.print(f"Unexpected error during OpenAI streaming: {e}", style="red")
            if self.verbose:
                import traceback

                traceback.print_exc()
            yield {"type": EventTypeEnum.ERROR, "message": f"Unexpected stream error: {e}"}
