import random
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from instructor import OpenAISchema
from pydantic import Field


class Function(OpenAISchema):
    """Fetch the webpage from the given URL."""

    url: str = Field(description="The URL to fetch the webpage from.")
    timeout: int = Field(
        default=30,
        description="Timeout in seconds for the request (default: 30).",
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of retries on failure (default: 3).",
    )
    use_trafilatura: bool = Field(
        default=False,
        description="Use trafilatura to extract main content (better for JS-rendered sites) (default: False).",
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates (default: True).",
    )
    follow_redirects: bool = Field(
        default=True,
        description="Follow HTTP redirects (default: True).",
    )
    user_agent: Optional[str] = Field(
        default=None,
        description="Custom User-Agent string (default: auto-rotate).",
    )
    cookies: Optional[dict] = Field(
        default=None,
        description="Custom cookies to send with the request (default: None).",
    )
    referer: Optional[str] = Field(
        default=None,
        description="Custom Referer header (default: None).",
    )
    language: Optional[str] = Field(
        default="auto",
        description="Accept-Language header (default: auto-detect from URL or zh-CN).",
    )

    class Config:
        title = "fetch_webpage"

    @staticmethod
    def _get_random_user_agent() -> str:
        """Get a random user agent from a pool of common browsers."""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
        ]
        return random.choice(user_agents)

    @staticmethod
    def _get_default_headers(
        user_agent: Optional[str] = None,
        language: Optional[str] = "auto",
        referer: Optional[str] = None,
        url: Optional[str] = None,
    ) -> dict:
        """Get default headers for web requests."""
        ua = user_agent or Function._get_random_user_agent()

        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": Function._get_accept_language(language, url),
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Sec-Ch-Ua": '"Chromium";v="143", "Not A(Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Pragma": "no-cache",
            "Priority": "u=0, i",
            "Cache-Control": "no-cache",
        }

        if referer:
            headers["Referer"] = referer

        return headers

    @staticmethod
    def _get_accept_language(language: Optional[str], url: Optional[str] = None) -> str:
        """Get Accept-Language header based on language preference or URL."""
        if language and language != "auto":
            return language

        if url:
            domain = urlparse(url).netloc.lower()

            if any(tld in domain for tld in [".cn", ".com.cn", ".net.cn", ".org.cn"]):
                return "zh-CN,zh;q=0.9,en;q=0.8"
            elif any(tld in domain for tld in [".jp", ".co.jp"]):
                return "ja-JP,ja;q=0.9,en;q=0.8"
            elif any(tld in domain for tld in [".kr", ".co.kr"]):
                return "ko-KR,ko;q=0.9,en;q=0.8"
            elif any(tld in domain for tld in [".de", ".at", ".ch"]):
                return "de-DE,de;q=0.9,en;q=0.8"
            elif any(tld in domain for tld in [".fr", ".be"]):
                return "fr-FR,fr;q=0.9,en;q=0.8"
            elif any(tld in domain for tld in [".es", ".ar", ".mx"]):
                return "es-ES,es;q=0.9,en;q=0.8"

        return "zh-CN,zh;q=0.9,en;q=0.8"

    @classmethod
    def execute(
        cls,
        url: str,
        timeout: int = 30,
        max_retries: int = 3,
        use_trafilatura: bool = False,
        verify_ssl: bool = True,
        follow_redirects: bool = True,
        user_agent: Optional[str] = None,
        cookies: Optional[dict] = None,
        referer: Optional[str] = None,
        language: Optional[str] = "auto",
    ):
        """execute the function"""
        headers = cls._get_default_headers(user_agent, language, referer, url)

        if use_trafilatura:
            return cls._fetch_with_trafilatura(
                url=url,
                timeout=timeout,
                max_retries=max_retries,
                verify_ssl=verify_ssl,
                follow_redirects=follow_redirects,
                headers=headers,
            )

        return cls._fetch_with_httpx(
            url=url,
            timeout=timeout,
            max_retries=max_retries,
            verify_ssl=verify_ssl,
            follow_redirects=follow_redirects,
            headers=headers,
            cookies=cookies,
        )

    @classmethod
    def _fetch_with_httpx(
        cls,
        url: str,
        timeout: int,
        max_retries: int,
        verify_ssl: bool,
        follow_redirects: bool,
        headers: dict,
        cookies: Optional[dict] = None,
    ) -> str:
        """Fetch webpage using httpx with retry logic."""
        last_error = None

        for attempt in range(max_retries):
            try:
                with httpx.Client(
                    verify=verify_ssl,
                    follow_redirects=follow_redirects,
                    timeout=timeout,
                    cookies=cookies,
                ) as client:
                    response = client.get(url, headers=headers)

                    if response.status_code == 200:
                        return response.text
                    elif response.status_code in [301, 302, 303, 307, 308]:
                        continue
                    else:
                        return f"Failed to fetch {url}: HTTP {response.status_code} - {response.reason_phrase}"

            except httpx.TimeoutException as e:
                last_error = f"Timeout error: {str(e)}"
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))
                    continue
            except httpx.ConnectError as e:
                last_error = f"Connection error (SSL): {str(e)}"
                if attempt < max_retries - 1 and verify_ssl:
                    verify_ssl = False
                    continue
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP status error: {str(e)}"
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))
                    continue
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))
                    continue

        return f"Failed to fetch {url} after {max_retries} attempts. Last error: {last_error}"

    @classmethod
    def _fetch_with_trafilatura(
        cls,
        url: str,
        timeout: int,
        max_retries: int,
        verify_ssl: bool,
        follow_redirects: bool,
        headers: dict,
    ) -> str:
        """Fetch webpage using trafilatura for better content extraction."""
        try:
            import trafilatura
        except ImportError:
            return "trafilatura is not installed. Falling back to httpx."

        last_error = None

        for attempt in range(max_retries):
            try:
                downloaded = trafilatura.fetch_url(
                    url,
                    no_ssl=not verify_ssl,
                    timeout=timeout,
                )

                if downloaded:
                    content = trafilatura.extract(downloaded)
                    if content:
                        return content

                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))
                    continue

            except Exception as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))
                    continue

        return f"Failed to extract content from {url} after {max_retries} attempts. Last error: {last_error}"
