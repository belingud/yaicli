"""Secret redaction before data is written to disk (v0.22 K20).

Tool output (an environment dump, a file full of credentials) and saved chat
sessions used to be persisted verbatim; only the audit log was redacted. This
module is the single implementation shared by every on-disk writer:

* :func:`redact_text` replaces well-known secret *value shapes* in free text:
  provider API keys (``sk-``/``rk-``/``pk-``, including ``sk-ant-``,
  ``sk-proj-``, ``sk-or-v1-``), AWS access key ids and secret access keys,
  GitHub/Slack/Google tokens, ``Bearer`` headers, PEM private key blocks,
  env-style ``KEY=value`` assignments, URL userinfo credentials and JWTs. It
  also strips terminal control characters (tab/newline are preserved).
* :func:`redact_json_value` redacts *by key name* in parsed JSON
  (``api_key``, ``apikey``, ``secret``, ``token``, ``password``, ``passwd``,
  ``authorization``, ``credential``, ``bearer``, ``private_key``) recursively.
* :func:`redact_message_dict` redacts one serialized chat-message dict
  (``content``/``reasoning``/``name`` and every tool call's ``arguments``)
  while keeping the dict structure and keys intact.
* :func:`is_redaction_enabled` reads the ``REDACT_SECRETS`` config key
  (default ``True``) through a lazy config import, so this module can be
  imported from stdlib-only leaf modules without an import cycle.

Redaction is a *disk* concern only: the in-memory message list, what the model
sees and what the terminal renders are never modified. The audit log
(``yaicli/tools/approval.py``) re-exports :func:`redact_text` and always redacts,
independent of ``REDACT_SECRETS`` (that key only controls the on-disk spill and
session copies).

Standard library only: this module runs on the tool-spill and session-write
paths.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

__all__ = [
    "REDACTED",
    "is_redaction_enabled",
    "redact_json_value",
    "redact_message_dict",
    "redact_text",
]

#: Marker substituted for every redacted secret (same marker as the v0.19 audit log).
REDACTED = "[redacted]"

# ---------------------------------------------------------------------------
# Value-shape patterns (free text)
# ---------------------------------------------------------------------------
# C0/C1 control characters other than tab/newline. Tool output and session content
# may contain ANSI/OSC escapes; they are stripped (like the old approval.redact_text
# did) because the text is re-read from disk and may be rendered again later.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

# Provider API keys: sk- (OpenAI; Anthropic sk-ant-, OpenAI project sk-proj-,
# OpenRouter sk-or-v1-), and rk-/pk- (also the underscore form used by Stripe).
# The 8+ char body keeps ordinary prose such as "task-runner", "disk-usage",
# "risk-assessment" or "sk-learn" untouched.
_PROVIDER_KEY_RE = re.compile(r"(?i)\b(?:sk|rk|pk)[-_][A-Za-z0-9_-]{8,}")

# AWS access key ids: AKIA (long-lived) and ASIA (temporary).
_AWS_ACCESS_KEY_ID_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{12,}\b")

# AWS secret access keys are only recognizable next to their key name.
_AWS_SECRET_ACCESS_KEY_RE = re.compile(
    r"(?i)(\baws[_-]?secret[_-]?access[_-]?key\b[\"']?\s*[=:]?\s*[\"']?)([A-Za-z0-9/+=]{20,})"
)

# GitHub tokens: classic (ghp_/gho_/ghu_/ghs_/ghr_) and fine-grained (github_pat_).
_GITHUB_TOKEN_RE = re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")
_GITHUB_PAT_RE = re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")

# Slack tokens.
_SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")

# Google API keys: "AIza" followed by 35 characters.
_GOOGLE_API_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")

# HTTP "Authorization: Bearer <token>" headers.
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")

# PEM private key blocks (PKCS#8, RSA, EC, OPENSSH, encrypted, PGP, ...).
_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"
    r"[\s\S]*?"
    r"-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"
)

# scheme://user:password@host — keep scheme/user/host, redact only the password.
# The scheme length is bounded (real schemes are short) so a long run of letters
# can not make the engine backtrack over megabytes before failing on "://".
_URL_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]{0,31}://[^\s/:@]+:)([^\s/@]+)(@)")

# JWTs: three base64url segments, the header always starts with "eyJ". The 10+
# char segments keep ordinary prose that merely starts with "eyJ" untouched.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")

# env/config assignments whose *key name* marks the value as secret:
# API_KEY=..., SECRET=..., DB_PASSWORD=..., "access_token": "...". The required
# "="/":" separator and the 8+ char value keep ordinary prose untouched. The
# optional quote is captured so JSON-shaped text keeps its quoting. The key runs
# are length-bounded: this pattern runs over whole tool outputs, and an unbounded
# "[A-Za-z0-9_.-]*" would backtrack over long runs before failing.
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)"
    r"(\b[A-Za-z0-9_.-]{0,64}(?:api[_-]?key|apikey|secret|token|password|passwd|"
    r"authorization|credential|private[_-]?key)[A-Za-z0-9_.-]{0,64})"
    r"([\"']?\s*[=:]\s*)"
    r"([\"']?)"
    r"([^\s\"'{},;&|]{8,})"
    r"\3"
)

#: ``(trigger fragments, pattern, replacement)`` rows. A pattern is only executed
#: when at least one of its fragments occurs in the *lowercased* text: every match
#: necessarily contains one (each list is a superset trigger), so conditional
#: execution can not miss a secret, while a multi-megabyte tool-output spill with
#: no secret-looking fragment pays a few fast ``str`` scans instead of a dozen
#: regex passes. Multi-line patterns come first so a PEM block is redacted as a
#: whole. Replacements keep the surrounding key/scheme text (and any JSON quotes)
#: so the redacted output stays readable and structurally valid.
_VALUE_PATTERN_RULES: Tuple[Tuple[Tuple[str, ...], re.Pattern, str], ...] = (
    (("-----begin",), _PEM_PRIVATE_KEY_RE, REDACTED),
    (("sk-", "sk_", "rk-", "rk_", "pk-", "pk_"), _PROVIDER_KEY_RE, REDACTED),
    (("akia", "asia"), _AWS_ACCESS_KEY_ID_RE, REDACTED),
    (("secret",), _AWS_SECRET_ACCESS_KEY_RE, r"\1" + REDACTED),
    (("ghp_", "gho_", "ghu_", "ghs_", "ghr_"), _GITHUB_TOKEN_RE, REDACTED),
    (("github_pat_",), _GITHUB_PAT_RE, REDACTED),
    (("xox",), _SLACK_TOKEN_RE, REDACTED),
    (("aiza",), _GOOGLE_API_KEY_RE, REDACTED),
    (("bearer",), _BEARER_RE, REDACTED),
    (("://",), _URL_USERINFO_RE, r"\1" + REDACTED + r"\3"),
    (("eyj",), _JWT_RE, REDACTED),
    (
        ("key", "secret", "token", "passw", "author", "credential"),
        _SECRET_ASSIGNMENT_RE,
        r"\1\2\3" + REDACTED + r"\3",
    ),
)

# ---------------------------------------------------------------------------
# Key-name patterns (structured JSON)
# ---------------------------------------------------------------------------
#: Serialized JSON keys whose value is a secret by definition. Same set the
#: v0.19 audit summary used (``search`` semantics, case-insensitive).
_SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|apikey|secret|token|password|passwd|authorization|credential|bearer|private[_-]?key)"
)

#: Chat-message fields that are free text and must be redacted before persistence.
_MESSAGE_TEXT_FIELDS: Tuple[str, ...] = ("content", "reasoning", "name")

#: Config values accepted as boolean ``false`` for ``REDACT_SECRETS``.
_FALSE_VALUES = frozenset({"0", "false", "no", "n", "f", "off"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def redact_text(text: str) -> str:
    """Redact well-known secret shapes from free text.

    Applies the value-shape patterns in :data:`_VALUE_PATTERN_RULES` (API keys,
    cloud tokens, ``Bearer`` headers, PEM private key blocks, env-style
    assignments, URL userinfo credentials, JWTs) and then strips C0/C1 control
    characters except tab/newline. Ordinary prose and program output are left
    untouched; the patterns require distinctive prefixes/lengths (8+ char bodies)
    so short words such as ``sk-learn``, ``task-runner`` or ``risk-assessment``
    survive.

    Non-string input is converted with ``str()`` (this function is called on
    whatever a tool or provider returned).
    """
    if not isinstance(text, str):
        text = str(text)
    # Cheap per-pattern pre-filter: a pattern only runs when one of its trigger
    # fragments occurs, so a multi-megabyte spill with no secret-looking fragment
    # costs a few str scans instead of a dozen regex passes over every byte.
    lower = text.lower()
    for fragments, pattern, replacement in _VALUE_PATTERN_RULES:
        if any(fragment in lower for fragment in fragments):
            text = pattern.sub(replacement, text)
    return _CONTROL_CHARS_RE.sub("", text)


def redact_json_value(value: Any) -> Any:
    """Recursively redact secret-looking keys and values in parsed JSON data.

    Dict keys matching :data:`_SECRET_KEY_RE` (case-insensitive:
    ``api_key``/``apikey``/``secret``/``token``/``password``/``passwd``/
    ``authorization``/``credential``/``bearer``/``private_key``) have their value
    replaced by :data:`REDACTED`. Every other dict/list is recursed into and the
    string leaves get :func:`redact_text` applied. The keys/structure are
    preserved, so the result is still serializable with :func:`json.dumps`.
    """
    if isinstance(value, dict):
        redacted: Dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_json_value(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_json_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_message_dict(payload: dict) -> dict:
    """Return a copy of one serialized chat-message dict with secrets redacted.

    ``content``, ``reasoning`` and ``name`` are redacted with
    :func:`redact_text`, and so is every tool call's ``arguments`` JSON string
    (both the ``{"id", "name", "arguments"}`` shape written by
    :meth:`yaicli.chat.Chat.save` and the OpenAI wire shape with a nested
    ``function.arguments``). ``tool_call_id``, ``images`` and all other keys are
    preserved so the saved session keeps loading. Non-dict input and non-string
    field values are tolerated (returned/kept unchanged).
    """
    if not isinstance(payload, dict):
        return payload
    redacted: Dict[str, Any] = dict(payload)
    for field_name in _MESSAGE_TEXT_FIELDS:
        if field_name in redacted:
            redacted[field_name] = _redact_field_value(redacted[field_name])
    tool_calls = redacted.get("tool_calls")
    if isinstance(tool_calls, list):
        redacted["tool_calls"] = [_redact_tool_call_dict(entry) for entry in tool_calls]
    return redacted


def is_redaction_enabled() -> bool:
    """Return whether on-disk redaction is enabled (``REDACT_SECRETS``).

    The key defaults to ``True`` (the shipped config map value) and is read
    defensively from the :data:`yaicli.config.cfg` singleton: a missing/unreadable
    config, an empty value or an unrecognized string keeps the safe default
    (enabled). Only an explicit false-ish value (``False``/``0``/``"false"``/
    ``"off"``/...) disables redaction. The config import is local so this stdlib
    module can be imported before/without the config singleton and never creates
    an import cycle.
    """
    try:
        from .config import cfg  # local import: avoids an import cycle at module load

        raw = cfg.get("REDACT_SECRETS") if hasattr(cfg, "get") else None
    except Exception:  # pragma: no cover - a broken config must not disable redaction
        return True
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    return str(raw).strip().lower() not in _FALSE_VALUES


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _redact_field_value(value: Any) -> Any:
    """Redact one chat-message text field, tolerating non-string values.

    Strings are redacted directly. A list of content blocks keeps its structure:
    block strings and a block's ``text`` field are redacted, while opaque payloads
    (for example an image block's base64 ``data``) are left byte-identical — running
    secret regexes over binary payloads would corrupt them.
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        blocks: List[Any] = []
        for item in value:
            if isinstance(item, str):
                blocks.append(redact_text(item))
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                block = dict(item)
                block["text"] = redact_text(item["text"])
                blocks.append(block)
            else:
                blocks.append(item)
        return blocks
    return value


def _redact_tool_call_dict(tool_call: Any) -> Any:
    """Redact the ``arguments`` string of one serialized tool-call dict."""
    if not isinstance(tool_call, dict):
        return tool_call
    redacted: Dict[str, Any] = dict(tool_call)
    if isinstance(redacted.get("arguments"), str):
        redacted["arguments"] = redact_text(redacted["arguments"])
    function = redacted.get("function")
    if isinstance(function, dict):
        function_copy = dict(function)
        if isinstance(function_copy.get("arguments"), str):
            function_copy["arguments"] = redact_text(function_copy["arguments"])
        redacted["function"] = function_copy
    return redacted
