"""Tests for worker-thread console routing (T2)."""

import threading
import time
from unittest.mock import MagicMock

import pytest

import yaicli.console as console_mod
import yaicli.tools as tools_mod
from yaicli.schemas import LLMResponse
from yaicli.stream_bridge import ThreadedStream, clear_active_bridge, get_active_bridge, set_active_bridge
from yaicli.worker_console import WorkerConsole, install_worker_console_routing


@pytest.fixture(autouse=True)
def _clean_bridge():
    clear_active_bridge()
    yield
    clear_active_bridge()


def make_bridge_that_waits():
    """Return (adapter, generator) where the generator waits until released."""
    allow = threading.Event()
    holder = {}

    def gen():
        holder["started"].set()
        allow.wait(2.0)
        yield LLMResponse(content="after")

    adapter = ThreadedStream(gen())
    return adapter, holder, allow


def run_in_thread(fn):
    thread = threading.Thread(target=fn)
    thread.start()
    thread.join(2.0)
    assert not thread.is_alive()


class TestMainThreadPassthrough:
    def test_main_thread_prints_to_real_console(self):
        real = MagicMock()
        console = WorkerConsole(real)
        console.print("hello", style="blue")
        real.print.assert_called_once_with("hello", style="blue")

    def test_main_thread_ignores_active_bridge(self):
        """The UI thread must keep writing (and replaying) to the real console."""
        real = MagicMock()
        console = WorkerConsole(real)
        adapter = MagicMock()
        adapter.dead = False
        set_active_bridge(adapter)
        console.print("ui")
        real.print.assert_called_once_with("ui")
        adapter.put_console.assert_not_called()

    def test_attribute_delegation(self):
        real = MagicMock()
        real.width = 88
        console = WorkerConsole(real)
        assert console.width == 88
        assert console.real is real


class TestWorkerRouting:
    def test_worker_print_is_queued_instead_of_written(self):
        real = MagicMock()
        console = WorkerConsole(real)
        adapter = MagicMock()
        adapter.dead = False
        set_active_bridge(adapter)
        run_in_thread(lambda: console.print("from worker", style="red"))
        real.print.assert_not_called()
        adapter.put_console.assert_called_once_with("from worker", stderr=False, style="red")

    def test_error_console_marks_stderr(self):
        real = MagicMock()
        console = WorkerConsole(real, stderr=True)
        adapter = MagicMock()
        adapter.dead = False
        set_active_bridge(adapter)
        run_in_thread(lambda: console.print("warning"))
        adapter.put_console.assert_called_once_with("warning", stderr=True)

    def test_worker_without_bridge_uses_real_console(self):
        real = MagicMock()
        console = WorkerConsole(real)
        run_in_thread(lambda: console.print("legacy"))
        real.print.assert_called_once_with("legacy")

    def test_dead_bridge_drops_worker_output(self):
        real = MagicMock()
        console = WorkerConsole(real)
        adapter = MagicMock()
        adapter.dead = True
        set_active_bridge(adapter)
        run_in_thread(lambda: console.print("late"))
        real.print.assert_not_called()
        adapter.put_console.assert_not_called()


class TestEndToEndOrdering:
    def test_worker_print_is_replayed_before_next_chunk(self):
        printed = []
        ready = threading.Event()
        holder = {}

        def gen():
            yield LLMResponse(content="a")
            ready.wait(2.0)  # let the test install the console + bridge first
            holder["console"].print("panel", style="dim")
            yield LLMResponse(content="b")

        adapter = ThreadedStream(gen(), on_console=lambda stderr, a, k: printed.append((stderr, a, k)))
        holder["console"] = WorkerConsole(MagicMock())
        set_active_bridge(adapter)
        ready.set()
        try:
            assert next(adapter).content == "a"
            assert next(adapter).content == "b"
            assert printed == [(False, ("panel",), {"style": "dim"})]
        finally:
            adapter.close()
        assert get_active_bridge() is None


class TestInstallRouting:
    def test_install_and_restore_swaps_consoles(self):
        real_main = MagicMock()
        real_error = MagicMock()
        saved_tools = tools_mod.console
        saved_error = console_mod._error_console
        routing = install_worker_console_routing(real_main, real_error)
        try:
            assert isinstance(tools_mod.console, WorkerConsole)
            assert isinstance(console_mod._error_console, WorkerConsole)
            assert tools_mod.console.real is real_main
            assert console_mod._error_console.real is real_error
            assert routing.main.real is real_main
            assert routing.error.real is real_error
        finally:
            routing.restore()
            assert tools_mod.console is saved_tools
            assert console_mod._error_console is saved_error
        assert routing.restored is True

    def test_restore_is_idempotent(self):
        routing = install_worker_console_routing(MagicMock(), MagicMock())
        routing.restore()
        routing.restore()  # no error / no double restore side effects
        assert routing.restored is True

    def test_installed_console_routes_worker_prints(self):
        real_main = MagicMock()
        routing = install_worker_console_routing(real_main, MagicMock())
        printed = []
        ready = threading.Event()

        def gen():
            ready.wait(2.0)  # let the test set the active bridge first
            tools_mod.console.print("tool panel")
            yield LLMResponse(content="after")

        adapter = ThreadedStream(gen(), on_console=lambda stderr, a, k: printed.append((stderr, a, k)))
        set_active_bridge(adapter)
        ready.set()
        try:
            routing.main.real.print.assert_not_called()
            assert next(adapter).content == "after"
        finally:
            adapter.close()
            routing.restore()
        assert printed == [(False, ("tool panel",), {})]

    def test_worker_console_after_restore_uses_real(self):
        real_main = MagicMock()
        routing = install_worker_console_routing(real_main, MagicMock())
        routing.restore()
        # A late worker call through the (now restored) real console path is
        # outside the routed window; the real console receives it.
        run_in_thread(lambda: routing.main.print("late"))
        real_main.print.assert_called_once_with("late")


class TestTiming:
    def test_worker_print_waits_for_ui_thread(self):
        """Routing must not block the worker on terminal writes."""
        real = MagicMock()
        console = WorkerConsole(real)
        adapter = MagicMock()
        adapter.dead = False
        set_active_bridge(adapter)

        started = time.time()
        run_in_thread(lambda: [console.print(f"line {i}") for i in range(50)])
        elapsed = time.time() - started

        assert elapsed < 1.0
        assert adapter.put_console.call_count == 50
        real.print.assert_not_called()


class TestAbandonedWorker:
    def test_abandoned_worker_output_is_dropped_even_with_new_active_bridge(self):
        """A worker left behind by an aborted turn cannot leak into a newer stream."""
        real_main = MagicMock()
        routing = install_worker_console_routing(real_main, MagicMock())
        release = threading.Event()
        finished = threading.Event()

        def gen():
            try:
                release.wait(2.0)
                tools_mod.console.print("late tool output", style="red")
                yield LLMResponse(content="late")
            finally:
                finished.set()

        adapter = ThreadedStream(gen())
        set_active_bridge(adapter)
        adapter.start()
        try:
            assert adapter.close(timeout=0.05) is True  # blocked worker -> abandoned
            # Simulate the next generation having its own active bridge.
            newer = MagicMock()
            newer.dead = False
            set_active_bridge(newer)
            release.set()
            assert finished.wait(2.0) is True
            deadline = time.time() + 2.0
            while adapter.alive and time.time() < deadline:
                time.sleep(0.01)
            assert adapter.alive is False
            real_main.print.assert_not_called()
            newer.put_console.assert_not_called()
        finally:
            routing.restore()
            clear_active_bridge()
