# K23 Implement Sheet — 持久 plan mode + submit_plan + todo（v0.24）

> 这是实现期唯一接口合同（plan of record 的接口附录）。需求 = `prd.md`，技术设计 = `design.md`。
> 冲突时优先级：**本文件 > design.md > prd.md**（本文件已经把三个模块的签名冻结，便于并行实现）。
> 所有实现都必须遵守 `.trellis/spec/py/*.md`、`.trellis/spec/repo/feature-spec-writing.md`。
> 分支：`feat/k23-plan-mode`（已创建）。**任何 agent 不得 commit/push，不得改别人的文件。**

## 0. 写作用域（严格执行）

| Owner | 允许写的文件 |
|---|---|
| `plan-store` | `yaicli/plan_store.py`(新)、`yaicli/plan_shell.py`(新)、`yaicli/const.py`(仅 PLAN_* 键 + INI + CMD_PLAN/CMD_TODO)、`yaicli/chat.py`(plan 字段)、`tests/test_plan_store.py`(新)、`tests/test_plan_shell.py`(新)、`tests/test_config.py`(只追加 PLAN 用例) |
| `docs-plan` | `README.md`、`docs/usage/plan-mode.md`(新)、`docs/usage/commands.md`、`docs/usage/headless.md`、`docs/usage/cli.md`、`docs/usage/configuration.md`、`docs/usage/sessions.md`、`mkdocs.yml` |
| `plan-core` | `yaicli/plan_mode.py`(新)、`yaicli/tools/session_tools.py`(新)、`yaicli/tools/__init__.py`、`yaicli/tools/function.py`、`yaicli/tools/workspace.py`、`yaicli/tools/risk.py`、`yaicli/llms/client.py`、`tests/test_plan_mode.py`(新)、`tests/test_todo_write.py`(新)、`tests/test_plan_revision.py`(新)、`tests/test_plan_shell_gate.py`(新) |
| `plan-cli` | `yaicli/cli.py`、`yaicli/cmd_handler.py`、`yaicli/printer.py`、`yaicli/entry.py`、`yaicli/errors.py`、`tests/test_plan_commands.py`(新)、`tests/test_plan_resume.py`(新)、`tests/test_plan_execution.py`(新)、`tests/test_headless_plan.py`(新) |
| Lead | 其余文件（conftest、integration fixes、最终门禁、commit/PR） |

被依赖的模块顺序：`plan-store` 先完成 §3/§4 两个文件（其它 agent 可以按合同先写代码，等文件出现后再跑集成测试）。
**禁止**运行 `just format`（会全仓改写）：只允许 `ruff format <自己的文件>` + `ruff check --no-fix <自己的文件>`。

## 1. 精确常量与配置键

### const.py（`plan-store` 添加）
```python
CMD_PLAN = "/plan"
CMD_TODO = "/todo"

DEFAULT_PLAN_ENABLED: BOOL_STR = "true"
DEFAULT_PLAN_MAX_STEPS: int = 20
DEFAULT_PLAN_KEEP: int = 80
DEFAULT_PLAN_ALLOW_READONLY_SHELL: BOOL_STR = "true"
DEFAULT_PLAN_DIR: str = ""          # 空 = <config-dir>/plans
```
`DEFAULT_CONFIG_MAP` 追加（顺序放在 `CONTEXT_*` 之后、`TOOL_TIMEOUT` 之前）：
```python
# Persistent plan mode (v0.24 K23)
"PLAN_ENABLED": {"value": DEFAULT_PLAN_ENABLED, "env_key": "YAI_PLAN_ENABLED", "type": bool},
"PLAN_MAX_STEPS": {"value": DEFAULT_PLAN_MAX_STEPS, "env_key": "YAI_PLAN_MAX_STEPS", "type": int},
"PLAN_KEEP": {"value": DEFAULT_PLAN_KEEP, "env_key": "YAI_PLAN_KEEP", "type": int},
"PLAN_ALLOW_READONLY_SHELL": {"value": DEFAULT_PLAN_ALLOW_READONLY_SHELL, "env_key": "YAI_PLAN_ALLOW_READONLY_SHELL", "type": bool},
"PLAN_DIR": {"value": DEFAULT_PLAN_DIR, "env_key": "YAI_PLAN_DIR", "type": str},
```
`DEFAULT_CONFIG_INI` 追加一段（放在 `# Project context settings` 段之前）：
```
# Plan mode (v0.24 K23)
# Persistent read-only planning mode: Shift+Tab / /plan, submit_plan -> approve -> todo execution.
PLAN_ENABLED=true
# Maximum number of steps accepted in one plan.
PLAN_MAX_STEPS=20
# Finished (done/aborted) plan files kept per project; older ones are pruned.
PLAN_KEEP=80
# Allow a fixed read-only shell allowlist while planning (true/false).
PLAN_ALLOW_READONLY_SHELL=true
# Plans root directory (empty = <config-dir>/plans).
PLAN_DIR=
```
注意 docs 表格由 `docs-plan` 更新；`tests/test_docs_config.py` 要求 README 表、docs 表、模板三处键集完全等于 `DEFAULT_CONFIG_MAP`，且默认值/ENV 列一致（`PLAN_DIR` 默认列写 `-`，因为空串被文档测试视为 `-`）。

### chat.py（`plan-store` 添加）
`Chat` 增加字段 `plan: Dict[str, Any] = field(default_factory=dict)`，并在
`_raw_dict()`（仅当非空时写 `"plan": self.plan`）、`from_dict()`、`load()` 中读写，保持旧会话兼容。不要改其他元数据。

### errors.py（`plan-cli` 添加）
`ErrorKind` 增加 `PLAN_NOT_SUBMITTED = "plan_not_submitted"`（其它 kind 不动）。

## 2. 状态机（实现口径）

```
NORMAL ──Shift+Tab//plan──▶ RESEARCHING ──submit_plan ok──▶ REVIEWING ──[a]──▶ EXECUTING ──all done──▶ NORMAL(done)
  ▲                              │                            │  [s]/[Esc] ──▶ NORMAL(draft kept)
  │                              └──Shift+Tab/Esc──▶ NORMAL   ├─ [e] ──▶ REVIEWING
  │                                                           └─ [r] ──▶ RESEARCHING(keep context)
  └── EXECUTING ──Shift+Tab//plan──▶ REVISING ──submit_plan(revision)──▶ REVIEWING(rev) ──[a]──▶ EXECUTING
                                               └── Esc ──▶ EXECUTING(plan unchanged)
```
会话内 `mode` 值就是字符串：`normal|researching|revising|reviewing|executing`（`executing` 是内部扩展：design 的状态机把它折叠进 NORMAL+active plan，但实现上单独一个值更好维护；对外仍然只暴露 `normal/plan` 两种提示符状态）。
`PlanMode` StrEnum 定义 `NORMAL/RESEARCHING/REVISING/REVIEWING/EXECUTING`。

## 3. `yaicli/plan_store.py`（`plan-store`，stdlib-only）

**只允许** import `hashlib, json, os, re, subprocess, sys, dataclasses, datetime, pathlib, typing`。不要 import `yaicli.*`、rich、typer、cfg 单例。文件写入必须原子（temp + `os.replace`）并 0600/0700。

```python
PLAN_DIR_MODE = 0o700
PLAN_FILE_MODE = 0o600
PLAN_STATUS_DRAFT = "draft"; PLAN_STATUS_IN_PROGRESS = "in-progress"
PLAN_STATUS_DONE = "done"; PLAN_STATUS_ABORTED = "aborted"
PLAN_TERMINAL_STATUSES = (PLAN_STATUS_DONE, PLAN_STATUS_ABORTED)
PLAN_STATUSES = (draft, in-progress, done, aborted)
PLAN_TODO_STATUSES = ("pending", "in_progress", "completed", "blocked")

class PlanStoreError(Exception): ...

@dataclass
class PlanStep:
    id: str
    title: str
    detail: str = ""
    acceptance: str = ""
    def to_dict(self) -> dict; @classmethod from_dict(cls, data) -> PlanStep

@dataclass
class Plan:
    id: str
    goal: str
    steps: List[PlanStep]
    assumptions: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    not_doing: List[str] = field(default_factory=list)
    status: str = PLAN_STATUS_DRAFT
    revision: int = 1
    session_id: str = ""
    created: str = ""
    updated: str = ""
    cwd: str = ""
    project_key: str = ""
    model: str = ""
    base_rev: str = ""
    approved_at: str = ""
    change_summary: str = ""
    path: Optional[Path] = None
    def to_dict(self) -> dict          # JSON/headless: id/goal/assumptions/steps/risks/not_doing/status/revision/session_id/created/updated/cwd/project_key/model/base_rev/approved_at/change_summary + path(str|None)
    def step_ids(self) -> List[str]
    def to_markdown(self) -> str
    @classmethod def from_markdown(cls, text: str, path: Optional[Path] = None) -> "Plan"   # 解析失败 raise PlanStoreError
    @classmethod def from_dict(cls, data: dict) -> "Plan"                                  # 会话恢复用，容错

# --- 路径 ---
def plans_root(plan_dir: str = "", config_dir: Optional[Path] = None) -> Path
    # plan_dir 非空 -> Path(plan_dir).expanduser().resolve()
    # config_dir 非空 -> Path(config_dir)/"plans"
    # 两者都没有 -> raise ValueError（调用方必须给一个；CLI 传 cfg["PLAN_DIR"], const.get_config_dir()）
def project_plan_dir(root: Path, cwd: Optional[Path] = None) -> Path   # root / sha256(resolved cwd)[:16]
def slugify_goal(goal: str, max_len: int = 40) -> str    # [a-z0-9-]，中文/空 -> "plan"
def new_plan_path(plan_dir: Path, goal: str, now: Optional[datetime] = None) -> Path
    # <YYYYMMDD-HHMMSS>-<slug>.md；同秒冲突追加 -2/-3；目录 mkdir 0700
def project_key(cwd: Optional[Path] = None) -> str        # sha256(str(resolved))[:16]
def git_rev(cwd: Optional[Path] = None) -> str            # `git rev-parse --short HEAD`；失败返回 ""

# --- IO ---
def write_plan(plan: Plan, path: Optional[Path] = None) -> Path      # 原子写 + 0600；设置 plan.path/updated；PlanStoreError 失败
def read_plan(path: Path) -> Plan
def list_plans(root: Path, project_key: Optional[str] = None) -> List[Plan]   # 按 updated 降序；损坏文件跳过（不 raise）
def find_plan(root: Path, plan_id: str, project_key: Optional[str] = None) -> Optional[Plan]
def find_latest_unfinished(root: Path, project_key: str, session_id: Optional[str] = None) -> Optional[Plan]
    # status in (draft, in-progress)；session_id 给定时必须匹配
def prune_plans(root: Path, project_key: str, keep: int, now: Optional[datetime] = None) -> List[Path]
    # 只删终态（done/aborted），按 updated 从旧到新，保留最新 keep 个；draft/in-progress 永不删
def clear_plans(root: Path, project_key: Optional[str] = None, *, done_only: bool = False) -> List[Path]
    # done_only=False 时删包括 draft/in-progress 的所有计划（= /plan clear --all），返回删除列表
def update_plan_status(plan: Plan, status: str) -> Plan   # 原地改 + updated，不写文件（写由调用方决定）
def shorten_path(path: Path) -> str                       # ~ 缩写 HOME，失败退化为原始路径
```

**plan.md 格式（必须 roundtrip）**
```markdown
---
id: 20261114-004230-token-estimator
status: in-progress
revision: 2
session_id: 2026-11-14T00:42:30.123456
created: 2026-11-14T00:42:30+08:00
updated: 2026-11-14T01:10:05+08:00
cwd: /Users/vic/Documents/codes/git/yaicli
project_key: 3f9a1c2d...
model: gpt-5.2
base_rev: c51f7a3
approved_at: 2026-11-14T00:45:00+08:00
change_summary: 支持 per-provider estimator 覆盖
---

# Plan: <goal>

## Goal
<goal>

## Assumptions
- ...

## Steps
- [x] **S1** <title>
  - acceptance: <acceptance>
  - detail: <detail>

## Risks
- ...

## Not doing
- ...
```
- frontmatter 只用 `key: value` 单行标量（空值写空），`Plan.from_markdown` 用正则解析，不引入 YAML。
- `change_summary` 只在非空时写。
- 复选框：completed→`[x]`，其它→`[ ]`；blocked 的行尾 ` (blocked: reason)`。
- Steps 的 `- detail` 行只在 detail 非空时出现；detail/acceptance 按单行保存（换行折叠为空格）。

**会话 JSON 字段**（`PlanSession.to_session_dict()` / `Plan.from_dict` 口径，由 `plan-cli` 写入 Chat.plan）：
```json
{"id": "...", "path": "...", "status": "in-progress", "revision": 2,
 "session_id": "2026-11-14T00:42:30.123456", "base_rev": "c51f7a3",
 "todos": [{"id": "S1", "content": "...", "status": "completed", "reason": ""}],
 "updated": "..."}
```

## 4. `yaicli/plan_shell.py`（`plan-store`，stdlib-only）

只允许 stdlib。**不解释 shell**（绝不 `shell=True`）。

```python
PLAN_SHELL_ALLOWLIST = ("ls", "pwd", "cat", "head", "tail", "wc", "grep", "rg", "find", "file", "stat", "tree", "which")
GIT_READONLY_SUBCOMMANDS = ("status", "diff", "log", "show", "ls-files", "blame", "rev-parse", "describe", "branch")
SHELL_METACHARS = (";", "&", "|", ">", "<", "`", "$(", ")", "\n", "\r")
DANGEROUS_ARGS = {
    "find": ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"),
    "rg": ("--pre", "--pre-glob", "--search-zip"),
    "tree": ("-o", "--output"),
    "file": ("-C", "--compile"),
    "git": ("-c", "--exec-path", "--config", "--upload-pack", "--work-tree"),
}
DEFAULT_TIMEOUT = 120
DEFAULT_OUTPUT_MAX_CHARS = 32000

@dataclass(frozen=True)
class PlanShellVerdict:
    allowed: bool
    argv: Tuple[str, ...] = ()
    reason: str = ""
    hint: str = "use fs_read_file / fs_search_files / leave plan mode with Shift+Tab"

def validate_plan_shell_command(command: str) -> PlanShellVerdict
```
校验顺序与文案（REPL 与结构化错误都用 `reason`）：
1. 空/非字符串 → `{"allowed": False, "reason": "empty command"}`。
2. 原始字符串含任一 `SHELL_METACHARS`（含 `$(`,`)`）→ reason:
   ``shell metacharacters are not allowed in plan mode (use `git status` or fs_read_file)``。注意：`$( )` 的 `$`/`(` 也要拒绝；括号无条件拒绝（含正则里的括号，保守）。
3. `shlex.split` 失败 → `cannot parse command: <err>`。
4. argv[0] 不在 allowlist → ``"`<cmd>` is not in the plan-mode read-only allowlist"``。
5. 任一参数的 basename/前缀命中 `DANGEROUS_ARGS[cmd]`（例如 `find -delete`、`-exec`、`rg --pre=...`、`tree -o`）→
   ``"`<flag>` is not allowed in plan mode"``。对 `find` 支持 `-execdir`、`-fprint*` 前缀匹配。
6. `git`：argv 形如 `git <sub> ...`；`argv[1]` 以 `-` 开头 → 拒绝（禁全局选项）；`argv[1]=="branch"` 时必须含 `--list` 或 `-l`，否则 reason ``"`git branch` without --list is not allowed in plan mode"``。
7. 通过 → `PlanShellVerdict(allowed=True, argv=tuple(argv))`。

```python
def run_plan_shell(argv: Sequence[str], *, cwd: Optional[str] = None, timeout: Optional[int] = None) -> str
```
- 直接 `subprocess.Popen(list(argv), shell=False, cwd=<workspace root>)`，进程组 + 超时 SIGKILL（exit code 124），
  捕获输出上限（env `YAI_TOOL_OUTPUT_MAX_CHARS`，默认 32000），child env 用与 shell 工具相同的 allowlist
  （PATH/HOME/LANG/LC_ALL/TERM/TMPDIR/SHELL/USER + Windows 变量；过滤 `YAI_`/KEY/TOKEN/SECRET/...）。
- `cwd` 解析到 `YAI_WORKSPACE_ROOT`（或当前 cwd）之内，越界返回 in-band 错误字符串。
- 返回格式与 `execute_shell_command` 一致：`"Exit code: N, Output:\n<text>"`，超时 `"Error: command timed out after Ns and was killed"`。
- 该函数在 plan 模式 shell 被允许时由 `tools.execute_tool_call` 调用（见 §7）。

## 5. `yaicli/plan_mode.py`（`plan-core`）

可 import `plan_store`/`plan_shell`/`const`/`config`（lazy 即可）；**不得 import cli/entry/tools**；不得 import rich。
所有"用户可见文案"见 §12。

```python
class PlanMode(StrEnum):
    NORMAL="normal"; RESEARCHING="researching"; REVISING="revising"; REVIEWING="reviewing"; EXECUTING="executing"

PLAN_READONLY_TOOL_NAMES = frozenset({...12 个 builtin 里的 read/network 工具名...})
PLAN_SHELL_TOOL = "execute_shell_command"
SESSION_TOOL_NAMES = frozenset({"submit_plan", "todo_write"})

# 工具可见性（供 tools/__init__.py 过滤 schema）
def plan_tool_allowlist(allow_readonly_shell: bool = True) -> frozenset[str]
    # PLAN_READONLY_TOOL_NAMES | {"submit_plan"} | (allow ? {"execute_shell_command"} : set())
def execution_tool_names() -> frozenset[str]  # {"todo_write"}
def is_tool_allowed_in_plan(name: str, allow_readonly_shell: bool = True) -> bool
def is_plan_mode_value(mode: Optional[str]) -> bool   # researching/revising
def is_execution_mode_value(mode: Optional[str]) -> bool

@dataclass
class TodoItem:
    id: str; content: str; status: str = "pending"; reason: str = ""
    def to_dict(self) -> dict; @classmethod from_dict

@dataclass
class RevisionDiff:
    added: List[PlanStep]; removed: List[PlanStep]; changed: List[PlanStep]; unchanged: List[PlanStep]
    def summary(self) -> str                 # "Changes: +N step  ~N step  -N steps"
    def detail_lines(self, max_lines: int = 12) -> List[str]
    def todo_impact(self, todos: List[TodoItem]) -> str

class PlanSession:
    mode: str = "normal"
    active_plan: Optional[Plan] = None      # 执行中的计划（in-progress）
    draft_plan: Optional[Plan] = None       # 已提交待批准（首次或修订）
    revision_base: Optional[Plan] = None    # 修订前的计划（计算 diff / 丢弃用）
    diff: Optional[RevisionDiff] = None
    todos: List[TodoItem] = field(default_factory=list)
    session_id: str = ""
    plans_root: Optional[Path] = None       # 本进程的 plans 根
    plan_dir: Optional[Path] = None         # 本项目的目录（plans_root/project_key）
    cwd: Path = field(default_factory=Path.cwd)
    model: str = ""; base_rev: str = ""; change_summary: str = ""
    max_steps: int = 20; keep: int = 80; allow_readonly_shell: bool = True
    # 生命周期
    def configure(self, *, plans_root: Path, cwd: Optional[Path]=None, model: str="", session_id: str="",
                  max_steps: int=20, keep: int=80, allow_readonly_shell: bool=True) -> None
    def reset(self) -> None
    def enter_researching(self) -> None       # 保留 active_plan，清 draft；记录 base_rev
    def enter_revising(self) -> None          # active_plan 必存在；revision_base=active_plan
    def cancel_draft(self) -> None            # 回到 NORMAL；保留 active_plan（execution）或清空
    def to_session_dict(self) -> dict         # 会话 JSON 口径，见 §3；无 active plan 返回 {}
    def restore_from_session(self, data: dict, *, session_id: str, plans_root: Path, cwd: Path) -> Optional[str]
        # 返回 None=成功恢复；否则返回一句 "saved plan not found/inconsistent; starting in normal mode" 的 detail
        # 校验：文件存在、可解析、id/status/session_id 匹配、status in (draft,in-progress)；只恢复 active_plan+todos，
        # mode 永远是 NORMAL（调用方负责打印提示）。
    @property
    def is_plan_mode(self) -> bool            # mode in researching/revising
    @property
    def is_reviewing(self) -> bool
    @property
    def is_executing(self) -> bool
    @property
    def active_plan_id(self) -> str
    def all_todos_completed(self) -> bool
    def todo_progress(self) -> Tuple[int, int]          # (completed_or_blocked? 只算 completed, total)
    def todo_snapshot(self) -> Tuple[Tuple[str, str], ...]

# 全局单例（execute_tool_call / client / CLI 共享）
def get_plan_session() -> PlanSession
def reset_plan_session() -> None
def set_plan_session(session: PlanSession) -> None

# submit_plan / todo_write 处理（session_tools 调用）
def handle_submit_plan(arguments: Dict[str, Any]) -> Dict[str, Any]
def handle_todo_write(arguments: Dict[str, Any]) -> Dict[str, Any]
def validate_submit_plan(arguments, *, session: PlanSession, mode: str) -> Tuple[Optional[Plan], Optional[dict]]
    # 首次：goal 非空≤500；steps 1..max_steps；每步 title/acceptance 非空；序列化≤8KB；忽略 revision/change_summary，id 分配 S1..Sn
    # 修订：revision == active_plan.revision+1；change_summary 必填≤500；id 必须属于 active ids 或 == S{n+1}..（n=len(active.steps)），
    #       不得重复；steps 1..max_steps；其它同上。
    # 失败返回 (None, {"error": "invalid_plan", "reason": "...", "hint": "..."})；成功返回 (Plan, None)
def validate_todo_write(arguments, *, session: PlanSession) -> Tuple[Optional[List[TodoItem]], Optional[dict]]
def seed_todos(plan: Plan) -> List[TodoItem]      # 全部 pending；S1 -> in_progress
def rebuild_todos_after_revision(session: PlanSession) -> List[TodoItem]
    # 保留 completed/changed 状态；removed 记录在 diff；added pending；当前 in_progress 被删则整体置 paused 提示
def apply_revision(session: PlanSession) -> Dict[str, Any]   # 写回 plan.md（原地：revision/updated、steps），重建 todos，mode=EXECUTING
def approve_new_plan(session: PlanSession) -> Dict[str, Any] # status=in-progress + approved_at，写文件，seed todos，mode=EXECUTING
def finish_plan(session: PlanSession) -> Dict[str, Any]      # status=done，写文件，mode=NORMAL，清 active/draft/todos（返回 summary 数据）
def abort_plan(session: PlanSession) -> Dict[str, Any]       # status=aborted，写文件，清状态
def pause_plan(session: PlanSession) -> None                 # mode=NORMAL，保留 active_plan+todos
def resume_plan(session: PlanSession) -> bool                # active in-progress -> mode=EXECUTING
def diff_plans(old: Plan, new: Plan) -> RevisionDiff
def plan_context_block(session: PlanSession, *, max_chars: int = 2000) -> str
    # plan 模式：goal + assumptions + 当前 steps（含 acceptance）要求"只读调研，用 submit_plan 结束"；
    # 修订模式追加当前 todos + 已批准计划 revision；
    # 执行模式：goal + [todo 1/4] 状态清单（≤500B 的 todo 部分）
def todo_summary(session: PlanSession, *, max_chars: int = 500) -> str
def plan_audit(event: str, **fields) -> None
    # cfg["TOOL_AUDIT"] 开启时向 const.TOOL_AUDIT_PATH 追加 {"ts", "event": "plan.<event>", ...}（0600，best-effort）
def write_plan_editor_draft(session: PlanSession, plan: Plan) -> Path    # 修订 [e] 用隐藏临时文件 .<id>.editor.md（0600）
def edit_plan_file(path: Path) -> Tuple[bool, str]   # $EDITOR（fallback vi）编辑 + 重新解析校验；返回 (ok, error)
```
`handle_submit_plan` 成功后：**首次**写计划文件（status=draft）到 `plan_dir`；**修订**只改内存 draft（不写主文件），
mode→REVIEWING，`plan_audit("submit"/"revise_submit", ...)`；返回
`{"success": True, "plan_id", "revision", "path", "steps": N, "revision_diff": {...}|None}`（JSON 字符串由 session_tools 序列化）。
`handle_todo_write` 成功后：写回 plan.md 复选框、`plan_audit("todo.update")`、返回
`{"success": True, "completed": n, "total": m, "blocked": k, "in_progress": "Sx"|""}`，并给 REPL 打一行进度（见 §12）。

## 6. `yaicli/tools/session_tools.py`（`plan-core`）

用 pydantic `OpenAISchema` 定义（这样 OpenAI/Anthropic/Gemini 三套 schema 都自动生成；字段一律具体类型、不要 Optional/Union）：

```python
class SubmitPlanFunction(OpenAISchema):
    """Submit the implementation plan to the user for approval. ..."""
    class Config: title = "submit_plan"
    goal: str = Field(..., description="...")
    assumptions: List[str] = Field(default=[], description="...")   # 用 default=[]，不能用 default_factory（会变 required）
    steps: List[PlanStepInput] = Field(..., description="...")
    risks: List[str] = Field(default=[], ...)
    not_doing: List[str] = Field(default=[], ...)
    revision: int = Field(default=0, ...)
    change_summary: str = Field(default="", ...)
    @classmethod def execute(cls, goal, assumptions=[], steps=[], risks=[], not_doing=[], revision=0, change_summary="") -> str
        # 调 plan_mode.handle_submit_plan(dict(...))，json.dumps(ensure_ascii=False)
class TodoWriteFunction(OpenAISchema): ... class Config: title = "todo_write"
    items: List[TodoItemInput] (id, content, status, reason)
    @classmethod execute(...) -> str  # 调 handle_todo_write
```
另暴露：
```python
def openai_schemas(mode: str) -> List[dict]      # mode "plan" -> [submit_plan]; "execution" -> [todo_write]
def anthropic_schemas(mode: str) -> List[dict]
def gemini_functions(mode: str) -> List[Callable]  # 用 yaicli.tools.function.wrap_gemini_function(Function.execute)
def execute_session_tool(name: str, arguments: Dict[str, Any]) -> str
def session_tool_available(name: str, mode: Optional[str]) -> bool
```
`execute_session_tool` 返回 JSON 字符串；参数类型错误也要 in-band JSON error（不 raise）。

## 7. `tools/__init__.py` / `function.py` / `workspace.py` / `risk.py`（`plan-core`）

`tools/__init__.py`：
```python
_plan_mode: Optional[str] = None       # None | "plan" | "execution"
def set_plan_tool_mode(mode: Optional[str]) -> None
def get_plan_tool_mode() -> Optional[str]
```
- `set_plan_tool_mode` 清空 `_filtered_schemas_cache` + `_gemini_functions_cache`（后者在 tools/function.py，提供
  `reset_gemini_schema_cache()` 或直接 import 其模块清缓存——**不要**在 tools/__init__ 模块顶层 import plan_mode/session_tools）。
- `get_openai_schemas()` / `get_anthropic_schemas()`：
  - `_plan_mode=="plan"`：先按 `plan_mode.plan_tool_allowlist(cfg["PLAN_ALLOW_READONLY_SHELL"])` 过滤 builtin schema，
    再追加 `session_tools.openai_schemas("plan")` / `anthropic_schemas("plan")`；
  - `_plan_mode=="execution"`：全部 builtin + `session_tools.*("execution")`；
  - 之后照旧应用 `ENABLED_TOOLS`。过滤/追加变体缓存 key 包含 mode。
- `get_openai_mcp_tools()` / `get_anthropic_mcp_tools()`：`_plan_mode=="plan"` 时返回 `[]`（不连 MCP server）。
- `execute_tool_call()` 在解析参数之后、执行工具之前插入（保持 announce 行已打印）：
  1. `name in SESSION_TOOL_NAMES`：`text = session_tools.execute_session_tool(name, arguments)`，
     `_emit_tool_result(..., show_output=False)`，`ok=True`；session_tools 内部负责审计；不走 approval/workspace。
  2. `name == "execute_shell_command"` 且 `plan_mode.get_plan_session().is_plan_mode`：
     - `verdict = plan_shell.validate_plan_shell_command(command)`；
     - denied：`result = json.dumps({"error":"plan_shell_denied","reason":<reason>,"hint":<hint>})`；
       `console.print(f"✗ plan_shell_denied: {safe_text(reason)}", style="red")`（tools.console 已是 TTY-aware：机器模式走 stderr）；
       `plan_mode.plan_audit("shell_denied", command=..., reason=...)`；`_emit_tool_result` 后 `return result, True`。
     - allowed：`result_text = plan_shell.run_plan_shell(verdict.argv, cwd=arguments.get("cwd"), timeout=arguments.get("timeout"))`；
       `plan_audit("shell", command=..., decision="allowed")`；继续走 `_emit_tool_result`。
- 不要改 `_emit_tool_result` 签名；不要动其它工具逻辑。

`tools/function.py`：`get_functions_gemini_format()` 同样按 §7 的 plan/execution 规则过滤与追加
（`_gemini_functions_cache` 改为按 mode 缓存，`set_plan_tool_mode` 清空）。注意 `yaicli.tools.function` 不能 import `yaicli.tools`
（会循环）：用函数内 lazy import `from . import session_tools` / `from . import plan_mode`（`yaicli.tools.function` 的 `from .` 指向 `yaicli.tools` 包属
性时可以，测试用 `importlib` 没关系；若循环风险，直接 `from ..plan_mode import ...` 亦可，plan_mode 不 import tools）。

`tools/workspace.py`：`prepare_mutation` 的保护检查追加一条：目标路径（resolve 后）位于 plans 根之下 → 拒绝写入
（in-band `{"success": false, "error": "protected_path", "reason": "plan files are managed by the CLI"}` 语义沿用现有 denial 形状）。
plans 根解析：`plan_dir=cfg.get("PLAN_DIR")`（lazy import config；stdlib 叶子的既有做法见 approval.py `_workspace_root()`），
空则 `const.get_config_dir()/"plans"`。

`tools/risk.py`：`BUILTIN_TOOL_RISK` 增加 `"submit_plan": RiskLevel.read`、`"todo_write": RiskLevel.read`（session 工具不会走到审批，
但审计/其它逻辑的 risk 分类要合理）。

## 8. `llms/client.py`（`plan-core`）

- `__slots__` 增加 `"plan_session"`；`__init__` 设 `self.plan_session = None`（对象由 CLI 注入，client 不 import plan_mode 于模块顶层）。
- `completion_with_tools` 不再需要注入 context（由 CLI `_build_messages` 注入，见 §9）。
- `_execute_tools_and_continue` 的门禁逻辑（在 `tool_enabled` 检查之后、`dangerous` 分类之前）插入 **plan 分支**：
  ```python
  plan_state = getattr(self.plan_session, "mode", None) if self.plan_session is not None else None
  plan_mode_active = plan_state in ("researching", "revising")
  if plan_mode_active:
      from ..plan_mode import is_tool_allowed_in_plan
      if not is_tool_allowed_in_plan(gate_name, allow_readonly_shell=bool(self.config.get("PLAN_ALLOW_READONLY_SHELL", True))):
          reason = (f"Tool '{gate_name}' is not available in plan mode; planning is read-only. "
                    "Use the read/network tools or a read-only shell command, then call submit_plan, "
                    "or leave plan mode with Shift+Tab.")
          append tool message {"error": "tool_not_available_in_mode", "reason": reason}; audit decision="denied" source="plan_mode";
          continue
      decision, source = ToolConfirmDecision.ONCE, "plan_mode"   # 不弹审批；shell 的白名单校验在 execute_tool_call 里做
  elif plan_state == "executing" and gate_name == "todo_write":
      decision, source = ToolConfirmDecision.ONCE, "plan_mode"
  ```
  然后再进入现有 `dangerous` / TOOL_POLICY / approval 分支（plan 分支已设置 decision 的，要跳过这些分支；用一个
  `plan_override = True` 标志或 if/elif 链）。session 工具（submit_plan/todo_write）在任何非匹配模式下硬发都要走
  "not available in mode" 拒绝（不要落到 approval 弹窗）。
- 审计：plan 分支的 deny 用现有 `_audit_tool_decision(... policy=policy_mode, decision="denied", source="plan_mode", reason=reason)`；
  plan 分支的 allow 在工具执行后用现有 audit 调用（`source="plan_mode"`，`decision="allowed"/"error"`）。
- 不改 provider、不改 token 预算逻辑；`_get_valid_tool_calls` 不动。

## 9. `cli.py`（`plan-cli`）

新增实例状态（`__slots__` + `__init__`）：
```
plan_session      # 懒创建（None 直到第一次用到；不 import plan_mode 在模块顶层）
plan_requested    # --plan headless 标志（configure_headless(plan=...)）
_plan_output_plan # headless 输出的 Plan（最后提交的 draft）
```
- `configure_headless(..., plan: bool = False)` 保存 `self.plan_requested`。
- `_get_plan_session()`：lazy import `plan_mode`，`get_plan_session()`；首次时
  `session.configure(plans_root=plan_store.plans_root(cfg["PLAN_DIR"], get_config_dir()), cwd=Path.cwd(),
  model=cfg["MODEL"], session_id=self.chat.date, max_steps=cfg["PLAN_MAX_STEPS"], keep=cfg["PLAN_KEEP"],
  allow_readonly_shell=cfg["PLAN_ALLOW_READONLY_SHELL"])`；设置 `self.client.plan_session = session`（如果 client 已存在）并
  `tools.set_plan_tool_mode("plan"/"execution"/None)`；调用点：进入模式/恢复计划/headless。
- `_sync_plan_tool_mode()`：按 session.mode 调 `tools.set_plan_tool_mode`（researching/revising→"plan"，executing→"execution"，else None）。
- `_toggle_plan_mode()`（Shift+Tab 与 `/plan` 共用；PLAN_ENABLED=false 时打一行提示并返回）：
  - current_mode==EXEC_MODE 时先回 CHAT_MODE + init_role；
  - REVIEWING → `_cancel_plan_review()`；
  - 其它 plan 模式 → `session.cancel_draft()`，清工具过滤，打印 `plan mode off`；
  - NORMAL：有 in-progress active_plan → `enter_revising()` + `[plan] revising (read-only) …`；否则 `enter_researching()` + `[plan] exploring (read-only) …`；
    打印状态行 `plan mode · read-only`；`_sync_plan_tool_mode()`。
- `get_prompt_tokens()`：plan 模式（researching/revising）返回 `[("class:qmark", f" [plan] {mode_icon} "), ("class:prompt", "> ")]`，其余保持现在格式。
- `_build_messages()`：在 role system message 之后、persistent context 之前插入
  `plan_mode.plan_context_block(session)`（mode != normal/executing 或 executing 时；空字符串不插入）。
- `_process_user_input` 之后：REPL 循环在每个正常 turn 后调用 `self._after_plan_turn()`：
  ```python
  def _after_plan_turn(self):
      session = self._plan_session
      if session is None or session.mode != "reviewing": return
      self._handle_plan_review_panel()
  ```
- 批准面板（`_handle_plan_review_panel`）：
  - `self.printer.show_plan_panel(plan, revision=bool(session.revision_base), diff=session.diff)` 打印面板；
    非修订：`Plan ready: <id>`；修订：`Plan revision <N>: <id>`。
  - `decision = self.printer.ask_plan_decision(revision=...)`；`edit` → `plan_mode.edit_plan_file(...)`（首次直接编辑 plan 文件；
    修订先 `write_plan_editor_draft` 再编辑，成功后把 parsed Plan 放回 session.draft_plan + 重算 diff）→ 重新循环面板；
    `redo` → session.cancel_draft() + enter_researching/revising + 提示 `[plan] keep planning — send a new message to revise the plan.`；
    `save` → 首次：保持 draft 文件 + mode NORMAL + `✓ saved as draft (<path>) · exit plan mode`；修订：丢弃修订 + 回 EXECUTING + `revision discarded`；
    `cancel` → 首次：mode NORMAL（draft 文件保留）+ `plan cancelled; draft saved at <path>`；修订：丢弃修订 + 回 EXECUTING + `revision discarded`；
    `approve` → 首次：若 `cfg["TOOL_POLICY"]=="readonly"` 先 `Prompt.ask("current TOOL_POLICY=readonly would deny writes; switch to standard?", default="n")`
      （no → 留在 REVIEWING）；然后 `plan_mode.approve_new_plan(session)`，打印
      `✓ plan approved · exiting plan mode · todo seeded (N steps)`；修订：`plan_mode.apply_revision(session)`，打印
      `✓ revision N applied · plan.md updated in place · resuming execution at <Sx>`；两者都 `_sync_plan_tool_mode()`（切到 execution）后 `_execute_plan()`。
  - 每次 session 状态变化后 `self.chat.plan = session.to_session_dict()`；若 `not self.is_temp_session` 且已有 path，调 `chat.save(chat_dir)` best-effort。
- `_execute_plan()`（执行循环）：
  ```python
  PLAN_MAX_EXECUTION_TURNS = 20   # module-level const
  turns = no_progress = 0
  while turns < PLAN_MAX_EXECUTION_TURNS and not session.all_todos_completed():
      before = session.todo_snapshot()
      instruction = KICKOFF if turns == 0 else CONTINUE
      try: self._process_user_input(instruction)
      except KeyboardInterrupt: plan_mode.pause_plan(session); print pause line; return
      turns += 1
      if session.todo_snapshot() == before and not session.all_todos_completed(): no_progress += 1
      else: no_progress = 0
      if no_progress >= 2: break
  if session.all_todos_completed():
      summary = plan_mode.finish_plan(session); _sync_plan_tool_mode()
      print f"✓ plan done · {done}/{total} steps"
  else:
      plan_mode.pause_plan(session); _sync_plan_tool_mode()
      print f"[plan] execution paused at {done}/{total} steps · /plan resume to continue · /plan abort to abandon"
  ```
  KICKOFF/CONTINUE 文案（不可见用户输入）：`"Execute the approved plan now. Use todo_write to mark the current step in_progress, mark it completed when done and advance the next step. Do not add or remove steps."` /
  `"Continue executing the approved plan from the current todo state."`
- `_restore_plan_from_session()`（只在 `run()` 的 chat 分支、`_resume_latest_session()` / `_start_chat_by_title()` 之后调用）：
  若 `self.chat.plan` 非空：`detail = session.restore_from_session(...)`；失败 → stderr `saved plan not found/inconsistent; starting in normal mode` 并清空 chat.plan；
  成功且 status draft → 打印两行（见 §12）；status in-progress → 两行 `/plan resume` 版本；永远 NORMAL、不自动进入 plan mode、不 `set_plan_tool_mode("plan")`。
- `/plan` 命令在 `cmd_handler.py` 实现（见 §10），CLI 暴露内部方法供其调用：
  `_get_plan_session`, `_toggle_plan_mode`, `_handle_plan_review_panel`, `_execute_plan`, `_sync_plan_tool_mode`,
  `_resume_plan_from_disk(plan_id_or_none)`, `_review_plan_from_disk(...)`。
- `_build_result()`：当 `self.plan_requested` 或 `self._plan_output_plan` 时追加
  `"plan": plan.to_dict()`、`"plan_path": str(plan.path)`、`"revision": plan.revision`（普通运行 JSON key 集合不变，保持既有合同）。
- headless `--plan`：`run()` 分支（`self.plan_requested and not chat`）→ `_run_headless_plan(user_input)`：
  ```python
  session = self._get_plan_session(); session.enter_researching(); self._sync_plan_tool_mode()
  self._emit_event({"type": "plan_start"})
  self._run_once(user_input)
  self._after_plan_turn()  # 不弹面板：headless 只保存
  plan = session.draft_plan
  if plan is None:
      self.had_error = True; self.error_kind = ErrorKind.PLAN_NOT_SUBMITTED
      self.error_message = "plan mode ended: model did not submit a plan"
  else:
      self._plan_output_plan = plan
      plan_mode.plan_audit("headless_saved", plan_id=plan.id, revision=plan.revision)
      self._emit_event({"type":"plan_ready","steps":len(plan.steps),"path":str(plan.path),"revision":plan.revision})
      if self.output_format == "text" and not self.quiet:
          sys.stdout.write(plan_markdown_for_stdout)  # body markdown（见 §12）
  session.cancel_draft(); self._sync_plan_tool_mode()
  self._finalize_headless()
  ```
  `_finalize_exit_code`：`error_kind == PLAN_NOT_SUBMITTED` → had_error 已置 1。
- 只加必要改动，不要重构现有 REPL/streaming 逻辑；`_finalize_headless`/JSON 合同保持。

## 10. `cmd_handler.py`（`plan-cli`）

`COMMAND_INFO` 增加（顺序放在 `/context` 附近）：
```python
CommandInfo(CMD_PLAN, "Plan mode: toggle, or plan a task; list/show/edit/review/resume/clear/abort",
            usage=f"{CMD_PLAN} [task|list [--all]|show [id]|edit|review [id]|resume [id]|clear [--done|--all]|abort]"),
CommandInfo(CMD_TODO, "Show the current plan todos"),
```
`CmdHandler.commands` 注册 `CMD_PLAN`、`CMD_TODO`；`handle_command` 的参数前缀匹配列表加入 `CMD_PLAN`。
`handle_plan(command_input)` 解析子命令（全部通过 `self.cli` 的 plan 方法，不允许直接操作 plan_store 状态机）：
- 无参数：`self.cli._toggle_plan_mode()`。
- `<task>`（非已知子命令）：REVIEWING → 打印 `a plan is waiting for review; approve or cancel it first`；
  否则进入 plan 模式（未进入时）→ 返回 task 字符串，让 REPL 作为普通 turn 发送（`/plan 调研 xxx`）。
- `list [--all]`：表格 `ID / STATUS / REV / UPDATED / GOAL`（宽度做上限），`--all` 时跨项目；无计划打印 `no plans yet`。
- `show [id]`：打印 `plan.to_markdown()`（Rich `Markdown`）或 `plan not found: <id>`；无当前计划同理。
- `edit`：当前 plan（draft/in-progress）→ `plan_mode.edit_plan_file`，失败打印 `invalid plan file: <path>: <reason>`。
- `review [id]`：从磁盘载入 draft → `self.cli._review_plan_from_disk(...)`（CLI 设置 session.draft/active 后走面板）。
- `resume [id]`：draft → 面板（`/plan review` 语义）；in-progress → 直接 EXECUTING + `_execute_plan()`；
  `plan is already in progress in another session` 冲突提示（实现：frontmatter session_id 与当前 chat.date 不同 → 提示，`--force` 不做）。
- `clear [--done|--all]`：`Prompt.ask(... default="n")` 确认后 `plan_store.clear_plans`；`--done` 只清终态；无参数时打印用法。
  非交互（`self.cli.interactive` 假）→ 打印 `plan clear needs an interactive confirmation`。
- `abort`：无 active plan 提示；否则确认后 `plan_mode.abort_plan`，打印 `plan aborted · todos cleared`。
`handle_todo()`：打印表格 `# / ID / STATUS / STEP`，结尾 `plan: <id> · <status> · revision N`；无计划打印 `no plan in this session`。
`CMD_PLAN`/`CMD_TODO` 的 help 文案同步 `cli.print_help()`（print_help 自动渲染 COMMAND_INFO，无需额外改；
但欢迎 banner/help 的 Shift+Tab 行要改）。

## 11. `printer.py`（`plan-cli`）

新增（不要改 `display_stream`/`_confirm_tool_call` 现有行为）：
```python
def show_plan_panel(self, plan: Plan, *, revision: bool = False, diff: Optional[RevisionDiff] = None) -> None
    # Panel(title=("Plan revision N: <id>" if revision else "Plan ready: <id>"), border_style="magenta")
    # 非修订：Goal: ... / Steps: N. title / File: <shorten_path>
    # 修订：diff.summary() / diff.detail_lines() / diff.todo_impact(todos)（todo 影响文本由 plan_mode 给出时直接渲染）
    # 所有模型文本用 untrusted_text/safe_text；路径用 safe_text
def ask_plan_decision(self, *, revision: bool = False) -> str
    # 交互：prompt_toolkit.prompt(消息, key_bindings=...) 支持 a/e/r/s + Esc；返回 "approve"|"edit"|"redo"|"save"|"cancel"
    # 消息非修订： "[a]pprove & execute  [e]dit  [r]edo  [s]ave only  [Esc]cancel: "
    # 消息修订：   "[a]pply & continue  [e]dit  [r]edo  [Esc]cancel revision: "
    # 非交互 fallback：返回 "save"
```
Esc 绑定用 `from prompt_toolkit.key_binding import KeyBindings`：`kb.add("a")`, `"e"`, `"r"`, `"s"`, `"escape"` 各自
`event.app.exit(result="...")`；prompt_toolkit 的 prompt 在非 TTY 测试里会被 mock（测试 patch `yaicli.cli._prompt_function` 或
printer 的 `_prompt_function`；实现时用与 cli.py 相同的 lazy-import 模式，便于测试替换 `printer.Prompt` 之类的 seam）。
`print_help()` 的 Shift+Tab 行改为：`Press [bold yellow]Shift+Tab[/bold yellow] to toggle plan mode (normal ↔ plan, read-only)`；
欢迎 banner 之外再加一行 `Plan mode: Shift+Tab / /plan · plan files under <config-dir>/plans`（PLAN_ENABLED=false 时改为 `Plan mode: disabled (PLAN_ENABLED=false)`）。

## 12. `entry.py`（`plan-cli`）

- `HeadlessOptions` 增加：
  ```python
  plan = typer.Option(False, "--plan", help="One-shot planning run: explore read-only, save the plan and exit without executing it.", rich_help_panel="Headless Options")
  ```
  `main(..., plan: bool = HeadlessOptions.plan)`；docstring 例子加一行。
- 校验（放在现有 `--json` 冲突检查之后）：
  - `plan and (shell or code)` → `_print_error("Error: --plan cannot be combined with --shell/--code.")` + `typer.Exit(2)`；
  - `plan` 令 `chat=False`（若同时给了 `--chat`/`--resume` → `_warn(...ignored with --plan; running one-shot.)`）；
  - `plan` 且 `not cfg.get("PLAN_ENABLED", True)` → `_print_error("Error: --plan requires PLAN_ENABLED=true.")` + exit 2；
  - `plan` 且没有 prompt/无 stdin → exit 2 的既有"no prompt provided"路径即可（`plan` 本身不能 REPL）。
- `cli.configure_headless(..., plan=plan)`。

## 13. 用户可见字符串（逐字，供 CLI/docs/测试共用）

```
[plan] 💬 >                                   # plan 模式提示符（REPL 输入行）
plan mode · read-only                         # 进入 plan 模式时打印的状态行（dim）
[plan] exploring (read-only) …                # enter researching
[plan] revising (read-only) …                 # enter revising
plan mode off
✗ plan_shell_denied: <reason>
[a]pprove & execute  [e]dit  [r]edo  [s]ave only  [Esc]cancel: 
[a]pply & continue  [e]dit  [r]edo  [Esc]cancel revision: 
✓ plan approved · exiting plan mode · todo seeded (N steps)
✓ revision N applied · plan.md updated in place · resuming execution at <Sx>
✓ saved as draft (<path>) · exit plan mode
plan cancelled; draft saved at <path>
revision discarded
✓ plan done · N/N steps
[plan] execution paused at N/M steps · /plan resume to continue · /plan abort to abandon
  ⚠ unfinished plan found: <id> (draft, revision 1)
  Use /plan review to continue it, or /plan list to see all plans.
  ⚠ unfinished plan found: <id> (in-progress, revision 2)
  Use /plan resume to continue it, or /plan list to see all plans.
saved plan not found/inconsistent; starting in normal mode
plan mode ended: model did not submit a plan
plan is already in progress in another session
plan not found: <id>
no plans yet
no plan in this session
a plan is waiting for review; approve or cancel it first
current TOOL_POLICY=readonly would deny writes; switch to standard? [y/N]
plan mode is disabled (PLAN_ENABLED=false)
```
审批面板（Rich Panel）标题：`Plan ready: <id>` / `Plan revision <N>: <id>`；内容行
`Goal: <goal>`、`Steps:`、` 1. <title>`、`File: <shortened path>`；修订：
`Changes: +N step  ~N step  -N steps`、` + S5 <title>`、` ~ S4 <title>`、` - S3 <title>`、`Todo impact: ...`。
todo 进度行（每个 in_progress/completed/blocked 变化打一行）：`[todo 2/4] S2 <title>`。
headless text 输出的计划正文 = `plan.to_markdown()` 的 `# Plan` 之后部分（或整篇；测试断言包含 `## Steps` 与步骤标题即可）。

## 14. 测试与门禁

每个 owner 必须：
- 新测试文件写在 §0 自己的作用域；用 `tmp_path` 做 plans 目录（`cfg["PLAN_DIR"]` 用 `monkeypatch.setitem(cfg, "PLAN_DIR", str(tmp_path / "plans"))`），
  严禁读写真实 `~/.config/yaicli`；provider/网络/编辑器/子进程全部 mock。
- 全局 plan session 的测试必须用 fixture `reset_global_plan_session`（Lead 会加在 `tests/conftest.py`：
  `plan_mode.reset_plan_session()` + `tools.set_plan_tool_mode(None)`，yield 前后都清）；`plan-core` 可以先把 fixture 写在自己的测试文件里
  （`tests/test_plan_mode.py` 顶部 autouse fixture），Lead 之后可提到 conftest。**不要修改 conftest.py**（Lead 所有）。
- `client.plan_session` 的测试：直接构造 `LLMClient.__new__` 或 MagicMock client？沿 `tests/llms/test_client.py` 的现有模式
  （用 `LLMClient` 实例 + mock provider）；plan 分支可以只构造 `PlanSession(mode="researching")` 注入。
- 质量门禁（自己的文件）：
  `uv run pytest tests/test_plan_store.py tests/test_plan_shell.py -q`
  `uv run pytest tests/test_plan_mode.py tests/test_todo_write.py tests/test_plan_revision.py tests/test_plan_shell_gate.py -q`
  `uv run pytest tests/test_plan_commands.py tests/test_plan_resume.py tests/test_plan_execution.py tests/test_headless_plan.py -q`
  `ruff check --no-fix <自己的文件>`（`ruff format <自己的文件>` 只格式化自己的文件）
- 完成时向 Lead 报告：改了哪些文件、测试命令与结果、遗留问题/接口偏差。

## 15. 验收标准映射（最终由 Lead 核对）

① 零写入：plan 模式 schema 过滤 + gate 拒绝 + audit；② Shift+Tab//plan 切换 + 提示符/状态行；③ submit_plan 唯一出口 + 结构化校验错误；
④ `[a]` 退出模式/恢复工具/seed todo/立即执行；⑤ todo_write 1:1 + 单 in_progress + 回写 md；⑥ plans 目录 0700/0600 + 项目隔离 +
PLAN_KEEP 清理 + 项目目录零新增；⑦ 修订原地更新 + 状态保留 + diff；⑧ --resume 永远 normal + 未完成提示；⑨ --plan JSON 三键 + exit 0/1；
⑩ 只读 shell 白名单/拒绝/审计/开关；⑪ 全量回归绿 + bench gate；⑫ /compact、K24/K25 交互（K24/K25 本期未实现：
记录为 deferred，不写 checks/checkpoint 代码，测试只覆盖 /compact 不丢 plan 字段）；⑬ 文档四处 + /help/banner 快捷键。

## 16. 已知边界（本期明确不做）

- 不做 K24 checks / K25 checkpoint（roadmap 后续任务）；`finish_plan` 不跑 checks，`✓ plan done` 不打印 checks 段。
- 不做跨项目 `/plan list --all` 之外的计划库管理；不做 plan 阶段子 agent；不做自动进入 plan mode。
- 不做 `--plan` 与 `--verify` 冲突提示（`--verify` 尚不存在）。
- 不做多终端并发锁（只在 `/plan resume` 时按 session_id 提示冲突）。
