from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple, TypeVar

from cohere import ChatResponse, ClientV2, StreamedChatResponseV2
from cohere.core.api_error import ApiError

from yaicli.const import EventTypeEnum
from yaicli.providers.base import BaseClient

ChunkType = Literal[
    "message-start",
    "content-start",
    "content-delta",
    "content-end",
    "tool-plan-delta",
    "tool-call-start",
    "tool-call-delta",
    "tool-call-end",
    "citation-start",
    "citation-end",
    "message-end",
    "debug",
]

# Type variable for chunks that have delta attribute
T = TypeVar("T", bound=StreamedChatResponseV2)


class CohereClient(BaseClient):
    """Cohere API client implementation using the official Cohere Python library."""

    def __init__(self, config: Dict[str, Any], console, verbose: bool):
        """Initialize the Cohere API client with configuration."""
        super().__init__(config, console, verbose)
        self.api_key = config["API_KEY"]
        self.model = config["MODEL"]
        if not config["BASE_URL"] or "cohere" not in config["BASE_URL"]:
            # BASE_URL can be empty, in which case we use the default base_url
            self.base_url = "https://api.cohere.com"
        else:
            self.base_url = config["BASE_URL"]
        self.base_url = self.base_url.rstrip("/")
        if self.base_url.endswith("v2") or self.base_url.endswith("v1"):
            self.base_url = self.base_url[:-2]

        # Initialize the Cohere client with our custom configuration
        self.client = ClientV2(
            api_key=self.api_key,
            base_url=self.base_url,
            client_name="Yaicli",
            timeout=self.timeout,
        )

    def _prepare_request_params(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Prepare the common request parameters for Cohere API calls."""
        # P value must be between 0.01 and 0.99, default to 0.75 if outside this range, also cohere api default is 0.75
        p = 0.75 if not (0.01 < self.config["TOP_P"] < 0.99) else self.config["TOP_P"]
        return {
            "messages": messages,
            "model": self.model,
            "temperature": self.config["TEMPERATURE"],
            "max_tokens": self.config["MAX_TOKENS"],
            "p": p,
        }

    def _process_completion_response(self, response: ChatResponse) -> Tuple[Optional[str], Optional[str]]:
        """Process the response from a non-streamed Cohere completion request."""
        try:
            content = response.message.content
            if not content:
                return None, None
            text = content[0].text
            if not text:
                return None, None
            return text, None

        except Exception as e:
            self.console.print(f"Error processing Cohere response: {e}", style="red")
            if self.verbose:
                self.console.print(f"Response: {response}")
            return None, None

    def completion(self, messages: List[Dict[str, str]]) -> Tuple[Optional[str], Optional[str]]:
        """Get a complete non-streamed response from the Cohere API."""
        params = self._prepare_request_params(messages)

        try:
            response: ChatResponse = self.client.chat(**params)
            return self._process_completion_response(response)
        except ApiError as e:
            self.console.print(f"Cohere API error: {e}", style="red")
            if self.verbose:
                self.console.print(f"Response: {e.body}")
            return None, None

    def stream_completion(self, messages: List[Dict[str, str]]) -> Iterator[Dict[str, Any]]:
        """Connect to the Cohere API and yield parsed stream events."""
        params = self._prepare_request_params(messages)

        try:
            for chunk in self.client.v2.chat_stream(**params):
                # Skip message start/end events
                if chunk.type in ("message-start", "message-end", "content-end"):  # type: ignore
                    continue

                # Safe attribute checking - skip if any required attribute is missing
                if not hasattr(chunk, "delta"):
                    continue

                # At this point we know chunk has delta attribute
                delta = getattr(chunk, "delta")
                if delta is None or not hasattr(delta, "message"):
                    continue

                message = getattr(delta, "message")
                if message is None or not hasattr(message, "content"):
                    continue

                content = getattr(message, "content")
                if content is None or not hasattr(content, "text"):
                    continue

                # Access text safely
                text = getattr(content, "text")
                if text:
                    yield {"type": EventTypeEnum.CONTENT, "chunk": text}

        except ApiError as e:
            self.console.print(f"Cohere API error during streaming: {e}", style="red")
            yield {"type": EventTypeEnum.ERROR, "message": str(e)}
        except Exception as e:
            self.console.print(f"Unexpected error during Cohere streaming: {e}", style="red")
            if self.verbose:
                import traceback

                traceback.print_exc()
            yield {"type": EventTypeEnum.ERROR, "message": f"Unexpected stream error: {e}"}
