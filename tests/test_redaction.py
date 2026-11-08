"""Tests for v0.22 K20 secret redaction (``yaicli/redaction.py``).

Covers the value-shape patterns (API keys, cloud tokens, ``Bearer`` headers,
PEM private keys, env-style assignments, URL userinfo, JWTs), the structured
JSON key-name redaction, the chat-message dict helper, and the
``REDACT_SECRETS`` on/off helper. The on-disk proof for spill files and saved
sessions lives in ``tests/test_spill_redaction.py`` and
``tests/test_chat_manage.py``.
"""

from copy import deepcopy

import pytest

from yaicli.config import cfg
from yaicli.redaction import (
    REDACTED,
    is_redaction_enabled,
    redact_json_value,
    redact_message_dict,
    redact_text,
)

def _fake(*parts: str) -> str:
    """Assemble a fake credential-shaped value from parts.

    The values must look like real tokens for the redactor tests, but no complete
    secret-shaped literal may live in the repository: a literal that matches a
    provider token format makes GitHub push protection block the whole push.
    Splitting the string keeps the behavior identical while the source contains
    no matchable secret.
    """
    return "".join(parts)


# --- Reusable secret shapes (fake, but structurally realistic) -------------
OPENAI_KEY = _fake("sk-", "1234567890abcdef")
ANTHROPIC_KEY = _fake("sk-ant-", "api03-", "abcdefghijklmnop")
PROJECT_KEY = _fake("sk-proj-", "abcdefghijklmnop")
OPENROUTER_KEY = _fake("sk-or-v1-", "abcdefghijklmnop")
STRIPE_LIVE_KEY = _fake("rk_live_", "abcdefghijklmnop")
STRIPE_PUBLISHABLE_KEY = _fake("pk_test_", "abcdefghijklmnop")
AWS_ACCESS_KEY_ID = _fake("AKIA", "IOSFODNN7EXAMPLE")
AWS_TEMP_KEY_ID = _fake("ASIA", "IOSFODNN7EXAMPLE")
AWS_SECRET_ACCESS_KEY = _fake("wJalrXUtnFEMI/", "K7MDENG/", "bPxRfiCYEXAMPLEKEY")
GITHUB_TOKEN = _fake("ghp_", "abcdefghijklmnopqrstuvwxyz0123456789")
GITHUB_PAT = _fake("github_pat_", "11ABCDEFG0123456789_", "abcdefghijklmnopqrstuvwxyz")
SLACK_TOKEN = _fake("xoxb-", "123456789012-", "1234567890123-", "abcdefghijklmnopqrstuvwx")
GOOGLE_API_KEY = _fake("AIza", "a" * 35)
BEARER_TOKEN = _fake("Bearer ", "abcdefghijklmnop")
JWT = _fake(
    "eyJhbGciOiJIUzI1NiJ9.",
    "eyJzdWIiOiIxMjM0NTY3ODkwIn0.",
    "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
)
PEM_RSA_HEADER = _fake("-----BEGIN ", "RSA PRIVATE KEY-----")
PEM_RSA_FOOTER = _fake("-----END ", "RSA PRIVATE KEY-----")
RSA_PRIVATE_KEY = _fake(
    PEM_RSA_HEADER,
    "\nMIIEowIBAAKCAQEA1234567890abcdefghijklmnopqrstuvwxyz\n",
    PEM_RSA_FOOTER,
)
OPENSSH_PRIVATE_KEY = _fake(
    "-----BEGIN ",
    "OPENSSH PRIVATE KEY-----",
    "\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAAB\n",
    "-----END ",
    "OPENSSH PRIVATE KEY-----",
)


class TestValueShapes:
    """Every supported secret shape is replaced by the shared marker."""

    @pytest.mark.parametrize(
        "secret",
        [
            OPENAI_KEY,
            ANTHROPIC_KEY,
            PROJECT_KEY,
            OPENROUTER_KEY,
            STRIPE_LIVE_KEY,
            STRIPE_PUBLISHABLE_KEY,
            AWS_ACCESS_KEY_ID,
            AWS_TEMP_KEY_ID,
            GITHUB_TOKEN,
            GITHUB_PAT,
            SLACK_TOKEN,
            GOOGLE_API_KEY,
            JWT,
        ],
    )
    def test_bare_token_is_redacted(self, secret):
        text = f"the credential is {secret} in the log"
        result = redact_text(text)
        assert secret not in result
        assert REDACTED in result
        assert result.startswith("the credential is ")
        assert result.endswith(" in the log")

    @pytest.mark.parametrize(
        "header",
        [
            f"Authorization: {BEARER_TOKEN}",
            f"authorization: {BEARER_TOKEN.lower()}",
            f"curl -H 'Authorization: {BEARER_TOKEN}'",
        ],
    )
    def test_bearer_tokens_are_redacted(self, header):
        result = redact_text(header)
        assert "abcdefghijklmnop" not in result
        assert REDACTED in result

    @pytest.mark.parametrize(
        ("assignment", "secret"),
        [
            (f"API_KEY={OPENAI_KEY}", OPENAI_KEY),
            ("SECRET=supersecretvalue", "supersecretvalue"),
            ("TOKEN=abcdefghijklmnop", "abcdefghijklmnop"),
            ("PASSWORD=hunter2hunter2", "hunter2hunter2"),
            ("PASSWD=hunter2hunter2", "hunter2hunter2"),
            ("DB_PASSWORD=abcdefghij", "abcdefghij"),
            (f"export GITHUB_TOKEN={GITHUB_TOKEN}", GITHUB_TOKEN),
            (f'AWS_SECRET_ACCESS_KEY="{AWS_SECRET_ACCESS_KEY}"', AWS_SECRET_ACCESS_KEY),
            (f"aws_secret_access_key = {AWS_SECRET_ACCESS_KEY}", AWS_SECRET_ACCESS_KEY),
            (f'"api_key": "{OPENAI_KEY}"', OPENAI_KEY),
            (f'"access_token": "{JWT}"', JWT),
        ],
    )
    def test_env_style_assignments_are_redacted(self, assignment, secret):
        result = redact_text(assignment)
        assert secret not in result
        assert REDACTED in result

    def test_env_assignment_keeps_the_key_name(self):
        assert redact_text("API_KEY=abcdef123456") == f"API_KEY={REDACTED}"
        assert redact_text('"api_key": "abcdefghijklmnop"') == f'"api_key": "{REDACTED}"'

    def test_pem_private_key_block_is_redacted_whole(self):
        text = f"before\n{RSA_PRIVATE_KEY}\nafter"
        result = redact_text(text)
        assert "MIIEow" + "IBAAK" not in result
        assert PEM_RSA_HEADER not in result
        assert PEM_RSA_FOOTER not in result
        assert result == f"before\n{REDACTED}\nafter"

    def test_openssh_private_key_block_is_redacted(self):
        result = redact_text(OPENSSH_PRIVATE_KEY)
        assert "b3BlbnNzaC1rZXk" not in result
        assert result == REDACTED

    def test_url_userinfo_password_is_redacted(self):
        result = redact_text("git clone https://user:s3cr3t-p4ss@example.com/repo.git")
        assert "s3cr3t-p4ss" not in result
        assert "https://user:[redacted]@example.com/repo.git" in result
        # The rest of the URL survives.
        assert "git clone " in result
        assert "/repo.git" in result

    def test_url_without_userinfo_is_untouched(self):
        text = "see https://example.com:8443/path?q=1 and ssh://git@example.com/repo"
        assert redact_text(text) == text

    def test_control_characters_are_stripped_but_whitespace_is_kept(self):
        result = redact_text("a\x00b\x1bc\x07d\te\nf\rg")
        assert result == "abcd\te\nfg"  # control chars removed, tab/newline preserved

    def test_repeated_redaction_is_idempotent(self):
        text = f"API_KEY={OPENAI_KEY}\n{BEARER_TOKEN}\n{RSA_PRIVATE_KEY}"
        once = redact_text(text)
        assert redact_text(once) == once


class TestNoOverRedaction:
    """Ordinary prose, code and program output must pass through unchanged."""

    @pytest.mark.parametrize(
        "text",
        [
            "The task-runner reports disk-usage at risk-assessment time.",
            "pip install scikit-learn",
            "sk-learn 1.0 is a classic ML library",
            "risk-assessment and desk-usage are not keys",
            "max_tokens: 4096 and max_tokens=8192",
            "token=short",
            "password: hunter2",
            '{"city": "Paris", "temperature": 0.7, "count": 3}',
            "A normal assistant answer with no secrets at all.",
            "The Bearer token is required.",
            "authorization failed: token expired",
            "eyJ not a real jwt",
            "pytest -q passed in 1.23s",
            "https://example.com/path",
            "user@example.com",
            "def redact_text(text): return text",
            "",
        ],
    )
    def test_ordinary_text_is_untouched(self, text):
        assert redact_text(text) == text

    def test_non_string_input_is_tolerated(self):
        assert redact_text(None) == "None"
        assert redact_text(12345) == "12345"


class TestRedactJsonValue:
    """Key-name based redaction for structured data."""

    @pytest.mark.parametrize(
        "key",
        [
            "api_key",
            "API_KEY",
            "apiKey",
            "apikey",
            "client_secret",
            "access_token",
            "PASSWORD",
            "passwd",
            "Authorization",
            "credential",
            "bearer",
            "private_key",
        ],
    )
    def test_secret_key_values_are_replaced(self, key):
        result = redact_json_value({key: "short"})
        assert result == {key: REDACTED}

    def test_non_secret_keys_and_values_are_preserved(self):
        payload = {"city": "Paris", "count": 3, "ok": True, "none": None}
        assert redact_json_value(payload) == payload

    def test_recurses_into_nested_dicts_and_lists(self):
        payload = {
            "headers": {"Authorization": BEARER_TOKEN, "Accept": "application/json"},
            "entries": [{"password": "p"}, {"token": "t"}],
            "env": {"API_KEY": OPENAI_KEY},
        }
        result = redact_json_value(payload)
        assert result["headers"]["Authorization"] == REDACTED
        assert result["headers"]["Accept"] == "application/json"
        assert result["entries"] == [{"password": REDACTED}, {"token": REDACTED}]
        assert result["env"] == {"API_KEY": REDACTED}

    def test_string_leaves_under_non_secret_keys_get_value_shape_redaction(self):
        payload = {"message": f"my key is {OPENAI_KEY}", "note": "nothing here"}
        result = redact_json_value(payload)
        assert OPENAI_KEY not in result["message"]
        assert REDACTED in result["message"]
        assert result["note"] == "nothing here"

    def test_top_level_and_tuple_inputs(self):
        assert OPENAI_KEY not in redact_json_value(f"key {OPENAI_KEY}")
        assert redact_json_value((OPENAI_KEY,)) == [REDACTED]

    def test_keys_are_preserved(self):
        payload = {"api_key": "x", "nested": {"client_secret": "y"}}
        assert list(redact_json_value(payload)) == ["api_key", "nested"]
        assert list(redact_json_value(payload)["nested"]) == ["client_secret"]


class TestRedactMessageDict:
    """The session-persistence helper for one serialized message dict."""

    def test_content_reasoning_and_name_are_redacted(self):
        payload = {
            "role": "assistant",
            "content": f"the key is {OPENAI_KEY}",
            "reasoning": f"found {GITHUB_TOKEN}",
            "name": f"tool-{SLACK_TOKEN}",
        }
        result = redact_message_dict(payload)
        assert OPENAI_KEY not in result["content"]
        assert GITHUB_TOKEN not in result["reasoning"]
        assert SLACK_TOKEN not in result["name"]
        assert result["role"] == "assistant"
        assert set(result) == set(payload)

    def test_tool_call_arguments_are_redacted(self):
        payload = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "execute_shell_command",
                    "arguments": f'{{"command": "curl -H \'Authorization: Bearer {BEARER_TOKEN}\'"}}',
                }
            ],
        }
        result = redact_message_dict(payload)
        arguments = result["tool_calls"][0]["arguments"]
        assert BEARER_TOKEN not in arguments
        assert REDACTED in arguments
        assert result["tool_calls"][0]["id"] == "call_1"
        assert result["tool_calls"][0]["name"] == "execute_shell_command"

    def test_openai_wire_shape_function_arguments_are_redacted(self):
        payload = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "f", "arguments": '{"api_key": "abcdefghijklmnop"}'},
                }
            ],
        }
        result = redact_message_dict(payload)
        function = result["tool_calls"][0]["function"]
        assert function["name"] == "f"
        assert "abcdefghijklmnop" not in function["arguments"]
        assert REDACTED in function["arguments"]

    def test_tool_call_id_is_untouched(self):
        payload = {"role": "tool", "content": "r", "name": "f", "tool_call_id": "call_abcdef123456"}
        assert redact_message_dict(payload)["tool_call_id"] == "call_abcdef123456"

    def test_images_are_preserved_untouched(self):
        base64_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        payload = {
            "role": "user",
            "content": "look",
            "images": [{"data": base64_data, "media_type": "image/png", "is_url": False}],
        }
        result = redact_message_dict(payload)
        assert result["images"][0]["data"] == base64_data

    def test_non_string_fields_are_tolerated(self):
        payload = {"role": "user", "content": None, "tool_calls": "not-a-list"}
        assert redact_message_dict(payload) == payload
        assert redact_message_dict({"role": "user", "content": 42})["content"] == 42

    def test_multimodal_content_blocks_text_is_redacted_without_touching_payloads(self):
        image_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg"
        payload = {
            "role": "user",
            "content": [
                {"type": "text", "text": f"my key is {OPENAI_KEY}"},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
        result = redact_message_dict(payload)
        assert OPENAI_KEY not in result["content"][0]["text"]
        assert result["content"][1]["image_url"]["url"] == image_url

    def test_input_payload_is_not_mutated(self):
        payload = {
            "role": "assistant",
            "content": f"key {OPENAI_KEY}",
            "tool_calls": [{"id": "c1", "name": "f", "arguments": f'{{"k": "{OPENAI_KEY}"}}'}],
        }
        snapshot = deepcopy(payload)
        redact_message_dict(payload)
        assert payload == snapshot

    def test_non_dict_payload_is_returned_unchanged(self):
        assert redact_message_dict("text") == "text"
        assert redact_message_dict(None) is None


class TestRedactionEnabled:
    """``REDACT_SECRETS`` config handling (default on, explicit off wins)."""

    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delitem(cfg, "REDACT_SECRETS", raising=False)
        assert is_redaction_enabled() is True

    @pytest.mark.parametrize("value", [True, 1, "true", "TRUE", "yes", "on"])
    def test_enabled_values(self, monkeypatch, value):
        monkeypatch.setitem(cfg, "REDACT_SECRETS", value)
        assert is_redaction_enabled() is True

    @pytest.mark.parametrize("value", [False, 0, "false", "FALSE", "no", "off", "0"])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setitem(cfg, "REDACT_SECRETS", value)
        assert is_redaction_enabled() is False

    def test_empty_or_unknown_values_keep_the_safe_default(self, monkeypatch):
        for value in (None, "", "banana"):
            monkeypatch.setitem(cfg, "REDACT_SECRETS", value)
            assert is_redaction_enabled() is True


class TestSharedWithAuditLog:
    """The audit log reuses the exact same implementation, unconditionally."""

    def test_approval_reexports_the_shared_function(self):
        from yaicli.tools.approval import redact_text as approval_redact_text

        assert approval_redact_text is redact_text

    def test_audit_redaction_ignores_redact_secrets_off(self, monkeypatch):
        from yaicli.tools.approval import summarize_arguments

        monkeypatch.setitem(cfg, "REDACT_SECRETS", False)
        summary = summarize_arguments("execute_shell_command", {"command": f"echo {OPENAI_KEY}"})
        assert OPENAI_KEY not in summary
        assert REDACTED in summary
