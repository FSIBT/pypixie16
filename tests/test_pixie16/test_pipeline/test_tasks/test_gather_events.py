import time
import unittest.mock as mock

import pixie16


class Test_GatherEvents:
    @staticmethod
    def test():
        """Test GatherEvents task functionality without complex pipeline integration."""
        # Create GatherEvents task directly to test its core functionality
        gather_task = pixie16.pipeline.tasks.GatherEvents()

        # Test initialization
        gather_task.do_init()

        # Verify attributes are set correctly after our fix
        assert hasattr(gather_task, "size"), (
            "GatherEvents should have size attribute after do_init"
        )
        assert gather_task.size == 1_000_000, (
            f"Expected size=1_000_000, got {gather_task.size}"
        )

        # Test configuration
        gather_task.do_configure({"size": 5})
        assert gather_task.size == 5, "Configuration should update size"

        gather_task.do_configure({})  # Empty config should use default
        assert gather_task.size == 1_000_000, "Empty config should restore default size"

        # Test start initialization
        gather_task.do_start()
        assert hasattr(gather_task, "count"), "do_start should set count"
        assert hasattr(gather_task, "queue"), "do_start should set queue"
        assert gather_task.count == 0, "Initial count should be 0"
        assert gather_task.queue == [], "Initial queue should be empty"

        # Test gathering functionality with small size
        gather_task.size = 3  # Small size for testing

        # Mock the report method to avoid pipeline messaging
        with mock.patch.object(gather_task, "report") as mock_report:
            # First batch - should not return anything (queue < size)
            result1 = gather_task.do_work([1, 2])
            assert result1 is None, "Should not return data when queue < size"
            assert gather_task.queue == [1, 2], "Queue should contain partial data"

            # Second batch - should return full batch (queue >= size)
            result2 = gather_task.do_work([3, 4])
            assert result2 == [1, 2, 3, 4], (
                "Should return entire queue when size reached"
            )
            assert gather_task.queue == [], (
                "Queue should be empty after returning batch"
            )
            assert gather_task.count == 1, "Count should increment"
            mock_report.assert_called_once()

        # Test stop functionality with remaining items in queue
        gather_task.queue = [5, 6]  # Add some items to queue
        with (
            mock.patch.object(gather_task, "send") as mock_send,
            mock.patch.object(gather_task, "report") as mock_report,
        ):
            gather_task.do_stop()
            (
                mock_send.assert_called_once_with([5, 6]),
                "Should send remaining queue items on stop",
            )
            mock_report.assert_called_once()
