import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, TypeVar

import typer
from rich.table import Table

from .config import cfg
from .console import YaiConsole, get_console
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
        self._ensure_roles_dir()
        self._load_default_roles()
        self._load_user_roles()

    def _ensure_roles_dir(self) -> None:
        """Ensure the roles directory exists, and create default roles if they don't exist"""
        self.roles_dir.mkdir(parents=True, exist_ok=True)
        for role in DEFAULT_ROLES.values():
            if not (self.roles_dir / f"{role['name']}.json").exists():
                with open(self.roles_dir / f"{role['name']}.json", "w") as f:
                    json.dump(role, f, indent=2)

    def _load_default_roles(self) -> None:
        """Load default roles"""
        for name, role_dict in DEFAULT_ROLES.items():
            self.roles[name] = Role(**role_dict)

    def _load_user_roles(self) -> None:
        """Load user-defined roles, user can overwrite default roles"""
        if not self.roles_dir.exists():
            return

        for filename in self.roles_dir.glob("*.json"):
            try:
                with open(filename, "r") as f:
                    role_dict = json.load(f)
                    role = Role(**role_dict)
                    self.roles[role.name] = role
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                self.console.print(f"Error loading role from {filename}: {e}", style="red")

    def get_role(self, name: str) -> Role:
        """Get a role by name"""
        if name not in self.roles:
            raise ValueError(f"Role '{name}' does not exist.")
        return self.roles[name]

    def create_role(self, name: str, description: str) -> Role:
        """Create and save a new role"""
        role = Role(name=name, prompt=description)
        self.roles[name] = role

        # Save to file
        role_path = self.roles_dir / f"{name}.json"
        with open(role_path, "w") as f:
            json.dump(role.to_dict(), f, indent=2)

        return role

    def delete_role(self, name: str) -> bool:
        """Delete a role"""

        # Delete role file
        role_path = self.roles_dir / f"{name}.json"
        if role_path.exists():
            role_path.unlink()

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

    def print_roles(self) -> None:
        """Print all role information"""
        table = Table("Name", "Description", "Temperature", "Top-P", title="Available Roles")

        for role in self.list_roles():
            table.add_row(
                role.name,
                role.prompt,
                str(role.temperature),
                str(role.top_p),
            )

        self.console.print(table)

    @classmethod
    @option_callback
    def print_list_option(cls, _: Any):
        """Print the list of roles.
        This method is a cli option callback.
        """
        table = Table(show_header=True, show_footer=False)
        table.add_column("Name", style="dim")
        table.add_column("Filepath", style="dim")
        for file in sorted(cls.roles_dir.glob("*.json"), key=lambda f: f.stat().st_mtime):
            table.add_row(file.stem, str(file))
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
            cls.console.print(f"Role '{value}' already exists.", style="red")
            return

        # Get role description
        description = typer.prompt("Enter role description")

        # Create role
        role = role_manager.create_role(value, description)
        cls.console.print(f"Created role: {role.name}", style="green")

    @classmethod
    @option_callback
    def delete_role_option(cls, value: str) -> None:
        """Delete role option callback"""
        if not value:
            return

        role_manager = RoleManager()

        # Check if role exists
        if value not in role_manager.roles:
            cls.console.print(f"Role '{value}' does not exist.", style="yellow")
            return

        # Delete role
        if role_manager.delete_role(value):
            cls.console.print(f"Deleted role: {value}", style="green")
        else:
            cls.console.print(f"Failed to delete role: {value}", style="red")

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
            cls.console.print(f"Role '{value}' does not exist.", style="red")
            return

        # Show role information
        cls.console.print(f"[bold]Name:[/bold] {role.name}")
        cls.console.print(f"[bold]Description:[/bold] {role.prompt}")

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
            cls.console.print(f"Role '{value}' does not exist. Using default role.", style="red")
            return DefaultRoleNames.DEFAULT

        return value


role_mgr = RoleManager()
