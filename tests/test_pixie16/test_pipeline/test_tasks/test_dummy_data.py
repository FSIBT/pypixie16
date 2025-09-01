import time
import unittest.mock as mock

import pixie16


class Test_DummyData:
    @staticmethod
    def test():
        """Test DummyData task functionality without complex pipeline integration."""
        # Create DummyData task directly to test its core functionality
        dummy_task = pixie16.pipeline.tasks.DummyData()

        # Test initialization
        dummy_task.do_init()

        # Verify attributes are set correctly after our fix
        assert hasattr(dummy_task, "runtime"), (
            "DummyData should have runtime attribute after do_init"
        )
        assert hasattr(dummy_task, "modules"), (
            "DummyData should have modules attribute after do_init"
        )
        assert hasattr(dummy_task, "chunk_size"), (
            "DummyData should have chunk_size attribute after do_init"
        )

        assert dummy_task.runtime == 2, f"Expected runtime=2, got {dummy_task.runtime}"
        assert dummy_task.modules == [2], (
            f"Expected modules=[2], got {dummy_task.modules}"
        )
        assert dummy_task.chunk_size == 20000, (
            f"Expected chunk_size=20000, got {dummy_task.chunk_size}"
        )

        # Test configuration (should not crash)
        dummy_task.do_configure({})
        dummy_task.do_configure({"runtime": 5, "modules": [1, 2]})
        assert dummy_task.runtime == 5, "Configuration should update runtime"
        assert dummy_task.modules == [1, 2], "Configuration should update modules"

        # Test start (should not crash)
        dummy_task.do_start()
        assert hasattr(dummy_task, "time_start"), "do_start should set time_start"
        assert hasattr(dummy_task, "position"), "do_start should set position"

        # Test do_work (should return data and not crash)
        # Mock the stop method to avoid complex pipeline interactions
        with mock.patch.object(dummy_task, "stop", return_value=None) as mock_stop:
            result = dummy_task.do_work(None)

            # Should return a dictionary with module data
            assert isinstance(result, dict), "do_work should return a dict"
            assert all(isinstance(k, int) for k in result.keys()), (
                "Keys should be module numbers"
            )

            # Test with time exceeded (should call stop)
            dummy_task.time_start = time.time() - 10  # Set start time to 10 seconds ago
            dummy_task.do_work(None)
            mock_stop.assert_called_once(), "Should call stop when runtime exceeded"
