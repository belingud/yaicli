# Google Gemini

Google's Gemini models via the official Google Generative AI API.

## Configuration

```ini
PROVIDER=gemini
API_KEY=your-google-ai-api-key
MODEL=gemini-1.5-flash
TEMPERATURE=0.3
TOP_P=1.0
MAX_TOKENS=1024
```

## Key Parameters

| Parameter            | Description                      | Default                                        |
| -------------------- | -------------------------------- | ---------------------------------------------- |
| `API_KEY`            | Google AI API key (required)     | -                                              |
| `MODEL`              | Model to use                     | -                                              |
| `TEMPERATURE`        | Randomness (0.0-1.0)             | `0.3`                                          |
| `TOP_P`              | Nucleus sampling                 | `1.0`                                          |
| `TOP_K`              | Top-k sampling                   | -                                              |
| `MAX_TOKENS`         | Max response tokens              | `1024`                                         |
| `TIMEOUT`            | Request timeout (seconds)        | `60`                                           |
| `PRESENCE_PENALTY`   | Presence penalty                 | -                                              |
| `FREQUENCY_PENALTY`  | Frequency penalty                | -                                              |
| `SEED`               | Random seed for deterministic output | -                                          |
| `INCLUDE_THOUGHTS`   | Include reasoning                | `true`                                         |
| `THINKING_BUDGET`    | Max tokens for reasoning         | `1000`                                         |
| `BASE_URL`           | Custom API endpoint              | `https://generativelanguage.googleapis.com/v1beta` |
| `API_VERSION`        | API version to use               | -                                              |


## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ Explicit reasoning via `ThinkingConfig`
- ✅ Multimodal capabilities
- ✅ Deterministic output with seed parameter

## Important Notes

- API key requires Google AI Studio account
- System prompts are supported
- Message history is properly maintained
- Uses the `google-genai` client library
- Pay-as-you-go billing through Google Cloud
- Free tier with generous limits available

## Resources

- [Official Documentation](https://ai.google.dev/docs)
- [Google AI Studio](https://aistudio.google.com/)
- [Gemini API Documentation](https://ai.google.dev/gemini-api/docs)
