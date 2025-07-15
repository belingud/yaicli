# Minimax

Minimax is a Chinese AI company providing language models with an OpenAI-compatible API.

## Configuration

```ini
PROVIDER=minimax
API_KEY=your-minimax-api-key
MODEL=abab6-chat
TEMPERATURE=0.3
TOP_P=1.0
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                   | Default                      |
| ------------- | ----------------------------- | ---------------------------- |
| `API_KEY`     | Minimax API key (required)    | -                            |
| `MODEL`       | Model to use                  | -                            |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                        |
| `TOP_P`       | Nucleus sampling              | `1.0`                        |
| `MAX_TOKENS`  | Max response tokens           | `1024`                       |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                         |
| `BASE_URL`    | Custom API endpoint           | `https://api.minimaxi.com/v1` |
| `EXTRA_BODY`  | Additional request parameters | -                            |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Chinese language optimization
- ✅ Multi-modal capabilities

## Important Notes

- Uses OpenAI-compatible client implementation
- Strong performance on Chinese language tasks
- Supports image understanding in compatible models
- Requires registration on the Minimax platform
- API documentation primarily available in Chinese
- Pay-as-you-go billing based on token usage

## Resources

- [Official Website](https://platform.minimaxi.com/)
- [Developer Documentation](https://platform.minimaxi.com/document/platform)
- [Model Catalog](https://platform.minimaxi.com/document/guides/models)
