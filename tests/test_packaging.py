"""Packaging policy tests (K09).

The base install must stay **tools-complete**: `pip install yaicli` keeps every builtin tool and MCP
working without extras, so `ddgs` (web_search), `trafilatura` (fetch_webpage extraction) and `fastmcp`
(MCP) belong to ``dependencies``. Only cloud provider SDK closures are optional
(``bedrock``/``vertex``). These tests lock that decision so a future slim-down cannot silently break
tools; update them together with any intentional extras change.

The parser is stdlib-only and works on Python 3.10 (no ``tomllib`` there).
"""

import re
from pathlib import Path
from typing import Dict, List

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

#: Packages that must stay in the base install so builtin tools work out of the box.
TOOLS_COMPLETE_BASE = ("ddgs", "trafilatura", "fastmcp")


def _parse_requirement_names(requirements: List[str]) -> List[str]:
    """Reduce requirement strings to their package name (including any extras marker)."""
    names = []
    for requirement in requirements:
        match = re.match(r"^\s*([A-Za-z0-9_.-]+(?:\[[^\]]*\])?)", requirement)
        if match:
            names.append(match.group(1))
    return names


def _load_pyproject() -> Dict:
    try:  # Python 3.11+
        import tomllib

        with PYPROJECT.open("rb") as handle:
            data = tomllib.load(handle)
        project = data.get("project", {})
        return {
            "dependencies": list(project.get("dependencies", [])),
            "optional-dependencies": dict(project.get("optional-dependencies", {})),
        }
    except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 only
        return _load_pyproject_with_regex(PYPROJECT.read_text(encoding="utf-8"))


def _load_pyproject_with_regex(text: str) -> Dict:
    """Minimal fallback parser for the simple arrays used by this pyproject."""
    project: Dict = {}

    dependencies_match = re.search(r"^dependencies = \[(.*?)^\]", text, re.S | re.M)
    dependencies = re.findall(r'"([^"]+)"', dependencies_match.group(1)) if dependencies_match else []
    project["dependencies"] = dependencies

    extras: Dict[str, List[str]] = {}
    optional_section = re.search(r"^\[project\.optional-dependencies\]\s*$(.*)", text, re.S | re.M)
    if optional_section:
        section = optional_section.group(1)
        # Multiline arrays start on their own line; inline arrays end on the same line.
        for name, body in re.findall(r"^([A-Za-z0-9_-]+) = \[\n(.*?)^\]", section, re.S | re.M):
            extras[name] = re.findall(r'"([^"]+)"', body)
        for name, body in re.findall(r"^([A-Za-z0-9_-]+) = \[([^\n\r]*)\]", section, re.M):
            extras.setdefault(name, re.findall(r'"([^"]+)"', body))
    project["optional-dependencies"] = extras
    return project


class TestToolsCompleteBase:
    def test_tool_dependencies_stay_in_base(self):
        base = _parse_requirement_names(_load_pyproject()["dependencies"])
        for package in TOOLS_COMPLETE_BASE:
            assert package in base, f"{package} must stay in base dependencies so builtin tools work"

    def test_anthropic_cloud_extras_are_not_in_base(self):
        base = _parse_requirement_names(_load_pyproject()["dependencies"])
        assert "anthropic" in base
        assert not any(name.startswith("anthropic[") for name in base)


class TestCloudExtras:
    def test_bedrock_and_vertex_extras_exist(self):
        extras = _load_pyproject()["optional-dependencies"]
        assert "anthropic[bedrock]" in " ".join(extras["bedrock"])
        assert "anthropic[vertex]" in " ".join(extras["vertex"])

    def test_all_still_includes_cloud_extras(self):
        extras = _load_pyproject()["optional-dependencies"]
        assert any("anthropic[bedrock,vertex]" in requirement for requirement in extras["all"])
        assert "anthropic[bedrock,vertex]" in " ".join(extras["all"])


class TestRegexFallbackParser:
    def test_parses_multiline_and_inline_arrays(self):
        sample = """
[project]
dependencies = [
    "anthropic>=0.57.1",
    "ddgs>=9.6.1",
]

[project.optional-dependencies]
all = [
    "anthropic[bedrock,vertex]>=0.57.1",
]
bedrock = ["anthropic[bedrock]>=0.57.1"]
"""
        parsed = _load_pyproject_with_regex(sample)
        assert "ddgs>=9.6.1" in parsed["dependencies"]
        assert parsed["optional-dependencies"]["bedrock"] == ["anthropic[bedrock]>=0.57.1"]
        assert parsed["optional-dependencies"]["all"] == ["anthropic[bedrock,vertex]>=0.57.1"]

    def test_requirement_name_reduction(self):
        assert _parse_requirement_names(["anthropic[bedrock,vertex]>=0.57.1"]) == ["anthropic[bedrock,vertex]"]
        assert _parse_requirement_names(["fastmcp>=2.10.1"]) == ["fastmcp"]
