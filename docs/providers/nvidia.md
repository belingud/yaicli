# NVIDIA NIM

NVIDIA's NIM (NVIDIA Inference Microservice) platform.

## Configuration

```ini
PROVIDER=nvidia
API_KEY=nvapi-your-nvidia-api-key
MODEL=meta/llama-3.1-70b-instruct
TEMPERATURE=0.3
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                   | Default                               |
| ------------- | ----------------------------- | ------------------------------------- |
| `API_KEY`     | NVIDIA API key (required)     | -                                     |
| `MODEL`       | Model to use                  | -                                     |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                                 |
| `TOP_P`       | Nucleus sampling              | `1.0`                                 |
| `MAX_TOKENS`  | Max response tokens           | `1024`                                |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                                  |
| `BASE_URL`    | Custom API endpoint           | `https://integrate.api.nvidia.com/v1` |
| `EXTRA_BODY`  | Additional request parameters | `{}`                                  |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ GPU-optimized inference
- ✅ Enterprise deployment

## Important Notes

- Uses OpenAI-compatible client implementation
- Automatically adds chat_template_kwargs to extra_body
- Supports thinking mode for compatible models (Qwen3/Granite)
- NVIDIA API accepts redundant parameters gracefully
- Optimized for GPU inference workloads
- Enterprise-grade security and compliance