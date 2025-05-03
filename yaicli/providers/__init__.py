from yaicli.const import DEFAULT_PROVIDER


def create_api_client(config, console, verbose):
    """Factory function to create the appropriate API client based on provider.

    Args:
        config: The configuration dictionary
        console: The rich console for output
        verbose: Whether to enable verbose output

    Returns:
        An instance of the appropriate ApiClient implementation
    """
    provider = config.get("PROVIDER", DEFAULT_PROVIDER).lower()

    if provider == "openai":
        from yaicli.providers.openai import OpenAIClient

        return OpenAIClient(config, console, verbose)
    elif provider == "cohere":
        from yaicli.providers.cohere import CohereClient

        return CohereClient(config, console, verbose)
    # elif provider == "google":
    #     return GoogleApiClient(config, console, verbose)
    # elif provider == "claude":
    #     return ClaudeApiClient(config, console, verbose)
    else:
        # Fallback to openai client
        from yaicli.providers.openai import OpenAIClient

        console.print(f"Using generic HTTP client for provider: {provider}", style="yellow")
        return OpenAIClient(config, console, verbose)
