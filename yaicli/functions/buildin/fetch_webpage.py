import ipaddress
import random
import socket
import time
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from yaicli.function_schema import OpenAISchema
from pydantic import Field

# SSRF hardening: only public http(s) endpoints may be fetched, every redirect hop is
# re-validated, and the response body is capped to avoid unbounded reads.
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB
_REDIRECT_STATUS_CODES = (301, 302, 303, 307, 308)


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

    @staticmethod
    def _is_public_ip(address: str) -> bool:
        """Return True when ``address`` is a public (non-SSRF) IP address.

        ``ip.is_global`` is the primary test: besides private/loopback/link-local/
        unspecified ranges it also rejects shared address space such as
        ``100.64.0.0/10`` (CGNAT — including the Alibaba Cloud metadata endpoint
        ``100.100.100.200``), which CPython does *not* flag via ``is_private`` or
        ``is_reserved``. Multicast is still reported as "global" by ``ipaddress``,
        and reserved/NAT64 prefixes (e.g. ``64:ff9b::/96``) can embed private IPv4
        targets, so those stay explicitly rejected for defence in depth.
        """
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        # Normalise IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) to its IPv4 form.
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return ip.is_global and not ip.is_multicast and not ip.is_reserved

    @classmethod
    def _validate_fetch_url(cls, url: str) -> Optional[str]:
        """Validate that ``url`` may be fetched (SSRF guard).

        Returns ``None`` when the URL is allowed, otherwise a human readable reason.
        Only http/https is accepted and every address the host resolves to must be a
        public address: loopback, private, link-local (incl. 169.254.169.254 cloud
        metadata), multicast, reserved and unspecified addresses are rejected.
        """
        if not isinstance(url, str):
            return "URL must be a string"
        try:
            parsed = urlparse(url)
        except ValueError as e:
            return f"Invalid URL: {e}"

        if parsed.scheme.lower() not in ("http", "https"):
            return f"Unsupported URL scheme {parsed.scheme!r} (only http/https are allowed)"

        host = parsed.hostname
        if not host:
            return "URL has no host"

        try:
            port = parsed.port
        except ValueError as e:
            return f"Invalid URL: {e}"

        try:
            ipaddress.ip_address(host)
        except ValueError:
            # Hostname: resolve *all* addresses and reject if any one is non-public.
            try:
                infos = socket.getaddrinfo(host, port or 0, type=socket.SOCK_STREAM)
            except (socket.gaierror, UnicodeError, OSError) as e:
                return f"Could not resolve host {host!r}: {e}"
            addresses = [info[4][0] for info in infos]
        else:
            addresses = [host]

        if not addresses:
            return f"Could not resolve host {host!r}"

        for address in addresses:
            if not cls._is_public_ip(address):
                return f"Refusing to fetch non-public address {address!r} (host {host!r})"
        return None

    @classmethod
    def _read_response_text(cls, response, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Read the response body, enforcing ``MAX_RESPONSE_BYTES``.

        Returns ``(text, None)`` on success, ``(None, error_message)`` when the body is
        too large.
        """
        chunks: List[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                return None, f"Failed to fetch {url}: response too large (>{MAX_RESPONSE_BYTES} bytes)"
            chunks.append(chunk)

        raw = b"".join(chunks)
        try:
            encoding = response.encoding or "utf-8"
        except (LookupError, ValueError):
            encoding = "utf-8"
        try:
            return raw.decode(encoding, errors="replace"), None
        except LookupError:
            return raw.decode("utf-8", errors="replace"), None

    @classmethod
    def _download_html(
        cls,
        url: str,
        timeout: int,
        max_retries: int,
        verify_ssl: bool,
        follow_redirects: bool,
        headers: dict,
        cookies: Optional[dict] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Download a page with retries and manually followed, re-validated redirects.

        Returns ``(text, None)`` on success or ``(None, error_message)`` on failure.
        Every request — including every redirect hop — is validated with
        ``_validate_fetch_url``, so a redirect cannot smuggle the request to a
        loopback/private/link-local/metadata address.
        """
        try:
            attempts = max(0, int(max_retries))
        except (TypeError, ValueError):
            attempts = 0

        # Fail fast, before creating any HTTP client: a non-public / non-http URL must
        # never trigger a network request at all.
        error = cls._validate_fetch_url(url)
        if error is not None:
            return None, f"Failed to fetch {url}: {error}"

        last_error = None
        for attempt in range(attempts):
            current_url = url
            try:
                # follow_redirects is disabled on purpose: hops are followed manually
                # below so that each target is re-validated before being requested.
                with httpx.Client(
                    verify=verify_ssl,
                    follow_redirects=False,
                    timeout=timeout,
                    cookies=cookies,
                ) as client:
                    redirects = 0
                    while True:
                        with client.stream("GET", current_url, headers=headers) as response:
                            status = response.status_code
                            if status in _REDIRECT_STATUS_CODES:
                                location = response.headers.get("location")
                                if not follow_redirects:
                                    return (
                                        None,
                                        f"Failed to fetch {current_url}: HTTP {status} redirect "
                                        "not followed (follow_redirects=False)",
                                    )
                                if not location:
                                    return (
                                        None,
                                        f"Failed to fetch {current_url}: HTTP {status} redirect "
                                        "without Location header",
                                    )
                                redirects += 1
                                if redirects > MAX_REDIRECTS:
                                    return (
                                        None,
                                        f"Failed to fetch {current_url}: too many redirects (>{MAX_REDIRECTS})",
                                    )
                                next_url = urljoin(current_url, location)
                                # Re-validate every redirect target before requesting it.
                                redirect_error = cls._validate_fetch_url(next_url)
                                if redirect_error is not None:
                                    return None, f"Failed to fetch {next_url}: {redirect_error}"
                                current_url = next_url
                                continue
                            if status != 200:
                                return (
                                    None,
                                    f"Failed to fetch {current_url}: HTTP {status} - {response.reason_phrase}",
                                )
                            return cls._read_response_text(response, current_url)

            except httpx.TimeoutException as e:
                last_error = f"Timeout error: {e}"
            except httpx.ConnectError as e:
                # NOTE: TLS verification is never relaxed as a retry strategy; a
                # certificate failure is reported as a connection error.
                last_error = f"Connection error: {e}"
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP status error: {e}"
            except Exception as e:
                last_error = f"Unexpected error: {e}"

            if attempt < attempts - 1:
                time.sleep(1 * (attempt + 1))

        return None, f"Failed to fetch {url} after {attempts} attempts. Last error: {last_error}"

    @staticmethod
    def _extract_content(html: str) -> str:
        """Extract readable text from HTML, falling back to the raw text."""
        try:
            import trafilatura
        except ImportError:
            return html
        try:
            extracted = trafilatura.extract(html)
        except Exception:
            return html
        return extracted or html

    @staticmethod
    def _warn_insecure_tls() -> None:
        """Print one prominent warning when the caller explicitly disables TLS checks.

        The caller's explicit ``verify_ssl=False`` choice is preserved (no behaviour
        change); the warning simply makes the MITM risk visible. Uses ``markup=False``
        so nothing model/user controlled is interpreted as console markup.
        """
        message = (
            "WARNING: TLS certificate verification is DISABLED (verify_ssl=False); "
            "the connection is vulnerable to man-in-the-middle attacks."
        )
        try:
            from yaicli.console import get_console

            get_console().print(message, style="bold yellow", markup=False)
        except Exception:  # pragma: no cover - console is always available inside yaicli
            print(message)

    @classmethod
    def execute(
        cls,
        url: str,
        timeout: int = 30,
        max_retries: int = 3,
        verify_ssl: bool = True,
        follow_redirects: bool = True,
        user_agent: Optional[str] = None,
        cookies: Optional[dict] = None,
        referer: Optional[str] = None,
        language: Optional[str] = "auto",
    ) -> str:
        """execute the function"""
        if not isinstance(url, str):
            return f"Failed to fetch {url}: URL must be a string"

        if verify_ssl is False:
            cls._warn_insecure_tls()

        headers = cls._get_default_headers(user_agent, language, referer, url)

        text, error = cls._download_html(
            url=url,
            timeout=timeout,
            max_retries=max_retries,
            verify_ssl=verify_ssl,
            follow_redirects=follow_redirects,
            headers=headers,
            cookies=cookies,
        )
        if text is None:
            return error or f"Failed to fetch {url}"

        return cls._extract_content(text)
