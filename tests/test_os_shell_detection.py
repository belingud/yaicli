from unittest.mock import patch

import pytest

from yaicli.utils import detect_os, detect_shell


@pytest.mark.parametrize(
    "os_name_config,expected_result",
    [
        ("custom_os", "custom_os"),  # Test custom OS_NAME
        ("auto", None),  # Auto detection, actual result depends on mock
    ],
)
@patch("yaicli.utils.platform.system")
def test_detect_os_with_config(mock_system, os_name_config, expected_result):
    """Test when OS_NAME is set in config file"""
    config = {"OS_NAME": os_name_config}
    if expected_result:
        assert detect_os(config) == expected_result
    else:
        # Mock system call to avoid real detection
        mock_system.return_value = "Linux"
        with patch("yaicli.utils.distro_name", return_value="MockDistro"):
            detect_os(config)  # Call is needed for coverage, assert not needed here
            mock_system.assert_called_once()


@patch("yaicli.utils.platform.system")
@patch("yaicli.utils.distro_name")
def test_detect_os_linux(mock_distro, mock_system):
    """Test Linux system detection"""
    config = {"OS_NAME": "auto"}
    mock_system.return_value = "Linux"
    mock_distro.return_value = "Ubuntu 20.04"
    assert detect_os(config) == "Linux/Ubuntu 20.04"
    mock_system.assert_called_once()
    mock_distro.assert_called_once_with(pretty=True)


@patch("yaicli.utils.platform.system")
@patch("yaicli.utils.platform.release")
def test_detect_os_windows(mock_release, mock_system):
    """Test Windows system detection"""
    config = {"OS_NAME": "auto"}
    mock_system.return_value = "Windows"
    mock_release.return_value = "10"
    assert detect_os(config) == "Windows 10"
    mock_system.assert_called_once()
    mock_release.assert_called_once()


@patch("yaicli.utils.platform.system")
@patch("yaicli.utils.platform.mac_ver")
def test_detect_os_macos(mock_mac_ver, mock_system):
    """Test MacOS system detection"""
    config = {"OS_NAME": "auto"}
    mock_system.return_value = "Darwin"
    mock_mac_ver.return_value = ("12.6", ("", "", ""), "")
    assert detect_os(config) == "Darwin/MacOS 12.6"
    mock_system.assert_called_once()
    mock_mac_ver.assert_called_once()


@patch("yaicli.utils.platform.system")
def test_detect_os_other(mock_system):
    """Test other unknown system detection"""
    config = {"OS_NAME": "auto"}
    mock_system.return_value = "SomeOtherOS"
    assert detect_os(config) == "SomeOtherOS"
    mock_system.assert_called_once()


@pytest.mark.parametrize(
    "shell_name_config,expected_result",
    [
        ("custom_shell", "custom_shell"),  # Test custom SHELL_NAME
        ("auto", None),  # Auto detection, actual result depends on mock
    ],
)
@patch("yaicli.utils.platform.system")
def test_detect_shell_with_config(mock_system, shell_name_config, expected_result):
    """Test when SHELL_NAME is set in config file"""
    config = {"SHELL_NAME": shell_name_config}
    if expected_result:
        assert detect_shell(config) == expected_result
    else:
        # Mock system call to avoid real detection
        mock_system.return_value = "Linux"  # Assume Linux for auto-detection path
        with patch("yaicli.utils.getenv", return_value="/bin/mock_shell"):
            detect_shell(config)  # Call is needed for coverage
            mock_system.assert_called_once()


@patch("yaicli.utils.platform.system")
@patch("yaicli.utils.getenv")
@patch("yaicli.utils.pathsep", ";")
def test_detect_shell_windows_powershell(mock_getenv, mock_system):
    """Test Windows PowerShell detection"""
    config = {"SHELL_NAME": "auto"}
    mock_system.return_value = "Windows"
    mock_getenv.return_value = "a;b;c"  # PSModulePath with 3 parts
    assert detect_shell(config) == "powershell.exe"
    mock_system.assert_called_once()
    mock_getenv.assert_called_once_with("PSModulePath", "")


@patch("yaicli.utils.platform.system")
@patch("yaicli.utils.getenv")
@patch("yaicli.utils.pathsep", ";")
def test_detect_shell_windows_cmd(mock_getenv, mock_system):
    """Test Windows CMD detection"""
    config = {"SHELL_NAME": "auto"}
    mock_system.return_value = "Windows"
    mock_getenv.return_value = "a"  # PSModulePath with less than 3 parts
    assert detect_shell(config) == "cmd.exe"
    mock_system.assert_called_once()
    mock_getenv.assert_called_once_with("PSModulePath", "")


# New test for 'nt' platform
@patch("yaicli.utils.platform.system")
@patch("yaicli.utils.getenv")
@patch("yaicli.utils.pathsep", ";")
def test_detect_shell_nt_platform(mock_getenv, mock_system):
    """Test Windows CMD detection on 'nt' platform"""
    config = {"SHELL_NAME": "auto"}
    mock_system.return_value = "nt"
    mock_getenv.return_value = "a"  # Assume CMD
    assert detect_shell(config) == "cmd.exe"
    mock_system.assert_called_once()
    mock_getenv.assert_called_once_with("PSModulePath", "")


@patch("yaicli.utils.platform.system")
@patch("yaicli.utils.getenv")
def test_detect_shell_linux(mock_getenv, mock_system):
    """Test Linux shell detection"""
    config = {"SHELL_NAME": "auto"}
    mock_system.return_value = "Linux"
    mock_getenv.return_value = "/bin/bash"
    assert detect_shell(config) == "bash"
    mock_system.assert_called_once()
    mock_getenv.assert_called_once_with("SHELL")


# New test for SHELL with full path
@patch("yaicli.utils.platform.system")
@patch("yaicli.utils.getenv")
def test_detect_shell_linux_fullpath(mock_getenv, mock_system):
    """Test Linux shell detection with full path in SHELL env var"""
    config = {"SHELL_NAME": "auto"}
    mock_system.return_value = "Darwin"  # Example non-Windows OS
    mock_getenv.return_value = "/usr/local/bin/zsh"
    assert detect_shell(config) == "zsh"
    mock_system.assert_called_once()
    mock_getenv.assert_called_once_with("SHELL")


@patch("yaicli.utils.platform.system")
@patch("yaicli.utils.getenv")
def test_detect_shell_default_sh(mock_getenv, mock_system):
    """Test default /bin/sh detection when SHELL not set"""
    config = {"SHELL_NAME": "auto"}
    mock_system.return_value = "Linux"
    mock_getenv.return_value = None
    assert detect_shell(config) == "sh"
    mock_system.assert_called_once()
    mock_getenv.assert_called_once_with("SHELL")
