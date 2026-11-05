"""Tests for the turn-tagged tool-output history used by the Ctrl+O viewer."""

import pytest

from yaicli.tools import output_history
from yaicli.tools.output_history import MAX_ENTRIES, ToolOutputEntry


@pytest.fixture(autouse=True)
def _reset_history():
    output_history.reset()
    yield
    output_history.reset()


def record(name="tool", turn_text="result", **kwargs):
    return output_history.record_output(
        kind=kwargs.pop("kind", "function"),
        name=name,
        arguments=kwargs.pop("arguments", "{}"),
        text=turn_text,
        total_chars=kwargs.pop("total_chars", len(turn_text)),
        **kwargs,
    )


class TestTurnGrouping:
    def test_outputs_are_grouped_by_turn(self):
        output_history.begin_turn()
        first = record("a")
        second = record("b")
        output_history.begin_turn()
        third = record("c")

        entries, label = output_history.viewer_outputs()
        assert label == "this turn"
        assert [entry.name for entry in entries] == ["c"]
        assert entries[0].turn == 2
        assert first.turn == second.turn == 1
        assert third.turn == 2

    def test_falls_back_to_last_non_empty_turn(self):
        output_history.begin_turn()
        record("first-turn")
        output_history.begin_turn()  # new turn without tool calls (e.g. slash command)
        entries, label = output_history.viewer_outputs()
        assert label == "last turn"
        assert [entry.name for entry in entries] == ["first-turn"]

    def test_empty_history(self):
        entries, label = output_history.viewer_outputs()
        assert entries == []
        assert label == ""


class TestRingBuffer:
    def test_index_and_sequence_increase(self):
        output_history.begin_turn()
        first = record("a")
        second = record("b")
        assert (first.index, second.index) == (1, 2)
        assert output_history.last_output() is second

    def test_history_is_bounded(self):
        output_history.begin_turn()
        for i in range(MAX_ENTRIES + 20):
            record(f"tool-{i}")
        entries = output_history.all_outputs()
        assert len(entries) == MAX_ENTRIES
        assert entries[-1].name == f"tool-{MAX_ENTRIES + 19}"

    def test_reset_clears_turns_and_sequence(self):
        output_history.begin_turn()
        record("a")
        output_history.reset()
        assert output_history.all_outputs() == []
        assert output_history.current_turn() == 0
        output_history.begin_turn()
        entry = record("b")
        assert entry.index == 1


class TestEntryMetadata:
    def test_entry_keeps_truncation_metadata(self):
        output_history.begin_turn()
        entry = output_history.record_output(
            kind="mcp",
            name="_mcp__clock",
            arguments='{"tz": "UTC"}',
            text="model-visible text",
            total_chars=100_000,
            spill_path="/tmp/spill.txt",
            truncated=True,
        )
        assert isinstance(entry, ToolOutputEntry)
        assert entry.kind == "mcp"
        assert entry.arguments == '{"tz": "UTC"}'
        assert entry.text == "model-visible text"
        assert entry.total_chars == 100_000
        assert entry.spill_path == "/tmp/spill.txt"
        assert entry.truncated is True
        assert entry.turn == 1
        assert entry.index == 1
