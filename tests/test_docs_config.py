"""Keep the configuration docs in sync with the typed configuration map.

Drift guard added in v0.21.2: the README reference table and the
``ai --template`` output had missed newer keys (``TOOL_POLICY``, the tool-display
keys, ``MINIMAX_REASONING_SPLIT``). Every key in :data:`DEFAULT_CONFIG_MAP` must
now appear in the docs reference table, the README table, the shipped template
and the configuration-file snippet shown in the docs, with its real environment
variable and default documented.
"""

import re
from pathlib import Path

from yaicli.const import DEFAULT_CONFIG_INI, DEFAULT_CONFIG_MAP

ROOT = Path(__file__).resolve().parents[1]
DOCS_CONFIG = ROOT / "docs" / "usage" / "configuration.md"
README = ROOT / "README.md"

_TABLE_ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]*)`\s*\|([^|]*)\|([^|]*)\|([^|]*)\|", re.MULTILINE)
_INI_KEY = re.compile(r"^\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)

#: Keys whose documented default is prose (unset / dynamic path) instead of a value.
_PLACEHOLDER_DEFAULTS = {"CHAT_HISTORY_DIR", "TOOL_OUTPUT_DIR"}


def _section(text: str, heading: str) -> str:
    """Return ``text`` from ``heading`` up to the next heading of any level."""
    start = text.index(heading)
    end = len(text)
    for marker in ("\n## ", "\n### "):
        found = text.find(marker, start + len(heading))
        if found != -1:
            end = min(end, found)
    return text[start:end]


def _reference_table(path: Path, heading: str) -> dict[str, tuple[str, str, str]]:
    """Parse a Markdown reference table into ``{key: (description, default, env)}``."""
    rows: dict[str, tuple[str, str, str]] = {}
    for match in _TABLE_ROW.finditer(_section(path.read_text(encoding="utf-8"), heading)):
        rows[match.group(1)] = (match.group(2).strip(), match.group(3).strip(), match.group(4).strip())
    return rows


def _docs_reference_table() -> dict[str, tuple[str, str, str]]:
    return _reference_table(DOCS_CONFIG, "## Configuration Options Reference")


def _readme_reference_table() -> dict[str, tuple[str, str, str]]:
    return _reference_table(README, "### Configuration Options Reference")


def _env_name(cell: str) -> str:
    return cell.strip().strip("`").strip()


def _documented_default(key: str) -> str:
    """Normalize a map default to the way it is displayed in the tables."""
    value = DEFAULT_CONFIG_MAP[key]["value"]
    # Empty JSON maps (str "{}" for legacy keys, a real dict for newer ones) are
    # documented as "-" (unset/empty), not as the literal payload.
    if value is None or value == "" or value == "{}" or value == {}:
        return "-"
    return str(value)


def test_docs_reference_table_lists_every_config_key():
    assert set(_docs_reference_table()) == set(DEFAULT_CONFIG_MAP)


def test_readme_reference_table_lists_every_config_key():
    assert set(_readme_reference_table()) == set(DEFAULT_CONFIG_MAP)


def test_reference_tables_use_the_configured_env_var():
    for table in (_docs_reference_table(), _readme_reference_table()):
        for key, (_, _, env) in table.items():
            assert _env_name(env) == DEFAULT_CONFIG_MAP[key]["env_key"], key


def test_reference_tables_document_the_configured_default():
    for table in (_docs_reference_table(), _readme_reference_table()):
        for key, (_, default, _) in table.items():
            if key in _PLACEHOLDER_DEFAULTS:
                continue
            assert default.strip("`") == _documented_default(key), key


def test_template_contains_every_config_key():
    assert set(_INI_KEY.findall(DEFAULT_CONFIG_INI)) == set(DEFAULT_CONFIG_MAP)


def test_docs_config_structure_matches_the_template():
    text = DOCS_CONFIG.read_text(encoding="utf-8")
    start = text.index("## Configuration File Structure")
    block_start = text.index("```ini", start) + len("```ini")
    block_end = text.index("```", block_start)
    snippet_keys = set(_INI_KEY.findall(text[block_start:block_end]))

    # The docs snippet intentionally comments CHAT_HISTORY_DIR out (unset = per
    # project sessions); every other key must mirror the shipped template.
    missing = set(DEFAULT_CONFIG_MAP) - snippet_keys
    assert missing == {"CHAT_HISTORY_DIR"}
    assert snippet_keys <= set(DEFAULT_CONFIG_MAP)
