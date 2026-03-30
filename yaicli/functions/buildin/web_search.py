import json

from yaicli.function_schema import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """
    Search the web using DuckDuckGo and return results as JSON.
    """

    query: str = Field(
        ...,
        json_schema_extra={
            "example": "Python programming tutorial",
        },
        description="Search query string.",
    )
    max_results: int = Field(
        default=10,
        json_schema_extra={
            "example": 10,
        },
        description="Maximum number of search results to return (default: 10).",
    )
    region: str = Field(
        default="us-en",
        json_schema_extra={
            "example": "zh-cn",
        },
        description="Region for search results (default: us-en, options: zh-cn, us-en, uk-en, etc.).",
    )
    safesearch: str = Field(
        default="moderate",
        json_schema_extra={
            "example": "moderate",
        },
        description="Safe search level: on, moderate, or off (default: moderate).",
    )

    class Config:
        title = "web_search"

    @classmethod
    def execute(cls, query: str, max_results: int = 10, region: str = "us-en", safesearch: str = "moderate") -> str:
        """
        Search the web using DuckDuckGo and return results as JSON.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            region: Region code for localized results (e.g., us-en, zh-cn).
            safesearch: Safe search level (on, moderate, off).

        Returns:
            str: JSON string with search results.
        """
        result = {
            "query": query,
            "engine": "duckduckgo",
            "success": False,
            "results": [],
            "result_count": 0,
            "error": None,
        }

        try:
            # Import here to avoid dependency issues if not installed
            try:
                from ddgs import DDGS
            except ImportError:
                result["error"] = "ddgs library not installed. Please install with: pip install -U ddgs"
                return json.dumps(result, ensure_ascii=False, indent=2)

            # Perform search using new ddgs API
            ddgs = DDGS()
            search_results = ddgs.text(
                query=query,
                region=region,
                safesearch=safesearch,
                max_results=max_results,
            )

            # Process results
            results = []
            for item in search_results:
                # ddgs returns dict with keys: title, href, body
                results.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("href", ""),
                        "snippet": item.get("body", ""),
                    }
                )

            result["success"] = True
            result["results"] = results
            result["result_count"] = len(results)

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result, ensure_ascii=False, indent=2)
