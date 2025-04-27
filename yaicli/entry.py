import sys
from typing import Annotated, Optional, Any

import typer

from yaicli.chat_manager import FileChatManager
from yaicli.cli import CLI
from yaicli.config import cfg
from yaicli.const import DEFAULT_CONFIG_INI, DefaultRoleNames, JustifyEnum
from yaicli.roles import RoleManager

app = typer.Typer(
    name="yaicli",
    help="YAICLI - Yet Another AI CLI Interface.",
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,  # Let the CLI handle errors gracefully
    rich_markup_mode="rich",  # Render rich text in help messages
)


def override_config(
    ctx: typer.Context,  # noqa: F841
    param: typer.CallbackParam,
    value: Any,
):
    """Override config with input value."""
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
        "-M",
        help="Specify the max tokens to use.",
        rich_help_panel="LLM Options",
        min=1,
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
    # ------------------- Shell Options -------------------
    shell: bool = typer.Option(
        False,
        "--shell",
        "-s",
        help="Generate and optionally execute a shell command (non-interactive).",
        rich_help_panel="Shell Options",
    ),
    # ------------------- Code Options -------------------
    code: bool = typer.Option(
        False,
        "--code",
        help="Generate and optionally execute a code block (non-interactive).",
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
        help=f"Show reasoning content from the LLM. [dim](default: {cfg['SHOW_REASONING']})[/dim]",
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
):
    """YAICLI: Your AI assistant in the command line.

    Call with a PROMPT to get a direct answer, use --shell to execute as command, or use --chat for an interactive session.
    """
    if template:
        print(DEFAULT_CONFIG_INI)
        raise typer.Exit()

    # Combine prompt argument with stdin content if available
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

    # Basic validation for conflicting options or missing prompt
    if not any([final_prompt, chat, list_chats, list_roles, create_role]):
        # If no prompt, not starting chat, and not listing chats or roles, show help
        typer.echo(ctx.get_help())
        raise typer.Exit()

    if role and role != DefaultRoleNames.DEFAULT and (shell or code):
        print("Warning: --role is ignored when --shell or --code is used.")
        role = DefaultRoleNames.DEFAULT

    if code:
        role = DefaultRoleNames.CODER

    try:
        # Instantiate the main CLI class with the specified role
        cli_instance = CLI(verbose=verbose, role=role)

        # Run the appropriate mode
        cli_instance.run(
            chat=chat,
            shell=shell,
            input=final_prompt,
            role=role,
        )
    except Exception as e:
        # Catch potential errors during CLI initialization or run
        print(f"An error occurred: {e}")
        if verbose:
            import traceback

            traceback.print_exc()
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
