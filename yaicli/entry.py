import sys
from typing import Annotated, Optional

import typer

from yaicli.cli import CLI
from yaicli.const import DEFAULT_CONFIG_INI

app = typer.Typer(
    name="yaicli",
    help="YAICLI - Yet Another AI CLI Interface.",
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,  # Let the CLI handle errors gracefully
    add_completion=False,  # Disable default shell completion for now
)


@app.command()
def main(
    ctx: typer.Context,
    prompt: Annotated[
        Optional[str], typer.Argument(help="The prompt to send to the LLM. Reads from stdin if available.")
    ] = None,
    chat: Annotated[
        bool, typer.Option("--chat", "-c", help="Start in interactive chat mode.", rich_help_panel="Mode Options")
    ] = False,
    shell: Annotated[
        bool,
        typer.Option(
            "--shell",
            "-s",
            help="Generate and optionally execute a shell command (non-interactive).",
            rich_help_panel="Mode Options",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose", "-V", help="Show verbose output (e.g., loaded config).", rich_help_panel="Other Options"
        ),
    ] = False,
    template: Annotated[
        bool,
        typer.Option(
            "--template", help="Show the default config file template and exit.", rich_help_panel="Other Options"
        ),
    ] = False,
):  # Removed trailing comma
    """YAICLI: Your AI assistant in the command line.

    Call with a PROMPT to get a direct answer, use --shell to execute as command,
    or use --chat for an interactive session.
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

    # Basic validation for conflicting options or missing prompt
    if not final_prompt and not chat:
        # If no prompt and not starting chat, show help
        typer.echo(ctx.get_help())
        raise typer.Exit()
    if chat and final_prompt:
        # Warn if both chat mode and a prompt are given (prompt will be ignored)
        # Or, could use the prompt as the first message in chat mode
        print("Warning: Starting in chat mode. Initial prompt argument will be ignored.")

    try:
        # Instantiate the main CLI class
        cli_instance = CLI(verbose=verbose)
        # Run the appropriate mode
        cli_instance.run(chat=chat, shell=shell, prompt=final_prompt)
    except Exception as e:
        # Catch potential errors during CLI initialization or run
        print(f"An error occurred: {e}")
        if verbose:
            import traceback

            traceback.print_exc()
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
