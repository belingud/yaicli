"""Independent acceptance tests for K23 persistent plan mode (v0.24).

These tests are derived from ``.trellis/tasks/11-14-k23-plan-mode/implement.md``
and ``prd.md`` acceptance criteria — not from the owners' unit tests — and they
exercise the real ``plan_mode`` / ``plan_store`` / ``plan_shell`` / ``tools`` /
CLI modules together. Only external boundaries are mocked: the LLM client, the
editor/prompt, subprocess execution and the terminal console.

Coverage map:

* AC①  zero-write plan mode: schema allowlist / execution append / restore,
       MCP hidden, ``PLAN_ALLOW_READONLY_SHELL=false`` removes the shell;
* AC③  ``submit_plan`` is the only planning exit + structured validation errors;
* AC⑤  todo 1:1 with the current revision, single in_progress, blocked reason,
       checkbox write-back, model-facing dispatch through ``execute_tool_call``;
* AC⑥  plans live under ``PLAN_DIR/<project-key>/`` (0600/0700, outside the
       repo), terminal plans pruned to ``PLAN_KEEP=80`` per project only;
* AC⑦  revision 2 is in-place (no new file), preserves completed todos, records
       removed ids in the diff and writes ``plan.*`` audit lines;
* AC⑨  headless ``--plan``: JSON ``plan``/``plan_path``/``revision`` + exit 0,
       no submission → exit 1 ``plan_not_submitted``, ``--plan --shell`` exit 2,
       text/stream-json output, normal JSON contract unchanged without ``--plan``;
* AC⑩  controlled read-only shell: metachar rejection is in-band + REPL line +
       audit and never spawns a process; allowed commands go through
       ``plan_shell.run_plan_shell``;
* AC⑪  the full lifecycle leaves the project directory untouched.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

import yaicli.const as const
from yaicli import plan_mode, plan_shell, plan_store, tools
from yaicli.config import cfg
from yaicli.entry import app
from yaicli.schemas import LLMResponse, ToolCall

REPO_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()

#: Builtin tools that mutate files and therefore must never be offered in plan mode.
WRITE_EXEC_TOOLS = frozenset({"fs_write_file", "fs_edit_file", "fs_file_operations"})
PLAN_SESSION_ID = "acceptance-session"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def schema_names(schemas):
    """Extract tool names from OpenAI (``function.name``) or Anthropic (``name``) schemas."""
    names = []
    for schema in schemas:
        if not isinstance(schema, dict):
            names.append("")
            continue
        function = schema.get("function")
        name = function.get("name") if isinstance(function, dict) else schema.get("name")
        names.append(str(name or ""))
    return names


def plan_payload(*, goal="Add a pluggable token estimator", steps=None, **extra):
    """A valid first-submission ``submit_plan`` payload."""
    payload = {
        "goal": goal,
        "assumptions": ["No provider API changes"],
        "steps": steps
        if steps is not None
        else [
            {
                "title": "Extract TokenEstimator protocol",
                "acceptance": "Existing token tests pass",
                "detail": "Keep the heuristic default",
            },
            {"title": "Delegate estimate_* calls", "acceptance": "Behavior unchanged"},
            {"title": "Add estimator tests", "acceptance": "New tests pass"},
        ],
        "risks": ["Token counts may drift"],
        "not_doing": ["No new providers"],
    }
    payload.update(extra)
    return payload


def step_titles(steps_payload):
    return [str(step.get("title", "")) for step in steps_payload]


def audit_events(plan_env):
    """All ``plan.*`` (or any) audit event names written to the patched audit path."""
    if not plan_env.audit_path.exists():
        return []
    events = []
    for line in plan_env.audit_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(str(json.loads(line).get("event", "")))
    return events


def parse_single_json(stdout):
    """Parse stdout that must contain exactly one JSON document (headless contract)."""
    documents = [line for line in stdout.splitlines() if line.strip()]
    assert len(documents) == 1, f"expected exactly one JSON document on stdout, got {len(documents)}: {stdout!r}"
    return json.loads(documents[0])


def parse_ndjson(stdout):
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def expected_plan_dir(plan_env):
    return plan_env.plans_root / plan_store.project_key(plan_env.cwd)


def write_seed_plan(directory, plan_id, status, updated, *, goal="seed plan"):
    """Write a hand-built plan file with a controlled ``updated`` timestamp."""
    directory.mkdir(parents=True, exist_ok=True)
    plan = plan_store.Plan(
        id=plan_id,
        goal=goal,
        steps=[plan_store.PlanStep(id="S1", title="seed step", acceptance="seed acceptance")],
        status=status,
        revision=1,
        session_id=PLAN_SESSION_ID,
        created=updated,
        updated=updated,
        cwd=str(directory.parent),
        path=directory / f"{plan_id}.md",
    )
    (directory / f"{plan_id}.md").write_text(plan.to_markdown(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def plan_env(tmp_path, monkeypatch):
    """Isolated plans root / project cwd / audit log + a configured PlanSession."""
    plans_root = tmp_path / "plans"
    cwd = tmp_path / "project"
    cwd.mkdir()
    audit_path = tmp_path / "audit" / "tool_audit.jsonl"
    monkeypatch.setitem(cfg, "PLAN_DIR", str(plans_root))
    monkeypatch.setitem(cfg, "PLAN_ENABLED", True)
    monkeypatch.setitem(cfg, "PLAN_MAX_STEPS", 20)
    monkeypatch.setitem(cfg, "PLAN_KEEP", 80)
    monkeypatch.setitem(cfg, "PLAN_ALLOW_READONLY_SHELL", True)
    monkeypatch.setitem(cfg, "ENABLED_TOOLS", "")
    monkeypatch.setitem(cfg, "TOOL_AUDIT", True)
    monkeypatch.setattr(const, "TOOL_AUDIT_PATH", audit_path)

    session = plan_mode.get_plan_session()
    session.configure(
        plans_root=plans_root,
        cwd=cwd,
        model="gpt-5.2",
        session_id=PLAN_SESSION_ID,
        max_steps=20,
        keep=80,
        allow_readonly_shell=True,
    )
    return SimpleNamespace(
        plans_root=plans_root.resolve(),
        raw_plans_root=plans_root,
        cwd=cwd,
        audit_path=audit_path,
        session=session,
    )


class _FakeClient:
    """Minimal LLM client stand-in (only the boundary is faked)."""

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.plan_session = None
        self.console = None
        self.interactive = False
        self.depth_limit_reached = False
        self.tool_denied = False

    def completion_with_tools(self, messages, stream=None, tool_policy=None):
        raise NotImplementedError


class _SubmittingPlanClient(_FakeClient):
    """Fake provider turn: submits a plan through the real session-tool handler."""

    def completion_with_tools(self, messages, stream=None, tool_policy=None):
        self.submitted = plan_mode.handle_submit_plan(plan_payload())
        yield LLMResponse(content="Plan submitted for approval.", finish_reason="stop")


class _NoSubmitClient(_FakeClient):
    """Fake provider turn that explores but never calls submit_plan."""

    def completion_with_tools(self, messages, stream=None, tool_policy=None):
        yield LLMResponse(content="I explored the task but stopped there.", finish_reason="stop")


# ---------------------------------------------------------------------------
# AC① — plan mode is read-only at the schema level
# ---------------------------------------------------------------------------
class TestAC1SchemaZeroWrite:
    def test_plan_mode_offers_only_the_read_only_allowlist(self, plan_env):
        baseline = set(schema_names(tools.get_openai_schemas()))
        assert {"fs_write_file", "fs_edit_file", "fs_file_operations", "execute_shell_command"} <= baseline

        tools.set_plan_tool_mode("plan")
        plan_openai = schema_names(tools.get_openai_schemas())

        expected = set(plan_mode.plan_tool_allowlist(allow_readonly_shell=True))
        assert set(plan_openai) == expected
        assert "submit_plan" in plan_openai
        assert WRITE_EXEC_TOOLS.isdisjoint(plan_openai)
        assert not any(name.startswith("_mcp__") for name in plan_openai)
        # Anthropic schema generation follows the same mode filter.
        assert set(schema_names(tools.get_anthropic_schemas())) == expected

        # MCP tools are not even discovered while planning (no server connection).
        with patch("yaicli.tools.get_mcp_manager") as manager:
            assert tools.get_openai_mcp_tools() == []
            assert tools.get_anthropic_mcp_tools() == []
            manager.assert_not_called()

    def test_execution_mode_adds_todo_write_only(self, plan_env):
        baseline = set(schema_names(tools.get_openai_schemas()))

        tools.set_plan_tool_mode("execution")
        execution_openai = set(schema_names(tools.get_openai_schemas()))

        assert execution_openai == baseline | {"todo_write"}
        assert "todo_write" in schema_names(tools.get_anthropic_schemas())
        assert WRITE_EXEC_TOOLS <= execution_openai

    def test_mode_none_restores_the_full_baseline(self, plan_env):
        baseline = schema_names(tools.get_openai_schemas())
        assert len(baseline) >= 12

        tools.set_plan_tool_mode("plan")
        assert set(schema_names(tools.get_openai_schemas())) != set(baseline)

        tools.set_plan_tool_mode(None)
        restored = schema_names(tools.get_openai_schemas())
        assert set(restored) == set(baseline)
        assert {"fs_write_file", "fs_edit_file", "fs_file_operations", "execute_shell_command"} <= set(restored)

    def test_disabling_the_read_only_shell_hides_it(self, plan_env, monkeypatch):
        monkeypatch.setitem(cfg, "PLAN_ALLOW_READONLY_SHELL", False)
        tools.set_plan_tool_mode("plan")

        names = set(schema_names(tools.get_openai_schemas()))
        assert "execute_shell_command" not in names
        assert "submit_plan" in names
        assert WRITE_EXEC_TOOLS.isdisjoint(names)

        # Flipping the switch back (same mode) refreshes the mode cache key.
        monkeypatch.setitem(cfg, "PLAN_ALLOW_READONLY_SHELL", True)
        tools.set_plan_tool_mode("plan")
        assert "execute_shell_command" in set(schema_names(tools.get_openai_schemas()))


# ---------------------------------------------------------------------------
# AC③ — submit_plan is the only exit and validates structurally
# ---------------------------------------------------------------------------
class TestAC3SubmitPlanValidation:
    def test_invalid_plans_return_structured_errors(self, plan_env):
        session = plan_env.session
        session.enter_researching()

        invalid_payloads = [
            plan_payload(goal=""),
            plan_payload(steps=[]),
            plan_payload(steps=[{"title": "no acceptance"}]),
            plan_payload(steps=[{"acceptance": "no title"}]),
            plan_payload(steps=[{"title": f"step {index}", "acceptance": "ok"} for index in range(25)]),
            plan_payload(goal="x" * 501),
        ]
        for payload in invalid_payloads:
            result = plan_mode.handle_submit_plan(payload)
            assert result.get("success") is not True, payload
            assert result["error"] == "invalid_plan"
            assert result["reason"]
            assert session.mode == "researching"
        # Nothing was written for rejected plans.
        assert list(plan_env.plans_root.rglob("*.md")) == []

    def test_second_submit_while_reviewing_is_rejected(self, plan_env):
        session = plan_env.session
        session.enter_researching()
        first = plan_mode.handle_submit_plan(plan_payload())
        assert first["success"] is True
        assert session.mode == "reviewing"

        second = plan_mode.handle_submit_plan(plan_payload(goal="A different plan"))
        assert second["success"] is False
        assert second["error"] == "plan_already_submitted"


# ---------------------------------------------------------------------------
# AC⑤/⑥ — persistent store, todo 1:1 and checkbox write-back
# ---------------------------------------------------------------------------
class TestAC5StoreAndTodos:
    def test_submit_plan_writes_a_private_plan_outside_the_repo(self, plan_env):
        session = plan_env.session
        session.enter_researching()
        result = plan_mode.handle_submit_plan(plan_payload())

        assert result["success"] is True
        assert result["steps"] == 3
        path = Path(result["path"])
        assert path.is_file()
        assert path.suffix == ".md"
        resolved = path.resolve()
        assert plan_env.plans_root in resolved.parents
        assert resolved.parent == expected_plan_dir(plan_env)
        assert REPO_ROOT not in resolved.parents
        assert session.mode == "reviewing"
        assert session.draft_plan is not None and session.draft_plan.id == path.stem
        if os.name == "posix":
            assert (resolved.stat().st_mode & 0o777) == 0o600
            assert (resolved.parent.stat().st_mode & 0o777) == 0o700

        stored = plan_store.read_plan(path)
        assert stored.status == "draft"
        assert stored.revision == 1
        assert stored.goal == "Add a pluggable token estimator"
        assert stored.step_ids() == ["S1", "S2", "S3"]

    def test_todo_write_requires_a_1_to_1_state_and_writes_checkboxes(self, plan_env):
        session = plan_env.session
        session.enter_researching()
        submitted = plan_mode.handle_submit_plan(plan_payload())
        path = Path(submitted["path"])
        titles = step_titles(plan_payload()["steps"])
        approved = plan_mode.approve_new_plan(session)
        assert approved["success"] is True
        assert session.mode == "executing"
        assert [(todo.id, todo.status) for todo in session.todos] == [
            ("S1", "in_progress"),
            ("S2", "pending"),
            ("S3", "pending"),
        ]

        def items(**overrides):
            base = [
                {"id": "S1", "content": titles[0], "status": "completed"},
                {"id": "S2", "content": titles[1], "status": "in_progress"},
                {"id": "S3", "content": titles[2], "status": "pending"},
            ]
            for index, value in overrides.items():
                base[int(index[1:]) - 1] = value
            return {"items": base}

        # Rejections: missing/extra step, changed content, two in_progress, blocked
        # without a reason — the todo list must stay 1:1 with the current revision.
        rejected = [
            {"items": [{"id": "S1", "content": titles[0], "status": "in_progress"}]},
            {"items": items()["items"] + [{"id": "S4", "content": "extra", "status": "pending"}]},
            items(s2={"id": "S2", "content": "totally different", "status": "pending"}),
            items(s1={"id": "S1", "content": titles[0], "status": "in_progress"}),
            items(s1={"id": "S1", "content": titles[0], "status": "blocked"}),
        ]
        for payload in rejected:
            result = plan_mode.handle_todo_write(payload)
            assert result.get("success") is not True, payload
            assert result["error"] == "invalid_todo"

        blocked = plan_mode.handle_todo_write(
            items(s2={"id": "S2", "content": titles[1], "status": "blocked", "reason": "waiting on API"})
        )
        assert blocked["success"] is True
        assert blocked["blocked"] == 1
        markdown = path.read_text(encoding="utf-8")
        assert "- [x] **S1**" in markdown
        assert "- [ ] **S2**" in markdown
        assert "(blocked: waiting on API)" in markdown

    def test_submit_plan_and_todo_write_work_through_tool_dispatch(self, plan_env):
        """The model-facing path: the client calls execute_tool_call for session tools."""
        session = plan_env.session
        session.enter_researching()
        tools.set_plan_tool_mode("plan")
        with patch.object(tools, "console", MagicMock()):
            result, ok = tools.execute_tool_call(
                ToolCall(id="call_submit", name="submit_plan", arguments=json.dumps(plan_payload())),
                announce=False,
            )
        payload = json.loads(result)
        assert ok is True, result
        assert payload["success"] is True, result
        path = Path(payload["path"])
        assert path.is_file()
        assert plan_store.read_plan(path).step_ids() == ["S1", "S2", "S3"]

        plan_mode.approve_new_plan(session)
        tools.set_plan_tool_mode("execution")
        titles = step_titles(plan_payload()["steps"])
        todo_payload = {
            "items": [
                {"id": "S1", "content": titles[0], "status": "completed"},
                {"id": "S2", "content": titles[1], "status": "in_progress"},
                {"id": "S3", "content": titles[2], "status": "pending"},
            ]
        }
        with patch.object(tools, "console", MagicMock()):
            result, ok = tools.execute_tool_call(
                ToolCall(id="call_todo", name="todo_write", arguments=json.dumps(todo_payload)),
                announce=False,
            )
        payload = json.loads(result)
        assert ok is True, result
        assert payload["success"] is True, result
        assert "- [x] **S1**" in path.read_text(encoding="utf-8")

    def test_prune_keeps_the_newest_80_terminal_plans_per_project(self, plan_env):
        directory = expected_plan_dir(plan_env)
        for index in range(1, 83):
            write_seed_plan(
                directory, f"seed-done-{index:03d}", "done", f"2026-11-14T{index // 60:02d}:{index % 60:02d}:00+08:00"
            )
        write_seed_plan(directory, "seed-draft", "draft", "2026-01-01T00:00:00+08:00")
        write_seed_plan(directory, "seed-active", "in-progress", "2026-01-02T00:00:00+08:00")
        # A second project must not be pruned by this project's cleanup.
        other_project = plan_env.plans_root / "another-project"
        for index in range(1, 4):
            write_seed_plan(other_project, f"other-done-{index}", "done", f"2026-11-14T00:0{index}:00+08:00")

        plan_env.session.enter_researching()
        submitted = plan_mode.handle_submit_plan(plan_payload())
        assert submitted["success"] is True

        stored = plan_store.list_plans(plan_env.raw_plans_root, plan_dir_key(plan_env))
        terminal = [plan for plan in stored if plan.status in plan_store.PLAN_TERMINAL_STATUSES]
        assert len(terminal) == 80
        assert {plan.id for plan in stored} >= {"seed-draft", "seed-active"}
        remaining_ids = {plan.id for plan in stored}
        assert "seed-done-001" not in remaining_ids
        assert "seed-done-002" not in remaining_ids
        assert "seed-done-082" in remaining_ids
        # The freshly submitted draft is also present.
        assert Path(submitted["path"]).is_file()
        # Another project's plans are untouched.
        other = plan_store.list_plans(plan_env.raw_plans_root, "another-project")
        assert {plan.id for plan in other} == {"other-done-1", "other-done-2", "other-done-3"}


def plan_dir_key(plan_env):
    """Project-key directory name used by the configured session."""
    return plan_store.project_key(plan_env.cwd)


# ---------------------------------------------------------------------------
# AC⑦ — in-place revision with preserved todo state and audit trail
# ---------------------------------------------------------------------------
class TestAC7Revision:
    def test_revision_updates_in_place_and_preserves_completed_todos(self, plan_env):
        session = plan_env.session
        session.enter_researching()
        first = plan_mode.handle_submit_plan(plan_payload())
        path = Path(first["path"])
        assert first["success"] is True
        titles = step_titles(plan_payload()["steps"])
        plan_mode.approve_new_plan(session)
        plan_mode.handle_todo_write(
            {
                "items": [
                    {"id": "S1", "content": titles[0], "status": "completed"},
                    {"id": "S2", "content": titles[1], "status": "in_progress"},
                    {"id": "S3", "content": titles[2], "status": "pending"},
                ]
            }
        )
        plan_dir = path.parent
        files_before = set(plan_dir.glob("*.md"))

        session.enter_revising()
        assert session.mode == "revising"
        revision = plan_mode.handle_submit_plan(
            {
                "goal": "Add a pluggable token estimator",
                "assumptions": ["No provider API changes"],
                "steps": [
                    {
                        "id": "S1",
                        "title": titles[0],
                        "detail": "Keep the heuristic default",
                        "acceptance": "Existing token tests pass",
                    },
                    {"id": "S2", "title": "Delegate estimate_* calls (updated)", "acceptance": "Behavior unchanged"},
                    {"id": "S4", "title": "Support provider-level estimator overrides", "acceptance": "Override tests"},
                ],
                "risks": ["Token counts may drift"],
                "not_doing": ["No new providers"],
                "revision": 2,
                "change_summary": "drop S3, add S4",
            }
        )
        assert revision["success"] is True
        assert revision["revision"] == 2
        assert revision["path"] == str(path)
        diff = revision["revision_diff"]
        assert diff["summary"] == "Changes: +1 step  ~1 step  -1 steps"
        assert [step["id"] for step in diff["removed"]] == ["S3"]
        assert [step["id"] for step in diff["added"]] == ["S4"]
        # A revision is staged in memory: no new plan file is written yet.
        assert set(plan_dir.glob("*.md")) == files_before

        applied = plan_mode.apply_revision(session)
        assert applied["success"] is True
        assert applied["path"] == str(path)
        assert set(plan_dir.glob("*.md")) == files_before  # same single file, in place
        stored = plan_store.read_plan(path)
        assert stored.revision == 2
        assert stored.step_ids() == ["S1", "S2", "S4"]
        assert stored.change_summary == "drop S3, add S4"
        assert stored.status == "in-progress"
        # Todo rebuild: completed S1 preserved, S2 in progress preserved, S4 pending.
        assert [(todo.id, todo.status) for todo in session.todos] == [
            ("S1", "completed"),
            ("S2", "in_progress"),
            ("S4", "pending"),
        ]
        assert session.mode == "executing"

        events = audit_events(plan_env)
        assert "plan.submit" in events
        assert "plan.approve" in events
        assert "plan.revise_submit" in events
        assert "plan.revise_apply" in events


# ---------------------------------------------------------------------------
# AC⑨ — headless `--plan`
# ---------------------------------------------------------------------------
class TestAC9HeadlessPlan:
    def _invoke(self, args, client_cls):
        with patch("yaicli.cli.LLMClient", client_cls):
            return runner.invoke(app, args)

    def test_json_submitted_plan_and_exit_zero(self, plan_env, monkeypatch):
        monkeypatch.chdir(plan_env.cwd)
        result = self._invoke(
            ["-p", "Add a pluggable token estimator", "--plan", "--output-format", "json"], _SubmittingPlanClient
        )

        assert result.exit_code == 0, result.stderr
        payload = parse_single_json(result.stdout)
        assert payload["plan"]["goal"] == "Add a pluggable token estimator"
        assert payload["plan"]["status"] == "draft"
        assert payload["plan"]["revision"] == 1
        assert payload["revision"] == 1
        assert payload["plan_path"] == payload["plan"]["path"]
        plan_path = Path(payload["plan_path"])
        assert plan_path.is_file()
        assert plan_env.plans_root in plan_path.resolve().parents
        assert plan_store.read_plan(plan_path).status == "draft"
        # Nothing was executed: no tools ran and no write/exec tool result exists.
        assert payload["tool_calls"] == []
        assert payload["error"] is None
        # The plan is saved as draft and the run never approves/executes it.
        assert plan_mode.get_plan_session().mode == "normal"

    def test_not_submitted_exits_one_with_plan_not_submitted(self, plan_env, monkeypatch):
        monkeypatch.chdir(plan_env.cwd)
        result = self._invoke(
            ["-p", "Add a pluggable token estimator", "--plan", "--output-format", "json"], _NoSubmitClient
        )

        assert result.exit_code == 1, result.stderr
        payload = parse_single_json(result.stdout)
        assert payload["error"]["kind"] == "plan_not_submitted"
        assert payload["plan"] is None
        assert payload["plan_path"] is None
        assert list(plan_env.plans_root.rglob("*.md")) == []

    def test_text_output_prints_the_plan_markdown(self, plan_env, monkeypatch):
        monkeypatch.chdir(plan_env.cwd)
        result = self._invoke(["-p", "Add a pluggable token estimator", "--plan"], _SubmittingPlanClient)

        assert result.exit_code == 0, result.stderr
        assert "## Steps" in result.stdout
        assert "Extract TokenEstimator protocol" in result.stdout
        assert "# Plan: Add a pluggable token estimator" in result.stdout

    def test_stream_json_emits_plan_events(self, plan_env, monkeypatch):
        monkeypatch.chdir(plan_env.cwd)
        result = self._invoke(
            ["-p", "Add a pluggable token estimator", "--plan", "--output-format", "stream-json"],
            _SubmittingPlanClient,
        )

        assert result.exit_code == 0, result.stderr
        events = parse_ndjson(result.stdout)
        types = [event.get("type") for event in events]
        assert types.count("plan_start") == 1
        assert types.count("plan_ready") == 1
        ready = [event for event in events if event.get("type") == "plan_ready"][0]
        assert ready["steps"] == 3
        assert ready["revision"] == 1
        assert Path(ready["path"]).is_file()
        assert types.count("done") == 1

    def test_plan_conflicts_with_shell_exit_two(self, plan_env, monkeypatch):
        monkeypatch.chdir(plan_env.cwd)
        result = runner.invoke(app, ["-p", "x", "--plan", "--shell"])

        assert result.exit_code == 2
        assert "--plan cannot be combined with --shell/--code" in result.stderr
        assert list(plan_env.plans_root.rglob("*.md")) == []

    def test_plan_requires_plan_enabled(self, plan_env, monkeypatch):
        monkeypatch.chdir(plan_env.cwd)
        monkeypatch.setitem(cfg, "PLAN_ENABLED", False)
        result = runner.invoke(app, ["-p", "x", "--plan"])

        assert result.exit_code == 2
        assert "PLAN_ENABLED=true" in result.stderr

    def test_normal_json_contract_unchanged_without_plan(self, plan_env, monkeypatch):
        monkeypatch.chdir(plan_env.cwd)

        result = self._invoke(["-p", "hello", "--output-format", "json"], _NoSubmitClient)

        assert result.exit_code == 0, result.stderr
        payload = parse_single_json(result.stdout)
        assert "plan" not in payload
        assert "plan_path" not in payload
        assert "revision" not in payload
        assert set(payload) == {
            "content",
            "tool_calls",
            "usage",
            "finish_reason",
            "model",
            "provider",
            "error",
            "exit_code",
        }


# ---------------------------------------------------------------------------
# AC⑩ — controlled read-only shell in plan mode
# ---------------------------------------------------------------------------
class TestAC10PlanShell:
    def test_denied_command_is_in_band_and_never_runs(self, plan_env):
        session = plan_env.session
        session.enter_researching()
        tools.set_plan_tool_mode("plan")
        console = MagicMock()
        with (
            patch.object(tools, "console", console),
            patch.object(plan_shell, "run_plan_shell") as run_shell,
            patch.object(plan_shell.subprocess, "Popen") as popen,
        ):
            result, ok = tools.execute_tool_call(
                ToolCall(
                    id="call_denied",
                    name="execute_shell_command",
                    arguments='{"command": "git status | head -5"}',
                ),
                announce=False,
            )

        payload = json.loads(result)
        assert ok is True
        assert payload["error"] == "plan_shell_denied"
        assert "metacharacters are not allowed in plan mode" in payload["reason"]
        assert payload["hint"]
        run_shell.assert_not_called()
        popen.assert_not_called()
        printed = " ".join(str(call.args[0]) for call in console.print.call_args_list if call.args)
        assert "✗ plan_shell_denied" in printed
        events = audit_events(plan_env)
        assert "plan.shell_denied" in events

    def test_allowed_command_goes_through_plan_shell(self, plan_env):
        session = plan_env.session
        session.enter_researching()
        tools.set_plan_tool_mode("plan")
        console = MagicMock()
        with (
            patch.object(tools, "console", console),
            patch.object(
                plan_shell,
                "run_plan_shell",
                return_value="Exit code: 0, Output:\nworking tree clean\n",
            ) as run_shell,
        ):
            result, ok = tools.execute_tool_call(
                ToolCall(id="call_ok", name="execute_shell_command", arguments='{"command": "git status"}'),
                announce=False,
            )

        assert ok is True
        assert result == "Exit code: 0, Output:\nworking tree clean\n"
        run_shell.assert_called_once_with(("git", "status"), cwd=None, timeout=None)
        assert "plan.shell" in audit_events(plan_env)

    def test_read_only_shell_is_hidden_when_disabled(self, plan_env, monkeypatch):
        monkeypatch.setitem(cfg, "PLAN_ALLOW_READONLY_SHELL", False)
        tools.set_plan_tool_mode("plan")

        names = set(schema_names(tools.get_openai_schemas()))
        assert "execute_shell_command" not in names
        assert "submit_plan" in names
        assert "execute_shell_command" not in set(schema_names(tools.get_anthropic_schemas()))
        # The model is not offered the shell; the client gate rejects a hard-sent call
        # in-band (EXECUTION gate tests live in test_plan_shell_gate.py).


# ---------------------------------------------------------------------------
# AC⑪ — the project directory stays clean through the full lifecycle
# ---------------------------------------------------------------------------
class TestAC11NoProjectPollution:
    def test_full_lifecycle_writes_plans_only_under_the_plans_root(self, plan_env):
        session = plan_env.session
        before = set(os.listdir(plan_env.cwd))

        session.enter_researching()
        submitted = plan_mode.handle_submit_plan(plan_payload())
        plan_mode.approve_new_plan(session)
        titles = step_titles(plan_payload()["steps"])
        plan_mode.handle_todo_write(
            {
                "items": [
                    {"id": "S1", "content": titles[0], "status": "completed"},
                    {"id": "S2", "content": titles[1], "status": "completed"},
                    {"id": "S3", "content": titles[2], "status": "completed"},
                ]
            }
        )
        finished = plan_mode.finish_plan(session)
        assert finished["success"] is True
        assert plan_mode.get_plan_session().mode == "normal"

        assert set(os.listdir(plan_env.cwd)) == before
        assert not any(Path(plan_env.cwd).rglob("*.md"))
        plan_files = list(plan_env.plans_root.rglob("*.md"))
        assert len(plan_files) == 1
        assert plan_files[0].resolve() == Path(submitted["path"]).resolve()
        assert plan_store.read_plan(plan_files[0]).status == "done"
