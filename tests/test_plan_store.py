"""Tests for the persistent plan store (v0.24 K23).

All filesystem work happens under ``tmp_path``; the real ``~/.config/yaicli`` is
never read or written. Timestamps are injected where the contract allows it so
ordering assertions stay deterministic.
"""

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yaicli import plan_store
from yaicli.chat import Chat
from yaicli.const import DEFAULT_CONFIG_MAP, DEFAULT_CONFIG_INI
from yaicli.plan_store import (
    PLAN_STATUS_ABORTED,
    PLAN_STATUS_DONE,
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_IN_PROGRESS,
    Plan,
    PlanStep,
    PlanStoreError,
    clear_plans,
    find_latest_unfinished,
    find_plan,
    git_rev,
    list_plans,
    new_plan_path,
    plans_root,
    project_key,
    project_plan_dir,
    prune_plans,
    read_plan,
    shorten_path,
    slugify_goal,
    update_plan_status,
    write_plan,
)

CREATED = "2026-11-14T00:42:30+08:00"
UPDATED = "2026-11-14T01:10:05+08:00"


def make_plan(
    plan_id: str = "20261114-004230-token-estimator",
    *,
    goal: str = "Add a pluggable token estimator",
    status: str = PLAN_STATUS_DRAFT,
    revision: int = 1,
    session_id: str = "session-abc",
    updated: str = UPDATED,
    created: str = CREATED,
    steps=None,
    **overrides,
) -> Plan:
    """Build a deterministic plan; overrides replace any Plan field."""
    plan = Plan(
        id=plan_id,
        goal=goal,
        steps=steps
        if steps is not None
        else [
            PlanStep(
                id="S1",
                title="Extract a TokenEstimator protocol",
                detail="Keep the heuristic default",
                acceptance="existing token tests keep passing",
            ),
            PlanStep(id="S2", title="Delegate estimate_* to the estimator"),
        ],
        assumptions=["No provider API changes"],
        risks=["Token counts may drift slightly"],
        not_doing=["No new provider support"],
        status=status,
        revision=revision,
        session_id=session_id,
        created=created,
        updated=updated,
        cwd="/repo",
        project_key=project_key(Path("/repo")),
        model="gpt-5.2",
        base_rev="c51f7a3",
        approved_at="2026-11-14T00:45:00+08:00",
        change_summary="Support per-provider estimator overrides",
    )
    for key, value in overrides.items():
        setattr(plan, key, value)
    return plan


def write_markdown_plan(plan: Plan, directory: Path) -> Path:
    """Write a plan file directly (keeps the plan's own ``updated`` timestamp)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{plan.id}.md"
    path.write_text(plan.to_markdown(), encoding="utf-8")
    return path


class TestMarkdownFormat:
    def test_to_markdown_writes_the_documented_format(self):
        plan = make_plan()
        markdown = plan.to_markdown()

        assert markdown.startswith("---\nid: 20261114-004230-token-estimator\n")
        assert "status: draft\n" in markdown
        assert "revision: 1\n" in markdown
        assert f"session_id: {plan.session_id}\n" in markdown
        assert f"created: {CREATED}\n" in markdown
        assert f"updated: {UPDATED}\n" in markdown
        assert "change_summary: Support per-provider estimator overrides\n" in markdown
        assert "\n---\n\n# Plan: Add a pluggable token estimator\n" in markdown
        assert "\n## Goal\nAdd a pluggable token estimator\n" in markdown
        assert "\n## Assumptions\n- No provider API changes\n" in markdown
        assert "\n## Steps\n- [ ] **S1** Extract a TokenEstimator protocol\n" in markdown
        assert "  - acceptance: existing token tests keep passing\n" in markdown
        assert "  - detail: Keep the heuristic default\n" in markdown
        assert "- [ ] **S2** Delegate estimate_* to the estimator\n" in markdown
        assert "\n## Risks\n- Token counts may drift slightly\n" in markdown
        assert "\n## Not doing\n- No new provider support\n" in markdown

    def test_roundtrip_preserves_every_parseable_field(self):
        plan = make_plan()
        restored = Plan.from_markdown(plan.to_markdown())

        assert restored.id == plan.id
        assert restored.goal == plan.goal
        assert restored.assumptions == plan.assumptions
        assert restored.risks == plan.risks
        assert restored.not_doing == plan.not_doing
        assert restored.status == plan.status
        assert restored.revision == plan.revision
        assert restored.session_id == plan.session_id
        assert restored.created == plan.created
        assert restored.updated == plan.updated
        assert restored.cwd == plan.cwd
        assert restored.project_key == plan.project_key
        assert restored.model == plan.model
        assert restored.base_rev == plan.base_rev
        assert restored.approved_at == plan.approved_at
        assert restored.change_summary == plan.change_summary
        assert [step.to_dict() for step in restored.steps] == [step.to_dict() for step in plan.steps]
        assert restored.path is None

    def test_roundtrip_empty_optional_sections_and_change_summary(self):
        plan = make_plan(
            assumptions=[],
            risks=[],
            not_doing=[],
            change_summary="",
            approved_at="",
        )
        markdown = plan.to_markdown()
        restored = Plan.from_markdown(markdown)

        assert "change_summary" not in markdown
        assert restored.assumptions == []
        assert restored.risks == []
        assert restored.not_doing == []
        assert restored.change_summary == ""
        assert restored.approved_at == ""
        assert restored.goal == plan.goal
        assert [step.id for step in restored.steps] == ["S1", "S2"]

    def test_multiline_detail_and_acceptance_are_folded_to_one_line(self):
        plan = make_plan(
            steps=[
                PlanStep(
                    id="S1",
                    title="Line one\nline two",
                    detail="first line\nsecond line",
                    acceptance="accept one\naccept two",
                )
            ]
        )
        markdown = plan.to_markdown()
        restored = Plan.from_markdown(markdown)

        assert "first line second line" in markdown
        assert "accept one accept two" in markdown
        assert restored.steps[0].title == "Line one line two"
        assert restored.steps[0].detail == "first line second line"
        assert restored.steps[0].acceptance == "accept one accept two"

    def test_from_markdown_ignores_check_state_and_blocked_suffix(self):
        markdown = """---
id: plan-1
status: in-progress
revision: 2
---

# Plan: Do the thing

## Goal
Do the thing

## Steps
- [x] **S1** First step (blocked: waiting on API)
- [ ] **S2** Second step
  - acceptance: works
"""
        plan = Plan.from_markdown(markdown)

        assert [step.id for step in plan.steps] == ["S1", "S2"]
        assert plan.steps[0].title == "First step"
        assert plan.steps[1].title == "Second step"
        assert plan.steps[1].acceptance == "works"

    def test_from_markdown_accepts_path_argument(self):
        plan = make_plan()
        path = Path("/tmp/whatever.md")
        restored = Plan.from_markdown(plan.to_markdown(), path=path)
        assert restored.path == path

    @pytest.mark.parametrize(
        "text",
        [
            "no frontmatter at all",
            "---\nid: p1\n---\n\n# Plan: goal\n\n## Plan steps\nnone\n",
            "---\nstatus: draft\n---\n\n# Plan: goal\n\n## Steps\n- [ ] **S1** x\n",
            "---\nid: p1\nstatus: watching\n---\n\n# Plan: goal\n\n## Steps\n- [ ] **S1** x\n",
            "---\nid: p1\nrevision: two\n---\n\n# Plan: goal\n\n## Steps\n- [ ] **S1** x\n",
            "---\nid: p1\nbogus line without colon\n---\n\n## Steps\n- [ ] **S1** x\n",
            "---\nid: p1\n---\n\n## Goal\n\n## Steps\n- [ ] **S1** x\n",
            "---\nid: p1\n---\n\n## Goal\ngoal\n\n## Steps\nno steps here\n",
            "---\nid: p1\n---\n\n## Goal\ngoal\n\n## Steps\n- [ ] **S1** \n",
            "---\nid: p1\n---\n\n## Goal\ngoal\n\n## Steps\n- [ ] **S1** a\n- [ ] **S1** b\n",
        ],
    )
    def test_from_markdown_rejects_corrupt_plans(self, text):
        with pytest.raises(PlanStoreError):
            Plan.from_markdown(text)

    def test_to_dict_exposes_the_headless_contract(self):
        plan = make_plan()
        data = plan.to_dict()

        assert list(data) == [
            "id",
            "goal",
            "assumptions",
            "steps",
            "risks",
            "not_doing",
            "status",
            "revision",
            "session_id",
            "created",
            "updated",
            "cwd",
            "project_key",
            "model",
            "base_rev",
            "approved_at",
            "change_summary",
            "path",
        ]
        assert data["path"] is None
        assert data["steps"][0] == {
            "id": "S1",
            "title": "Extract a TokenEstimator protocol",
            "detail": "Keep the heuristic default",
            "acceptance": "existing token tests keep passing",
        }
        plan.path = Path("/tmp/plan.md")
        assert plan.to_dict()["path"] == "/tmp/plan.md"
        assert plan.step_ids() == ["S1", "S2"]

    def test_from_dict_roundtrips_and_tolerates_missing_fields(self):
        plan = make_plan()
        restored = Plan.from_dict(plan.to_dict())
        assert restored.id == plan.id
        assert restored.goal == plan.goal
        assert restored.steps == plan.steps
        assert restored.assumptions == plan.assumptions
        assert restored.status == plan.status
        assert restored.revision == plan.revision
        assert restored.path is None

        tolerant = Plan.from_dict(
            {
                "id": 123,
                "goal": None,
                "steps": ["junk", {"id": "S1", "title": "only title"}],
                "assumptions": "not-a-list",
                "status": "unknown",
                "revision": "bad",
                "path": "",
            }
        )
        assert tolerant.id == "123"
        assert tolerant.goal == ""
        assert tolerant.steps == [PlanStep(id="S1", title="only title")]
        assert tolerant.assumptions == []
        assert tolerant.status == PLAN_STATUS_DRAFT
        assert tolerant.revision == 1
        assert tolerant.path is None

        assert Plan.from_dict("not-a-dict").id == ""


class TestPaths:
    def test_plans_root_prefers_plan_dir(self, tmp_path):
        assert plans_root(str(tmp_path / "custom"), tmp_path / "config") == (tmp_path / "custom").resolve()

    def test_plans_root_falls_back_to_config_dir(self, tmp_path):
        assert plans_root("", tmp_path / "config") == (tmp_path / "config" / "plans").resolve()
        assert plans_root("   ", tmp_path / "config") == (tmp_path / "config" / "plans").resolve()

    def test_plans_root_requires_an_argument(self):
        with pytest.raises(ValueError):
            plans_root()
        with pytest.raises(ValueError):
            plans_root("")
        with pytest.raises(ValueError):
            plans_root("   ")

    def test_project_key_is_stable_and_directory_specific(self, tmp_path):
        key = project_key(tmp_path)
        assert key == project_key(tmp_path)
        assert len(key) == 16
        assert all(char in "0123456789abcdef" for char in key)
        assert project_key(tmp_path / "a") != project_key(tmp_path / "b")
        assert project_key(tmp_path) == project_key(str(tmp_path))

    def test_project_plan_dir_uses_the_project_key(self, tmp_path):
        root = tmp_path / "plans"
        directory = project_plan_dir(root, tmp_path)
        assert directory == root / project_key(tmp_path)

    @pytest.mark.parametrize(
        ("goal", "expected"),
        [
            ("Add a pluggable token estimator", "add-a-pluggable-token-estimator"),
            ("  FS   read/write  ", "fs-read-write"),
            ("token_estimator_v2", "token-estimator-v2"),
            ("将 token 估算器抽象为可插拔接口", "token"),
            ("把 tokens 的估算器换成可插拔实现", "tokens"),
            ("中文目标", "plan"),
            ("", "plan"),
        ],
    )
    def test_slugify_goal(self, goal, expected):
        assert slugify_goal(goal) == expected

    def test_slugify_goal_honours_max_len(self):
        slug = slugify_goal("abcdefghij klmnopqrst", max_len=10)
        assert slug == "abcdefghij"
        assert len(slug) <= 10

    def test_new_plan_path_uses_injected_clock_and_creates_the_dir(self, tmp_path):
        plan_dir = tmp_path / "plans" / "project"
        now = datetime(2026, 11, 14, 0, 42, 30)
        path = new_plan_path(plan_dir, "Token estimator abstraction", now=now)

        assert path == plan_dir / "20261114-004230-token-estimator-abstraction.md"
        assert plan_dir.is_dir()
        if os.name == "posix":
            assert (plan_dir.stat().st_mode & 0o777) == 0o700

    def test_new_plan_path_avoids_same_second_collisions(self, tmp_path):
        plan_dir = tmp_path / "plans"
        now = datetime(2026, 11, 14, 0, 42, 30)
        first = new_plan_path(plan_dir, "goal", now=now)
        first.write_text("x", encoding="utf-8")
        second = new_plan_path(plan_dir, "goal", now=now)

        assert second.name == "20261114-004230-goal-2.md"
        second.write_text("x", encoding="utf-8")
        assert new_plan_path(plan_dir, "goal", now=now).name == "20261114-004230-goal-3.md"

    def test_shorten_path_uses_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert shorten_path(tmp_path / "a" / "b.md") == "~/a/b.md"
        assert shorten_path(tmp_path) == "~"
        outside = Path("/definitely/not/under/home/file.md")
        assert shorten_path(outside) == str(outside)

    def test_git_rev_success(self, tmp_path):
        completed = MagicMock(returncode=0, stdout="c51f7a3\n")
        with patch.object(plan_store.subprocess, "run", return_value=completed) as run:
            assert git_rev(tmp_path) == "c51f7a3"
        assert run.call_args.args[0] == ["git", "rev-parse", "--short", "HEAD"]
        assert run.call_args.kwargs["cwd"] == str(tmp_path)

    def test_git_rev_failure_returns_empty(self, tmp_path):
        failed = MagicMock(returncode=128, stdout="")
        with patch.object(plan_store.subprocess, "run", return_value=failed):
            assert git_rev(tmp_path) == ""
        with patch.object(plan_store.subprocess, "run", side_effect=OSError("no git")):
            assert git_rev(tmp_path) == ""


class TestPlanIO:
    def test_write_plan_sets_path_and_timestamp_privately(self, tmp_path):
        plan = make_plan()
        target = tmp_path / "plans" / "project" / "plan.md"
        returned = write_plan(plan, target)

        assert returned == target
        assert plan.path == target
        assert plan.updated
        assert target.read_text(encoding="utf-8") == plan.to_markdown()
        if os.name == "posix":
            assert (target.stat().st_mode & 0o777) == 0o600
            assert (target.parent.stat().st_mode & 0o777) == 0o700
        # No temporary file survives an atomic write.
        assert sorted(item.name for item in target.parent.iterdir()) == ["plan.md"]

    def test_write_plan_uses_plan_path_when_omitted(self, tmp_path):
        plan = make_plan(path=tmp_path / "plan.md")
        assert write_plan(plan) == tmp_path / "plan.md"
        assert read_plan(plan.path).id == plan.id

    def test_write_plan_requires_a_path(self):
        with pytest.raises(PlanStoreError):
            write_plan(make_plan())

    def test_write_plan_wraps_os_errors(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        with pytest.raises(PlanStoreError):
            write_plan(make_plan(), blocker / "plan.md")

    def test_write_plan_overwrites_atomically(self, tmp_path):
        target = tmp_path / "plan.md"
        write_plan(make_plan(), target)
        rewritten = make_plan(revision=2, goal="A new goal")
        write_plan(rewritten, target)
        content = target.read_text(encoding="utf-8")
        assert "revision: 2" in content
        assert "A new goal" in content
        if os.name == "posix":
            assert (target.stat().st_mode & 0o777) == 0o600

    def test_read_plan_roundtrip(self, tmp_path):
        plan = make_plan()
        target = write_plan(plan, tmp_path / "plan.md")
        restored = read_plan(target)
        assert restored.id == plan.id
        assert restored.goal == plan.goal
        assert restored.steps == plan.steps
        assert restored.path == target

    def test_read_plan_errors(self, tmp_path):
        with pytest.raises(PlanStoreError):
            read_plan(tmp_path / "missing.md")
        corrupt = tmp_path / "corrupt.md"
        corrupt.write_text("not a plan", encoding="utf-8")
        with pytest.raises(PlanStoreError):
            read_plan(corrupt)

    def test_update_plan_status_updates_memory_only(self, tmp_path):
        plan = make_plan()
        previous = plan.updated
        update_plan_status(plan, PLAN_STATUS_IN_PROGRESS)
        assert plan.status == PLAN_STATUS_IN_PROGRESS
        assert plan.updated != previous
        assert plan.path is None
        with pytest.raises(PlanStoreError):
            update_plan_status(plan, "finished")


class TestListingAndLookup:
    def _root(self, tmp_path) -> Path:
        return tmp_path / "plans"

    def test_list_plans_is_newest_first_and_skips_corrupt_files(self, tmp_path):
        root = self._root(tmp_path)
        directory = project_plan_dir(root, tmp_path)
        write_markdown_plan(make_plan("old-plan", updated="2026-11-14T00:00:00+08:00"), directory)
        write_markdown_plan(make_plan("new-plan", updated="2026-11-14T02:00:00+08:00"), directory)
        (directory / "broken.md").write_text("broken", encoding="utf-8")

        plans = list_plans(root, project_key(tmp_path))

        assert [plan.id for plan in plans] == ["new-plan", "old-plan"]

    def test_list_plans_isolates_projects_and_handles_missing_root(self, tmp_path):
        root = self._root(tmp_path)
        write_markdown_plan(make_plan("project-a"), project_plan_dir(root, tmp_path / "a"))
        write_markdown_plan(make_plan("project-b"), project_plan_dir(root, tmp_path / "b"))

        all_plans = list_plans(root)
        assert {plan.id for plan in all_plans} == {"project-a", "project-b"}
        only_a = list_plans(root, project_key(tmp_path / "a"))
        assert [plan.id for plan in only_a] == ["project-a"]
        assert list_plans(tmp_path / "missing-root") == []
        assert list_plans(root, "deadbeef") == []

    def test_find_plan_by_id_and_filename_stem(self, tmp_path):
        root = self._root(tmp_path)
        directory = project_plan_dir(root, tmp_path)
        write_markdown_plan(make_plan("20261114-004230-token-estimator"), directory)

        by_id = find_plan(root, "20261114-004230-token-estimator", project_key(tmp_path))
        assert by_id is not None
        assert by_id.id == "20261114-004230-token-estimator"
        assert find_plan(root, "", project_key(tmp_path)) is None
        assert find_plan(root, "nope", project_key(tmp_path)) is None

    def test_find_latest_unfinished_filters_status_and_session(self, tmp_path):
        root = self._root(tmp_path)
        directory = project_plan_dir(root, tmp_path)
        write_markdown_plan(
            make_plan("done-plan", status=PLAN_STATUS_DONE, updated="2026-11-14T03:00:00+08:00"),
            directory,
        )
        write_markdown_plan(
            make_plan("draft-plan", status=PLAN_STATUS_DRAFT, session_id="s-1", updated="2026-11-14T01:00:00+08:00"),
            directory,
        )
        write_markdown_plan(
            make_plan(
                "progress-plan",
                status=PLAN_STATUS_IN_PROGRESS,
                session_id="s-2",
                updated="2026-11-14T02:00:00+08:00",
            ),
            directory,
        )

        latest = find_latest_unfinished(root, project_key(tmp_path))
        assert latest is not None
        assert latest.id == "progress-plan"
        by_session = find_latest_unfinished(root, project_key(tmp_path), session_id="s-1")
        assert by_session is not None
        assert by_session.id == "draft-plan"
        assert find_latest_unfinished(root, project_key(tmp_path), session_id="s-3") is None


class TestPruneAndClear:
    def _root(self, tmp_path) -> Path:
        return tmp_path / "plans"

    def _seed(self, directory: Path, count: int) -> None:
        for index in range(1, count + 1):
            write_markdown_plan(
                make_plan(
                    f"plan-{index}",
                    status=PLAN_STATUS_DONE if index % 2 else PLAN_STATUS_ABORTED,
                    updated=f"2026-11-14T0{index}:00:00+08:00",
                ),
                directory,
            )

    def test_prune_keeps_newest_terminal_plans(self, tmp_path):
        root = self._root(tmp_path)
        directory = project_plan_dir(root, tmp_path)
        self._seed(directory, 5)
        write_markdown_plan(
            make_plan("draft-plan", status=PLAN_STATUS_DRAFT, updated="2026-11-14T00:30:00+08:00"),
            directory,
        )
        write_markdown_plan(
            make_plan("active-plan", status=PLAN_STATUS_IN_PROGRESS, updated="2026-11-14T00:40:00+08:00"),
            directory,
        )

        deleted = prune_plans(root, project_key(tmp_path), keep=2)

        assert {path.name for path in deleted} == {"plan-1.md", "plan-2.md", "plan-3.md"}
        remaining = {plan.id for plan in list_plans(root, project_key(tmp_path))}
        assert remaining == {"plan-4", "plan-5", "draft-plan", "active-plan"}
        assert prune_plans(root, project_key(tmp_path), keep=2) == []

    def test_prune_never_deletes_draft_or_in_progress(self, tmp_path):
        root = self._root(tmp_path)
        directory = project_plan_dir(root, tmp_path)
        write_markdown_plan(make_plan("draft-plan", status=PLAN_STATUS_DRAFT), directory)
        write_markdown_plan(make_plan("active-plan", status=PLAN_STATUS_IN_PROGRESS), directory)

        assert prune_plans(root, project_key(tmp_path), keep=0) == []
        assert len(list_plans(root, project_key(tmp_path))) == 2

    def test_clear_plans_all_and_done_only(self, tmp_path):
        root = self._root(tmp_path)
        directory = project_plan_dir(root, tmp_path)
        write_markdown_plan(make_plan("done-plan", status=PLAN_STATUS_DONE), directory)
        write_markdown_plan(make_plan("draft-plan", status=PLAN_STATUS_DRAFT), directory)
        write_markdown_plan(make_plan("active-plan", status=PLAN_STATUS_IN_PROGRESS), directory)

        deleted = clear_plans(root, project_key(tmp_path), done_only=True)
        assert [path.name for path in deleted] == ["done-plan.md"]
        assert {plan.id for plan in list_plans(root, project_key(tmp_path))} == {"draft-plan", "active-plan"}

        deleted = clear_plans(root, project_key(tmp_path))
        assert {path.name for path in deleted} == {"draft-plan.md", "active-plan.md"}
        assert list_plans(root, project_key(tmp_path)) == []

    def test_clear_plans_can_span_projects(self, tmp_path):
        root = self._root(tmp_path)
        write_markdown_plan(make_plan("plan-a"), project_plan_dir(root, tmp_path / "a"))
        write_markdown_plan(make_plan("plan-b"), project_plan_dir(root, tmp_path / "b"))

        assert len(clear_plans(root)) == 2
        assert list_plans(root) == []


class TestChatPlanField:
    def test_plan_field_is_optional_and_private_to_plan_sessions(self):
        chat = Chat(title="plain", history=[])
        assert chat.plan == {}
        assert "plan" not in chat._raw_dict()

        chat.plan = {"id": "plan-1", "status": "in-progress"}
        assert chat._raw_dict()["plan"] == {"id": "plan-1", "status": "in-progress"}

    def test_save_and_load_preserves_the_plan_payload(self, tmp_path):
        chat = Chat(title="plan-session")
        chat.add_message("user", "plan something")
        plan_payload = {
            "id": "20261114-004230-token-estimator",
            "path": str(tmp_path / "plan.md"),
            "status": "in-progress",
            "revision": 2,
            "session_id": "2026-11-14T00:42:30.123456",
            "base_rev": "c51f7a3",
            "todos": [{"id": "S1", "content": "step one", "status": "completed", "reason": ""}],
            "updated": UPDATED,
        }
        chat.plan = plan_payload
        assert chat.save(tmp_path) is True

        restored = Chat(path=chat.path)
        assert restored.load() is True
        assert restored.plan == plan_payload

    def test_from_dict_and_load_are_legacy_compatible(self, tmp_path):
        legacy = Chat.from_dict({"title": "Old", "date": "2024-01-01", "history": [{"role": "user", "content": "hi"}]})
        assert legacy.plan == {}
        assert Chat.from_dict({"plan": "not-a-dict"}).plan == {}

        legacy_file = tmp_path / "legacy.json"
        legacy_file.write_text('{"title": "Old", "history": [{"role": "user", "content": "hi"}]}', encoding="utf-8")
        chat = Chat(path=legacy_file)
        assert chat.load() is True
        assert chat.plan == {}


class TestConfigWiring:
    """The plan keys must be wired through DEFAULT_CONFIG_MAP + the INI template."""

    @pytest.mark.parametrize(
        ("key", "expected_value", "env_key", "expected_type"),
        [
            ("PLAN_ENABLED", "true", "YAI_PLAN_ENABLED", bool),
            ("PLAN_MAX_STEPS", 20, "YAI_PLAN_MAX_STEPS", int),
            ("PLAN_KEEP", 80, "YAI_PLAN_KEEP", int),
            ("PLAN_ALLOW_READONLY_SHELL", "true", "YAI_PLAN_ALLOW_READONLY_SHELL", bool),
            ("PLAN_DIR", "", "YAI_PLAN_DIR", str),
        ],
    )
    def test_config_map_entries(self, key, expected_value, env_key, expected_type):
        entry = DEFAULT_CONFIG_MAP[key]
        assert entry["value"] == expected_value
        assert entry["env_key"] == env_key
        assert entry["type"] is expected_type

    def test_config_ini_template_contains_the_plan_block(self):
        for line in (
            "PLAN_ENABLED=true",
            "PLAN_MAX_STEPS=20",
            "PLAN_KEEP=80",
            "PLAN_ALLOW_READONLY_SHELL=true",
            "PLAN_DIR=",
            "# Plan mode (v0.24 K23)",
        ):
            assert line in DEFAULT_CONFIG_INI
