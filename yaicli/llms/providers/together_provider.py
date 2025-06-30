from yaicli.config import cfg

from .openai_provider import OpenAIProvider


class TogetherProvider(OpenAIProvider):
    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        super().__init__(config, verbose, **kwargs)
        import warnings

        warnings.filterwarnings("ignore", category=DeprecationWarning)

    DEFAULT_BASE_URL = "https://api.together.xyz/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
    }
