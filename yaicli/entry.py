import sys
from typing import Annotated, Any, Optional

import typer

from .chat import FileChatManager
from .config import cfg
from .const import DEFAULT_CONFIG_INI, DefaultRoleNames, JustifyEnum
from .functions import install_functions, print_functions
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


@app.command()
def main(
    ctx: typer.Context,
    prompt: Annotated[
        Optional[str], typer.Argument(help="The prompt to send to the LLM. Reads from stdin if available.")
    ] = None,
    # ------------------- LLM Options -------------------
    model: str = typer.Option(  # noqa: F841
        "",
        "--model",
        "-M",
        help="Specify the model to use.",
        rich_help_panel="LLM Options",
        callback=override_config,
    ),
    temperature: float = typer.Option(  # noqa: F841
        cfg["TEMPERATURE"],
        "--temperature",
        "-T",
        help="Specify the temperature to use.",
        rich_help_panel="LLM Options",
        min=0.0,
        max=2.0,
        callback=override_config,
    ),
    top_p: float = typer.Option(  # noqa: F841
        cfg["TOP_P"],
        "--top-p",
        "-P",
        help="Specify the top-p to use.",
        rich_help_panel="LLM Options",
        min=0.0,
        max=1.0,
        callback=override_config,
    ),
    max_tokens: int = typer.Option(  # noqa: F841
        cfg["MAX_TOKENS"],
        "--max-tokens",
        help="Specify the max tokens to use.",
        rich_help_panel="LLM Options",
        min=1,
        callback=override_config,
    ),
    stream: bool = typer.Option(  # noqa: F841
        cfg["STREAM"],
        "--stream/--no-stream",
        help=f"Specify whether to stream the response. [dim](default: {'stream' if cfg['STREAM'] else 'no-stream'})[/dim]",
        rich_help_panel="LLM Options",
        show_default=False,
        callback=override_config,
    ),
    # ------------------- Role Options -------------------
    role: str = typer.Option(
        DefaultRoleNames.DEFAULT,
        "--role",
        "-r",
        help="Specify the assistant role to use.",
        rich_help_panel="Role Options",
        callback=RoleManager.check_id_ok,
    ),
    create_role: str = typer.Option(
        "",
        "--create-role",
        help="Create a new role with the specified name.",
        rich_help_panel="Role Options",
        callback=RoleManager.create_role_option,
    ),
    delete_role: str = typer.Option(  # noqa: F841
        "",
        "--delete-role",
        help="Delete a role with the specified name.",
        rich_help_panel="Role Options",
        callback=RoleManager.delete_role_option,
    ),
    list_roles: bool = typer.Option(
        False,
        "--list-roles",
        help="List all available roles.",
        rich_help_panel="Role Options",
        callback=RoleManager.print_list_option,
    ),
    show_role: str = typer.Option(  # noqa: F841
        "",
        "--show-role",
        help="Show the role with the specified name.",
        rich_help_panel="Role Options",
        callback=RoleManager.show_role_option,
    ),
    # ------------------- Chat Options -------------------
    chat: bool = typer.Option(
        False,
        "--chat",
        "-c",
        help="Start in interactive chat mode.",
        rich_help_panel="Chat Options",
    ),
    # # ------------------- Shell Options -------------------
    shell: bool = typer.Option(
        False,
        "--shell",
        "-s",
        help="Generate and optionally execute a shell command (non-interactive).",
        rich_help_panel="Shell Options",
    ),
    # # ------------------- Code Options -------------------
    code: bool = typer.Option(
        False,
        "--code",
        help="Generate code in plaintext (non-interactive).",
        rich_help_panel="Code Options",
    ),
    # ------------------- Chat Options -------------------
    list_chats: bool = typer.Option(
        False,
        "--list-chats",
        help="List saved chat sessions.",
        rich_help_panel="Chat Options",
        callback=FileChatManager.print_list_option,
    ),
    # ------------------- Other Options -------------------
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-V",
        help="Show verbose output (e.g., loaded config).",
        rich_help_panel="Other Options",
    ),
    template: bool = typer.Option(
        False,
        "--template",
        help="Show the default config file template and exit.",
        rich_help_panel="Other Options",
    ),
    show_reasoning: bool = typer.Option(  # noqa: F841
        cfg["SHOW_REASONING"],
        "--show-reasoning/--hide-reasoning",
        help=f"Show reasoning content from the LLM. [dim](default: {'show' if cfg['SHOW_REASONING'] else 'hide'})[/dim]",
        rich_help_panel="Other Options",
        show_default=False,
        callback=override_config,
    ),
    justify: JustifyEnum = typer.Option(  # noqa: F841
        cfg["JUSTIFY"],
        "--justify",
        "-j",
        help="Specify the justify to use.",
        rich_help_panel="Other Options",
        callback=override_config,
    ),
    # ------------------- Function Options -------------------
    install_functions: bool = typer.Option(  # noqa: F841
        False,
        "--install-functions",
        help="Install default functions.",
        rich_help_panel="Function Options",
        callback=install_functions,
    ),
    list_functions: bool = typer.Option(  # noqa: F841
        False,
        "--list-functions",
        help="List all available functions.",
        rich_help_panel="Function Options",
        callback=print_functions,
    ),
    enable_functions: bool = typer.Option(  # noqa: F841
        cfg["ENABLE_FUNCTIONS"],
        "--enable-functions/--disable-functions",
        help=f"Enable/disable function calling in API requests [dim](default: {'enabled' if cfg['ENABLE_FUNCTIONS'] else 'disabled'})[/dim]",
        rich_help_panel="Function Options",
        show_default=False,
        callback=override_config,
    ),
    show_function_output: bool = typer.Option(  # noqa: F841
        cfg["SHOW_FUNCTION_OUTPUT"],
        "--show-function-output/--hide-function-output",
        help=f"Show the output of functions [dim](default: {'show' if cfg['SHOW_FUNCTION_OUTPUT'] else 'hide'})[/dim]",
        rich_help_panel="Function Options",
        show_default=False,
        callback=override_config,
    ),
):
    """YAICLI: Your AI assistant in the command line.

    Call with a PROMPT to get a direct answer, use --shell to execute as command, or use --chat for an interactive session.
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

    # Instantiate the main CLI class with the specified role
    cli = CLI(verbose=verbose, role=role)

    # Run the appropriate mode
    cli.run(
        chat=chat,
        shell=shell,
        code=code,
        user_input=final_prompt,
    )


if __name__ == "__main__":
    app()
