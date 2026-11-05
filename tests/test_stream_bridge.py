"""Tests for the background-generation stream bridge (T1, no UI/CLI wiring)."""

import threading
import time

import pytest

from yaicli.schemas import ConfirmToolCall, LLMResponse, ToolCall, ToolConfirmDecision
from yaicli.stream_bridge import ThreadedStream


def make_tool_call():
    return ToolCall(id="c1", name="get_weather", arguments="{}")


def drain(adapter, timeout=5.0):
    """Collect chunks until StopIteration (with a watchdog)."""
    chunks = []
    deadline = time.time() + timeout

    def consume():
        try:
            while True:
                chunks.append(next(adapter))
        except StopIteration:
            pass

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "adapter did not finish"
    assert time.time() < deadline
    return chunks


class TestChunks:
    def test_yields_all_chunks_then_stops(self):
        def gen():
            yield LLMResponse(content="a")
            yield LLMResponse(content="b")

        adapter = ThreadedStream(gen())
        try:
            first = next(adapter)
            second = next(adapter)
            assert first.content == "a"
            assert second.content == "b"
            with pytest.raises(StopIteration):
                next(adapter)
        finally:
            adapter.close()

    def test_generator_exception_is_forwarded(self):
        def gen():
            yield LLMResponse(content="a")
            raise RuntimeError("provider exploded")

        adapter = ThreadedStream(gen())
        try:
            assert next(adapter).content == "a"
            with pytest.raises(RuntimeError, match="provider exploded"):
                next(adapter)
        finally:
            adapter.close()

    def test_generator_close_is_called(self):
        closed = []

        def gen():
            try:
                yield LLMResponse(content="a")
                yield LLMResponse(content="b")
            finally:
                closed.append(True)

        adapter = ThreadedStream(gen())
        try:
            drain(adapter)
        finally:
            adapter.close()
        assert closed == [True]


class TestConsoleEvents:
    def test_console_events_are_replayed_in_order(self):
        printed = []
        holder = {}
        ready = threading.Event()

        def gen():
            yield LLMResponse(content="a")
            ready.wait(2.0)
            holder["adapter"].put_console("between", style="blue")
            yield LLMResponse(content="b")
            holder["adapter"].put_console("after")

        adapter = ThreadedStream(gen(), on_console=lambda stderr, a, k: printed.append((stderr, a, k)))
        holder["adapter"] = adapter
        ready.set()
        try:
            assert next(adapter).content == "a"
            # The console event queued before "b" is replayed while waiting for it.
            assert next(adapter).content == "b"
            assert printed == [(False, ("between",), {"style": "blue"})]
            with pytest.raises(StopIteration):
                next(adapter)
            assert printed[-1] == (False, ("after",), {})
        finally:
            adapter.close()

    def test_dropped_console_after_abort(self):
        def gen():
            yield LLMResponse(content="a")
            while True:
                time.sleep(0.05)
                yield LLMResponse(content="tick")

        adapter = ThreadedStream(gen())
        try:
            next(adapter)
            adapter.abort()
            before = adapter._queue.qsize()
            adapter.put_console("late")
            assert adapter._queue.qsize() == before
        finally:
            adapter.close()


class TestConfirmationHandshake:
    def test_send_decision_goes_back_to_generator(self):
        received = []

        def gen():
            decision = yield ConfirmToolCall(tool_call=make_tool_call())
            received.append(decision)
            yield LLMResponse(content="after-approval")

        adapter = ThreadedStream(gen())
        try:
            chunk = next(adapter)
            assert isinstance(chunk, ConfirmToolCall)
            result = adapter.send(ToolConfirmDecision.ONCE)
            assert result.content == "after-approval"
            assert received == [ToolConfirmDecision.ONCE]
            with pytest.raises(StopIteration):
                next(adapter)
        finally:
            adapter.close()

    def test_send_without_pending_confirmation_raises(self):
        def gen():
            yield LLMResponse(content="a")

        adapter = ThreadedStream(gen())
        try:
            next(adapter)
            with pytest.raises(TypeError):
                adapter.send(ToolConfirmDecision.ONCE)
        finally:
            adapter.close()

    def test_abort_unblocks_pending_confirmation(self):
        closed = []

        def gen():
            try:
                yield ConfirmToolCall(tool_call=make_tool_call())
                yield LLMResponse(content="unreachable")
            finally:
                closed.append(True)

        adapter = ThreadedStream(gen())
        try:
            assert isinstance(next(adapter), ConfirmToolCall)
            adapter.close(timeout=2.0)
            assert adapter.alive is False
        finally:
            adapter.close()
        assert closed == [True]


class TestAbort:
    def test_abort_stops_worker_and_drops_events(self):
        release = threading.Event()

        def gen():
            try:
                yield LLMResponse(content="first")
                release.wait(2.0)
                yield LLMResponse(content="late")
            finally:
                pass

        adapter = ThreadedStream(gen())
        try:
            assert next(adapter).content == "first"
            adapter.abort()
            release.set()
            adapter.close(timeout=2.0)
            assert adapter.alive is False
            with pytest.raises(StopIteration):
                next(adapter)
        finally:
            adapter.close()

    def test_abort_is_idempotent(self):
        def gen():
            yield LLMResponse(content="a")

        adapter = ThreadedStream(gen())
        adapter.abort()
        adapter.abort()
        adapter.close()
        assert adapter.dead is True


class TestUiThreadIndependence:
    def test_ui_thread_can_do_work_between_chunks(self):
        """The point of the bridge: the consumer is free while the worker produces."""
        produced = threading.Event()
        allow = threading.Event()

        def gen():
            yield LLMResponse(content="a")
            allow.wait(2.0)
            produced.set()
            yield LLMResponse(content="b")

        adapter = ThreadedStream(gen())
        try:
            assert next(adapter).content == "a"
            # Simulate the main thread being inside the viewer (not consuming).
            time.sleep(0.1)
            allow.set()
            assert produced.wait(2.0) is True
            assert next(adapter).content == "b"
        finally:
            adapter.close()


class TestThreadRegistry:
    def test_worker_thread_is_registered(self):
        from yaicli.stream_bridge import get_bridge_for_current_thread

        holder = {}
        started = threading.Event()
        release = threading.Event()

        def gen():
            holder["bridge"] = get_bridge_for_current_thread()
            started.set()
            yield LLMResponse(content="a")
            release.wait(2.0)
            yield LLMResponse(content="b")

        adapter = ThreadedStream(gen())
        try:
            assert next(adapter).content == "a"
            assert started.wait(2.0) is True
            assert holder["bridge"] is adapter
            # The UI thread is not a generation worker.
            assert get_bridge_for_current_thread() is None
            release.set()
        finally:
            adapter.close(timeout=2.0)
        assert get_bridge_for_current_thread() is None

    def test_close_returns_alive_for_blocked_worker(self):
        release = threading.Event()

        def gen():
            release.wait(2.0)
            yield LLMResponse(content="late")

        adapter = ThreadedStream(gen())
        adapter.start()
        try:
            assert adapter.close(timeout=0.05) is True
            assert adapter.alive is True
        finally:
            release.set()
        assert adapter.close(timeout=2.0) is False
        assert adapter.alive is False
