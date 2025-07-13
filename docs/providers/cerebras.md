# Cerebras

Cerebras Cloud SDK for fast inference on Cerebras hardware.

## Configuration

```ini
PROVIDER=cerebras
API_KEY=your-cerebras-api-key
MODEL=llama3.1-70b
TEMPERATURE=0.7
MAX_TOKENS=4096
```

## Key Parameters

| Parameter     | Description                   | Default                   |
| ------------- | ----------------------------- | ------------------------- |
| `API_KEY`     | Cerebras API key (required)   | -                         |
| `MODEL`       | Model to use                  | -                         |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                     |
| `TOP_P`       | Nucleus sampling              | `1.0`                     |
| `MAX_TOKENS`  | Max response tokens           | `1024`                    |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                      |
| `BASE_URL`    | Custom API endpoint           | `https://api.cerebras.ai` |
| `EXTRA_BODY`  | Additional request parameters | `{}`                      |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Ultra-fast inference
- ✅ Hardware acceleration

## Important Notes

- Uses Cerebras Cloud SDK with OpenAI compatibility
- Warm TCP connection disabled by default for better performance
- Optimized for speed with specialized hardware
- Uses max_completion_tokens instead of max_tokens internally
- Designed for high-throughput inference workloads