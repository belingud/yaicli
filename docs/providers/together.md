# Together

Together AI's platform for accessing various open-source models.

## Configuration

```ini
PROVIDER=together
API_KEY=your-together-api-key
MODEL=meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo
TEMPERATURE=0.3
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                   | Default                       |
| ------------- | ----------------------------- | ----------------------------- |
| `API_KEY`     | Together API key (required)   | -                             |
| `MODEL`       | Model to use                  | -                             |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                         |
| `TOP_P`       | Nucleus sampling              | `1.0`                         |
| `MAX_TOKENS`  | Max response tokens           | `1024`                        |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                          |
| `BASE_URL`    | Custom API endpoint           | `https://api.together.xyz/v1` |
| `EXTRA_BODY`  | Additional request parameters | `{}`                          |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Multiple open-source models
- ✅ Cost-effective inference

## Important Notes

- Uses OpenAI-compatible client implementation
- Access to various open-source models
- Competitive pricing for open-source models
- Supports latest Llama, Qwen, and other models
- Good alternative for open-source model access