"""Tool dispatch and its guarded side effects, output capture and result channel."""

import json
import os
from typing import Any, Dict, Optional, Tuple, cast

from json_repair import repair_json

from ..console import safe_text, strip_control_chars
from ..schemas import ToolCall
from . import output_history, workspace
from .display import _tool_call_caption, announce_tool_call, display_tool_result
from .function import get_function
from .limits import (
    format_arguments_text,
    summarize_arguments,
    truncate_tool_output_meta,
)
from .schemas import (
    MCP_TOOL_NAME_PREFIX,
    get_plan_tool_mode,
    plan_allows_readonly_shell,
)

_SHELL_GUARDRAIL_ENV = (
    ("TOOL_TIMEOUT", "YAI_TOOL_TIMEOUT"),
    ("TOOL_ENV_INHERIT", "YAI_TOOL_ENV_INHERIT"),
    ("WORKSPACE_ROOT", "YAI_WORKSPACE_ROOT"),
    ("TOOL_OUTPUT_MAX_CHARS", "YAI_TOOL_OUTPUT_MAX_CHARS"),
)


def parse_mcp_tool_name(name: str) -> str:
    """Parse MCP tool name - remove the prefix _mcp__ from the tool name."""
    return name.removeprefix(MCP_TOOL_NAME_PREFIX)


def get_mcp(name: str):
    """Lazy import and get MCP tool"""
    from .mcp import get_mcp as _get_mcp

    return _get_mcp(name)


def _sync_shell_guardrail_env(config: Any) -> None:
    """Best-effort: expose config tool guardrails via environment variables.

    The shell tool and the workspace write guard (``tools/workspace.py``) run as
    standalone code that cannot import ``cfg``; the only way to pass configuration
    is the environment. ``cfg`` is env-first (``YAI_*`` > config.ini > defaults):
    for a user-exported variable the value written back is the same one that was
    loaded from the environment. When the CLI overrides configuration at runtime —
    notably ``--cwd``, which writes the resolved directory to
    ``cfg["WORKSPACE_ROOT"]`` — the config value deliberately wins over a stale
    environment variable. Empty/unset values are skipped so the tool's own defaults
    apply.
    """
    try:
        for config_key, env_key in _SHELL_GUARDRAIL_ENV:
            try:
                value = config.get(config_key)
            except Exception:  # pragma: no cover - mocked/broken config mapping
                continue
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                value = "true" if value else "false"
            try:
                os.environ[env_key] = str(value)
            except (OSError, ValueError):  # pragma: no cover - exotic environments
                continue
    except Exception:  # pragma: no cover - env propagation must never block tool calls
        pass


def _emit_tool_result(
    result_text: Any,
    *,
    console: Any,
    kind: str,
    name: str,
    preview_arguments: str,
    full_arguments: str = "",
    caption: str,
    show_output: bool,
) -> str:
    """Truncate, record and display one tool result (successful or guard-denied).

    ``preview_arguments`` is the compact one-line summary shown on the announce
    line and, as a fallback, in the viewer list; ``full_arguments`` is the
    complete pretty-printed argument text kept for the Ctrl+O detail pane.

    Returns the model-visible text. Guard denials go through the same pipeline as
    successful results, so the terminal/``Ctrl+O`` view and the model context stay
    consistent.
    """
    result_meta = truncate_tool_output_meta(result_text, name)
    # K02: bound what enters the conversation. The same truncated text is shown
    # in the terminal panel, so a huge result can not flood either channel.
    result = result_meta.text
    # Terminal display is head-only and independent from the model-facing cap;
    # Ctrl+O opens the full-screen viewer with every output of the current turn.
    display_text = strip_control_chars(result)
    output_history.record_output(
        kind=kind,
        name=name,
        arguments=preview_arguments,
        text=display_text,
        caption=caption,
        total_chars=result_meta.total_chars,
        spill_path=result_meta.spill_path,
        truncated=result_meta.truncated,
        full_arguments=full_arguments,
    )
    if show_output:
        display_tool_result(console, display_text, kind)
    return result


def _execute_plan_mode_call(
    tool_call: ToolCall,
    arguments: Dict[str, Any],
    *,
    config: Any,
    console: Any,
    kind: str,
    preview_arguments: str,
    full_arguments: str = "",
    caption: str,
    show_output: bool,
) -> Optional[Tuple[str, bool]]:
    """Run one plan-mode-only tool call, or return ``None`` for the normal path.

    ``preview_arguments`` is the compact announce-line summary; ``full_arguments``
    is the complete argument text recorded for the Ctrl+O detail pane.

    Handles (v0.24 K23, only active while ``set_plan_tool_mode`` selected a mode):

    * session tools (``submit_plan`` / ``todo_write``): they mutate the plan/todo
      state only — never the workspace and never the approval/audit gate. The
      result is recorded but the output panel is suppressed (the CLI renders the
      approval panel / todo progress instead).
    * the controlled read-only shell while planning: the command is validated by
      :mod:`yaicli.plan_shell` first; a denial becomes the model-facing
      ``plan_shell_denied`` JSON plus one red REPL line and one audit event, an
      allowed command runs with the plan-shell guardrails (argv only, no shell).
    """
    from ..planning import service as plan_mode

    name = tool_call.name
    if name in plan_mode.SESSION_TOOL_NAMES:
        from . import session_tools

        try:
            text = session_tools.execute_session_tool(name, arguments)
        except BaseException:
            import sys

            module = sys.modules.get("yaicli.checkpoints")
            capture = module.current_capture() if module is not None else None
            if capture is not None:
                capture.barrier = True
            raise
        result = _emit_tool_result(
            text,
            console=console,
            kind=kind,
            name=name,
            preview_arguments=preview_arguments,
            full_arguments=full_arguments,
            caption=caption,
            # The tool result is the session state JSON; the plan/todo panel is the
            # user-facing view, so don't print a duplicate output panel.
            show_output=False,
        )
        return result, True

    if name != plan_mode.PLAN_SHELL_TOOL:
        return None
    session = plan_mode.get_plan_session()
    if not session.is_plan_mode:
        return None
    if not plan_allows_readonly_shell(config):
        # Defence in depth for the direct dispatch path (the client gate already
        # refuses the tool because it is not advertised); never run the command.
        denied = json.dumps(
            {
                "success": False,
                "error": "tool_not_available_in_mode",
                "reason": "execute_shell_command is not available in plan mode (PLAN_ALLOW_READONLY_SHELL=false).",
                "hint": "Use fs_read_file / fs_search_files, or enable PLAN_ALLOW_READONLY_SHELL.",
            },
            ensure_ascii=False,
        )
        result = _emit_tool_result(
            denied,
            console=console,
            kind=kind,
            name=name,
            preview_arguments=preview_arguments,
            full_arguments=full_arguments,
            caption=caption,
            show_output=False,
        )
        return result, True

    from .. import plan_shell

    command = arguments.get("command")
    verdict = plan_shell.validate_plan_shell_command(command)
    if not verdict.allowed:
        reason = str(verdict.reason)
        hint = str(verdict.hint or "")
        denied = json.dumps({"error": "plan_shell_denied", "reason": reason, "hint": hint}, ensure_ascii=False)
        # REPL-visible denial line (console is TTY-aware: machine mode goes to stderr).
        console.print(f"✗ plan_shell_denied: {safe_text(reason)}", style="red")
        plan_mode.plan_audit("shell_denied", command=command, reason=reason)
        result = _emit_tool_result(
            denied,
            console=console,
            kind=kind,
            name=name,
            preview_arguments=preview_arguments,
            full_arguments=full_arguments,
            caption=caption,
            show_output=False,
        )
        return result, True

    import sys

    module = sys.modules.get("yaicli.checkpoints")
    capture = module.current_capture() if module is not None else None
    if capture is not None:
        capture.barrier = True
    result_text = plan_shell.run_plan_shell(
        verdict.argv,
        cwd=arguments.get("cwd"),
        timeout=arguments.get("timeout"),
    )
    plan_mode.plan_audit("shell", command=command, decision="allowed")
    result = _emit_tool_result(
        result_text,
        console=console,
        kind=kind,
        name=name,
        preview_arguments=preview_arguments,
        full_arguments=full_arguments,
        caption=caption,
        show_output=show_output,
    )
    return result, True


def execute_tool_call(tool_call: ToolCall, announce: bool = True, *, config: Any, console: Any) -> Tuple[str, bool]:
    """Execute a tool call and return the result

    Args:
        tool_call: The tool call to execute
        announce: Whether to print the "@... call" line. Set False when the call was
            already shown to the user (e.g., by a confirmation prompt) to avoid duplication.

    Returns:
        Tuple[str, bool]: (result text, success flag)
    """
    is_function_call = not tool_call.name.startswith(MCP_TOOL_NAME_PREFIX)
    if is_function_call:
        get_tool_func = get_function
        show_output = config["SHOW_FUNCTION_OUTPUT"]
        _type = "function"
    else:
        tool_call.name = parse_mcp_tool_name(tool_call.name)
        get_tool_func = get_mcp
        show_output = config["SHOW_MCP_OUTPUT"]
        _type = "mcp"

    # Tool name/arguments are model output: never let them act as Rich markup
    # or emit terminal control sequences here. Arguments are compacted as well:
    # a single huge content/command value must not wrap over several screens.
    preview_arguments = summarize_arguments(tool_call.arguments)

    if announce:
        announce_tool_call(console, _type, tool_call.name, preview_arguments)

    # v0.24 K23: in plan/execution mode the session tools (submit_plan/todo_write)
    # and the read-only shell gate are dispatched BEFORE the builtin lookup: session
    # tools are not entries of the function map, so the normal "get the tool" step
    # would reject them. The normal path (no plan tool mode) keeps its ordering.
    arguments: Dict[str, Any] | None = None
    caption = ""
    # Complete argument text for the Ctrl+O detail pane; the announce line keeps
    # using the compact ``preview_arguments`` summary above.
    full_arguments = ""
    if is_function_call and get_plan_tool_mode() is not None:
        try:
            parsed_arguments = repair_json(tool_call.arguments, return_objects=True)
            if not isinstance(parsed_arguments, dict):
                error_msg = f"Invalid arguments type: {parsed_arguments!r}, should be JSON object"
                console.print(safe_text(error_msg), style="red")
                return error_msg, False
            arguments = cast(dict, parsed_arguments)
        except Exception as e:
            error_msg = f"Invalid arguments from llm: {e}\nRaw arguments: {tool_call.arguments!r}"
            console.print(safe_text(error_msg), style="red")
            return error_msg, False
        caption = _tool_call_caption(arguments)
        full_arguments = format_arguments_text(arguments)
        plan_result = _execute_plan_mode_call(
            tool_call,
            arguments,
            config=config,
            console=console,
            kind=_type,
            preview_arguments=preview_arguments,
            full_arguments=full_arguments,
            caption=caption,
            show_output=show_output,
        )
        if plan_result is not None:
            return plan_result

    # 1. Get the tool
    try:
        tool = get_tool_func(tool_call.name)
    except ValueError as e:
        error_msg = f"{_type.title()} '{tool_call.name!r}' not exists: {e}"
        console.print(safe_text(error_msg), style="red")
        return error_msg, False

    # 2. Parse tool arguments (already parsed for the plan-mode branch above)
    if arguments is None:
        try:
            parsed_arguments = repair_json(tool_call.arguments, return_objects=True)
            if not isinstance(parsed_arguments, dict):
                error_msg = f"Invalid arguments type: {parsed_arguments!r}, should be JSON object"
                console.print(safe_text(error_msg), style="red")
                return error_msg, False
            arguments = cast(dict, parsed_arguments)
        except Exception as e:
            error_msg = f"Invalid arguments from llm: {e}\nRaw arguments: {tool_call.arguments!r}"
            console.print(safe_text(error_msg), style="red")
            return error_msg, False
        caption = _tool_call_caption(arguments)
        full_arguments = format_arguments_text(arguments)

    # 3. Execute the tool
    try:
        # K03/K11 integration: the standalone shell tool and the workspace write
        # guard both read their configuration from the environment. Propagate the
        # (env-first) config values right before a shell call or a filesystem
        # mutation so config.ini / ``--cwd`` control them.
        if is_function_call and (
            tool_call.name == "execute_shell_command" or tool_call.name in workspace.MUTATING_TOOL_NAMES
        ):
            _sync_shell_guardrail_env(config)
        guard_plan = None
        if is_function_call and tool_call.name in workspace.MUTATING_TOOL_NAMES:
            # K11: workspace confinement + protected paths + pre-mutation backups.
            # A denial is an in-band result (ok=True below): the call reached the
            # tool path, the model reads actionable JSON and the filesystem is
            # untouched. The guard never raises and never prints.
            with workspace.mutation_lock():
                guard_plan = workspace.prepare_mutation(tool_call.name, arguments)
                if guard_plan.denial is not None:
                    result_text = guard_plan.denial
                else:
                    import sys

                    checkpoint_module = sys.modules.get("yaicli.checkpoints")
                    capture = checkpoint_module.current_capture() if checkpoint_module is not None else None
                    if capture is not None:
                        if getattr(tool, "source", "builtin") != "builtin":
                            capture.barrier = True
                        capture.prepare(
                            guard_plan.build_undo_entry(),
                            [
                                str(arguments[key])
                                for key in ("file_path", "path", "destination")
                                if isinstance(arguments.get(key), str)
                            ],
                        )
                    try:
                        result_text = tool.execute(**arguments)
                    except BaseException:
                        if capture is not None:
                            capture.barrier = True
                        raise
                    succeeded = workspace.tool_result_succeeded(result_text)
                    if checkpoint_module is not None:
                        checkpoint_module.record_mutation(guard_plan.build_undo_entry(), succeeded)
                    if guard_plan.has_originals and succeeded:
                        workspace.push_undo(guard_plan.build_undo_entry())
        else:
            # Only an active interactive capture loads checkpoints on non-file calls.
            import sys

            checkpoint_module = sys.modules.get("yaicli.checkpoints")
            capture = checkpoint_module.current_capture() if checkpoint_module is not None else None
            if capture is not None and (
                not is_function_call
                or tool_call.name == "execute_shell_command"
                or getattr(tool, "source", "builtin") != "builtin"
            ):
                capture.barrier = True
            result_text = tool.execute(**arguments)
        result = _emit_tool_result(
            result_text,
            console=console,
            kind=_type,
            name=tool_call.name,
            preview_arguments=preview_arguments,
            full_arguments=full_arguments,
            caption=caption,
            show_output=show_output,
        )
        return result, True
    except Exception as e:
        error_msg = f"Call {_type} error: {e}\n{_type} name: {tool_call.name!r}\nArguments: {arguments!r}"
        console.print(safe_text(error_msg), style="red")
        return error_msg, False
