# Groq

Groq's fast inference platform for various open-source models.

## Configuration

```ini
PROVIDER=groq
API_KEY=gsk_your-groq-api-key
MODEL=llama-3.1-70b-versatile
TEMPERATURE=0.3
MAX_TOKENS=1024
```

## Key Parameters

| Parameter          | Description                   | Default                          |
| ------------------ | ----------------------------- | -------------------------------- |
| `API_KEY`          | Groq API key (required)       | -                                |
| `MODEL`            | Model to use                  | -                                |
| `TEMPERATURE`      | Randomness (0.0-1.0)          | `0.3`                            |
| `TOP_P`            | Nucleus sampling              | `1.0`                            |
| `MAX_TOKENS`       | Max response tokens           | `1024`                           |
| `TIMEOUT`          | Request timeout (seconds)     | `60`                             |
| `BASE_URL`         | Custom API endpoint           | `https://api.groq.com/openai/v1` |
| `REASONING_EFFORT` | Reasoning effort level        | -                                |
| `EXTRA_BODY`       | Additional request parameters | `{}`                             |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Ultra-fast inference
- ✅ Reasoning capabilities (qwen3 models)

## Important Notes

- Uses OpenAI-compatible client implementation
- N parameter is automatically set to 1 (Groq limitation)
- Reasoning effort only supported for qwen3 models
- Valid reasoning_effort values: `null`, `default`
- Optimized for speed with high tokens per second
- Multiple open-source models available
