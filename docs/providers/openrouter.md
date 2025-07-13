# OpenRouter

OpenRouter's unified API for accessing multiple LLM providers.

## Configuration

```ini
PROVIDER=openrouter
API_KEY=sk-or-your-openrouter-api-key
MODEL=anthropic/claude-3.5-sonnet
TEMPERATURE=0.3
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                   | Default                        |
| ------------- | ----------------------------- | ------------------------------ |
| `API_KEY`     | OpenRouter API key (required) | -                              |
| `MODEL`       | Model to use                  | -                              |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                          |
| `TOP_P`       | Nucleus sampling              | `1.0`                          |
| `MAX_TOKENS`  | Max response tokens           | `1024`                         |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                           |
| `BASE_URL`    | Custom API endpoint           | `https://openrouter.ai/api/v1` |
| `EXTRA_BODY`  | Additional request parameters | `{}`                           |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Multiple providers
- ✅ Unified pricing

## Important Notes

- Uses OpenAI-compatible client implementation
- Access to models from multiple providers
- Single API key for all providers
- Transparent pricing and usage tracking
- Model routing and fallback options
- Credits-based billing system