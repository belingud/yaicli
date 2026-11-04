import json
from unittest.mock import MagicMock, patch

import pytest
import typer
from pytest import raises

from yaicli.config import cfg
from yaicli.const import DEFAULT_ROLES, DefaultRoleNames
from yaicli.role import Role, RoleManager


# Mock the option_callback decorator to avoid typer.Exit issues
@pytest.fixture
def mock_option_callback(monkeypatch):
    def mock_decorator(func):
        def wrapper(cls, value):
            if not value:
                return value
            return func(cls, value)

        return wrapper

    monkeypatch.setattr("yaicli.utils.option_callback", mock_decorator)
    return mock_decorator


class TestRole:
    """Test the Role class"""

    def test_init_valid(self):
        """Test valid Role initialization"""
        role = Role(name="test", prompt="This is a test role")
        assert role.name == "test"
        assert role.prompt == "This is a test role"
        assert "_os" in role.variables
        assert "_shell" in role.variables

    def test_init_invalid_name(self):
        """Test invalid name parameter"""
        with raises(ValueError, match="Role must have a non-empty name"):
            Role(name="", prompt="Test prompt")
        with raises(ValueError, match="Role must have a non-empty name"):
            Role(name=None, prompt="Test prompt")

    def test_init_invalid_prompt(self):
        """Test invalid prompt parameter"""
        with raises(ValueError, match="Role must have a non-empty description"):
            Role(name="test", prompt="")
        with raises(ValueError, match="Role must have a non-empty description"):
            Role(name="test", prompt=None)

    def test_format_prompt(self):
        """Test prompt string formatting"""
        variables = {"name": "user", "language": "Python"}
        role = Role(name="test", prompt="Hello {name}, welcome to {language}", variables=variables)
        assert role.prompt == "Hello user, welcome to Python"

    def test_to_dict(self):
        """Test to_dict method"""
        role = Role(name="test", prompt="Test prompt", variables={"var1": "value1"})
        role_dict = role.to_dict()
        assert role_dict["name"] == "test"
        assert role_dict["prompt"] == "Test prompt"
        assert role_dict["variables"]["var1"] == "value1"


class TestRoleManager:
    """Test the RoleManager class"""

    @pytest.fixture
    def mock_roles_dir(self, tmp_path):
        """Create a temporary directory to simulate roles directory"""
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        return roles_dir

    @pytest.fixture
    def mock_console(self):
        """Mock console object"""
        console = MagicMock()
        return console

    @patch("yaicli.role.ROLES_DIR")
    @patch("yaicli.role.get_console")
    def test_init_and_load_default_roles(self, mock_get_console, mock_roles_dir_patch, mock_roles_dir, mock_console):
        """Test initialization and loading of default roles"""
        mock_roles_dir_patch.return_value = mock_roles_dir
        mock_get_console.return_value = mock_console

        manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)

        # Verify default roles are loaded
        assert len(manager.roles) >= len(DEFAULT_ROLES)
        for name in DEFAULT_ROLES:
            assert name in manager.roles

    @patch("yaicli.role.get_console")
    def test_init_does_not_write_role_files(self, mock_get_console, mock_roles_dir, mock_console):
        """v0.19 K21: constructing RoleManager must not write role files (read-only HOME safe)."""
        mock_get_console.return_value = mock_console

        manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)

        # Default roles are available from memory without seeding any JSON file.
        assert len(manager.roles) >= len(DEFAULT_ROLES)
        assert list(mock_roles_dir.glob("*.json")) == []

    @patch("yaicli.role.get_console")
    def test_create_role_creates_dir_and_writes_file_on_demand(self, mock_get_console, mock_roles_dir, mock_console):
        """Role JSON is written on create; the roles dir is created lazily."""
        mock_get_console.return_value = mock_console
        roles_dir = mock_roles_dir / "nested" / "roles"  # does not exist yet

        manager = RoleManager(roles_dir=roles_dir, console=mock_console)
        assert not roles_dir.exists()
        assert list(roles_dir.glob("*.json")) == []

        manager.create_role("custom_role", "Custom prompt")

        assert roles_dir.exists()
        assert (roles_dir / "custom_role.json").exists()

    @patch("yaicli.role.get_console")
    def test_create_role_survives_read_only_roles_dir(self, mock_get_console, mock_roles_dir, mock_console):
        """A read-only roles directory only warns: the role still exists in memory."""
        mock_get_console.return_value = mock_console
        manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)
        mock_roles_dir.chmod(0o500)
        try:
            role = manager.create_role("readonly_role", "Prompt")
        finally:
            mock_roles_dir.chmod(0o700)

        assert role.name == "readonly_role"
        assert "readonly_role" in manager.roles
        assert mock_console.print.called

    @patch("yaicli.role.get_console")
    def test_load_user_roles(self, mock_get_console, mock_roles_dir, mock_console):
        """Test loading user role files"""
        mock_get_console.return_value = mock_console

        # Create test user role file
        user_role_path = mock_roles_dir / "user_role.json"
        user_role_data = {
            "name": "user_role",
            "prompt": "This is a user defined role",
            "variables": {"custom": "value"},
        }
        with open(user_role_path, "w") as f:
            json.dump(user_role_data, f)

        # Create an invalid role file
        invalid_role_path = mock_roles_dir / "invalid_role.json"
        with open(invalid_role_path, "w") as f:
            f.write("Not a valid JSON")

        manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)

        # Verify user role was loaded
        assert "user_role" in manager.roles
        assert manager.roles["user_role"].name == "user_role"
        assert manager.roles["user_role"].prompt == "This is a user defined role"
        assert manager.roles["user_role"].variables["custom"] == "value"

        # Verify error handling
        mock_console.print.assert_called_once()

    @patch("yaicli.role.get_console")
    def test_get_role(self, mock_get_console, mock_roles_dir, mock_console):
        """Test getting a role"""
        mock_get_console.return_value = mock_console

        manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)

        # Get default role
        default_role_name = list(DEFAULT_ROLES.keys())[0]
        role = manager.get_role(default_role_name)
        assert role.name == DEFAULT_ROLES[default_role_name]["name"]

        # Test getting a non-existent role
        with raises(ValueError, match="Role 'non_existent' does not exist."):
            manager.get_role("non_existent")

    @patch("yaicli.role.get_console")
    def test_create_and_delete_role(self, mock_get_console, mock_roles_dir, mock_console):
        """Test creating and deleting roles"""
        mock_get_console.return_value = mock_console

        manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)

        # Create new role
        role = manager.create_role("test_role", "Test description")
        assert role.name == "test_role"
        assert role.prompt == "Test description"
        assert "test_role" in manager.roles
        assert (mock_roles_dir / "test_role.json").exists()

        # Delete role
        result = manager.delete_role("test_role")
        assert result is True
        assert "test_role" not in manager.roles
        assert not (mock_roles_dir / "test_role.json").exists()

        # Test deleting a non-existent role
        result = manager.delete_role("non_existent")
        assert result is False

    @patch("yaicli.role.get_console")
    def test_list_roles(self, mock_get_console, mock_roles_dir, mock_console):
        """Test listing all roles"""
        mock_get_console.return_value = mock_console

        manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)

        # Create test roles
        manager.create_role("test_role1", "Test description 1")
        manager.create_role("test_role2", "Test description 2")

        roles_list = manager.list_roles()
        assert len(roles_list) >= len(DEFAULT_ROLES) + 2

        # Verify test roles are in the list
        role_names = [role["name"] for role in roles_list]
        assert "test_role1" in role_names
        assert "test_role2" in role_names

    @staticmethod
    def _printed_messages(console):
        """Return the first positional argument of every console.print call."""
        return [str(call.args[0]) for call in console.print.call_args_list if call.args]

    @patch("yaicli.role.get_console")
    def test_builtin_role_modification_warns(self, mock_get_console, mock_roles_dir, mock_console):
        """create_role/delete_role warn when a built-in role is modified."""
        mock_get_console.return_value = mock_console
        manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)
        builtin_name = next(iter(DEFAULT_ROLES))

        manager.create_role(builtin_name, "Overridden built-in prompt")
        manager.delete_role(builtin_name)

        warnings = self._printed_messages(mock_console)
        assert len(warnings) == 2
        assert all(builtin_name in message and "built-in role" in message for message in warnings)
        assert all(call.kwargs.get("style") == "yellow" for call in mock_console.print.call_args_list)

    @patch("yaicli.role.get_console")
    def test_builtin_role_warning_defaults_to_enabled(self, mock_get_console, mock_roles_dir, mock_console):
        """A missing ROLE_MODIFY_WARNING key defaults to warning enabled."""
        mock_get_console.return_value = mock_console
        config_without_flag = {key: value for key, value in cfg.items() if key != "ROLE_MODIFY_WARNING"}
        with patch("yaicli.role.cfg", config_without_flag):
            manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)
            builtin_name = next(iter(DEFAULT_ROLES))
            manager.create_role(builtin_name, "Overridden built-in prompt")

        warnings = self._printed_messages(mock_console)
        assert any(builtin_name in message and "built-in role" in message for message in warnings)

    @patch("yaicli.role.get_console")
    def test_builtin_role_modification_silent_when_disabled(self, mock_get_console, mock_roles_dir, mock_console):
        """ROLE_MODIFY_WARNING=false suppresses the built-in role warning."""
        mock_get_console.return_value = mock_console
        with patch("yaicli.role.cfg", {**cfg, "ROLE_MODIFY_WARNING": False}):
            manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)
            builtin_name = next(iter(DEFAULT_ROLES))
            manager.create_role(builtin_name, "Overridden built-in prompt")
            manager.delete_role(builtin_name)

        mock_console.print.assert_not_called()

    @patch("yaicli.role.get_console")
    def test_custom_role_modification_does_not_warn(self, mock_get_console, mock_roles_dir, mock_console):
        """Custom roles never trigger the built-in role warning."""
        mock_get_console.return_value = mock_console
        manager = RoleManager(roles_dir=mock_roles_dir, console=mock_console)

        manager.create_role("custom_role", "Custom prompt")
        manager.delete_role("custom_role")

        mock_console.print.assert_not_called()

    def test_print_list_option(self, tmp_path):
        """Test the print_list_option class method.

        Built-in roles live in memory only (v0.19 K21) and are merged into the
        listing, so user files plus the built-in roles are shown.
        """
        # Create temporary roles directory and test files
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()

        # Create test role files
        test_role1_data = {"name": "test_role1", "prompt": "Test description 1", "variables": {}}
        test_role2_data = {"name": "test_role2", "prompt": "Test description 2", "variables": {}}

        with open(roles_dir / "test_role1.json", "w") as f:
            json.dump(test_role1_data, f)

        with open(roles_dir / "test_role2.json", "w") as f:
            json.dump(test_role2_data, f)

        # Prepare mock objects
        mock_table = MagicMock()
        mock_console = MagicMock()

        # Save original values for restoration
        original_roles_dir = RoleManager.roles_dir
        original_console = RoleManager.console

        try:
            # Set class attributes to actual temporary directory
            RoleManager.roles_dir = roles_dir
            RoleManager.console = mock_console

            # Mock Table class
            with patch("yaicli.role.Table", return_value=mock_table):
                try:
                    RoleManager.print_list_option(1)
                except typer.Exit:
                    pass

                # Verify interactions
                mock_table.add_column.assert_any_call("Name", style="dim")
                mock_table.add_column.assert_any_call("Filepath", style="dim")

                # User files plus the in-memory built-in roles are listed.
                assert mock_table.add_row.call_count == 2 + len(DEFAULT_ROLES)
                rendered_names = {str(call.args[0]) for call in mock_table.add_row.call_args_list}
                assert {"test_role1", "test_role2"} <= rendered_names
                assert DefaultRoleNames.DEFAULT.value in rendered_names

                # Verify console output
                mock_console.print.assert_any_call(mock_table)
                mock_console.print.assert_any_call("Use `ai --show-role <name>` to view a role.", style="dim")
        finally:
            # Restore original values
            RoleManager.roles_dir = original_roles_dir
            RoleManager.console = original_console

    def test_print_list_option_fresh_home_lists_builtin_roles(self, tmp_path):
        """A fresh HOME has no role files: the listing still shows built-in roles."""
        roles_dir = tmp_path / "missing-roles"  # never created on init (K21)
        mock_table = MagicMock()
        mock_console = MagicMock()
        original_roles_dir = RoleManager.roles_dir
        original_console = RoleManager.console
        try:
            RoleManager.roles_dir = roles_dir
            RoleManager.console = mock_console
            with patch("yaicli.role.Table", return_value=mock_table):
                try:
                    RoleManager.print_list_option(1)
                except typer.Exit:
                    pass

            assert mock_table.add_row.call_count == len(DEFAULT_ROLES)
            assert not roles_dir.exists()
        finally:
            RoleManager.roles_dir = original_roles_dir
            RoleManager.console = original_console

    def test_create_role_option(self, monkeypatch):
        """Test create_role_option class method"""
        # Bypass decorator to extract original function implementation
        # Can find the decorated function by looking at the source code

        # Prepare test mock objects
        mock_role_manager = MagicMock()
        mock_role = MagicMock()
        mock_role.name = "new_role"
        mock_role_manager.roles = {}
        mock_role_manager.create_role.return_value = mock_role

        mock_prompt = MagicMock(return_value="Test role description")
        mock_console = MagicMock()

        # Patch test environment
        monkeypatch.setattr("yaicli.role.RoleManager", lambda: mock_role_manager)
        monkeypatch.setattr("typer.prompt", mock_prompt)
        monkeypatch.setattr(RoleManager, "console", mock_console)

        # Get original function
        original_func = RoleManager.create_role_option

        # Call function directly, catching expected Exit
        try:
            # Call function directly instead of through class method
            original_func("new_role")
        except typer.Exit:
            pass  # Normal behavior

        # Verify interactions
        mock_role_manager.create_role.assert_called_once_with("new_role", "Test role description")
        mock_console.print.assert_called_once_with("Created role: new_role", style="green")

    def test_create_role_option_existing(self, monkeypatch):
        """Test create_role_option class method (role already exists case)"""
        # Prepare test mock objects
        mock_role_manager = MagicMock()
        mock_role_manager.roles = {"existing_role": MagicMock()}
        mock_console = MagicMock()

        # Patch test environment
        monkeypatch.setattr("yaicli.role.RoleManager", lambda: mock_role_manager)
        monkeypatch.setattr(RoleManager, "console", mock_console)

        # Get original function
        original_func = RoleManager.create_role_option

        # Call function directly, catching expected Exit
        try:
            original_func("existing_role")
        except typer.Exit:
            pass  # Normal behavior

        # Verify interactions
        mock_console.print.assert_called_once_with("Role 'existing_role' already exists.", style="red")

    def test_delete_role_option(self, monkeypatch):
        """Test delete_role_option class method"""
        # Prepare test mock objects
        mock_role_manager = MagicMock()
        mock_role_manager.roles = {"test_role": MagicMock()}
        mock_role_manager.delete_role.return_value = True
        mock_console = MagicMock()

        # Patch test environment
        monkeypatch.setattr("yaicli.role.RoleManager", lambda: mock_role_manager)
        monkeypatch.setattr(RoleManager, "console", mock_console)

        # Get original function
        original_func = RoleManager.delete_role_option

        # Call function directly, catching expected Exit
        try:
            original_func("test_role")
        except typer.Exit:
            pass  # Normal behavior

        # Verify interactions
        mock_role_manager.delete_role.assert_called_once_with("test_role")
        mock_console.print.assert_called_once_with("Deleted role: test_role", style="green")

    def test_show_role_option(self, monkeypatch):
        """Test show_role_option class method"""
        # Prepare test mock objects
        mock_role_manager = MagicMock()
        mock_role = MagicMock()
        mock_role.name = "test_role"
        mock_role.prompt = "Test description"
        mock_role_manager.get_role.return_value = mock_role
        mock_console = MagicMock()

        # Patch test environment
        monkeypatch.setattr("yaicli.role.RoleManager", lambda: mock_role_manager)
        monkeypatch.setattr(RoleManager, "console", mock_console)

        # Get original function
        original_func = RoleManager.show_role_option

        # Call function directly, catching expected Exit
        try:
            original_func("test_role")
        except typer.Exit:
            pass  # Normal behavior

        # Verify interactions
        mock_role_manager.get_role.assert_called_once_with("test_role")
        mock_console.print.assert_any_call("[bold]Name:[/bold] test_role")
        mock_console.print.assert_any_call("[bold]Description:[/bold] Test description")

    def test_check_id_ok(self):
        """Test check_id_ok class method"""
        from yaicli.const import DefaultRoleNames

        # Test empty value
        assert RoleManager.check_id_ok("") == ""

        # Test default role
        assert RoleManager.check_id_ok(list(DEFAULT_ROLES.keys())[0]) == list(DEFAULT_ROLES.keys())[0]

        # Test non-existent role
        with patch("yaicli.role.RoleManager") as mock_role_manager_cls:
            mock_role_manager_instance = mock_role_manager_cls.return_value
            mock_role_manager_instance.roles = {}
            mock_console = MagicMock()
            RoleManager.console = mock_console

            assert RoleManager.check_id_ok("non_existent") == DefaultRoleNames.DEFAULT
            mock_console.print.assert_called_once_with(
                "Role 'non_existent' does not exist. Using default role.", style="red"
            )
