# LongCat Provider

LongCat is an OpenAI-compatible API provider that supports tool calls and streaming responses. This document provides configuration details and usage examples for the LongCat provider.

## Configuration Options

LongCat uses the standard YAICLI configuration keys; there are no `LONGCAT_*`-prefixed
variables.

| Key | Description | Default |
| --- | --- | --- |
| `PROVIDER` | `longcat` for the OpenAI-compatible endpoint, `longcat-anthropic` for the Anthropic-compatible endpoint | - |
| `API_KEY` | LongCat API key (`YAI_API_KEY` env var) | - |
| `MODEL` | Model name (`YAI_MODEL`), e.g. `LongCat-Flash-Chat` | - |
| `BASE_URL` | Optional custom endpoint (`YAI_BASE_URL`) | `https://api.longcat.chat/openai` (`longcat-anthropic`: `https://api.longcat.chat/anthropic`) |
| `TIMEOUT` | Request timeout in seconds (`YAI_TIMEOUT`) | `60` |
| `EXTRA_HEADERS` | JSON object of extra HTTP headers (`YAI_EXTRA_HEADERS`) | `{}` |

## Example Configuration

```ini
[core]
PROVIDER=longcat
API_KEY=your-api-key
MODEL=LongCat-Flash-Chat
```

The Anthropic-compatible endpoint uses the same credentials:

```ini
[core]
PROVIDER=longcat-anthropic
API_KEY=your-api-key
MODEL=LongCat-Flash-Chat
```

## Features

- **Tool Calls**: Supports tool calls with the format:
  ```xml
  <longcat_tool_call>function_name
  <longcat_arg_key>key1</longcat_arg_key>
  <longcat_arg_value>value1</longcat_arg_value>
  </longcat_tool_call>
  ```
- **Streaming Responses**: Supports streaming responses for real-time interaction.
- **Anthropic Compatibility**: Also provides an Anthropic-compatible API endpoint.

## Usage Examples

### Basic Usage

```bash
export YAI_PROVIDER=longcat
export YAI_API_KEY=your-api-key
export YAI_MODEL=LongCat-Flash-Chat
ai "What is the capital of France?"
```

### Tool Call Example

```bash
ai "Call the weather API for New York"
```

## Troubleshooting

- **Error: Invalid API Key**
  Ensure your `API_KEY` (or `YAI_API_KEY`) is correctly set and valid.

- **Error: Connection Timeout**
  Check your network connection or adjust the `TIMEOUT` / `YAI_TIMEOUT` value.

## Additional Resources

- [LongCat Platform](https://longcat.chat/platform/)
- [LongCat API Documentation](https://longcat.chat/platform/docs/zh/)
