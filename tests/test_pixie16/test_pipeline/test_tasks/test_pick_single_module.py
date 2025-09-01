import time

import pixie16


class Test_PickSingleModule:
    @staticmethod
    def test():
        """Test PickSingleModule task functionality without complex pipeline integration."""
        # Create PickSingleModule task directly to test its core functionality
        pick_task = pixie16.pipeline.tasks.PickSingleModule()

        # Test initialization
        pick_task.do_init()

        # Verify attributes are set correctly after our fix
        assert hasattr(pick_task, "module"), (
            "PickSingleModule should have module attribute after do_init"
        )
        assert pick_task.module == 2, f"Expected module=2, got {pick_task.module}"

        # Test configuration
        pick_task.do_configure({"module": 5})
        assert pick_task.module == 5, "Configuration should update module"

        pick_task.do_configure({})  # Empty config should use default
        assert pick_task.module == 2, "Empty config should restore default module"

        # Test filtering functionality
        pick_task.module = 3  # Set module to filter

        # Test with data containing multiple modules
        test_data = {
            1: [1, 2, 3],
            3: [4, 5, 6],  # This should be selected
            5: [7, 8, 9],
        }

        result = pick_task.do_work(test_data)
        expected = {3: [4, 5, 6]}
        assert result == expected, f"Expected {expected}, got {result}"

        # Test with data not containing the target module
        test_data_no_match = {1: [1, 2, 3], 2: [4, 5, 6]}

        result_no_match = pick_task.do_work(test_data_no_match)
        assert result_no_match == {}, "Should return empty dict when module not found"

        # Test with empty data
        result_empty = pick_task.do_work({})
        assert result_empty == {}, "Should return empty dict for empty input"
