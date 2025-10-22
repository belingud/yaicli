import sys
from typing import Annotated, Any, Optional

import typer

from .chat import FileChatManager
from .config import cfg
from .const import DEFAULT_CONFIG_INI, DefaultRoleNames, JustifyEnum
from .exceptions import YaicliError
from .functions import (
    MCP_DETAILS_ALL_FLAG,
    install_functions,
    print_functions,
    print_mcp,
    print_mcp_details,
)
from .llms.provider import ProviderFactory
from .role import RoleManager

app = typer.Typer(
    name="yaicli",
    help="YAICLI - Your AI assistant in command line.",
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,  # Let the CLI handle errors gracefully
    rich_markup_mode="rich",  # Render rich text in help messages
)


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
        callback=RoleManager.check_id_ok,
    )

    create_role = typer.Option(
        "",
        "--create-role",
        help="Create a new role with the specified name.",
        rich_help_panel="Role Options",
        callback=RoleManager.create_role_option,
    )

    delete_role = typer.Option(
        "",
        "--delete-role",
        help="Delete a role with the specified name.",
        rich_help_panel="Role Options",
        callback=RoleManager.delete_role_option,
    )

    list_roles = typer.Option(
        False,
        "--list-roles",
        help="List all available roles.",
        rich_help_panel="Role Options",
        callback=RoleManager.print_list_option,
    )

    show_role = typer.Option(
        "",
        "--show-role",
        help="Show the role with the specified name.",
        rich_help_panel="Role Options",
        callback=RoleManager.show_role_option,
    )


class ChatOptions:
    chat = typer.Option(
        False,
        "--chat",
        "-c",
        help="Start in interactive chat mode.",
        rich_help_panel="Chat Options",
    )

    list_chats = typer.Option(
        False,
        "--list-chats",
        help="List saved chat sessions.",
        rich_help_panel="Chat Options",
        callback=FileChatManager.print_list_option,
    )


class ShellOptions:
    shell = typer.Option(
        False,
        "--shell",
        "-s",
        help="Generate and optionally execute a shell command (non-interactive).",
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
        callback=ProviderFactory.list_providers,
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
        callback=print_mcp,
    )
    list_mcp_details = typer.Option(
        None,
        "--list-mcp-details",
        help="Show MCP configuration and tools. Optionally filter by MCP name.",
        rich_help_panel="MCP Options",
        flag_value=MCP_DETAILS_ALL_FLAG,
        callback=print_mcp_details,
        show_default=False,
        metavar="[MCP_NAME]",
    )


class FunctionOptions:
    install_functions = typer.Option(
        False,
        "--install-functions",
        help="Install default functions.",
        rich_help_panel="Function Options",
        callback=install_functions,
    )

    list_functions = typer.Option(
        False,
        "--list-functions",
        help="List all available functions.",
        rich_help_panel="Function Options",
        callback=print_functions,
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
    list_chats: bool = ChatOptions.list_chats,  # noqa: F841
    # ------------------- Shell Options -------------------
    shell: bool = ShellOptions.shell,
    # ------------------- Code Options -------------------
    code: bool = CodeOptions.code,
    # ------------------- Other Options -------------------
    verbose: bool = OtherOptions.verbose,
    template: bool = OtherOptions.template,
    list_providers: bool = OtherOptions.list_providers,  # noqa: F841
    show_reasoning: bool = OtherOptions.show_reasoning,  # noqa: F841
    justify: JustifyEnum = OtherOptions.justify,  # noqa: F841
    # ------------------- Function Options -------------------
    install_functions: bool = FunctionOptions.install_functions,  # noqa: F841
    list_functions: bool = FunctionOptions.list_functions,  # noqa: F841
    enable_functions: bool = FunctionOptions.enable_functions,  # noqa: F841
    show_function_output: bool = FunctionOptions.show_function_output,  # noqa: F841
    # ------------------- MCP Options -------------------
    enable_mcp: bool = MCPOptions.enable_mcp,  # noqa: F841
    show_mcp_output: bool = MCPOptions.show_mcp_output,  # noqa: F841
    list_mcp: bool = MCPOptions.list_mcp,  # noqa: F841
    list_mcp_details: Optional[str] = MCPOptions.list_mcp_details,  # noqa: F841
):
    """YAICLI: Your AI assistant in the command line.

    Call with a PROMPT to get a direct answer, use --shell to execute as command, or use --chat for an interactive session.

    Example:
        ai "What is the capital of France?"
        ai --code "Write a fibonacci generator in Python"
        ai --chat "What's the meaning of life"  # Start a chat session with a title
        ai --chat  # Start a temporary chat session
        ai --shell "Start docker image python:3.13.5-alpine3.22 with ports 8080 and map current dir to /app in container"
    """
    if template:
        print(DEFAULT_CONFIG_INI)
        raise typer.Exit()

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
            print("Warning: --chat is ignored when stdin was redirected.")
            chat = False
    if not any([final_prompt, chat]):
        print(ctx.get_help())
        return

    # # Use build-in role for --shell or --code mode
    if role and role != DefaultRoleNames.DEFAULT and (shell or code):
        print("Warning: --role is ignored when --shell or --code is used.")
        role = DefaultRoleNames.DEFAULT

    from yaicli.cli import CLI

    role = CLI.evaluate_role_name(code, shell, role)

    try:
        # Instantiate the main CLI class with the specified role
        cli = CLI(verbose=verbose, role=role)
        # Run the appropriate mode
        cli.run(
            chat=chat,
            shell=shell,
            code=code,
            user_input=final_prompt,
        )
    except YaicliError as e:
        typer.echo(f"YAICLI Error: {e}")
    except (typer.Abort, typer.Exit):
        pass
    except Exception as e:
        typer.echo(f"Unknown error: {e}")


if __name__ == "__main__":
    app()
