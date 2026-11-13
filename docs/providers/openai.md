# OpenAI

OpenAI's GPT models and API services.

## Configuration

```ini
PROVIDER=openai
API_KEY=sk-your-openai-api-key
MODEL=o3
TEMPERATURE=0.3
TOP_P=1.0
MAX_TOKENS=1024
REASONING_EFFORT=low
```

## Key Parameters

| Parameter          | Description                   | Default                     |
| ------------------ | ----------------------------- | --------------------------- |
| `API_KEY`          | OpenAI API key (required)     | -                           |
| `MODEL`            | Model to use                  | -                           |
| `TEMPERATURE`      | Randomness (0.0-1.0)          | `0.3`                       |
| `TOP_P`            | Nucleus sampling              | `1.0`                       |
| `MAX_TOKENS`       | Max response tokens           | `1024`                      |
| `TIMEOUT`          | Request timeout (seconds)     | `60`                        |
| `REASONING_EFFORT` | Reasoning effort (`low`, `medium`, `high`, `default`, `null`) | - |
| `BASE_URL`         | Custom API endpoint           | `https://api.openai.com/v1` |
| `EXTRA_HEADERS`    | Additional request headers    | -                           |
| `EXTRA_BODY`       | Additional request parameters | -                           |

## Azure OpenAI Configuration

```ini
PROVIDER=openai-azure
API_KEY=your-azure-openai-key
AZURE_ENDPOINT=https://your-resource.openai.azure.com/
API_VERSION=2024-02-01
AZURE_DEPLOYMENT=your-deployment-name
MODEL=gpt-4
```

## Azure Key Parameters

| Parameter       | Description                     | Default      |
| --------------- | ------------------------------- | ------------ |
| `API_KEY`         | Azure OpenAI key                | -            |
| `AZURE_ENDPOINT`  | Azure OpenAI endpoint           | -            |
| `API_VERSION`     | Azure OpenAI API version        | `2024-02-01` |
| `AZURE_DEPLOYMENT`| Azure deployment name           | -            |
| `AZURE_AD_TOKEN`  | Azure AD OAuth token (optional) | -            |
| `DEFAULT_QUERY` | Default query parameters        | -            |

> `API_VERSION` falls back to the `OPENAI_API_VERSION` environment variable when it is not set in
> the config file. `AZURE_AD_TOKEN_PROVIDER` (a callable) and `DEFAULT_HEADERS` (a dict) are only
> available when embedding YAICLI in Python; they cannot be expressed in `config.ini`.

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ Vision capabilities
- ✅ Reasoning parameters
- ✅ Azure integration
- ✅ High context windows

## Transport

Since v0.24.0, `openai` requests use the built-in httpx transport by default instead of the `openai`
Python SDK, which speeds up one-shot startup; responses, tool calls and error messages are
unchanged. Set `LITE_TRANSPORT=false` (or `YAI_LITE_TRANSPORT=false`) to fall back to the SDK.
`openai-azure` always uses the SDK. See
[Transport Selection](../usage/configuration.md#transport-selection).

## Important Notes

- API keys start with `sk-`
- Rate limits apply based on your plan
- Azure requires additional configuration
- Models have different token limits and capabilities
- Pricing varies by model and usage
- Some models support image input
- Custom base URLs can be set for compatible endpoints

## Resources

- [OpenAI API Documentation](https://platform.openai.com/docs/api-reference)
- [Azure OpenAI Documentation](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
- [OpenAI Models](https://platform.openai.com/docs/models)
- [OpenAI Pricing](https://openai.com/pricing)
