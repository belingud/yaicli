# LongCat Provider

LongCat is an OpenAI-compatible API provider that supports tool calls and streaming responses. This document provides configuration details and usage examples for the LongCat provider.

## Configuration Options

### Required Settings

| Environment Variable | Description          | Example Value              |
| -------------------- | -------------------- | -------------------------- |
| `LONGCAT_API_KEY`    | Your LongCat API key | `longcat_1234567890abcdef` |
| `LONGCAT_MODEL`      | Model name to use    | `LongCat-Flash-Chat`       |

### Optional Settings

| Environment Variable    | Description                | Default Value                     |
| ----------------------- | -------------------------- | --------------------------------- |
| `LONGCAT_BASE_URL`      | Base URL for the API       | `https://api.longcat.chat/openai` |
| `LONGCAT_TIMEOUT`       | Request timeout in seconds | `30`                              |
| `LONGCAT_EXTRA_HEADERS` | Additional HTTP headers    | `{}`                              |

## Example Configuration

```ini
PROVIDER=longcat
LONGCAT_API_KEY=your-api-key
LONGCAT_MODEL=LongCat-Flash-Chat
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
export LONGCAT_API_KEY=your-api-key
export LONGCAT_MODEL=LongCat-Flash-Chat
ai "What is the capital of France?"
```

### Tool Call Example

```bash
ai "Call the weather API for New York"
```

## Troubleshooting

- **Error: Invalid API Key**
  Ensure your `LONGCAT_API_KEY` is correctly set and valid.

- **Error: Connection Timeout**
  Check your network connection or adjust the `LONGCAT_TIMEOUT` value.

## Additional Resources

- [LongCat Platform](https://longcat.chat/platform/)
- [LongCat API Documentation](https://longcat.chat/platform/docs/zh/)
