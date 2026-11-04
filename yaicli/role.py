import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, TypeVar

import typer
from rich.table import Table

from .config import cfg
from .console import YaiConsole, get_console, safe_text, untrusted_text
from .const import DEFAULT_ROLES, ROLES_DIR, DefaultRoleNames
from .utils import detect_os, detect_shell, option_callback

T = TypeVar("T")


@dataclass
class Role:
    name: str
    prompt: str
    variables: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("Role must have a non-empty name")

        if not self.prompt or not isinstance(self.prompt, str):
            raise ValueError("Role must have a non-empty description")

        if not self.variables:
            self.variables = {"_os": detect_os(cfg), "_shell": detect_shell(cfg)}
        self.prompt = self.prompt.format(**self.variables)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RoleManager:
    roles: Dict[str, Role] = field(default_factory=dict)
    roles_dir: Path = ROLES_DIR
    console: YaiConsole = get_console()

    def __post_init__(self) -> None:
        # Never seed/write role files at import time (v0.19 K21): default roles
        # live in memory, user files are read when present, and disk writes only
        # happen on explicit create/modify/delete. This keeps read-only HOMEs and
        # ``--version``/``--help``/``--list-*`` write-free.
        self._load_default_roles()
        self._load_user_roles()

    def _write_role_file(self, role: Role) -> bool:
        """Persist one role JSON file. Best effort, never raises."""
        role_path = self.roles_dir / f"{role.name}.json"
        try:
            self.roles_dir.mkdir(parents=True, exist_ok=True)
            with open(role_path, "w", encoding="utf-8") as f:
                json.dump(role.to_dict(), f, indent=2)
            return True
        except OSError as e:
            self.console.print(
                f"Warning: could not save role {safe_text(role.name)} to {safe_text(str(role_path))}: "
                f"{safe_text(str(e))}",
                style="yellow",
            )
            return False

    def _load_default_roles(self) -> None:
        """Load default roles"""
        for name, role_dict in DEFAULT_ROLES.items():
            self.roles[name] = Role(**role_dict)

    def _load_user_roles(self) -> None:
        """Load user-defined roles, user can overwrite default roles"""
        if not self.roles_dir.exists():
            return

        try:
            role_files = list(self.roles_dir.glob("*.json"))
        except OSError as e:  # pragma: no cover - unreadable roles dir
            self.console.print(
                f"Warning: could not read roles directory {safe_text(str(self.roles_dir))}: {safe_text(str(e))}",
                style="yellow",
            )
            return

        for filename in role_files:
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    role_dict = json.load(f)
                    role = Role(**role_dict)
                    self.roles[role.name] = role
            except OSError as e:
                self.console.print(f"Error loading role from {safe_text(filename)}: {safe_text(e)}", style="red")
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                self.console.print(f"Error loading role from {safe_text(filename)}: {safe_text(e)}", style="red")

    def get_role(self, name: str) -> Role:
        """Get a role by name"""
        if name not in self.roles:
            raise ValueError(f"Role '{name}' does not exist.")
        return self.roles[name]

    def _warn_builtin_role_modification(self, name: str) -> None:
        """Warn when a built-in role is about to be modified, if enabled.

        Custom (user) roles never trigger this warning. The check is gated by
        the ``ROLE_MODIFY_WARNING`` config value (default: enabled).
        """
        if name not in DEFAULT_ROLES:
            return
        if not cfg.get("ROLE_MODIFY_WARNING", True):
            return

        self.console.print(
            f"Warning: modifying built-in role '{safe_text(name)}'. "
            "Set ROLE_MODIFY_WARNING=false to disable this warning.",
            style="yellow",
        )

    def create_role(self, name: str, description: str) -> Role:
        """Create and save a new role.

        The role is always added to the in-memory registry; persisting the JSON
        file is best effort so a read-only config directory does not crash.
        """
        self._warn_builtin_role_modification(name)
        role = Role(name=name, prompt=description)
        self.roles[name] = role

        # Save to file (best effort, never raises)
        self._write_role_file(role)

        return role

    def delete_role(self, name: str) -> bool:
        """Delete a role"""
        self._warn_builtin_role_modification(name)

        # Delete role file (best effort: a read-only dir only warns)
        role_path = self.roles_dir / f"{name}.json"
        try:
            if role_path.exists():
                role_path.unlink()
        except OSError as e:
            self.console.print(
                f"Warning: could not delete role file {safe_text(str(role_path))}: {safe_text(str(e))}",
                style="yellow",
            )

        # Delete role from memory
        if name in self.roles:
            del self.roles[name]
            return True

        return False

    def list_roles(self) -> list:
        """List all available roles info"""
        roles_list = []
        for role_id, role in sorted(self.roles.items()):
            roles_list.append(
                {
                    "id": role_id,
                    "name": role.name,
                    "prompt": role.prompt,
                    "is_default": role_id in DEFAULT_ROLES,
                    "filepath": self.roles_dir / f"{role_id}.json",
                }
            )
        return roles_list

    @classmethod
    @option_callback
    def print_list_option(cls, _: Any):
        """Print the list of roles.
        This method is a cli option callback.
        """
        table = Table(show_header=True, show_footer=False)
        table.add_column("Name", style="dim")
        table.add_column("Filepath", style="dim")
        # Built-in roles live in memory and are not written to disk at startup
        # (v0.19 K21), so merge them into the listing: a fresh/read-only HOME
        # still shows the built-in roles instead of an empty table.
        try:
            files = sorted(cls.roles_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
        except OSError:  # pragma: no cover - unreadable roles dir
            files = []
        seen_names = set()
        rows = []
        for file in files:
            if file.stem in seen_names:
                continue
            seen_names.add(file.stem)
            rows.append((file.stem, file))
        for name in sorted(DEFAULT_ROLES):
            if name in seen_names:
                continue
            rows.append((name, cls.roles_dir / f"{name}.json"))
        for name, path in rows:
            # Role file names are user-controlled: render them literally.
            table.add_row(untrusted_text(name), untrusted_text(str(path)))
        cls.console.print(table)
        cls.console.print("Use `ai --show-role <name>` to view a role.", style="dim")

    @classmethod
    @option_callback
    def create_role_option(cls, value: str) -> None:
        """Create role option callback"""
        if not value:
            return

        role_manager = RoleManager()

        # Check if role name already exists
        if value in role_manager.roles:
            cls.console.print(f"Role '{safe_text(value)}' already exists.", style="red")
            return

        # Get role description
        description = typer.prompt("Enter role description")

        # Create role
        role = role_manager.create_role(value, description)
        cls.console.print(f"Created role: {safe_text(role.name)}", style="green")

    @classmethod
    @option_callback
    def delete_role_option(cls, value: str) -> None:
        """Delete role option callback"""
        if not value:
            return

        role_manager = RoleManager()

        # Check if role exists
        if value not in role_manager.roles:
            cls.console.print(f"Role '{safe_text(value)}' does not exist.", style="yellow")
            return

        # Delete role
        if role_manager.delete_role(value):
            cls.console.print(f"Deleted role: {safe_text(value)}", style="green")
        else:
            cls.console.print(f"Failed to delete role: {safe_text(value)}", style="red")

    @classmethod
    @option_callback
    def show_role_option(cls, value: str) -> None:
        """Show role option callback"""
        if not value:
            return

        role_manager = RoleManager()

        # Check if role exists
        role = role_manager.get_role(value)
        if not role:
            cls.console.print(f"Role '{safe_text(value)}' does not exist.", style="red")
            return

        # Show role information (name/prompt are user-controlled: render literally)
        cls.console.print(f"[bold]Name:[/bold] {safe_text(role.name)}")
        cls.console.print(f"[bold]Description:[/bold] {safe_text(role.prompt)}")

    @classmethod
    def check_id_ok(cls, value: str) -> str:
        """Check if role ID is valid option callback"""
        if not value:
            # Empty value is valid
            return value
        if value in DEFAULT_ROLES:
            # Built-in role is valid
            return value

        role_manager = RoleManager()

        if value not in role_manager.roles:
            cls.console.print(f"Role '{safe_text(value)}' does not exist. Using default role.", style="red")
            return DefaultRoleNames.DEFAULT

        return value


role_mgr = RoleManager()
