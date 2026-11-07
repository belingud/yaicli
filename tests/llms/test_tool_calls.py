"""Tests for the shared tool-call helper and the multi-call schema contract.

Covers ``yaicli/llms/tool_calls.py`` (streaming accumulation/merge rules,
canonicalization, cross-response dedupe) and the dual ``LLMResponse.tool_call`` /
``LLMResponse.tool_calls`` views in ``yaicli/schemas.py``.
"""

from yaicli.llms.tool_calls import ToolCallAccumulator, dedupe_tool_calls, merge_argument_mapping
from yaicli.schemas import LLMResponse, ToolCall


class TestToolCallAccumulator:
    """Merge rules providers rely on."""

    def test_index_based_interleaved_fragments(self):
        """Fragments merge by index even when they arrive interleaved/out of order."""
        accumulator = ToolCallAccumulator()
        accumulator.add_fragment(index=0, call_id="call_a", name="fs_read_file")
        accumulator.add_fragment(index=1, call_id="call_b", name="fs_read_file")
        accumulator.add_fragment(index=1, arguments='{"path": ')
        accumulator.add_fragment(index=0, arguments='{"path": ')
        accumulator.add_fragment(index=1, arguments='"b.txt"}')
        accumulator.add_fragment(index=0, arguments='"a.txt"}')

        calls = accumulator.finalize()

        assert [call.id for call in calls] == ["call_a", "call_b"]
        assert [call.name for call in calls] == ["fs_read_file", "fs_read_file"]
        assert [call.arguments for call in calls] == ['{"path": "a.txt"}', '{"path": "b.txt"}']

    def test_id_based_merge_without_index(self):
        """An id identifies a call even when the stream never sends an index."""
        accumulator = ToolCallAccumulator()
        accumulator.add_fragment(call_id="call_1", name="get_weather")
        accumulator.add_fragment(call_id="call_1", arguments='{"city": ')
        accumulator.add_fragment(call_id="call_1", arguments='"Paris"}')

        calls = accumulator.finalize()

        assert len(calls) == 1
        assert calls[0].id == "call_1"
        assert calls[0].arguments == '{"city": "Paris"}'

    def test_id_then_index_is_the_same_call(self):
        """A call first seen by id and later by index is folded into one call."""
        accumulator = ToolCallAccumulator()
        accumulator.add_fragment(call_id="call_x", name="f")
        accumulator.add_fragment(index=3, call_id="call_x", arguments='{"a": 1}')

        calls = accumulator.finalize()

        assert len(calls) == 1
        assert calls[0].id == "call_x"
        assert calls[0].arguments == '{"a": 1}'

    def test_same_name_calls_without_ids_stay_distinct(self):
        """The Gemini bug: two same-name calls in one stream must not merge."""
        accumulator = ToolCallAccumulator()
        accumulator.add_fragment(name="get_weather")
        merge_argument_mapping(accumulator.calls[-1], {"city": "Paris"})
        accumulator.add_fragment(name="get_weather")
        merge_argument_mapping(accumulator.calls[-1], {"city": "London"})

        calls = accumulator.finalize()

        assert len(calls) == 2
        assert calls[0].arguments == '{"city": "Paris"}'
        assert calls[1].arguments == '{"city": "London"}'
        assert calls[0].id != calls[1].id

    def test_nameless_fragment_continues_last_call(self):
        """Proxies that send the name only once rely on continuation fragments."""
        accumulator = ToolCallAccumulator()
        accumulator.add_fragment(name="get_weather")
        accumulator.add_fragment(arguments='{"city": ')
        accumulator.add_fragment(arguments='"Rome"}')

        calls = accumulator.finalize()

        assert len(calls) == 1
        assert calls[0].name == "get_weather"
        assert calls[0].arguments == '{"city": "Rome"}'

    def test_nameless_fragment_without_a_call_is_ignored_by_providers(self):
        """An unattributable fragment creates a call but with no name (providers skip it)."""
        accumulator = ToolCallAccumulator()
        accumulator.add_fragment(arguments='{"x": 1}')

        calls = accumulator.finalize()

        assert len(calls) == 1
        assert calls[0].name == ""

    def test_replace_arguments_for_complete_resends(self):
        """AI21 re-sends complete JSON; replace instead of concatenating."""
        accumulator = ToolCallAccumulator()
        accumulator.add_fragment(call_id="call_1", name="f", arguments="")
        accumulator.add_fragment(call_id="call_1", arguments='{"a": 1}', replace_arguments=True)

        calls = accumulator.finalize()

        assert calls[0].arguments == '{"a": 1}'

    def test_complete_calls_keep_order_and_same_names(self):
        """Block-style APIs (Anthropic/Ollama/Mistral) add complete calls in order."""
        accumulator = ToolCallAccumulator()
        accumulator.add_complete(ToolCall(id="tool_1", name="get_weather", arguments='{"city": "Paris"}'))
        accumulator.add_complete(ToolCall(id="tool_2", name="get_weather", arguments='{"city": "London"}'))

        calls = accumulator.finalize()

        assert [call.id for call in calls] == ["tool_1", "tool_2"]
        assert [call.name for call in calls] == ["get_weather", "get_weather"]

    def test_complete_call_replayed_with_same_id_is_not_duplicated(self):
        accumulator = ToolCallAccumulator()
        accumulator.add_complete(ToolCall(id="call_1", name="f", arguments='{"a": 1}'))
        accumulator.add_complete(ToolCall(id="call_1", name="f", arguments='{"a": 1}'))

        calls = accumulator.finalize()

        assert len(calls) == 1

    def test_finalize_generates_unique_stable_ids(self):
        accumulator = ToolCallAccumulator()
        accumulator.add_complete(ToolCall(id="", name="f", arguments="{}"))
        accumulator.add_complete(ToolCall(id="", name="f", arguments="{}"))

        first = accumulator.finalize()
        second = accumulator.finalize()

        assert len(first) == 2
        assert first[0].id and first[1].id
        assert first[0].id != first[1].id
        # Finalizing twice does not churn ids (safe for message_delta + message_stop yields).
        assert [call.id for call in first] == [call.id for call in second]

    def test_finalize_returns_copies(self):
        """Later fragments must not mutate an already emitted call."""
        accumulator = ToolCallAccumulator()
        accumulator.add_complete(ToolCall(id="call_1", name="f", arguments='{"a": 1}'))

        snapshot = accumulator.finalize()
        accumulator.add_fragment(call_id="call_1", arguments='{"later": 2}')

        # The emitted snapshot is a copy, untouched by the later fragment; the
        # accumulator itself keeps accumulating for the next finalize().
        assert snapshot[0].arguments == '{"a": 1}'
        assert accumulator.finalize()[0].arguments == '{"a": 1}{"later": 2}'

    def test_ignores_non_string_fragment_fields(self):
        """MagicMock/dict-shaped chunks must not create phantom calls."""
        accumulator = ToolCallAccumulator()
        accumulator.add_fragment(index=object(), call_id=object(), name=object(), arguments=object())

        calls = accumulator.finalize()

        assert len(calls) == 1
        assert calls[0].name == ""
        assert calls[0].arguments == ""


class TestDedupeToolCalls:
    """Cross-response dedupe used by LLMClient."""

    def test_dedupes_by_id_and_preserves_order(self):
        first = ToolCall(id="call_a", name="fs_read_file", arguments='{"path": "a.txt"}')
        second = ToolCall(id="call_b", name="fs_read_file", arguments='{"path": "b.txt"}')

        merged = dedupe_tool_calls([first, second, ToolCall(id="call_a", name="dup", arguments="{}")])

        assert [call.id for call in merged] == ["call_a", "call_b"]
        assert merged[0] is first

    def test_assigns_ids_to_idless_calls(self):
        merged = dedupe_tool_calls([ToolCall(id="", name="f", arguments="{}")])

        assert len(merged) == 1
        assert merged[0].id.startswith("yaicli_")

    def test_skips_none(self):
        assert dedupe_tool_calls([None, None]) == []


class TestMergeArgumentMapping:
    def test_concatenates_repeated_string_values(self):
        call = ToolCall(id="c", name="f", arguments="")
        merge_argument_mapping(call, {"arguments": '{"city": "Bei'})
        merge_argument_mapping(call, {"arguments": 'jing"}'})

        assert call.arguments == '{"arguments": "{\\"city\\": \\"Beijing\\"}"}'

    def test_overwrites_non_string_values(self):
        call = ToolCall(id="c", name="f", arguments='{"count": 1}')
        merge_argument_mapping(call, {"count": 2})

        assert call.arguments == '{"count": 2}'

    def test_ignores_empty_updates_and_recovers_from_invalid_json(self):
        call = ToolCall(id="c", name="f", arguments="")
        merge_argument_mapping(call, None)
        assert call.arguments == ""

        call.arguments = "not json"
        merge_argument_mapping(call, {"a": 1})
        assert call.arguments == '{"a": 1}'


class TestLLMResponseMultiCallSchema:
    """The dual ``tool_call``/``tool_calls`` schema views stay in sync."""

    def test_legacy_single_call_constructor_fills_plural(self):
        tool_call = ToolCall(id="call_1", name="get_weather", arguments="{}")

        response = LLMResponse(tool_call=tool_call)

        assert response.tool_call is tool_call
        assert response.tool_calls == [tool_call]

    def test_plural_constructor_fills_legacy_view_with_first_call(self):
        first = ToolCall(id="call_a", name="f", arguments='{"path": "a"}')
        second = ToolCall(id="call_b", name="f", arguments='{"path": "b"}')

        response = LLMResponse(tool_calls=[first, second])

        assert response.tool_calls == [first, second]
        assert response.tool_call is first

    def test_both_views_consistent_when_both_given(self):
        first = ToolCall(id="call_a", name="f", arguments="{}")
        second = ToolCall(id="call_b", name="f", arguments="{}")

        response = LLMResponse(tool_call=first, tool_calls=[second])
        assert [call.id for call in response.tool_calls] == ["call_a", "call_b"]
        assert response.tool_call is first

    def test_no_calls(self):
        response = LLMResponse(content="hi")

        assert response.tool_call is None
        assert response.tool_calls == []

    def test_explicit_none_plural_is_normalized(self):
        """Defensive: a provider passing tool_calls=None still yields an iterable list."""
        response = LLMResponse(content="hi", tool_calls=None)

        assert response.tool_calls == []
        assert response.tool_call is None
