import json
from typing import Any, Dict, Generator, List, Optional

import ollama
from ollama import ChatResponse

from ...config import cfg
from ...console import get_console
from ...errors import wrap_provider_exception
from ...model_limits import ModelLimits, limits_from_dict
from ...schemas import ChatMessage, LLMResponse, ToolCall, ToolPolicy
from ...tools import get_openai_schemas
from ...usage import usage_from_ollama
from ...utils import gen_tool_call_id, str2bool
from ..provider import Provider
from ..tool_calls import ToolCallAccumulator


class OllamaProvider(Provider):
    """Ollama provider implementation based on ollama Python library"""

    DEFAULT_BASE_URL = "http://localhost:11434"
    OPTION_KEYS = (
        ("SEED", "seed"),
        ("NUM_PREDICT", "num_predict"),
        ("NUM_CTX", "num_ctx"),
        ("NUM_BATCH", "num_batch"),
        ("NUM_GPU", "num_gpu"),
        ("MAIN_GPU", "main_gpu"),
        ("LOW_VRAM", "low_vram"),
        ("F16_KV", "f16_kv"),
        ("LOGITS_ALL", "logits_all"),
        ("VOCAB_ONLY", "vocab_only"),
        ("USE_MMAP", "use_mmap"),
        ("USE_MLOCK", "use_mlock"),
        ("NUM_THREAD", "num_thread"),
    )

    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        self.config = config
        self.enable_function = self.config.get("ENABLE_FUNCTIONS", False)
        self.verbose = verbose
        self.think = str2bool(self.config.get("THINK", False))

        # Initialize client params - Ollama host support
        self.host = self.config.get("BASE_URL") or self.DEFAULT_BASE_URL

        # Initialize console
        self.console = get_console()

        self.client = ollama.Client(host=self.host, timeout=self.config["TIMEOUT"])

    def model_limits(self, model: str) -> Optional[ModelLimits]:
        """Return the context length advertised by a local Ollama model.

        ``client.show(model)`` reports the model architecture in ``model_info``;
        the largest positive ``*.context_length`` entry is the model's real
        window. ``NUM_CTX`` is deliberately ignored (user decision): only this
        metadata or an explicit config override is authoritative. One probe, no
        prints, no caching, and any failure returns ``None``.
        """
        if not model:
            return None
        try:
            info = self.client.show(model)
            model_info = getattr(info, "model_info", None) or {}
            window: Optional[int] = None
            for key, value in model_info.items():
                if not str(key).endswith(".context_length"):
                    continue
                try:
                    candidate = int(value)
                except (TypeError, ValueError):
                    continue
                if candidate > 0 and (window is None or candidate > window):
                    window = candidate
            return limits_from_dict(
                {
                    "window": window,
                    "source": "metadata",
                    "detail": "ollama /api/show",
                }
            )
        except Exception:
            return None

    def _convert_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """Convert a list of ChatMessage objects to a list of Ollama message dicts."""
        converted_messages = []
        for msg in messages:
            message: dict[str, Any] = {"role": msg.role, "content": msg.content or ""}

            if msg.name:
                message["name"] = msg.name

            # Handle tool calls - Ollama now supports the OpenAI format directly
            if msg.role == "assistant" and msg.tool_calls:
                message["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.loads(tc.arguments)},
                    }
                    for tc in msg.tool_calls
                ]

            # Handle tool responses - Ollama supports tool_call_id directly
            if msg.role == "tool" and msg.tool_call_id:
                message["tool_call_id"] = msg.tool_call_id

            # Handle images: Ollama uses a separate 'images' array of base64 strings
            if msg.images:
                message["images"] = [img.data for img in msg.images]

            converted_messages.append(message)

        return converted_messages

    def completion(
        self,
        messages: List[ChatMessage],
        stream: bool = False,
        tool_policy: ToolPolicy | None = None,
    ) -> Generator[LLMResponse, None, None]:
        """Send messages to Ollama and get response"""
        effective_tool_policy = self.resolve_tool_policy(tool_policy)
        # Convert message format
        ollama_messages = self._convert_messages(messages)
        if self.verbose:
            self.console.print("Messages:")
            self.console.print(ollama_messages)
        options = {
            "temperature": self.config["TEMPERATURE"],
            "top_p": self.config["TOP_P"],
            "frequency_penalty": self.config["FREQUENCY_PENALTY"],
        }
        for k, v in self.OPTION_KEYS:
            if self.config.get(k, None) is not None:
                options[v] = self.config[k]

        # Apply exclude params filtering to options
        options = Provider.filter_excluded_params(
            options,
            self.config,
            verbose=self.verbose,
            console=self.console,
        )

        # Prepare parameters
        params = {
            "model": self.config.get("MODEL", "llama3"),
            "messages": ollama_messages,
            "stream": stream,
            "think": self.think,
            "options": options,
        }

        # Add tools if enabled
        if effective_tool_policy.enable_functions:
            params["tools"] = get_openai_schemas()

        if self.verbose:
            self.console.print("Ollama API params:")
            self.console.print(params)
        try:
            if stream:
                response_generator = self.client.chat(**params)
                yield from self._handle_stream_response(response_generator, effective_tool_policy.enable_functions)
            else:
                response = self.client.chat(**params)
                yield from self._handle_normal_response(response, effective_tool_policy.enable_functions)

        except Exception as e:
            # Never swallow Ollama API/network failures (including a stream that
            # breaks mid-iteration) as assistant content: raise classified instead.
            raise wrap_provider_exception(e, "Ollama") from e

    @staticmethod
    def _to_tool_call(tc: dict) -> ToolCall:
        """Convert one Ollama tool-call dict to a canonical :class:`ToolCall`."""
        function_data = tc.get("function", {}) or {}
        arguments = function_data.get("arguments", "")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)
        return ToolCall(
            id=tc.get("id") or gen_tool_call_id(),
            name=function_data.get("name", ""),
            arguments=arguments,
        )

    def _handle_normal_response(
        self,
        response: ChatResponse,
        tool_calls_enabled: bool,
    ) -> Generator[LLMResponse, None, None]:
        """Handle normal (non-streaming) response; keep every tool call.

        Ollama reports usage as ``prompt_eval_count``/``eval_count``; it is
        attached to the single emitted response.
        """
        content = response.message.content or ""
        reasoning = response.message.thinking or ""

        # Ollama returns complete calls; retain all of them (parallel tool use).
        accumulator = ToolCallAccumulator()
        if tool_calls_enabled:
            for tc in response.message.tool_calls or []:
                accumulator.add_complete(self._to_tool_call(tc))

        yield LLMResponse(
            content=content,
            reasoning=reasoning,
            tool_calls=accumulator.finalize(),
            usage=usage_from_ollama(response),
        )

    def _handle_stream_response(
        self,
        response_generator,
        tool_calls_enabled: bool,
    ) -> Generator[LLMResponse, None, None]:
        """Handle streaming response; keep every tool call from the final message.

        Ollama only reports usage counts on the final stream message; the latest
        snapshot is attached to the closing response (the tool-call response when
        there is one, otherwise a terminal usage-only response).
        """
        accumulator = ToolCallAccumulator()
        stream_usage = None

        for chunk in response_generator:
            chunk_usage = usage_from_ollama(chunk)
            if chunk_usage is not None:
                stream_usage = chunk_usage
            # Extract content from the current chunk
            message = chunk.message
            content = message.content or ""
            reasoning = message.thinking or ""

            if content or reasoning:
                yield LLMResponse(content=content, reasoning=reasoning)

            # Ollama sends complete calls (usually once, after the text stream);
            # collect all of them instead of only the first one.
            if tool_calls_enabled:
                for tc in message.tool_calls or []:
                    accumulator.add_complete(self._to_tool_call(tc))

        # After streaming is complete, emit every complete tool call at once.
        tool_calls = accumulator.finalize()
        if tool_calls:
            yield LLMResponse(tool_calls=tool_calls, usage=stream_usage)
        elif stream_usage is not None:
            yield LLMResponse(usage=stream_usage)

    def detect_tool_role(self) -> str:
        """Return the role to be used for tool responses"""
        return "tool"
