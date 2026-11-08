import os
import signal
import sys
import traceback
from pathlib import Path
from typing import Annotated, Any, List, Optional

import typer

from . import __version__ as yaicli_version
from .config import cfg
from .console import get_error_console, untrusted_text
from .const import DEFAULT_CONFIG_INI, DEFAULT_OUTPUT_FORMAT, DefaultRoleNames, JustifyEnum, StrEnum
from .errors import (
    EXIT_EPIPE,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_SIGINT,
    EXIT_TOOL_DENIED,
)
from .exceptions import YaicliError

try:  # v0.19 K21: config files are materialised lazily on first real run.
    from .config import ensure_config_file
except ImportError:  # pragma: no cover - older config module without lazy writes
    ensure_config_file = None  # type: ignore[assignment]


class OutputFormat(StrEnum):  # type: ignore
    """Machine-readable output modes for the v0.19 headless contract."""

    TEXT = "text"
    JSON = "json"
    STREAM_JSON = "stream-json"


class YaiApp(typer.Typer):
    """Typer app that makes a closed pipe a clean, non-failing exit.

    ``ai --help | head -1`` used to die with exit code 1 because Rich converts
    ``BrokenPipeError`` into ``SystemExit(1)``. On POSIX we restore the default
    ``SIGPIPE`` disposition before the command runs, so the process terminates
    quietly with the conventional 141 instead of surfacing an error. A
    ``BrokenPipeError`` that still reaches Python is silenced the same way.
    """

    def __call__(self, *args: Any, **kwargs: Any):
        _enable_default_sigpipe()
        try:
            return super().__call__(*args, **kwargs)
        except BrokenPipeError:
            _silence_broken_pipe()
            raise SystemExit(EXIT_EPIPE) from None


def _enable_default_sigpipe() -> None:
    """Restore SIGPIPE's default disposition (POSIX) so ``| head`` exits 141."""
    if not hasattr(signal, "SIGPIPE"):  # pragma: no cover - Windows
        return
    try:
        if signal.getsignal(signal.SIGPIPE) != signal.SIG_DFL:
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ValueError, OSError):  # pragma: no cover - non-main thread/platform
        pass


def _silence_broken_pipe() -> None:
    """Point stdout at /dev/null so interpreter shutdown does not re-raise EPIPE."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except (OSError, ValueError, AttributeError):  # pragma: no cover - exotic platforms
        pass


def _warn(message: str) -> None:
    """Print a warning to stderr (stdout is reserved for results)."""
    get_error_console().print(f"Warning: {message}", style="yellow")


def _print_error(message: str) -> None:
    """Print an error to stderr without interpreting untrusted text as markup."""
    get_error_console().print(untrusted_text(message), style="red")


def _resolve_exit_code(cli: Any) -> int:
    """Map the public CLI state contract to a process exit code.

    The CLI resolves ``exit_code`` itself; the attribute fallbacks keep mocked /
    legacy CLI objects working and document the contract:

    - 0 success, 1 handled error / depth limit, 2 usage (typer),
    - 3 denied tool when ``--fail-on-tool-denied``, 130 SIGINT, 141 EPIPE.
    """
    code = getattr(cli, "exit_code", None)
    if type(code) is int:
        return code
    if getattr(cli, "interrupted", False) is True:
        return EXIT_SIGINT
    if getattr(cli, "fail_on_tool_denied", False) is True and getattr(cli, "tool_denied", False) is True:
        return EXIT_TOOL_DENIED
    if getattr(cli, "had_error", False) is True:
        return EXIT_ERROR
    if getattr(cli, "depth_limit_reached", False) is True:
        return EXIT_ERROR
    return EXIT_OK


# ---------------------------------------------------------------------------
# Lazily imported option callbacks (K08)
#
# Typer introspects these signatures when the app is built, so the proxies must exist
# at import time. The heavy modules behind them (role/chat/functions/provider registry)
# are imported only when the matching flag is actually used, keeping --help/--template
# from importing the whole CLI stack.
# ---------------------------------------------------------------------------


def _role_check(value: str) -> str:
    from .role import RoleManager

    return RoleManager.check_id_ok(value)


def _role_create(value: str) -> None:
    from .role import RoleManager

    RoleManager.create_role_option(value)


def _role_delete(value: str) -> None:
    from .role import RoleManager

    RoleManager.delete_role_option(value)


def _role_list(_: Any) -> None:
    from .role import RoleManager

    RoleManager.print_list_option(_)


def _role_show(value: str) -> None:
    from .role import RoleManager

    RoleManager.show_role_option(value)


def _chat_list(value: bool) -> bool:
    from .chat import FileChatManager

    return FileChatManager.print_list_option(value)


def _provider_list(_: Any) -> None:
    from .llms.provider import ProviderFactory

    ProviderFactory.list_providers(_)


def _install_functions_callback(cls: Any, value: Any) -> None:
    from .functions import install_functions

    install_functions(cls, value)


def _print_functions_callback(cls: Any, value: Any) -> None:
    from .functions import print_functions

    print_functions(cls, value)


def _reinstall_functions_callback(cls: Any, value: Any) -> None:
    from .functions import reinstall_functions

    reinstall_functions(cls, value)


def _print_mcp_callback(cls: Any, value: Any) -> None:
    from .functions import print_mcp

    print_mcp(cls, value)


def version_callback(value: bool):
    if value:
        typer.echo(f"yaicli {yaicli_version}")
        raise typer.Exit()


def override_config(
    ctx: typer.Context,  # noqa: F841
    param: typer.CallbackParam,
    value: Any,
):
    """Override config with input value if value not equal to option default."""
    if value != param.default and isinstance(param.name, str):
        cfg[param.name.upper()] = value
    return value


class LLMOptions:
    model = typer.Option(
        "",
        "--model",
        "-M",
        help="Specify the model to use.",
        rich_help_panel="LLM Options",
        callback=override_config,
    )

    temperature = typer.Option(
        cfg["TEMPERATURE"],
        "--temperature",
        "-T",
        help="Specify the temperature to use.",
        rich_help_panel="LLM Options",
        min=0.0,
        max=2.0,
        callback=override_config,
    )

    top_p = typer.Option(
        cfg["TOP_P"],
        "--top-p",
        "-P",
        help="Specify the top-p to use.",
        rich_help_panel="LLM Options",
        min=0.0,
        max=1.0,
        callback=override_config,
    )

    max_tokens = typer.Option(
        cfg["MAX_TOKENS"],
        "--max-tokens",
        help="Specify the max tokens to use.",
        rich_help_panel="LLM Options",
        min=1,
        callback=override_config,
    )

    stream = typer.Option(
        cfg["STREAM"],
        "--stream/--no-stream",
        help=f"Specify whether to stream the response. [dim](default: {'stream' if cfg['STREAM'] else 'no-stream'})[/dim]",
        rich_help_panel="LLM Options",
        show_default=False,
        callback=override_config,
    )


class RoleOptions:
    role = typer.Option(
        cfg["DEFAULT_ROLE"],
        "--role",
        "-r",
        help="Specify the assistant role to use.",
        rich_help_panel="Role Options",
        callback=_role_check,
    )

    create_role = typer.Option(
        "",
        "--create-role",
        help="Create a new role with the specified name.",
        rich_help_panel="Role Options",
        callback=_role_create,
    )

    delete_role = typer.Option(
        "",
        "--delete-role",
        help="Delete a role with the specified name.",
        rich_help_panel="Role Options",
        callback=_role_delete,
    )

    list_roles = typer.Option(
        False,
        "--list-roles",
        help="List all available roles.",
        rich_help_panel="Role Options",
        callback=_role_list,
    )

    show_role = typer.Option(
        "",
        "--show-role",
        help="Show the role with the specified name.",
        rich_help_panel="Role Options",
        callback=_role_show,
    )


class ChatOptions:
    chat = typer.Option(
        False,
        "--chat",
        "-c",
        help="Start in interactive chat mode.",
        rich_help_panel="Chat Options",
    )

    resume = typer.Option(
        False,
        "--resume",
        help="Resume the most recent chat session for the current project.",
        rich_help_panel="Chat Options",
    )

    list_chats = typer.Option(
        False,
        "--list-chats",
        help="List saved chat sessions.",
        rich_help_panel="Chat Options",
        callback=_chat_list,
    )


class HeadlessOptions:
    print_mode = typer.Option(
        False,
        "--print",
        "-p",
        help="Explicit one-shot run: print the result only (no REPL, no prompts).",
        rich_help_panel="Headless Options",
    )

    output_format = typer.Option(
        OutputFormat(DEFAULT_OUTPUT_FORMAT),
        "--output-format",
        help="Output format: text, json or stream-json (NDJSON events).",
        rich_help_panel="Headless Options",
    )

    quiet = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Only print the answer on stdout (no labels, panels or progress).",
        rich_help_panel="Headless Options",
    )

    json_output = typer.Option(
        False,
        "--json",
        help="Shorthand for --output-format json (machine-readable one-shot output).",
        rich_help_panel="Headless Options",
    )

    max_turns = typer.Option(
        None,
        "--max-turns",
        help="Override the maximum number of tool-call rounds (MAX_TOOL_CALL_DEPTH).",
        rich_help_panel="Headless Options",
        min=1,
    )

    yes = typer.Option(
        False,
        "--yes",
        "-y",
        help="Non-interactive approval: auto-allow read-level tools only.",
        rich_help_panel="Headless Options",
    )

    allowed_tools = typer.Option(
        "",
        "--allowed-tools",
        help='Comma-separated per-run tool allowlist, glob patterns allowed (e.g. "fs_*,execute_shell_command").',
        rich_help_panel="Headless Options",
    )

    cwd = typer.Option(
        None,
        "--cwd",
        help="Run as if started in DIR; also used as the tool workspace root.",
        rich_help_panel="Headless Options",
    )

    fail_on_tool_denied = typer.Option(
        False,
        "--fail-on-tool-denied",
        help="Exit with code 3 when a tool call was denied.",
        rich_help_panel="Headless Options",
    )


class ShellOptions:
    shell = typer.Option(
        False,
        "--shell",
        "-s",
        help="Generate a shell command; in a non-interactive run only print it (execute with --yes).",
        rich_help_panel="Shell Options",
    )


class CodeOptions:
    code = typer.Option(
        False,
        "--code",
        help="Generate code in plaintext (non-interactive).",
        rich_help_panel="Code Options",
    )


class OtherOptions:
    version = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        rich_help_panel="Other Options",
        callback=version_callback,
        is_eager=True,
    )

    verbose = typer.Option(
        False,
        "--verbose",
        "-V",
        help="Show verbose output (e.g., loaded config).",
        rich_help_panel="Other Options",
    )

    template = typer.Option(
        False,
        "--template",
        help="Show the default config file template and exit.",
        rich_help_panel="Other Options",
    )

    list_providers = typer.Option(
        False,
        "--list-providers",
        help="List the available providers and exit.",
        rich_help_panel="Other Options",
        callback=_provider_list,
    )

    show_reasoning = typer.Option(
        cfg["SHOW_REASONING"],
        "--show-reasoning/--hide-reasoning",
        help=f"Show reasoning content from the LLM. [dim](default: {'show' if cfg['SHOW_REASONING'] else 'hide'})[/dim]",
        rich_help_panel="Other Options",
        show_default=False,
        callback=override_config,
    )

    justify = typer.Option(
        cfg["JUSTIFY"],
        "--justify",
        "-j",
        help="Specify the justify to use.",
        rich_help_panel="Other Options",
        callback=override_config,
    )


class MCPOptions:
    enable_mcp = typer.Option(
        cfg["ENABLE_MCP"],
        "--enable-mcp/--disable-mcp",
        help=f"Enable/disable MCP in API requests [dim](default: {'enabled' if cfg['ENABLE_MCP'] else 'disabled'})[/dim]",
        rich_help_panel="MCP Options",
        callback=override_config,
    )

    show_mcp_output = typer.Option(
        cfg["SHOW_MCP_OUTPUT"],
        "--show-mcp-output/--hide-mcp-output",
        help=f"Show the output of MCP [dim](default: {'show' if cfg['SHOW_MCP_OUTPUT'] else 'hide'})[/dim]",
        rich_help_panel="MCP Options",
        show_default=False,
        callback=override_config,
    )
    list_mcp = typer.Option(
        False,
        "--list-mcp",
        help="List all available mcp.",
        rich_help_panel="MCP Options",
        callback=_print_mcp_callback,
    )


class ImageOptions:
    image = typer.Option(
        None,
        "--image",
        "-i",
        help="Image file path or URL to include with the prompt. Can be specified multiple times.",
        rich_help_panel="Image Options",
    )


class FunctionOptions:
    install_functions = typer.Option(
        False,
        "--install-functions",
        help="Export editable copies of builtin functions (builtins load automatically; existing files are skipped).",
        rich_help_panel="Function Options",
        callback=_install_functions_callback,
    )

    list_functions = typer.Option(
        False,
        "--list-functions",
        help="List loaded tools and their source (builtin/user).",
        rich_help_panel="Function Options",
        callback=_print_functions_callback,
    )

    reinstall_functions = typer.Option(
        False,
        "--reinstall-functions",
        help="Refresh exported builtin function copies (preserves user-defined functions).",
        rich_help_panel="Function Options",
        callback=_reinstall_functions_callback,
    )

    enable_functions = typer.Option(
        cfg["ENABLE_FUNCTIONS"],
        "--enable-functions/--disable-functions",
        help=f"Enable/disable function calling in API requests [dim](default: {'enabled' if cfg['ENABLE_FUNCTIONS'] else 'disabled'})[/dim]",
        rich_help_panel="Function Options",
        show_default=False,
        callback=override_config,
    )

    show_function_output = typer.Option(
        cfg["SHOW_FUNCTION_OUTPUT"],
        "--show-function-output/--hide-function-output",
        help=f"Show the output of functions [dim](default: {'show' if cfg['SHOW_FUNCTION_OUTPUT'] else 'hide'})[/dim]",
        rich_help_panel="Function Options",
        show_default=False,
        callback=override_config,
    )

    enabled_tools = typer.Option(
        "",
        "--tools",
        help=(
            "Comma-separated tool-name globs to offer the model (empty = all tools; "
            "MCP tools use the _mcp__ prefix, e.g. fs_*,web_search or _mcp__github_*)."
        ),
        rich_help_panel="Function Options",
        callback=override_config,
    )


def _apply_cwd(cwd: str) -> str:
    """Validate ``--cwd``, chdir into it and use it as the tool workspace root."""
    target = Path(cwd).expanduser()
    try:
        if not target.is_dir():
            raise typer.BadParameter(f"Not a directory: {cwd}", param_hint="--cwd")
        resolved = str(target.resolve())
        os.chdir(resolved)
    except OSError as e:  # pragma: no cover - races/permission errors
        raise typer.BadParameter(f"Cannot use --cwd {cwd}: {e}", param_hint="--cwd") from None
    cfg["WORKSPACE_ROOT"] = resolved
    return resolved


def _parse_allowed_tools(raw: str) -> List[str]:
    """Parse the comma-separated ``--allowed-tools`` value into patterns."""
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _apply_run_tool_policy(cli: Any, *, yes: bool, allowed_tools: List[str]) -> None:
    """Forward the per-run approval flags (``--yes`` / ``--allowed-tools``) to the gate.

    ``CLI.configure_headless`` stores the flags for the public state contract; the tool
    gate consults the *approval manager*, so the K06 policy is mirrored there. The
    lookup is duck-typed: tests replace the CLI/client with mocks, and a manager
    without the v2 run-policy API simply keeps its old behaviour.
    """
    client = getattr(cli, "client", None)
    approval = getattr(client, "approval", None)
    configure_run = getattr(approval, "configure_run", None)
    if not callable(configure_run):
        return
    try:
        configure_run(yes=bool(yes), allowed_tools=list(allowed_tools))
    except Exception:  # pragma: no cover - policy plumbing must never block a run
        pass


app = YaiApp(
    name="yaicli",
    help="YAICLI - A lightweight agent in your terminal.",
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,  # Let the CLI handle errors gracefully
    rich_markup_mode="rich",  # Render rich text in help messages
)


@app.command()
def main(
    ctx: typer.Context,
    prompt: Annotated[
        Optional[str], typer.Argument(help="The prompt to send to the LLM. Reads from stdin if available.")
    ] = None,
    # ------------------- LLM Options -------------------
    model: str = LLMOptions.model,  # noqa: F841
    temperature: float = LLMOptions.temperature,  # noqa: F841
    top_p: float = LLMOptions.top_p,  # noqa: F841
    max_tokens: int = LLMOptions.max_tokens,  # noqa: F841
    stream: bool = LLMOptions.stream,  # noqa: F841
    # ------------------- Role Options -------------------
    role: str = RoleOptions.role,
    create_role: str = RoleOptions.create_role,  # noqa: F841
    delete_role: str = RoleOptions.delete_role,  # noqa: F841
    list_roles: bool = RoleOptions.list_roles,  # noqa: F841
    show_role: str = RoleOptions.show_role,  # noqa: F841
    # ------------------- Chat Options -------------------
    chat: bool = ChatOptions.chat,
    resume: bool = ChatOptions.resume,
    list_chats: bool = ChatOptions.list_chats,  # noqa: F841
    # ------------------- Headless Options -------------------
    print_mode: bool = HeadlessOptions.print_mode,
    output_format: OutputFormat = HeadlessOptions.output_format,
    quiet: bool = HeadlessOptions.quiet,
    json_output: bool = HeadlessOptions.json_output,
    max_turns: Optional[int] = HeadlessOptions.max_turns,
    yes: bool = HeadlessOptions.yes,
    allowed_tools: str = HeadlessOptions.allowed_tools,
    cwd: Optional[str] = HeadlessOptions.cwd,
    fail_on_tool_denied: bool = HeadlessOptions.fail_on_tool_denied,
    # ------------------- Shell Options -------------------
    shell: bool = ShellOptions.shell,
    # ------------------- Code Options -------------------
    code: bool = CodeOptions.code,
    # ------------------- Other Options -------------------
    version: Optional[bool] = OtherOptions.version,  # noqa: F841
    verbose: bool = OtherOptions.verbose,
    template: bool = OtherOptions.template,
    list_providers: bool = OtherOptions.list_providers,  # noqa: F841
    show_reasoning: bool = OtherOptions.show_reasoning,  # noqa: F841
    justify: JustifyEnum = OtherOptions.justify,  # noqa: F841
    # ------------------- Function Options -------------------
    install_functions: bool = FunctionOptions.install_functions,  # noqa: F841
    reinstall_functions: bool = FunctionOptions.reinstall_functions,  # noqa: F841
    list_functions: bool = FunctionOptions.list_functions,  # noqa: F841
    enable_functions: bool = FunctionOptions.enable_functions,  # noqa: F841
    show_function_output: bool = FunctionOptions.show_function_output,  # noqa: F841
    enabled_tools: str = FunctionOptions.enabled_tools,  # noqa: F841
    # ------------------- MCP Options -------------------
    enable_mcp: bool = MCPOptions.enable_mcp,  # noqa: F841
    show_mcp_output: bool = MCPOptions.show_mcp_output,  # noqa: F841
    list_mcp: bool = MCPOptions.list_mcp,  # noqa: F841
    # ------------------- Image Options -------------------
    image: Optional[List[str]] = ImageOptions.image,
):
    """YAICLI: a lightweight agent in your terminal.

    Call with a PROMPT to get a direct answer, use --shell to generate a command, or use
    --chat for an interactive session.

    Scripting: stdout only carries the result, diagnostics go to stderr, and the exit code
    is script-friendly (0 ok / 1 error / 2 usage / 3 denied / 130 SIGINT / 141 EPIPE).
    Use -p/--print with --output-format json (or stream-json) for machine-readable output.

    Example:
        ai "What is the capital of France?"
        ai -p "Summarize this file" > summary.md
        ai -p "List the TODO comments in src" --output-format json | jq -r .content
        ai -p "Summarize this repo" --json | jq -r .content
        echo "error log" | ai -p "Explain these errors"
        ai -p "Run the tests and summarize failures" -y --fail-on-tool-denied
        ai --code "Write a fibonacci generator in Python"
        ai --chat "What's the meaning of life"  # Start a chat session with a title
        ai --chat  # Start a temporary chat session
        ai --resume  # Continue the newest chat session of this project
        ai --shell "Start docker image python:3.13.5-alpine3.22 with ports 8080"
    """
    if template:
        print(DEFAULT_CONFIG_INI)
        raise typer.Exit()

    # ``--json`` is the documented shorthand for ``--output-format json``.
    if json_output and output_format is not OutputFormat.JSON:
        if output_format is not OutputFormat.TEXT:
            _print_error(f"Error: --json conflicts with --output-format {output_format.value}.")
            raise typer.Exit(code=2)
        output_format = OutputFormat.JSON

    # --cwd must be applied before relative prompt/image paths are resolved.
    resolved_cwd = _apply_cwd(cwd) if cwd else None
    if max_turns is not None:
        cfg["MAX_TOOL_CALL_DEPTH"] = max_turns

    # ``--resume`` is an interactive mode: it implies --chat (v0.21 K13).
    if resume:
        chat = True

    # Structured output and -p are explicit one-shot modes: a REPL cannot emit
    # one JSON document (and must not mix prompts with machine output).
    if (print_mode or output_format is not OutputFormat.TEXT) and chat:
        if resume:
            _warn("--resume is ignored with --print/--output-format; running one-shot.")
        else:
            _warn("--chat is ignored with --print/--output-format; running one-shot.")
        chat = False
        resume = False

    # # Combine prompt argument with stdin content if available
    final_prompt = prompt
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read().strip()
        if stdin_content:
            if final_prompt:
                # Prepend stdin content to the argument prompt
                final_prompt = f"{stdin_content}\n\n{final_prompt}"
            else:
                final_prompt = stdin_content
        # prompt_toolkit will raise EOFError if stdin is redirected
        # Set chat to False to prevent starting interactive mode.
        if chat:
            if resume:
                _warn("--resume is ignored when stdin was redirected.")
            else:
                _warn("--chat is ignored when stdin was redirected.")
            chat = False
            resume = False
    if not any([final_prompt, chat, image]):
        if output_format is not OutputFormat.TEXT:
            # Machine-readable output must not degrade into a help screen.
            _print_error("Error: no prompt provided (pass a prompt or pipe stdin with --output-format).")
            raise typer.Exit(code=2)
        print(ctx.get_help())
        return

    # Process image arguments
    image_data_list = []
    if image:
        from .image import process_image_source

        for img_source in image:
            try:
                image_data_list.append(process_image_source(img_source))
            except typer.BadParameter as e:
                _print_error(f"Error: {e}")
                raise typer.Exit(1)

    # Allow image-only invocation (no text prompt). CLI.run() aborts on a falsy prompt,
    # so send a minimal non-empty prompt along with the images.
    if image_data_list and not final_prompt and not chat:
        final_prompt = "Describe the image." if len(image_data_list) == 1 else "Describe these images."

    if not any([final_prompt is not None, chat]):
        print(ctx.get_help())
        return

    # # Use build-in role for --shell or --code mode
    if role and role != DefaultRoleNames.DEFAULT and (shell or code):
        _warn("--role is ignored when --shell or --code is used.")
        role = DefaultRoleNames.DEFAULT

    from yaicli.cli import CLI

    role = CLI.evaluate_role_name(code, shell, role)
    allowed_tool_patterns = _parse_allowed_tools(allowed_tools)
    output_format_value = output_format.value

    # v0.19 K21: the config file is created on first real run, never for
    # --version/--help/--template/--list-* (those paths return before this point).
    if ensure_config_file is not None:
        try:
            ensure_config_file()
        except Exception:  # pragma: no cover - helper is documented as never raising
            pass

    cli = None
    try:
        # Instantiate the main CLI class with the specified role. The headless
        # intent (K04 D3) is passed to the constructor so the console/printer/
        # client/prompt_toolkit setup is already correct before any output.
        cli = CLI(
            verbose=verbose,
            role=role,
            print_mode=print_mode,
            output_format=output_format_value,
            quiet=quiet,
        )
        # Apply the v0.19 headless contract (state attributes live on the CLI).
        cli.configure_headless(
            print_mode=print_mode,
            output_format=output_format_value,
            quiet=quiet,
            yes=yes,
            allowed_tools=allowed_tool_patterns,
            fail_on_tool_denied=fail_on_tool_denied,
            max_turns=max_turns,
            cwd=resolved_cwd,
            resume=resume,
        )
        # v0.19 K06: expose --yes/--allowed-tools to the tool gate (per-run grants).
        _apply_run_tool_policy(cli, yes=yes, allowed_tools=allowed_tool_patterns)
        # Run the appropriate mode
        cli.run(
            chat=chat,
            shell=shell,
            code=code,
            user_input=final_prompt,
            images=image_data_list,
        )
    except typer.Exit:
        # Explicit exit requests keep their code.
        raise
    except typer.BadParameter:
        # Usage errors are formatted by click with exit code 2.
        raise
    except BrokenPipeError:
        # A closed pipe is a success for the producer: never print a traceback.
        raise typer.Exit(code=EXIT_EPIPE) from None
    except KeyboardInterrupt:
        # SIGINT during a one-shot run: one short stderr line, exit 130.
        get_error_console().print("Interrupted.", style="yellow")
        raise typer.Exit(code=EXIT_SIGINT) from None
    except YaicliError as e:
        # Classified errors carry a user-facing message with an actionable hint.
        detail = getattr(e, "user_message", None) or str(e)
        _print_error(f"YAICLI Error: {detail}")
        raise typer.Exit(code=EXIT_ERROR)
    except typer.Abort:
        # Abort is a non-zero outcome (e.g. no input, client creation failed);
        # let typer/click handle it instead of swallowing it as a success.
        raise
    except Exception as e:
        _print_error(f"Unknown error: {e}")
        if verbose:
            traceback.print_exc()
        raise typer.Exit(code=EXIT_ERROR)

    if not chat and cli is not None:
        # Non-chat runs expose their outcome through the CLI state contract
        # (exit_code / interrupted / had_error / tool_denied / depth_limit_reached).
        raise typer.Exit(code=_resolve_exit_code(cli))


if __name__ == "__main__":
    app()
