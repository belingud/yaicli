# Fireworks AI

[Fireworks AI](https://fireworks.ai/) is an artificial intelligence platform that provides high-performance large language model APIs.

## Features

- Support for function calling and MCP
- OpenAI API compatibility
- Support for various advanced models like Llama 3.1, Mixtral, and more


## Configuration

To use Fireworks AI, you need to:
1. Register on the [Fireworks AI website](https://fireworks.ai/) and obtain an API key
2. Install the `fireworks-ai` package: `uv tool install 'yaicli[fireworks]'`
3. Set up your API key and model

### Configuration Options

```ini
# Fireworks configuration
PROVIDER=fireworks  # Provider type
MODEL=llama-v3p1-70b-instruct  # Model name
API_KEY=your_api_key_here  # Your API key
ACCOUNT=fireworks
```

## Function Calling Support

Fireworks supports an OpenAI-compatible function calling API, but with some differences:

- No support for parallel function calls
- No support for nested function calls
- Simplified tool choice options

### Best Practices for Function Calling

- **Number of Functions**: For best performance, keep the function list below 7 items
- **Function Description**: Describe function capabilities in detail to improve model understanding
- **System Prompt**: Not recommended to add additional system prompts to avoid interfering with function calling capabilities
- **Temperature Parameter**: Set temperature to 0.0 or a low value to help the model generate only confident predictions

## Example

Using Fireworks AI for a simple conversation:

```ini
PROVIDER=fireworks
MODEL=llama-v3p1-70b-instruct
API_KEY=your_api_key_here
```

```bash
ai "Explain the basic principles of quantum computing"
```

## References

- [Fireworks AI Website](https://fireworks.ai/)
- [Fireworks Docs](https://fireworks.ai/docs/getting-started/introduction) 