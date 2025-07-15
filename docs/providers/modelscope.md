# ModelScope

ModelScope is Alibaba's open-source model platform providing AI models through an OpenAI-compatible API.

## Configuration

```ini
PROVIDER=modelscope
API_KEY=your-modelscope-api-key
MODEL=Qwen/Qwen3-235B-A22B
TEMPERATURE=0.3
TOP_P=1.0
MAX_TOKENS=1024
EXTRA_BODY={"enable_thinking": true, "thinking_budget": 500}
```

## Key Parameters

| Parameter     | Description                   | Default                                |
| ------------- | ----------------------------- | -------------------------------------- |
| `API_KEY`     | ModelScope API key (required) | -                                      |
| `MODEL`       | Model to use                  | -                                      |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                                  |
| `TOP_P`       | Nucleus sampling              | `1.0`                                  |
| `MAX_TOKENS`  | Max response tokens           | `1024`                                 |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                                   |
| `BASE_URL`    | Custom API endpoint           | `https://api-inference.modelscope.cn/v1/` |
| `EXTRA_BODY`  | Additional request parameters | -                                      |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Access to diverse model ecosystem

## Important Notes

- Uses OpenAI-compatible client implementation
- Provides access to various models in the ModelScope ecosystem
- Requires registration on the ModelScope platform
- Models include Qwen series and other Alibaba AI models
- Strong performance on both Chinese and English tasks
- Pay-as-you-go billing based on token usage

## Resources

- [Official Website](https://modelscope.cn)
- [API Documentation](https://modelscope.cn/docs/model-service/API-Inference/intro)
- [Model Hub](https://modelscope.cn/models)
