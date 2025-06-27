import asyncio
from unittest.mock import Mock, patch

from yaicli.utils import get_or_create_event_loop


def test_get_or_create_event_loop_running():
    """Test that get_or_create_event_loop returns the running loop if one exists."""
    # Create a test loop and run it
    mock_loop = Mock(spec=asyncio.AbstractEventLoop)

    with patch("asyncio.get_running_loop", return_value=mock_loop):
        # Call the function under test
        result = get_or_create_event_loop()

        # Assert that it returned the mock loop
        assert result is mock_loop


def test_get_or_create_event_loop_existing():
    """Test getting an existing but not running event loop."""
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("No running event loop")):
        mock_loop = Mock(spec=asyncio.AbstractEventLoop)

        with patch("asyncio.get_event_loop", return_value=mock_loop):
            result = get_or_create_event_loop()

        assert result is mock_loop


def test_get_or_create_event_loop_new():
    """Test creating a new event loop when none exists."""
    # Simulate both get_running_loop and get_event_loop raising exceptions
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("No running event loop")):
        with patch("asyncio.get_event_loop", side_effect=RuntimeError("No event loop")):
            mock_loop = Mock(spec=asyncio.AbstractEventLoop)

            with patch("asyncio.new_event_loop", return_value=mock_loop):
                with patch("asyncio.set_event_loop") as mock_set_loop:
                    result = get_or_create_event_loop()

                    # Check that the loop was set as the current event loop
                    mock_set_loop.assert_called_once_with(mock_loop)

            assert result is mock_loop
