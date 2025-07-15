# Zhipu AI (ChatGLM)

Zhipu AI's ChatGLM series models via their official API.

## Configuration

```ini
PROVIDER=chatglm
API_KEY=your-zhipu-api-key
MODEL=glm-z1-flash
TEMPERATURE=0.3
TOP_P=1.0
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                 | Default                                 |
| ------------- | --------------------------- | --------------------------------------- |
| `API_KEY`     | Zhipu AI API key (required) | -                                       |
| `MODEL`       | Model to use                | -                                       |
| `TEMPERATURE` | Randomness (0.0-1.0)        | `0.3`                                   |
| `TOP_P`       | Nucleus sampling            | `1.0`                                   |
| `MAX_TOKENS`  | Max response tokens         | `1024`                                  |
| `DO_SAMPLE`   | Enable sampling             | -                                       |
| `TIMEOUT`     | Request timeout (seconds)   | `60`                                    |
| `BASE_URL`    | Custom API endpoint         | `https://open.bigmodel.cn/api/paas/v4/` |

## Supported Models

- `glm-4`: Latest flagship model with advanced reasoning and tool use capabilities
- `glm-3-turbo`: Fast and efficient model for general-purpose use
- `glm-4v`: Multimodal version with vision capabilities
- `cogview-3`: Image generation model

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Reasoning via `<think>` tags

## Important Notes

- API key requires registration on the Zhipu AI platform
- Models are particularly well-optimized for Chinese language
- Supports explicit reasoning through `<think>...</think>` syntax
- Uses OpenAI-compatible implementation
- Pay-as-you-go billing based on token usage

## Resources

- [Official Documentation](https://open.bigmodel.cn/dev/api)
- [API Registration](https://open.bigmodel.cn/)
