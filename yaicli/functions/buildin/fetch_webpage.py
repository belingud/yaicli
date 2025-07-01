import httpx
from instructor import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """Fetch the webpage from the given URL."""

    url: str = Field(description="The URL to fetch the webpage from.")

    class Config:
        title = "fetch_webpage"

    @classmethod
    def execute(cls, url: str):
        """execute the function"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Upgrade-Insecure-Requests": "1",
            "Connection": "keep-alive",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
        }
        try:
            response = httpx.get(url, headers=headers, timeout=10)
            return response.text
        except Exception as e:
            return f"Failed to get the webpage from {url}: {str(e)}"
