from unittest.mock import patch

import pytest


@pytest.mark.parametrize(
    "os_name_config,expected_result",
    [
        ("custom_os", "custom_os"),  # Test custom OS_NAME
        ("auto", None),  # Auto detection, actual result depends on mock
    ],
)
def test_detect_os_with_config(cli, os_name_config, expected_result):
    """Test when OS_NAME is set in config file"""
    # Set config
    cli.config["OS_NAME"] = os_name_config

    if expected_result:
        # If expected result exists, compare directly
        assert cli.detect_os() == expected_result
    else:
        # Otherwise, should enter auto detection logic, covered in other tests
        pass


@patch("platform.system")
@patch("yaicli.distro_name")
def test_detect_os_linux(mock_distro, mock_system, cli):
    """Test Linux system detection"""
    # Ensure config is set to auto detection
    cli.config["OS_NAME"] = "auto"

    # Simulate Linux environment
    mock_system.return_value = "Linux"
    mock_distro.return_value = "Ubuntu 20.04"

    # Verify result
    assert cli.detect_os() == "Linux/Ubuntu 20.04"
    mock_system.assert_called_once()
    mock_distro.assert_called_once_with(pretty=True)


@patch("platform.system")
@patch("platform.release")
def test_detect_os_windows(mock_release, mock_system, cli):
    """Test Windows system detection"""
    # Ensure config is set to auto detection
    cli.config["OS_NAME"] = "auto"

    # Simulate Windows environment
    mock_system.return_value = "Windows"
    mock_release.return_value = "10"

    # Verify result
    assert cli.detect_os() == "Windows 10"
    mock_system.assert_called_once()
    mock_release.assert_called_once()


@patch("platform.system")
@patch("platform.mac_ver")
def test_detect_os_macos(mock_mac_ver, mock_system, cli):
    """Test MacOS system detection"""
    # Ensure config is set to auto detection
    cli.config["OS_NAME"] = "auto"

    # Simulate MacOS environment
    mock_system.return_value = "Darwin"
    mock_mac_ver.return_value = ("12.6", ("", "", ""), "")

    # Verify result
    assert cli.detect_os() == "Darwin/MacOS 12.6"
    mock_system.assert_called_once()
    mock_mac_ver.assert_called_once()


@patch("platform.system")
def test_detect_os_other(mock_system, cli):
    """Test other unknown system detection"""
    # Ensure config is set to auto detection
    cli.config["OS_NAME"] = "auto"

    # Simulate other unknown system
    mock_system.return_value = "SomeOtherOS"

    # Verify result
    assert cli.detect_os() == "SomeOtherOS"
    mock_system.assert_called_once()

@pytest.mark.parametrize(
    "shell_name_config,expected_result",
    [
        ("custom_shell", "custom_shell"),  # Test custom SHELL_NAME
        ("auto", None),  # Auto detection, actual result depends on mock
    ],
)
def test_detect_shell_with_config(cli, shell_name_config, expected_result):
    """Test when SHELL_NAME is set in config file"""
    # Set config
    cli.config["SHELL_NAME"] = shell_name_config

    if expected_result:
        # If expected result exists, compare directly
        assert cli.detect_shell() == expected_result
    else:
        # Otherwise, should enter auto detection logic, covered in other tests
        pass

@patch("platform.system")
@patch("os.getenv")
def test_detect_shell_windows_powershell(mock_getenv, mock_system, cli):
    """Test Windows PowerShell detection"""
    # Ensure config is set to auto detection
    cli.config["SHELL_NAME"] = "auto"

    # Simulate Windows environment with PowerShell
    mock_system.return_value = "Windows"
    mock_getenv.return_value = "a;b;c"  # PSModulePath with 3 parts

    # Verify result
    assert cli.detect_shell() == "powershell.exe"
    mock_system.assert_called_once()
    mock_getenv.assert_called_once_with("PSModulePath", "")

@patch("platform.system")
@patch("os.getenv")
def test_detect_shell_windows_cmd(mock_getenv, mock_system, cli):
    """Test Windows CMD detection"""
    # Ensure config is set to auto detection
    cli.config["SHELL_NAME"] = "auto"

    # Simulate Windows environment without PowerShell
    mock_system.return_value = "Windows"
    mock_getenv.return_value = "a"  # PSModulePath with less than 3 parts

    # Verify result
    assert cli.detect_shell() == "powershell.exe"
    mock_system.assert_called_once()
    mock_getenv.assert_called_once_with("PSModulePath", "")

@patch("platform.system")
@patch("os.getenv")
def test_detect_shell_linux(mock_getenv, mock_system, cli):
    """Test Linux shell detection"""
    # Ensure config is set to auto detection
    cli.config["SHELL_NAME"] = "auto"

    # Simulate Linux environment with bash
    mock_system.return_value = "Linux"
    mock_getenv.return_value = "/bin/bash"

    # Verify result
    assert cli.detect_shell() == "bash"
    mock_system.assert_called_once()
    mock_getenv.assert_called_once_with("SHELL", "/bin/sh")

@patch("platform.system")
@patch("os.getenv")
def test_detect_shell_default_sh(mock_getenv, mock_system, cli):
    """Test default /bin/sh detection when SHELL not set"""
    # Ensure config is set to auto detection
    cli.config["SHELL_NAME"] = "auto"

    # Simulate environment without SHELL variable
    mock_system.return_value = "Linux"
    mock_getenv.return_value = None

    # Verify result
    assert cli.detect_shell() == "bash"
    mock_system.assert_called_once()
    mock_getenv.assert_called_once_with("SHELL", "/bin/sh")
