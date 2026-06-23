"""Test fetch_webpage function."""

import httpx
import pytest
from unittest.mock import Mock, patch

from yaicli.functions.buildin.fetch_webpage import Function

TRAFILATURA_FALLBACK = "Failed to import trafilatura. Falling back to httpx."


class TestFetchWebpage:
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
        custom_ua = "CustomUserAgent/1.0"
        headers = Function._get_default_headers(custom_ua)
        assert headers["User-Agent"] == custom_ua

    @patch.object(Function, "_fetch_with_trafilatura", return_value=TRAFILATURA_FALLBACK)
    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_success(self, mock_client_class, _mock_trafilatura):
        """Test successful webpage fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html>Test content</html>"

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        result = Function.execute("https://example.com")

        assert result == "<html>Test content</html>"
        mock_client.get.assert_called_once()

    @patch.object(Function, "_fetch_with_trafilatura", return_value=TRAFILATURA_FALLBACK)
    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_with_custom_timeout(self, mock_client_class, _mock_trafilatura):
        """Test execute with custom timeout."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html>Test content</html>"

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        Function.execute("https://example.com", timeout=60)

        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs["timeout"] == 60

    @patch.object(Function, "_fetch_with_trafilatura", return_value=TRAFILATURA_FALLBACK)
    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_with_max_retries(self, mock_client_class, _mock_trafilatura):
        """Test execute with custom max_retries."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html>Test content</html>"

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        result = Function.execute("https://example.com", max_retries=5)

        assert result == "<html>Test content</html>"

    @patch.object(Function, "_fetch_with_trafilatura", return_value=TRAFILATURA_FALLBACK)
    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_http_error(self, mock_client_class, _mock_trafilatura):
        """Test execute with HTTP error status."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.reason_phrase = "Not Found"

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        result = Function.execute("https://example.com/notfound")

        assert "Failed to fetch" in result
        assert "404" in result

    @patch.object(Function, "_fetch_with_trafilatura", return_value=TRAFILATURA_FALLBACK)
    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    @patch("yaicli.functions.buildin.fetch_webpage.time.sleep")
    def test_execute_retry_on_timeout(self, mock_sleep, mock_client_class, _mock_trafilatura):
        """Test that execute retries on timeout."""
        import httpx

        mock_client = Mock()
        mock_client.get.side_effect = httpx.TimeoutException("Timeout")
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        result = Function.execute("https://example.com", max_retries=2)

        assert "Failed to fetch" in result
        assert "Timeout error" in result
        assert mock_client.get.call_count == 2

    @patch.object(Function, "_fetch_with_trafilatura", return_value=TRAFILATURA_FALLBACK)
    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    @patch("yaicli.functions.buildin.fetch_webpage.time.sleep")
    def test_execute_retry_on_ssl_error(self, mock_sleep, mock_client_class, _mock_trafilatura):
        """Test that execute retries on SSL error and disables SSL verification."""
        import httpx

        mock_client = Mock()
        mock_client.get.side_effect = httpx.ConnectError("SSL error")
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        result = Function.execute("https://example.com", max_retries=2, verify_ssl=True)

        assert "Failed to fetch" in result
        assert "Connection error" in result

    @patch.object(Function, "_fetch_with_trafilatura", return_value=TRAFILATURA_FALLBACK)
    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_with_verify_ssl_false(self, mock_client_class, _mock_trafilatura):
        """Test execute with verify_ssl=False."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html>Test content</html>"

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        Function.execute("https://example.com", verify_ssl=False)

        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs["verify"] is False

    @patch.object(Function, "_fetch_with_trafilatura", return_value=TRAFILATURA_FALLBACK)
    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_execute_with_follow_redirects_false(self, mock_client_class, _mock_trafilatura):
        """Test execute with follow_redirects=False."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html>Test content</html>"

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        Function.execute("https://example.com", follow_redirects=False)

        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs["follow_redirects"] is False

    @patch("builtins.__import__")
    def test_fetch_with_trafilatura(self, mock_import):
        """Test fetching with trafilatura."""
        mock_trafilatura = Mock()
        mock_trafilatura.fetch_url.return_value = "<html>Test content</html>"
        mock_trafilatura.extract.return_value = "Extracted content"

        def import_side_effect(name, *args, **kwargs):
            if name == "trafilatura":
                return mock_trafilatura
            return __import__(name, *args, **kwargs)

        mock_import.side_effect = import_side_effect

        result = Function.execute("https://example.com")

        assert result == "Extracted content"
        mock_trafilatura.fetch_url.assert_called_once()
        mock_trafilatura.extract.assert_called_once()

    @patch("builtins.__import__")
    @patch("yaicli.functions.buildin.fetch_webpage.httpx.Client")
    def test_fetch_with_trafilatura_not_installed(self, mock_client_class, mock_import):
        """Test that httpx fallback works when trafilatura is not installed."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html>Test content</html>"

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        def import_side_effect(name, *args, **kwargs):
            if name == "trafilatura":
                raise ImportError("No module named 'trafilatura'")
            return __import__(name, *args, **kwargs)

        mock_import.side_effect = import_side_effect

        result = Function.execute("https://example.com")

        assert result == "<html>Test content</html>"
        mock_client.get.assert_called_once()

    @patch("builtins.__import__")
    @patch("yaicli.functions.buildin.fetch_webpage.time.sleep")
    def test_fetch_with_trafilatura_retry(self, mock_sleep, mock_import):
        """Test that trafilatura fetch retries on failure."""
        mock_trafilatura = Mock()
        mock_trafilatura.fetch_url.side_effect = [None, "<html>Test content</html>"]
        mock_trafilatura.extract.return_value = "Extracted content"

        def import_side_effect(name, *args, **kwargs):
            if name == "trafilatura":
                return mock_trafilatura
            return __import__(name, *args, **kwargs)

        mock_import.side_effect = import_side_effect

        result = Function.execute("https://example.com", max_retries=2)

        assert result == "Extracted content"
        assert mock_trafilatura.fetch_url.call_count == 2


class TestFetchWebpageCoverage:
    """Cover remaining branches in fetch_webpage."""

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

    def _make_client(self, response=None, side_effect=None):
        client = Mock()
        if side_effect is not None:
            client.get.side_effect = side_effect
        else:
            client.get.return_value = response
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        return client

    @patch("yaicli.functions.buildin.fetch_webpage.time.sleep")
    def test_httpx_redirect_status_exhausts(self, _sleep):
        resp = Mock()
        resp.status_code = 301
        client = self._make_client(response=resp)
        with patch("yaicli.functions.buildin.fetch_webpage.httpx.Client", return_value=client):
            result = Function._fetch_with_httpx(
                url="http://x", timeout=1, max_retries=2, verify_ssl=True, follow_redirects=True, headers={}
            )
        assert "Failed to fetch" in result

    def test_httpx_non_200_returns_failed(self):
        resp = Mock()
        resp.status_code = 404
        resp.reason_phrase = "Not Found"
        client = self._make_client(response=resp)
        with patch("yaicli.functions.buildin.fetch_webpage.httpx.Client", return_value=client):
            result = Function._fetch_with_httpx(
                url="http://x", timeout=1, max_retries=1, verify_ssl=True, follow_redirects=True, headers={}
            )
        assert "HTTP 404" in result

    @patch("yaicli.functions.buildin.fetch_webpage.time.sleep")
    def test_httpx_status_error_exhausts(self, _sleep):
        client = self._make_client(side_effect=httpx.HTTPStatusError("err", request=Mock(), response=Mock()))
        with patch("yaicli.functions.buildin.fetch_webpage.httpx.Client", return_value=client):
            result = Function._fetch_with_httpx(
                url="http://x", timeout=1, max_retries=2, verify_ssl=True, follow_redirects=True, headers={}
            )
        assert "Failed to fetch" in result

    @patch("yaicli.functions.buildin.fetch_webpage.time.sleep")
    def test_httpx_unexpected_error_exhausts(self, _sleep):
        client = self._make_client(side_effect=ValueError("boom"))
        with patch("yaicli.functions.buildin.fetch_webpage.httpx.Client", return_value=client):
            result = Function._fetch_with_httpx(
                url="http://x", timeout=1, max_retries=2, verify_ssl=True, follow_redirects=True, headers={}
            )
        assert "Failed to fetch" in result

    @patch("builtins.__import__")
    @patch("yaicli.functions.buildin.fetch_webpage.time.sleep")
    def test_trafilatura_exception_exhausts(self, _sleep, mock_import):
        mock_traf = Mock()
        mock_traf.fetch_url.side_effect = ValueError("boom")

        def import_side_effect(name, *args, **kwargs):
            if name == "trafilatura":
                return mock_traf
            return __import__(name, *args, **kwargs)

        mock_import.side_effect = import_side_effect
        result = Function._fetch_with_trafilatura(
            url="http://x", timeout=1, max_retries=2, verify_ssl=True, follow_redirects=True, headers={}
        )
        assert "Failed to extract content" in result
