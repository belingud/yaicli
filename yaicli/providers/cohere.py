from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Union

import cohere

from ..tools import Function
from ..providers.base import LLMContent, LLMProvider, Message
from ..role import Role


@dataclass
class CohereProvider(LLMProvider):
    """Cohere提供商实现"""

    def __post_init__(self) -> None:
        """初始化Cohere客户端"""
        self.client = cohere.Client(
            api_key=self.api_key,
            timeout=self.timeout
        )

    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, str]]:
        """转换消息格式为Cohere API需要的格式"""
        cohere_messages = []

        for msg in messages:
            role = msg.role
            # Cohere使用"USER"和"CHATBOT"角色，而不是OpenAI使用的"user"和"assistant"
            if role == "user":
                role = "USER"
            elif role == "assistant":
                role = "CHATBOT"
            elif role == "system":
                role = "SYSTEM"

            cohere_messages.append({
                "role": role,
                "message": msg.content
            })

        return cohere_messages

    def _convert_functions(self, functions: List[Function]) -> List[Dict[str, Any]]:
        """转换函数格式为Cohere API需要的格式"""
        cohere_tools = []

        for func in functions:
            cohere_tools.append({
                "name": func.name,
                "description": func.description,
                "parameter_definitions": func.parameters.get("properties", {}),
            })

        return cohere_tools

    def completion(
        self,
        messages: List[Message],
        role: Role,
        stream: bool = False,
        functions: Optional[List[Function]] = None,
        max_tokens: Optional[int] = None,
    ) -> Union[LLMContent, Generator[LLMContent, None, None]]:
        """发送消息到Cohere"""
        cohere_messages = self._convert_messages(messages)

        # 准备请求参数
        params: Dict[str, Any] = {
            "model": self.model,
            "message": cohere_messages[-1]["message"],  # 最新消息
            "chat_history": cohere_messages[:-1],  # 历史消息
            "temperature": role.temperature,
            "p": role.top_p,
            "stream": stream,
        }

        # 添加可选参数
        if functions:
            params["tools"] = self._convert_functions(functions)

        if max_tokens:
            params["max_tokens"] = max_tokens

        # 发送请求
        if stream:
            return self._handle_stream_response(self.client.chat(**params))
        else:
            return self._handle_normal_response(self.client.chat(**params))

    def _handle_normal_response(self, response: Any) -> LLMContent:
        """处理普通（非流式）响应"""
        return LLMContent(reasoning=None, content=response.text if hasattr(response, 'text') else str(response))

    def _handle_stream_response(self, response: Any) -> Generator[LLMContent, None, None]:
        """处理流式响应"""
        for event in response:
            if hasattr(event, 'text') and event.text:
                yield LLMContent(reasoning=None, content=event.text)

    def get_total_tokens(self, prompt: str) -> int:
        """
        获取提示词的token数量

        注意：Cohere没有提供精确的token计数API，使用近似方法
        """
        # 英文单词按空格分割，每个单词约1.3个token
        # 中文和其他语言每个字符约1个token
        words = prompt.split()
        return int(len(words) * 1.3 + len(prompt) - len(" ".join(words)))