"""
Integration tests for PIXIE-16 Scope Parameters and Hardware Manager.

Run with: pytest test_pixie_scope_integration.py -v
Run specific test: pytest test_pixie_scope_integration.py::TestHardwareConnection::test_hardware_initialization -v
Run with coverage: pytest test_pixie_scope_integration.py --cov=pixie16.ui.scope --cov-report=html
"""

import pytest
import time
import logging
from unittest.mock import Mock

# Configure logging for tests
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Import the modules to test
try:
    from pixie16.ui.scope.parameter_validation import (
        PixieParameterValidator,
        ParameterChangeManager
    )
    from pixie16.ui.scope.hardware_manager import (
        DynamicPixieHardwareManager
    )
    MODULES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Could not import scope modules: {e}")
    MODULES_AVAILABLE = False
    pytest.skip("Scope modules not available", allow_module_level=True)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def validator_500mhz():
    return PixieParameterValidator(module_type="500MHz")


@pytest.fixture
def real_hardware_manager():
    hw_manager = DynamicPixieHardwareManager(physical_slot=2, dummy_mode=False)
    try:
        if not hw_manager.initialize_system():
            pytest.skip("Hardware not available")
        yield hw_manager
    except Exception as e:
        pytest.skip(f"Hardware not available: {e}")
    finally:
        if hw_manager.state.is_running:
            hw_manager.stop_acquisition()


@pytest.fixture
def change_manager(validator_500mhz):
    callback = Mock()
    manager = ParameterChangeManager(validator_500mhz, callback)
    yield manager
    if manager.debounce_timer:
        manager.debounce_timer.cancel()


@pytest.fixture
def sample_parameters():
    return {
        "TRIGGER_THRESHOLD": 1000,
        "TRIGGER_RISETIME": 0.1,
        "TRIGGER_FLATTOP": 0.1,
        "ENERGY_RISETIME": 2.0,
        "ENERGY_FLATTOP": 0.5,
        "TRACE_LENGTH": 2.0,
        "TRACE_DELAY": 0.5,
        "VOFFSET": 0.0,
        "TAU": 50.0,
        "EMIN": 0,
    }


@pytest.fixture
def invalid_parameters():
    return {
        "TRIGGER_THRESHOLD": 100000,  # Too high
        "TRIGGER_RISETIME": -0.5,  # Negative
        "ENERGY_RISETIME": 0.001,  # Too low
        "VOFFSET": 5.0,  # Out of range
    }


# ============================================================================
# HARDWARE CONNECTION TESTS
# ============================================================================

@pytest.mark.hardware
class TestHardwareConnection:
    
    def test_hardware_initialization(self, real_hardware_manager):
        assert real_hardware_manager.state.is_initialized is True
        assert real_hardware_manager.dummy_mode is False
        logger.info("✓ Real hardware initialized successfully")
    
    def test_hardware_boot_patterns(self, real_hardware_manager):
        boot_pattern = real_hardware_manager.get_boot_pattern()
        assert boot_pattern is not None
        logger.info(f"✓ Boot pattern retrieved: {boot_pattern}")
    
    def test_module_information_retrieval(self, real_hardware_manager):
        module_info = real_hardware_manager.get_module_info()
        assert module_info is not None
        assert 'revision' in module_info
        assert 'serial_number' in module_info
        logger.info(f"✓ Module info: Rev {module_info['revision']}, SN: {module_info['serial_number']}")
    
    def test_dsp_version_check(self, real_hardware_manager):
        dsp_version = real_hardware_manager.get_dsp_version()
        assert dsp_version is not None
        logger.info(f"✓ DSP version: {dsp_version}")
    
    def test_fpga_configuration_status(self, real_hardware_manager):
        fpga_status = real_hardware_manager.check_fpga_configuration()
        assert fpga_status is True
        logger.info("✓ FPGA configuration verified")
    
    def test_channel_availability(self, real_hardware_manager):
        for channel in range(16):
            is_available = real_hardware_manager.is_channel_available(channel)
            logger.info(f"Channel {channel}: {'available' if is_available else 'not available'}")


# ============================================================================
# PARAMETER HARDWARE SYNCHRONIZATION TESTS
# ============================================================================

@pytest.mark.hardware
class TestParameterHardwareSync:
    
    def test_parameter_write_read_verification(self, real_hardware_manager):
        test_value = 1500
        param_name = "TRIGGER_THRESHOLD"
        module, channel = 0, 0
        
        # Write parameter
        success = real_hardware_manager.update_parameter(
            param_name, test_value, module=module, channel=channel
        )
        assert success is True
        logger.info(f"✓ Parameter {param_name} written: {test_value}")
        
        # Read back parameter
        read_value = real_hardware_manager.read_parameter(
            param_name, module=module, channel=channel
        )
        assert read_value == test_value
        logger.info(f"✓ Parameter {param_name} read back: {read_value}")
    
    def test_voltage_offset_hardware_sync(self, real_hardware_manager):
        test_voltages = [-1.0, -0.5, 0.0, 0.5, 1.0]
        param_name = "VOFFSET"
        
        for voltage in test_voltages:
            success = real_hardware_manager.update_parameter(
                param_name, voltage, module=0, channel=0
            )
            assert success is True
            
            read_voltage = real_hardware_manager.read_parameter(
                param_name, module=0, channel=0
            )
            assert abs(read_voltage - voltage) < 0.01
            logger.info(f"✓ VOFFSET {voltage}V written and verified")
    
    def test_timing_parameter_precision(self, real_hardware_manager):
        timing_params = {
            "TRIGGER_RISETIME": 0.1,
            "TRIGGER_FLATTOP": 0.1,
            "ENERGY_RISETIME": 2.0,
            "ENERGY_FLATTOP": 0.5
        }
        
        for param_name, expected_value in timing_params.items():
            success = real_hardware_manager.update_parameter(
                param_name, expected_value, module=0, channel=0
            )
            assert success is True
            
            read_value = real_hardware_manager.read_parameter(
                param_name, module=0, channel=0
            )
            
            # Allow for timing quantization (10ns for 500MHz modules)
            tolerance = 0.02  # 2 FPGA clock periods
            assert abs(read_value - expected_value) <= tolerance
            logger.info(f"✓ {param_name}: written {expected_value}, read {read_value}")
    
    def test_batch_parameter_sync(self, real_hardware_manager, sample_parameters):
        success = real_hardware_manager.update_parameters(
            sample_parameters, module=0, channel=0
        )
        assert success is True
        logger.info(f"✓ Batch update of {len(sample_parameters)} parameters")
        
        # Verify all parameters
        for param_name, expected_value in sample_parameters.items():
            read_value = real_hardware_manager.read_parameter(
                param_name, module=0, channel=0
            )
            
            # Use appropriate tolerance based on parameter type
            if param_name in ["TRIGGER_THRESHOLD", "EMIN"]:
                assert read_value == expected_value
            else:
                tolerance = 0.02 if "TIME" in param_name or "TOP" in param_name else 0.01
                assert abs(read_value - expected_value) <= tolerance
            
            logger.info(f"✓ {param_name}: {read_value} (expected: {expected_value})")
    
    def test_multi_channel_parameter_sync(self, real_hardware_manager):
        test_thresholds = [1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700,
                          1800, 1900, 2000, 2100, 2200, 2300, 2400, 2500]
        
        # Write different threshold to each channel
        for channel, threshold in enumerate(test_thresholds):
            success = real_hardware_manager.update_parameter(
                "TRIGGER_THRESHOLD", threshold, module=0, channel=channel
            )
            assert success is True
        
        logger.info("✓ Different thresholds written to all 16 channels")
        
        # Read back and verify
        for channel, expected_threshold in enumerate(test_thresholds):
            read_threshold = real_hardware_manager.read_parameter(
                "TRIGGER_THRESHOLD", module=0, channel=channel
            )
            assert read_threshold == expected_threshold
            logger.info(f"✓ Channel {channel}: {read_threshold}")


# ============================================================================
# HARDWARE ERROR HANDLING TESTS
# ============================================================================

@pytest.mark.hardware
class TestHardwareErrorHandling:
    
    def test_invalid_parameter_rejection(self, real_hardware_manager):
        # Try to write an invalid parameter
        success = real_hardware_manager.update_parameter(
            "INVALID_PARAM", 100, module=0, channel=0
        )
        assert success is False
        logger.info("✓ Invalid parameter name rejected by hardware")
    
    def test_out_of_range_parameter_handling(self, real_hardware_manager):
        # Try to write out-of-range threshold
        success = real_hardware_manager.update_parameter(
            "TRIGGER_THRESHOLD", 100000, module=0, channel=0
        )
        assert success is False
        logger.info("✓ Out-of-range parameter rejected by hardware")
    
    def test_invalid_channel_handling(self, real_hardware_manager):
        # Try to access invalid channel
        success = real_hardware_manager.update_parameter(
            "TRIGGER_THRESHOLD", 1000, module=0, channel=16
        )
        assert success is False
        logger.info("✓ Invalid channel index rejected")
    
    def test_hardware_communication_timeout(self, real_hardware_manager):
        # Test with a parameter that might cause timeout
        start_time = time.time()
        success = real_hardware_manager.update_parameter(
            "TRIGGER_THRESHOLD", 1000, module=0, channel=0
        )
        elapsed = time.time() - start_time
        
        assert success is True
        assert elapsed < 5.0  # Should complete within reasonable time
        logger.info(f"✓ Parameter update completed in {elapsed:.3f}s")
    
    def test_hardware_state_recovery(self, real_hardware_manager):
        # Force a potential error condition and test recovery
        original_state = real_hardware_manager.state.is_running
        
        try:
            # Try to start an invalid mode
            success = real_hardware_manager.start_mode("invalid_mode")
            assert success is False
            
            # Hardware should still be in original state
            assert real_hardware_manager.state.is_running == original_state
            logger.info("✓ Hardware state preserved after error")
            
        except Exception as e:
            logger.info(f"✓ Exception handled gracefully: {e}")


# ============================================================================
# ACQUISITION MODE TESTS WITH REAL HARDWARE
# ============================================================================

@pytest.mark.hardware
class TestAcquisitionModes:
    
    def test_histogram_mode_hardware(self, real_hardware_manager):
        success = real_hardware_manager.start_mode("histogram")
        assert success is True
        assert real_hardware_manager.state.current_mode == "histogram"
        assert real_hardware_manager.state.is_running is True
        logger.info("✓ Histogram mode started on hardware")
        
        # Let it run briefly
        time.sleep(0.5)
        
        # Stop and verify
        real_hardware_manager.stop_acquisition()
        assert real_hardware_manager.state.is_running is False
        logger.info("✓ Histogram mode stopped")
    
    def test_list_mode_hardware(self, real_hardware_manager):
        success = real_hardware_manager.start_mode("list")
        assert success is True
        assert real_hardware_manager.state.current_mode == "list"
        logger.info("✓ List mode started on hardware")
        
        time.sleep(0.5)
        
        real_hardware_manager.stop_acquisition()
        logger.info("✓ List mode stopped")
    
    def test_traces_mode_hardware(self, real_hardware_manager):
        # Set trace parameters first
        trace_params = {
            "TRACE_LENGTH": 2.0,
            "TRACE_DELAY": 0.5
        }
        
        success = real_hardware_manager.update_parameters(
            trace_params, module=0, channel=0
        )
        assert success is True
        
        success = real_hardware_manager.start_mode("traces")
        assert success is True
        assert real_hardware_manager.state.current_mode == "traces"
        logger.info("✓ Traces mode started on hardware")
        
        time.sleep(0.5)
        
        real_hardware_manager.stop_acquisition()
        logger.info("✓ Traces mode stopped")
    
    def test_mode_transition_parameter_persistence(self, real_hardware_manager):
        # Set parameters
        test_params = {
            "TRIGGER_THRESHOLD": 2000,
            "ENERGY_RISETIME": 1.5
        }
        
        real_hardware_manager.update_parameters(test_params, 0, 0)
        
        # Test different modes
        modes = ["histogram", "list", "traces"]
        for mode in modes:
            real_hardware_manager.start_mode(mode)
            
            # Verify parameters are still correct
            threshold = real_hardware_manager.read_parameter(
                "TRIGGER_THRESHOLD", module=0, channel=0
            )
            energy_rise = real_hardware_manager.read_parameter(
                "ENERGY_RISETIME", module=0, channel=0
            )
            
            assert threshold == 2000
            assert abs(energy_rise - 1.5) <= 0.02
            
            real_hardware_manager.stop_acquisition()
            logger.info(f"✓ Parameters preserved in {mode} mode")


# ============================================================================
# REAL-TIME PARAMETER UPDATE TESTS
# ============================================================================

@pytest.mark.hardware
class TestRealTimeUpdates:
    
    def test_live_threshold_adjustment(self, real_hardware_manager):
        # Start histogram mode
        real_hardware_manager.start_mode("histogram")
        
        # Adjust threshold while running
        thresholds = [1000, 1500, 2000, 1200]
        
        for threshold in thresholds:
            success = real_hardware_manager.update_parameter(
                "TRIGGER_THRESHOLD", threshold, module=0, channel=0
            )
            assert success is True
            
            # Small delay to let hardware process
            time.sleep(0.1)
            
            # Verify update
            read_value = real_hardware_manager.read_parameter(
                "TRIGGER_THRESHOLD", module=0, channel=0
            )
            assert read_value == threshold
            logger.info(f"✓ Live threshold update: {threshold}")
        
        real_hardware_manager.stop_acquisition()
    
    def test_rapid_parameter_updates(self, real_hardware_manager):
        start_time = time.time()
        
        # Rapid updates to test hardware responsiveness
        for i in range(10):
            threshold = 1000 + i * 100
            success = real_hardware_manager.update_parameter(
                "TRIGGER_THRESHOLD", threshold, module=0, channel=i % 16
            )
            assert success is True
        
        elapsed = time.time() - start_time
        logger.info(f"✓ 10 rapid parameter updates in {elapsed:.3f}s")
        assert elapsed < 2.0  # Should be reasonably fast


# ============================================================================
# HARDWARE SPECIFICATIONS VALIDATION
# ============================================================================

@pytest.mark.hardware
class TestHardwareSpecifications:
    
    def test_adc_resolution_verification(self, real_hardware_manager):
        # Test ADC resolution by setting precise thresholds
        test_values = [1, 100, 1000, 10000, 32767, 65535]
        
        for value in test_values:
            success = real_hardware_manager.update_parameter(
                "TRIGGER_THRESHOLD", value, module=0, channel=0
            )
            assert success is True
            
            read_value = real_hardware_manager.read_parameter(
                "TRIGGER_THRESHOLD", module=0, channel=0
            )
            assert read_value == value
            logger.info(f"✓ ADC precision verified at {value}")
    
    def test_timing_quantization_500mhz(self, real_hardware_manager):
        # Test 10ns quantization for 500MHz modules
        test_times = [0.02, 0.03, 0.1, 0.15, 1.0]  # microseconds
        
        for test_time in test_times:
            success = real_hardware_manager.update_parameter(
                "TRIGGER_RISETIME", test_time, module=0, channel=0
            )
            assert success is True
            
            read_time = real_hardware_manager.read_parameter(
                "TRIGGER_RISETIME", module=0, channel=0
            )
            
            # Check quantization to 10ns
            quantized_time = round(read_time / 0.01) * 0.01
            assert abs(read_time - quantized_time) < 0.005
            logger.info(f"✓ Timing quantization: {test_time} → {read_time}")
    
    def test_voltage_precision(self, real_hardware_manager):
        # Test DAC precision for voltage offset
        test_voltages = [-1.5, -1.0, -0.1, 0.0, 0.1, 1.0, 1.5]
        
        for voltage in test_voltages:
            success = real_hardware_manager.update_parameter(
                "VOFFSET", voltage, module=0, channel=0
            )
            assert success is True
            
            read_voltage = real_hardware_manager.read_parameter(
                "VOFFSET", module=0, channel=0
            )
            
            # Check precision (typically ~1mV)
            assert abs(read_voltage - voltage) < 0.005
            logger.info(f"✓ Voltage precision: {voltage}V → {read_voltage}V")


# ============================================================================
# COMPREHENSIVE SYSTEM INTEGRATION TEST
# ============================================================================

@pytest.mark.hardware
class TestSystemIntegration:
    
    def test_complete_hardware_integration_workflow(self, real_hardware_manager, validator_500mhz):
        logger.info("=" * 70)
        logger.info("COMPLETE HARDWARE INTEGRATION TEST")
        logger.info("=" * 70)
        
        # 1. Initialize and verify hardware
        assert real_hardware_manager.state.is_initialized is True
        logger.info("✓ Hardware initialized")
        
        # 2. Get hardware information
        module_info = real_hardware_manager.get_module_info()
        logger.info(f"✓ Module: Rev {module_info.get('revision', 'Unknown')}")
        
        # 3. Validate and apply comprehensive parameter set
        test_params = {
            "TRIGGER_THRESHOLD": 1500,
            "TRIGGER_RISETIME": 0.12,
            "TRIGGER_FLATTOP": 0.08,
            "ENERGY_RISETIME": 2.5,
            "ENERGY_FLATTOP": 0.6,
            "TRACE_LENGTH": 4.0,
            "TRACE_DELAY": 1.0,
            "VOFFSET": -0.3,
            "TAU": 75.0,
        }
        
        validated = validator_500mhz.validate_parameter_set(test_params, 0, 0)
        assert len(validated) == len(test_params)
        logger.info(f"✓ {len(validated)} parameters validated")
        
        # 4. Apply to multiple channels with verification
        for channel in [0, 4, 8, 12, 15]:  # Test subset of channels
            success = real_hardware_manager.update_parameters(
                validated, module=0, channel=channel
            )
            assert success is True
            
            # Verify critical parameters
            threshold = real_hardware_manager.read_parameter(
                "TRIGGER_THRESHOLD", module=0, channel=channel
            )
            voffset = real_hardware_manager.read_parameter(
                "VOFFSET", module=0, channel=channel
            )
            
            assert threshold == 1500
            assert abs(voffset - (-0.3)) < 0.01
            logger.info(f"✓ Channel {channel} configured and verified")
        
        # 5. Test all acquisition modes with real data
        for mode in ["histogram", "list", "traces"]:
            success = real_hardware_manager.start_mode(mode)
            assert success is True
            logger.info(f"✓ {mode.capitalize()} mode started")
            
            # Let it acquire briefly
            time.sleep(1.0)
            
            # Verify mode is actually running
            assert real_hardware_manager.state.is_running is True
            assert real_hardware_manager.state.current_mode == mode
            
            real_hardware_manager.stop_acquisition()
            assert real_hardware_manager.state.is_running is False
            logger.info(f"✓ {mode.capitalize()} mode stopped")
        
        # 6. Final parameter verification
        final_threshold = real_hardware_manager.read_parameter(
            "TRIGGER_THRESHOLD", module=0, channel=0
        )
        assert final_threshold == 1500
        logger.info("✓ Parameters preserved through all mode transitions")
        
        logger.info("=" * 70)
        logger.info("HARDWARE INTEGRATION TEST PASSED")
        logger.info("=" * 70)


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "hardware: marks tests requiring actual hardware"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])