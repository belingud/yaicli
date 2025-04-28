import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from yaicli.config import cfg
from yaicli.console import get_console
from yaicli.const import DEFAULT_ROLES, ROLES_DIR, DefaultRoleNames
from yaicli.exceptions import RoleAlreadyExistsError, RoleCreationError
from yaicli.utils import detect_os, detect_shell, option_callback


class Role:
    def __init__(
        self, name: str, prompt: str, variables: Optional[Dict[str, Any]] = None, filepath: Optional[str] = None
    ):
        self.name = name
        self.prompt = prompt
        if not variables:
            variables = {"_os": detect_os(cfg), "_shell": detect_shell(cfg)}
        self.variables = variables
        self.filepath = filepath

        self.prompt = self.prompt.format(**self.variables)

    def to_dict(self) -> Dict[str, Any]:
        """Convert Role to dictionary for serialization"""
        return {
            "name": self.name,
            "prompt": self.prompt,
        }

    @classmethod
    def from_dict(cls, role_id: str, data: Dict[str, Any], filepath: Optional[str] = None) -> "Role":
        """Create Role object from dictionary"""
        return cls(
            name=data.get("name", role_id),
            prompt=data.get("prompt", ""),
            variables=data.get("variables", {}),
            filepath=filepath,
        )

    def __str__(self):
        return f"Role(name={self.name}, prompt={self.prompt[:30]}...)"


class RoleManager:
    roles_dir: Path = ROLES_DIR
    console: Console = get_console()

    def __init__(self):
        self.roles: Dict[str, Role] = self._load_roles()

    def _load_roles(self) -> Dict[str, Role]:
        """Load all role configurations"""
        roles = {}
        self.roles_dir.mkdir(parents=True, exist_ok=True)

        # Check if any role files exist
        role_files: list[Path] = list(self.roles_dir.glob("*.json"))

        if not role_files:
            # Fast path: no existing roles, just create defaults
            for role_id, role_config in DEFAULT_ROLES.items():
                role_file = self.roles_dir / f"{role_id}.json"
                filepath = str(role_file)
                roles[role_id] = Role.from_dict(role_id, role_config, filepath)
                with role_file.open("w", encoding="utf-8") as f:
                    json.dump(role_config, f, indent=2)
            return roles

        # Load existing role files
        for role_file in role_files:
            role_id = role_file.stem
            filepath = str(role_file)
            try:
                with role_file.open("r", encoding="utf-8") as f:
                    role_data = json.load(f)
                    roles[role_id] = Role.from_dict(role_id, role_data, filepath)
            except Exception as e:
                self.console.print(f"Error loading role {role_id}: {e}", style="red")

        # Ensure default roles exist
        for role_id, role_config in DEFAULT_ROLES.items():
            if role_id not in roles:
                role_file = self.roles_dir / f"{role_id}.json"
                filepath = str(role_file)
                roles[role_id] = Role.from_dict(role_id, role_config, filepath)
                with role_file.open("w", encoding="utf-8") as f:
                    json.dump(role_config, f, indent=2)

        return roles

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
                    "filepath": role.filepath,
                }
            )
        return roles_list

    @classmethod
    @option_callback
    def show_role_option(cls, name: str):
        """Show a role's prompt.
        This method is a cli option callback.
        """
        self = cls()
        role = self.get_role(name)
        if not role:
            self.console.print(f"Role '{name}' does not exist", style="red")
            return
        self.console.print(role.prompt)

    def get_role(self, role_id: str) -> Optional[Role]:
        """Get role by ID"""
        return self.roles.get(role_id)

    @classmethod
    def check_id_ok(cls, role_id: str):
        """Check if role exists by ID.
        This method is a cli option callback.
        If role does not exist, exit with error.
        """
        if not role_id:
            return role_id
        self = cls()
        if not self.role_exists(role_id):
            self.console.print(f"Role '{role_id}' does not exist", style="red")
            raise typer.Abort()
        return role_id

    def role_exists(self, role_id: str) -> bool:
        """Check if role exists"""
        return role_id in self.roles

    def save_role(self, role_id: str, role: Role) -> None:
        """Save role configuration"""
        try:
            self.roles[role_id] = role
            role_file = self.roles_dir / f"{role_id}.json"
            role.filepath = str(role_file)
            with role_file.open("w", encoding="utf-8") as f:
                json.dump(role.to_dict(), f, indent=2)
        except Exception as e:
            raise RoleCreationError(f"RoleCreationError {e}") from e

    @classmethod
    @option_callback
    def create_role_option(cls, name: str):
        """Create a new role and save it to file.
        This method is a cli option callback.
        """
        self = cls()
        if name in self.roles:
            self.console.print(f"Role '{name}' already exists", style="yellow")
            return
        description = Prompt.ask("Enter role description")

        # Format the prompt as "You are {role_id}, {description}"
        prompt = f"You are {name}, {description}"

        role = Role(name=name, prompt=prompt)
        self.create_role(name, role)
        self.console.print(f"Role '{name}' created successfully", style="green")

    def create_role(self, role_id: str, role: Union[Role, Dict[str, Any]]) -> None:
        """Create a new role and save it to file"""
        if role_id in self.roles:
            raise RoleAlreadyExistsError(f"Role '{role_id}' already exists")
        if isinstance(role, dict):
            if "name" not in role or "prompt" not in role:
                raise RoleCreationError("Role must have 'name' and 'prompt' keys")
            # Convert dict to Role object
            role = Role.from_dict(role_id, role)
        self.save_role(role_id, role)

    @classmethod
    @option_callback
    def delete_role_option(cls, name: str):
        """Delete a role and its file.
        This method is a cli option callback.
        """
        self = cls()
        if self.delete_role(name):
            self.console.print(f"Role '{name}' deleted successfully", style="green")

    def delete_role(self, role_id: str) -> bool:
        """Delete a role and its file"""
        if role_id not in self.roles:
            self.console.print(f"Role '{role_id}' does not exist", style="red")
            return False

        # Don't allow deleting default roles
        if role_id in DEFAULT_ROLES:
            self.console.print(f"Cannot delete default role: '{role_id}'", style="red")
            return False

        try:
            role = self.roles[role_id]
            if role.filepath:
                Path(role.filepath).unlink(missing_ok=True)
            del self.roles[role_id]
            return True
        except Exception as e:
            self.console.print(f"Error deleting role: {e}", style="red")
            return False

    def get_system_prompt(self, role_id: str) -> str:
        """Get prompt from file by role ID"""
        role = self.get_role(role_id)
        if not role:
            # Fall back to default role if specified role doesn't exist
            self.console.print(f"Role {role_id} not found, using default role", style="yellow")
            role = self.get_role(DefaultRoleNames.DEFAULT)
            if not role:
                # Last resort fallback
                default_config = DEFAULT_ROLES[DefaultRoleNames.DEFAULT]
                role = Role.from_dict(DefaultRoleNames.DEFAULT, default_config)

        # Create a copy of the role with system variables
        system_role = Role(name=role.name, prompt=role.prompt)
        return system_role.prompt
