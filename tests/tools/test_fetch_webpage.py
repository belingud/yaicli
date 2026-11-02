"""Test fetch_webpage function."""

import socket
import sys
from unittest.mock import Mock, patch

import httpx
import pytest

from yaicli.functions.buildin import fetch_webpage
from yaicli.functions.buildin.fetch_webpage import Function

PUBLIC_IP = "93.184.216.34"


def _public_getaddrinfo(host, port, *args, **kwargs):
    """Fake DNS: every hostname resolves to one public IPv4 address."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port or 443))]


@pytest.fixture
def public_dns(monkeypatch):
    """Never perform real DNS lookups in tests."""
    monkeypatch.setattr(fetch_webpage.socket, "getaddrinfo", _public_getaddrinfo)


@pytest.fixture
def no_trafilatura(monkeypatch):
    """Simulate trafilatura not being installed (raw-text fallback)."""
    monkeypatch.setitem(sys.modules, "trafilatura", None)


def make_stream_response(
    status_code: int = 200,
    body: bytes = b"<html>Test content</html>",
    headers: dict | None = None,
    reason_phrase: str = "OK",
    encoding: str = "utf-8",
    body_chunks: list[bytes] | None = None,
):
    """Build a mock httpx streaming response."""
    response = Mock()
    response.status_code = status_code
    response.headers = headers or {}
    response.reason_phrase = reason_phrase
    response.encoding = encoding
    response.iter_bytes = Mock(return_value=iter(body_chunks if body_chunks is not None else [body]))
    stream = Mock()
    stream.__enter__ = Mock(return_value=response)
    stream.__exit__ = Mock(return_value=False)
    return stream


def make_client(*streams, side_effect=None):
    """Build a mock httpx.Client (context manager) returning the given stream responses."""
    client = Mock()
    client.cookies = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    if side_effect is not None:
        client.stream = Mock(side_effect=side_effect)
    elif len(streams) == 1:
        client.stream = Mock(return_value=streams[0])
    else:
        client.stream = Mock(side_effect=list(streams))
    return client


class TestHelpers:
    def test_get_random_user_agent(self):
        """Test that _get_random_user_agent returns a valid user agent."""
        ua = Function._get_random_user_agent()
        assert ua
        assert "Mozilla" in ua
        assert "Chrome" in ua or "Firefox" in ua or "Safari" in ua

    def test_get_default_headers(self):
        """Test that _get_default_headers returns proper headers."""
        headers = Function._get_default_headers()
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        assert "DNT" in headers
        assert headers["DNT"] == "1"

    def test_get_default_headers_with_custom_ua(self):
        """Test that custom user agent is used when provided."""
        headers = Function._get_default_headers("CustomUserAgent/1.0")
        assert headers["User-Agent"] == "CustomUserAgent/1.0"

    def test_default_headers_with_referer(self):
        headers = Function._get_default_headers(referer="http://ref.example")
        assert headers["Referer"] == "http://ref.example"

    def test_accept_language_explicit(self):
        assert Function._get_accept_language("en-US") == "en-US"

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("http://site.cn", "zh-CN"),
            ("http://site.jp", "ja-JP"),
            ("http://site.kr", "ko-KR"),
            ("http://site.de", "de-DE"),
            ("http://site.fr", "fr-FR"),
            ("http://site.es", "es-ES"),
        ],
    )
    def test_accept_language_by_tld(self, url, expected):
        assert expected in Function._get_accept_language("auto", url)

    def test_accept_language_default_fallback(self):
        assert "zh-CN" in Function._get_accept_language("auto", "http://site.io")


class TestURLValidation:
    """SSRF guard: the URL must be http(s) and resolve only to public addresses."""

    def test_allows_public_http_and_https(self, public_dns):
        assert Function._validate_fetch_url("https://example.com/page") is None
        assert Function._validate_fetch_url("http://example.com:8080/") is None

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/x",
            "javascript:alert(1)",
            "gopher://example.com/",
            "data:text/html,hello",
        ],
    )
    def test_rejects_non_http_schemes(self, url):
        error = Function._validate_fetch_url(url)
        assert error is not None
        assert "scheme" in error.lower()

    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",
            "127.10.0.1",
            "10.0.0.1",
            "172.16.5.4",
            "192.168.1.10",
            "169.254.169.254",  # cloud metadata
            "0.0.0.0",
            "224.0.0.1",  # multicast
            "240.0.0.1",  # reserved
        ],
    )
    def test_rejects_non_public_ipv4_literals(self, host):
        error = Function._validate_fetch_url(f"http://{host}/secret")
        assert error is not None
        assert "non-public" in error

    @pytest.mark.parametrize("host", ["[::1]", "[fc00::1]", "[fe80::1]", "[::]"])
    def test_rejects_non_public_ipv6_literals(self, host):
        error = Function._validate_fetch_url(f"http://{host}/")
        assert error is not None
        assert "non-public" in error

    def test_rejects_ipv4_mapped_loopback(self):
        error = Function._validate_fetch_url("http://[::ffff:127.0.0.1]/")
        assert error is not None
        assert "non-public" in error

    def test_rejects_ipv4_mapped_private(self):
        error = Function._validate_fetch_url("http://[::ffff:10.1.2.3]/")
        assert error is not None
        assert "non-public" in error

    def test_rejects_hostname_resolving_to_private(self, monkeypatch):
        monkeypatch.setattr(
            fetch_webpage.socket,
            "getaddrinfo",
            lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 443))],
        )
        error = Function._validate_fetch_url("https://internal.example/")
        assert error is not None
        assert "non-public" in error

    def test_rejects_when_any_resolved_address_is_private(self, monkeypatch):
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]
        monkeypatch.setattr(fetch_webpage.socket, "getaddrinfo", lambda *a, **k: answers)
        error = Function._validate_fetch_url("https://mixed.example/")
        assert error is not None
        assert "non-public" in error

    def test_rejects_unresolvable_host(self, monkeypatch):
        def boom(*args, **kwargs):
            raise socket.gaierror("name not known")

        monkeypatch.setattr(fetch_webpage.socket, "getaddrinfo", boom)
        error = Function._validate_fetch_url("https://does-not-exist.example/")
        assert error is not None
        assert "resolve" in error.lower()

    def test_rejects_url_without_host(self):
        assert Function._validate_fetch_url("http:///path") is not None

    def test_rejects_non_string_url(self):
        assert Function._validate_fetch_url(None) is not None  # type: ignore[arg-type]


    @pytest.mark.parametrize("host", ["100.100.100.200", "100.64.0.1", "100.127.255.254"])
    def test_rejects_cgnat_shared_address_space(self, host):
        """Test that 100.64.0.0/10 (CGNAT/shared space) is rejected.

        CPython reports 100.64.0.0/10 as neither private nor reserved, while
        100.100.100.200 is the Alibaba Cloud metadata endpoint.
        """
        error = Function._validate_fetch_url(f"http://{host}/latest/meta-data/")
        assert error is not None
        assert "non-public" in error

    @pytest.mark.parametrize(
        "url",
        [
            "http://8.8.8.8/",
            "http://1.1.1.1/",
            "http://[2606:4700::1111]/",
        ],
    )
    def test_allows_public_ip_literals(self, url):
        """Test that public IPv4 and IPv6 literals are allowed."""
        assert Function._validate_fetch_url(url) is None

    def test_is_public_ip_primary_judgement(self):
        """Test the is_global based predicate directly."""
        assert Function._is_public_ip("8.8.8.8") is True
        assert Function._is_public_ip("1.1.1.1") is True
        assert Function._is_public_ip("2606:4700::1111") is True
        assert Function._is_public_ip("100.100.100.200") is False
        assert Function._is_public_ip("100.64.0.1") is False
        assert Function._is_public_ip("100.127.255.254") is False
        assert Function._is_public_ip("224.0.0.1") is False
        assert Function._is_public_ip("::ffff:127.0.0.1") is False
        assert Function._is_public_ip("not-an-ip") is False


    def test_normalize_host(self):
        """Test hostname normalisation used for cross-host redirect detection."""
        assert Function._normalize_host("Example.COM.") == "example.com"
        assert Function._normalize_host("bücher.example") == "xn--bcher-kva.example"
        assert Function._normalize_host(None) == ""


class TestFetchWebpage:
    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_success(self, mock_client_class, public_dns, no_trafilatura):
        """Test successful fetch returns the body when trafilatura is unavailable."""
        mock_client_class.return_value = make_client(make_stream_response())

        result = Function.execute("https://example.com")

        assert result == "<html>Test content</html>"
        mock_client = mock_client_class.return_value
        assert mock_client.stream.call_args.args[0] == "GET"
        assert mock_client.stream.call_args.args[1] == "https://example.com"

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_success_extracts_with_trafilatura(self, mock_client_class, public_dns, monkeypatch):
        """Test that trafilatura.extract is applied to the downloaded HTML."""
        fake_trafilatura = Mock()
        fake_trafilatura.extract = Mock(return_value="Extracted content")
        monkeypatch.setitem(sys.modules, "trafilatura", fake_trafilatura)
        mock_client_class.return_value = make_client(make_stream_response())

        result = Function.execute("https://example.com")

        assert result == "Extracted content"
        fake_trafilatura.extract.assert_called_once_with("<html>Test content</html>")

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_extract_failure_falls_back_to_raw(self, mock_client_class, public_dns, monkeypatch):
        """Test that a trafilatura extraction failure falls back to the raw text."""
        fake_trafilatura = Mock()
        fake_trafilatura.extract = Mock(side_effect=ValueError("boom"))
        monkeypatch.setitem(sys.modules, "trafilatura", fake_trafilatura)
        mock_client_class.return_value = make_client(make_stream_response())

        result = Function.execute("https://example.com")

        assert result == "<html>Test content</html>"

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_with_custom_timeout(self, mock_client_class, public_dns, no_trafilatura):
        """Test execute with custom timeout."""
        mock_client_class.return_value = make_client(make_stream_response())

        Function.execute("https://example.com", timeout=60)

        call_kwargs = mock_client_class.call_args.kwargs
        assert call_kwargs["timeout"] == 60
        assert call_kwargs["follow_redirects"] is False

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    @patch("yaicli.functions.buildin.fetch_webpage.time.sleep")
    def test_execute_with_max_retries(self, mock_sleep, mock_client_class, public_dns, no_trafilatura):
        """Test that execute retries up to max_retries."""
        mock_client_class.return_value = make_client(
            side_effect=httpx.TimeoutException("Timeout"),
        )

        result = Function.execute("https://example.com", max_retries=5)

        assert "Failed to fetch" in result
        assert "Timeout error" in result
        assert mock_client_class.return_value.stream.call_count == 5
        assert mock_client_class.call_count == 5

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_http_error(self, mock_client_class, public_dns, no_trafilatura):
        """Test execute with HTTP error status."""
        mock_client_class.return_value = make_client(
            make_stream_response(status_code=404, reason_phrase="Not Found")
        )

        result = Function.execute("https://example.com/notfound")

        assert "Failed to fetch" in result
        assert "404" in result

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    @patch("yaicli.functions.buildin.fetch_webpage.time.sleep")
    def test_execute_retry_on_timeout(self, mock_sleep, mock_client_class, public_dns, no_trafilatura):
        """Test that execute retries on timeout."""
        mock_client_class.return_value = make_client(
            side_effect=httpx.TimeoutException("Timeout"),
        )

        result = Function.execute("https://example.com", max_retries=2)

        assert "Failed to fetch" in result
        assert "Timeout error" in result
        assert mock_client_class.return_value.stream.call_count == 2

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    @patch("yaicli.functions.buildin.fetch_webpage.time.sleep")
    def test_execute_retry_on_connection_error(self, mock_sleep, mock_client_class, public_dns, no_trafilatura):
        """Test that connection errors are retried without relaxing TLS verification."""
        mock_client_class.return_value = make_client(
            side_effect=httpx.ConnectError("certificate verify failed"),
        )

        result = Function.execute("https://example.com", max_retries=2, verify_ssl=True)

        assert "Failed to fetch" in result
        assert "Connection error" in result
        verify_args = [call.kwargs["verify"] for call in mock_client_class.call_args_list]
        assert verify_args == [True, True]

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_with_verify_ssl_false(self, mock_client_class, public_dns, no_trafilatura):
        """Test execute with verify_ssl=False."""
        mock_client_class.return_value = make_client(make_stream_response())

        Function.execute("https://example.com", verify_ssl=False)

        call_kwargs = mock_client_class.call_args.kwargs
        assert call_kwargs["verify"] is False

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_with_verify_ssl_true(self, mock_client_class, public_dns, no_trafilatura):
        """Test that verify_ssl=True is always passed through unchanged."""
        mock_client_class.return_value = make_client(make_stream_response())

        Function.execute("https://example.com", verify_ssl=True)

        assert mock_client_class.call_args.kwargs["verify"] is True

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_with_follow_redirects_false(self, mock_client_class, public_dns, no_trafilatura):
        """Test execute with follow_redirects=False does not follow a redirect."""
        redirect = make_stream_response(status_code=302, headers={"location": "https://example.com/next"})
        mock_client_class.return_value = make_client(redirect)

        result = Function.execute("https://example.com", follow_redirects=False)

        assert "Failed to fetch" in result
        assert "redirect not followed" in result
        assert mock_client_class.return_value.stream.call_count == 1

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_redirect_to_public_host(self, mock_client_class, public_dns, no_trafilatura):
        """Test that a redirect to another public URL is followed and re-validated."""
        redirect = make_stream_response(status_code=302, headers={"location": "https://cdn.example/final"})
        final = make_stream_response(body=b"<html>Final page</html>")
        mock_client_class.return_value = make_client(redirect, final)

        result = Function.execute("https://example.com/start")

        assert result == "<html>Final page</html>"
        stream_calls = mock_client_class.return_value.stream.call_args_list
        assert [call.args[1] for call in stream_calls] == [
            "https://example.com/start",
            "https://cdn.example/final",
        ]

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_relative_redirect(self, mock_client_class, public_dns, no_trafilatura):
        """Test that a relative Location header is resolved with urljoin."""
        redirect = make_stream_response(status_code=302, headers={"location": "/next"})
        final = make_stream_response(body=b"<html>Next page</html>")
        mock_client_class.return_value = make_client(redirect, final)

        result = Function.execute("https://example.com/start")

        assert result == "<html>Next page</html>"
        stream_calls = mock_client_class.return_value.stream.call_args_list
        assert [call.args[1] for call in stream_calls] == ["https://example.com/start", "https://example.com/next"]

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_redirect_to_private_blocked(self, mock_client_class, public_dns, no_trafilatura):
        """Test that a redirect to a private/metadata address is refused before requesting it."""
        redirect = make_stream_response(
            status_code=302,
            headers={"location": "http://169.254.169.254/latest/meta-data/iam/security-credentials/"},
        )
        mock_client_class.return_value = make_client(redirect)

        result = Function.execute("https://example.com/start")

        assert "Failed to fetch" in result
        assert "non-public" in result
        # Only the initial request may be made; the metadata request must never happen.
        assert mock_client_class.return_value.stream.call_count == 1

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_redirect_to_loopback_blocked(self, mock_client_class, public_dns, no_trafilatura):
        """Test that a redirect to loopback is refused."""
        redirect = make_stream_response(status_code=302, headers={"location": "http://127.0.0.1:8080/admin"})
        mock_client_class.return_value = make_client(redirect)

        result = Function.execute("https://example.com/start")

        assert "Failed to fetch" in result
        assert "non-public" in result
        assert mock_client_class.return_value.stream.call_count == 1

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_redirect_limit(self, mock_client_class, public_dns, no_trafilatura):
        """Test that redirect loops are capped."""
        redirects = [
            make_stream_response(status_code=302, headers={"location": f"https://example.com/{i}"})
            for i in range(fetch_webpage.MAX_REDIRECTS + 1)
        ]
        mock_client_class.return_value = make_client(*redirects)

        result = Function.execute("https://example.com/start")

        assert "Failed to fetch" in result
        assert "too many redirects" in result

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_redirect_without_location(self, mock_client_class, public_dns, no_trafilatura):
        """Test that a redirect without a Location header fails."""
        mock_client_class.return_value = make_client(make_stream_response(status_code=302))

        result = Function.execute("https://example.com")

        assert "Failed to fetch" in result
        assert "without Location" in result

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_blocks_loopback_without_request(self, mock_client_class):
        """Test that loopback URLs are rejected without any request being made."""
        result = Function.execute("http://127.0.0.1:8080/secret")

        assert "Failed to fetch" in result
        assert "non-public" in result
        mock_client_class.assert_not_called()

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_blocks_metadata_without_request(self, mock_client_class):
        """Test that the cloud metadata endpoint is rejected without any request."""
        result = Function.execute("http://169.254.169.254/latest/meta-data/")

        assert "Failed to fetch" in result
        assert "non-public" in result
        mock_client_class.assert_not_called()

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_blocks_file_scheme_without_request(self, mock_client_class):
        """Test that non-http schemes are rejected without any request."""
        result = Function.execute("file:///etc/passwd")

        assert "Failed to fetch" in result
        assert "scheme" in result.lower()
        mock_client_class.assert_not_called()

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_response_too_large(self, mock_client_class, public_dns, no_trafilatura, monkeypatch):
        """Test that oversized responses are rejected."""
        monkeypatch.setattr(fetch_webpage, "MAX_RESPONSE_BYTES", 5)
        response = make_stream_response(body_chunks=[b"1234", b"5678"])
        mock_client_class.return_value = make_client(response)

        result = Function.execute("https://example.com")

        assert "Failed to fetch" in result
        assert "too large" in result

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_error_messages_are_prefixed(self, mock_client_class):
        """Test that every failure path keeps the 'Failed to fetch ...' prefix."""
        for url in (
            "http://127.0.0.1/",
            "file:///etc/passwd",
            "https://does-not-exist.invalid/",
        ):
            with patch.object(fetch_webpage.socket, "getaddrinfo", side_effect=socket.gaierror("no dns")):
                assert Function.execute(url).startswith("Failed to fetch")
        mock_client_class.assert_not_called()

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_passes_headers_and_cookies(self, mock_client_class, public_dns, no_trafilatura):
        """Test that documented request options are actually forwarded to httpx."""
        client = make_client(make_stream_response())
        mock_client_class.return_value = client

        Function.execute(
            "https://example.com",
            timeout=7,
            user_agent="CustomUA/1.0",
            referer="https://ref.example/",
            cookies={"session": "abc123"},
        )

        client_kwargs = mock_client_class.call_args.kwargs
        assert client_kwargs["timeout"] == 7
        assert client_kwargs["cookies"] == {"session": "abc123"}
        headers = client.stream.call_args.kwargs["headers"]
        assert headers["User-Agent"] == "CustomUA/1.0"
        assert headers["Referer"] == "https://ref.example/"

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_rejects_non_string_url(self, mock_client_class):
        """Test that a non-string url fails gracefully with the standard error prefix."""
        result = Function.execute(123)  # type: ignore[arg-type]

        assert result.startswith("Failed to fetch")
        assert "URL must be a string" in result
        mock_client_class.assert_not_called()

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_blocks_cgnat_metadata_without_request(self, mock_client_class):
        """Test that the Alibaba Cloud metadata address (100.64.0.0/10) is rejected."""
        result = Function.execute("http://100.100.100.200/latest/meta-data/")

        assert result.startswith("Failed to fetch")
        assert "non-public" in result
        mock_client_class.assert_not_called()

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_allows_public_ip_literal(self, mock_client_class, no_trafilatura):
        """Test that a public IP literal is fetched (mock client, no real network)."""
        mock_client_class.return_value = make_client(make_stream_response(body=b"<html>OK</html>"))

        result = Function.execute("http://8.8.8.8/")

        assert result == "<html>OK</html>"
        assert mock_client_class.call_args.kwargs["verify"] is True

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_warns_when_verify_ssl_disabled(self, mock_client_class, public_dns, no_trafilatura, capfd):
        """Test that explicitly disabling TLS verification emits a prominent warning."""
        mock_client_class.return_value = make_client(make_stream_response())

        Function.execute("https://example.com", verify_ssl=False)

        captured = capfd.readouterr()
        assert "TLS certificate verification is DISABLED" in captured.out
        assert mock_client_class.call_args.kwargs["verify"] is False

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_does_not_warn_when_verify_ssl_enabled(
        self, mock_client_class, public_dns, no_trafilatura, capfd
    ):
        """Test that no TLS warning is printed when verification stays enabled (default)."""
        mock_client_class.return_value = make_client(make_stream_response())

        Function.execute("https://example.com")

        captured = capfd.readouterr()
        assert "TLS certificate verification is DISABLED" not in captured.out

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_cross_host_redirect_strips_cookies_and_referer(
        self, mock_client_class, public_dns, no_trafilatura
    ):
        """Test that a cross-host redirect drops user cookies and the explicit Referer."""
        redirect = make_stream_response(status_code=302, headers={"location": "https://other.example/final"})
        final = make_stream_response(body=b"<html>Other</html>")
        client = make_client(redirect, final)
        mock_client_class.return_value = client

        result = Function.execute(
            "https://example.com/start",
            cookies={"session": "secret"},
            referer="https://ref.example/page",
        )

        assert result == "<html>Other</html>"
        stream_calls = client.stream.call_args_list
        # First (same-host) hop keeps the caller-provided headers/cookies.
        assert stream_calls[0].kwargs["headers"]["Referer"] == "https://ref.example/page"
        # The cross-host hop must not forward cookies nor the explicit Referer.
        second_headers = {k.lower(): v for k, v in stream_calls[1].kwargs["headers"].items()}
        assert "referer" not in second_headers
        assert "cookie" not in second_headers
        client.cookies.clear.assert_called_once()

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_same_host_redirect_keeps_cookies_and_referer(
        self, mock_client_class, public_dns, no_trafilatura
    ):
        """Test that a same-host redirect keeps cookies and the explicit Referer."""
        redirect = make_stream_response(status_code=302, headers={"location": "/next"})
        final = make_stream_response(body=b"<html>Next</html>")
        client = make_client(redirect, final)
        mock_client_class.return_value = client

        result = Function.execute(
            "https://example.com/start",
            cookies={"session": "secret"},
            referer="https://ref.example/page",
        )

        assert result == "<html>Next</html>"
        stream_calls = client.stream.call_args_list
        assert stream_calls[1].kwargs["headers"]["Referer"] == "https://ref.example/page"
        client.cookies.clear.assert_not_called()

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_rejects_https_to_http_downgrade(self, mock_client_class, public_dns, no_trafilatura):
        """Test that an https -> http downgrade redirect is refused and not followed."""
        redirect = make_stream_response(status_code=302, headers={"location": "http://example.com/insecure"})
        client = make_client(redirect)
        mock_client_class.return_value = client

        result = Function.execute("https://example.com/start", follow_redirects=True)

        assert result.startswith("Failed to fetch")
        assert "refusing https->http downgrade redirect" in result
        assert client.stream.call_count == 1

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_allows_http_to_https_upgrade(self, mock_client_class, no_trafilatura):
        """Test that an http -> https upgrade redirect is followed."""
        redirect = make_stream_response(status_code=302, headers={"location": "https://example.com/secure"})
        final = make_stream_response(body=b"<html>Secure</html>")
        client = make_client(redirect, final)
        mock_client_class.return_value = client

        result = Function.execute("http://example.com/start")

        assert result == "<html>Secure</html>"
        assert client.stream.call_count == 2

    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_malformed_url_returns_error_string(self, mock_client_class):
        """Test that malformed URLs never raise and keep the 'Failed to fetch ...' contract."""
        for url in ("http://[::1", "http://[]/", "http://[::1]/x"):
            result = Function.execute(url)
            assert isinstance(result, str)
            assert result.startswith("Failed to fetch"), f"{url!r} -> {result!r}"
        mock_client_class.assert_not_called()
