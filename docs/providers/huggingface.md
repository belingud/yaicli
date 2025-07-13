    # HuggingFace

HuggingFace Inference API for accessing various models.

## Configuration

```ini
PROVIDER=huggingface
API_KEY=hf_your-huggingface-token
MODEL=meta-llama/Llama-3.1-70B-Instruct
TEMPERATURE=0.7
HF_PROVIDER=auto
```

## Key Parameters

| Parameter       | Description                      | Default |
| --------------- | -------------------------------- | ------- |
| `API_KEY`       | HuggingFace API token (required) | -       |
| `MODEL`         | Model to use                     | -       |
| `TEMPERATURE`   | Randomness (0.0-1.0)             | `0.3`   |
| `TOP_P`         | Nucleus sampling                 | `1.0`   |
| `MAX_TOKENS`    | Max response tokens              | `1024`  |
| `TIMEOUT`       | Request timeout (seconds)        | `60`    |
| `BASE_URL`      | Custom API endpoint              | -       |
| `HF_PROVIDER`   | HuggingFace provider             | `auto`  |
| `BILL_TO`       | Billing configuration            | -       |
| `EXTRA_HEADERS` | Additional HTTP headers          | `{}`    |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ Multiple model access
- ✅ Serverless inference
- ✅ Dedicated endpoints
- ✅ Custom billing options

## Important Notes

- Based on ChatGLM provider implementation
- Uses HuggingFace InferenceClient
- Supports both serverless and dedicated endpoints
- Provider can be set to specific inference backends
- Billing can be configured for enterprise usage
- Wide variety of open-source models available