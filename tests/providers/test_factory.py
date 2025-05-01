from unittest.mock import MagicMock, patch

import pytest

from yaicli.providers import create_api_client


@pytest.fixture
def mock_console():
    """模拟控制台"""
    console = MagicMock()
    return console


@pytest.fixture
def test_config():
    """测试配置"""
    return {
        "API_KEY": "test-api-key",
        "MODEL": "gpt-3.5-turbo",
        "BASE_URL": "https://api.openai.com/v1",
        "TIMEOUT": 60,
        "TEMPERATURE": 0.7,
        "TOP_P": 1.0,
        "MAX_TOKENS": 4000,
        "PROVIDER": "openai",
    }


class TestCreateApiClient:
    """测试创建API客户端工厂函数"""

    def test_create_openai_client(self, mock_console, test_config):
        """测试创建OpenAI客户端"""
        with patch("yaicli.providers.OpenAIClient") as mock_openai_client:
            client = create_api_client(test_config, mock_console, verbose=False)
            mock_openai_client.assert_called_once_with(test_config, mock_console, False)
            assert client is mock_openai_client.return_value

    def test_create_cohere_client(self, mock_console, test_config):
        """测试创建Cohere客户端"""
        config = test_config.copy()
        config["PROVIDER"] = "cohere"

        with patch("yaicli.providers.CohereClient") as mock_cohere_client:
            client = create_api_client(config, mock_console, verbose=False)
            mock_cohere_client.assert_called_once_with(config, mock_console, False)
            assert client is mock_cohere_client.return_value

    def test_fallback_to_openai(self, mock_console, test_config):
        """测试使用未知提供商时回退到OpenAI"""
        config = test_config.copy()
        config["PROVIDER"] = "unknown_provider"

        with patch("yaicli.providers.OpenAIClient") as mock_openai_client:
            client = create_api_client(config, mock_console, verbose=False)
            mock_openai_client.assert_called_once_with(config, mock_console, False)
            assert client is mock_openai_client.return_value
            # 验证打印了警告消息
            mock_console.print.assert_called_once_with(
                "Using generic HTTP client for provider: unknown_provider", style="yellow"
            )
