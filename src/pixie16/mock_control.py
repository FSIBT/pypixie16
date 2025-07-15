"""Mock implementation of pixie16.control for testing and dummy mode.

This module provides a complete mock of the pixie16.control interface that can be used
for testing and development when actual hardware is not available.
"""

import time
from unittest.mock import MagicMock
import numpy as np
from pathlib import Path
from collections.abc import Iterable
from contextlib import contextmanager
import json


class MockPixieControl:
    def __init__(self):
        # Load dummy data
        self.dummy_data_file = None
        self.dummy_data = None
        self.data_position = 0
        self.call_log = []
        self.module_list = [2]  # Default modules
        self.run_active = False

    def set_dummy_data_file(self, filepath: str):
        """Set which binary file to use for mock data"""
        self.dummy_data_file = filepath
        self.dummy_data = self._load_dummy_data()
        self.data_position = 0
        print(f"MOCK: Set dummy data file to: {filepath}")

    def _load_dummy_data(self):
        """Load binary data file for realistic testing"""
        if self.dummy_data_file:
            # Use explicitly set file
            data_path = Path(self.dummy_data_file)
            if data_path.exists():
                print(f"MOCK: Loading dummy data from: {data_path}")
                return np.fromfile(data_path, dtype=np.uint8)
            else:
                print(
                    f"MOCK: WARNING - Specified dummy data file not found: {data_path}"
                )

        # Try to find a data file in the tests directory
        possible_paths = [
            Path(__file__).parent.parent.parent
            / "tests"
            / "files"
            / "bin"
            / "pixie16-data-01.bin",
            Path(__file__).parent.parent
            / "tests"
            / "files"
            / "bin"
            / "pixie16-data-01.bin",
            Path(__file__).parent / "tests" / "files" / "bin" / "pixie16-data-01.bin",
            Path(__file__).parent.parent.parent
            / "tests"
            / "files"
            / "bin"
            / "pixie16_binary_data-01.bin",
            Path(__file__).parent.parent
            / "tests"
            / "files"
            / "bin"
            / "pixie16_binary_data-01.bin",
        ]

        for path in possible_paths:
            if path.exists():
                print(f"MOCK: Loading dummy data from: {path}")
                return np.fromfile(path, dtype=np.uint8)

        raise FileNotFoundError(
            "No dummy binary data file found. Please specify a file using "
            "mock_instance.set_dummy_data_file(path) or ensure test files are available in tests/files/bin/"
        )

    def _log_call(self, func_name, *args, **kwargs):
        """Log function calls for debugging"""
        arg_str = ", ".join([str(arg) for arg in args])
        kwarg_str = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
        all_args = ", ".join(filter(None, [arg_str, kwarg_str]))

        call_info = f"pixie16.control.{func_name}({all_args})"
        self.call_log.append(call_info)
        print(f"MOCK: {call_info}")

        return call_info

    def get_dummy_data_chunk(self, chunk_size=20000):
        """Return a chunk of dummy data, cycling through the loaded data"""
        if self.dummy_data is None:
            self.dummy_data = self._load_dummy_data()

        if len(self.dummy_data) == 0:
            return np.array([], dtype=np.uint8)

        # Get chunk and advance position
        start_pos = self.data_position
        end_pos = start_pos + chunk_size

        if end_pos >= len(self.dummy_data):
            # Wrap around to beginning
            chunk = self.dummy_data[start_pos:]
            remaining = chunk_size - len(chunk)
            if remaining > 0:
                chunk = np.concatenate([chunk, self.dummy_data[:remaining]])
            self.data_position = remaining
        else:
            chunk = self.dummy_data[start_pos:end_pos]
            self.data_position = end_pos

        return chunk


# Global mock instance
_mock_instance = None


def get_mock_instance():
    """Get or create the global mock instance"""
    global _mock_instance
    if _mock_instance is None:
        _mock_instance = MockPixieControl()
    return _mock_instance


def set_mock_data_file(filepath: str):
    """Set which binary file to use for mock data"""
    mock = get_mock_instance()
    mock.set_dummy_data_file(filepath)


module_list = [2]


def init(modules: list[int], offline_mode: bool = False, verbose: bool = False) -> None:
    global module_list
    module_list = modules
    mock = get_mock_instance()
    mock.module_list = modules
    mock._log_call("init", modules, offline_mode=offline_mode, verbose=verbose)


def boot(
    section_name: str | None = "default",
    modules: list[int] | None = None,
    boot_pattern: int = 0x7F,
    verbose: bool = False,
) -> None:
    mock = get_mock_instance()
    mock._log_call(
        "boot", section_name, modules, boot_pattern=boot_pattern, verbose=verbose
    )


def init_and_boot(
    offline_mode: bool = False,
    section_name: str | None = "default",
    modules: list[int] | None = None,
    boot_pattern: int = 0x7F,
    verbose: bool = False,
) -> None:
    global module_list
    if modules is None:
        modules = [2]
    module_list = modules
    mock = get_mock_instance()
    mock.module_list = modules
    mock._log_call(
        "init_and_boot",
        offline_mode=offline_mode,
        section_name=section_name,
        modules=modules,
        boot_pattern=boot_pattern,
        verbose=verbose,
    )


def adjust_offsets(modules: Iterable[int] | None = None) -> None:
    mock = get_mock_instance()
    mock._log_call("adjust_offsets", modules)


def set_sync_mode(modules: Iterable[int] | None = None) -> None:
    mock = get_mock_instance()
    mock._log_call("set_sync_mode", modules)


def unset_sync_mode(modules: Iterable[int] | None = None) -> None:
    mock = get_mock_instance()
    mock._log_call("unset_sync_mode", modules)


def empty_fifo(module: int) -> None:
    """Read all data in a fifo of a specific module and discard it."""
    mock = get_mock_instance()
    mock._log_call("empty_fifo", module)


def empty_all_fifos() -> None:
    """Read data from all fifos and discard it."""
    mock = get_mock_instance()
    mock._log_call("empty_all_fifos")


def start_histogram_run() -> None:
    mock = get_mock_instance()
    mock.run_active = True
    mock._log_call("start_histogram_run")


def start_list_mode_run() -> None:
    mock = get_mock_instance()
    mock.run_active = True
    mock._log_call("start_list_mode_run")


def check_run_status() -> bool:
    mock = get_mock_instance()
    mock._log_call("check_run_status")
    return mock.run_active


def end_run() -> None:
    mock = get_mock_instance()
    mock.run_active = False
    mock._log_call("end_run")


def exit_system() -> None:
    mock = get_mock_instance()
    mock._log_call("exit_system")


def read_list_mode_fifo(
    check: bool = True, threshold: int = 64, modules: Iterable[int] | None = None
) -> list[np.ndarray]:
    """Reads data from pixies FIFO across all modules defined in pixie16.control.modules

    Returns
    -------
    List[np.ndarray]
        List with data as a numpy array of 32 bit unsigned integers for each module.
    """
    mock = get_mock_instance()
    mock._log_call(
        "read_list_mode_fifo", check=check, threshold=threshold, modules=modules
    )

    if modules is None:
        modules = module_list

    # Simulate the check logic from real function
    do_read = True
    if check:
        do_read = False
        # Simulate that we occasionally have data above threshold
        if np.random.random() > 0.3:  # 70% chance of having data
            do_read = True

    output = []
    if do_read:
        for i, _ in enumerate(modules):
            # Generate realistic amount of data
            chunk_size = threshold * 4 if do_read else 0
            if chunk_size > 0:
                chunk = mock.get_dummy_data_chunk(chunk_size)
                # Convert to uint32 as pixie16 returns
                if len(chunk) % 4 != 0:
                    # Pad to make it divisible by 4
                    pad_size = 4 - (len(chunk) % 4)
                    chunk = np.concatenate([chunk, np.zeros(pad_size, dtype=np.uint8)])

                # Convert to uint32
                uint32_data = chunk.view(np.uint32)
                output.append(uint32_data)
            else:
                output.append(np.array([], dtype=np.uint32))

    return output


def take_list_mode_data(
    duration: float,
    modules: Iterable[int] | None = None,
) -> dict[int, np.ndarray]:
    """Take list mode data for a certain time.

    Parameters
    ----------
    duration
       Length in seconds of how long data is acquired for
    modules
       List of modules, use the ones defined during `init` if None.

    Returns
    -------
    Dict of module index to numpy arrays
    """
    mock = get_mock_instance()
    mock._log_call("take_list_mode_data", duration, modules=modules)

    if modules is None:
        modules = module_list

    # Simulate acquisition time (but don't actually wait)
    time.sleep(min(duration, 0.5))

    out = {}
    for i, module in enumerate(modules):
        chunk_size = int(duration * 10000)  # Simulate data rate
        chunk = mock.get_dummy_data_chunk(chunk_size)
        # Convert to uint32 to match real pixie data
        if len(chunk) % 4 != 0:
            pad_size = 4 - (len(chunk) % 4)
            chunk = np.concatenate([chunk, np.zeros(pad_size, dtype=np.uint8)])
        uint32_data = chunk.view(np.uint32)
        out[i] = uint32_data

    return out


def take_MCA_spectra(
    channels: Iterable[tuple[int, int]],
    duration: float,
    verbose: bool = True,
    position: int = 0,
) -> list[np.ndarray]:
    """Takes MCA spectra for a certain time on the specified channels.

    Returns
    -------
    list(nd.ndarray)
         List of numpy arrays. One for each channel.
    """
    mock = get_mock_instance()
    mock._log_call(
        "take_MCA_spectra", channels, duration, verbose=verbose, position=position
    )

    # Simulate acquisition time
    time.sleep(min(duration, 0.5))  # Don't actually wait the full duration

    # Return list of histograms (one per channel)
    histograms = []
    for _ in channels:
        # Create a fake histogram with some peaks
        histogram = np.random.poisson(10, 32768)  # 32k channels
        # Add some fake peaks
        histogram[1000:1010] += np.random.poisson(100, 10)
        histogram[5000:5020] += np.random.poisson(200, 20)
        histograms.append(histogram.astype(np.uint32))
    return histograms


def read_histograms(module_channels: Iterable[tuple[int, int]]) -> list[np.ndarray]:
    """Read histograms from several channels."""
    mock = get_mock_instance()
    mock._log_call("read_histograms", module_channels)

    histograms = []
    for module, channel in module_channels:
        # Create a fake histogram with some peaks
        histogram = np.random.poisson(10, 32768)
        # Add some fake peaks based on channel number
        peak_pos = 1000 + channel * 100
        histogram[peak_pos : peak_pos + 10] += np.random.poisson(100, 10)
        histograms.append(histogram.astype(np.uint32))

    return histograms


def get_stats():
    """Get statistics for all modules."""
    mock = get_mock_instance()
    mock._log_call("get_stats")

    # Return format needs to match what real function returns
    stats = []
    for module in module_list:
        stat = {
            "module": module,
            "input_count_rate": np.random.randint(1000, 10000),
            "output_count_rate": np.random.randint(500, 5000),
            "live_time": 0.95 + np.random.random() * 0.04,
            "real_time": 1.0,
        }
        stats.append(stat)

    return stats


def save_stats_to_json(filename: Path) -> None:
    """Get statistics for all modules and save as json to file."""
    mock = get_mock_instance()
    mock._log_call("save_stats_to_json", filename)

    stats = get_stats()
    with open(filename, "w") as f:
        json.dump(stats, f, indent=2)


def save_settings_to_json(filename: Path):
    """Save the current settings to a file."""
    mock = get_mock_instance()
    mock._log_call("save_settings_to_json", filename)
    # Actually create a dummy file
    with open(filename, "w") as f:
        json.dump({"mock": "settings", "timestamp": str(time.time())}, f, indent=2)


def reset_coincidence_setting(channels: Iterable[tuple[int, int]]) -> None:
    """Reset all setting in regards to coincidence mode."""
    mock = get_mock_instance()
    mock._log_call("reset_coincidence_setting", channels)


def enable_trace_settings(
    channels: Iterable[tuple[int, int]], disable_CFD: bool = True
) -> None:
    """Enable traces, histograms, and sums."""
    mock = get_mock_instance()
    mock._log_call("enable_trace_settings", channels, disable_CFD=disable_CFD)


def change_setting_from_dict(settings: dict, call_pixie: bool | None = True):
    """Update settings in the pixie16."""
    mock = get_mock_instance()
    mock._log_call("change_setting_from_dict", settings, call_pixie=call_pixie)
    return []  # Return empty list as in real function


def set_channel_parameter(name: str, value, module: int, channel: int):
    """Set and read back a parameter for a channel on the pixie16."""
    mock = get_mock_instance()
    mock._log_call("set_channel_parameter", name, value, module, channel)
    return value  # Return the set value


def set_module_parameter(name: str, value, module: int):
    """Set and read back a parameter for a module on the pixie16."""
    mock = get_mock_instance()
    mock._log_call("set_module_parameter", name, value, module)
    return value  # Return the set value


def set_run_time(runtime, module):
    """Sets the run time for the next run on the pixie16."""
    mock = get_mock_instance()
    mock._log_call("set_run_time", runtime, module)
    return set_module_parameter("HOST_RT_PRESET", runtime, module)


def set_traces(module: int, channel: int, status: bool) -> None:
    mock = get_mock_instance()
    mock._log_call("set_traces", module, channel, status)


def set_defaults_for_module(module: int, call_pixie: bool | None = True):
    mock = get_mock_instance()
    mock._log_call("set_defaults_for_module", module, call_pixie=call_pixie)


def read_settings():
    """Read the current setting into memory."""
    mock = get_mock_instance()
    mock._log_call("read_settings")
    # Return a minimal settings object that matches expected interface
    return MagicMock()


def write_settings(data):
    mock = get_mock_instance()
    mock._log_call("write_settings", data)


@contextmanager
def temporary_settings():
    mock = get_mock_instance()
    mock._log_call("temporary_settings.__enter__")
    try:
        yield None
    finally:
        mock._log_call("temporary_settings.__exit__")


# Additional helper functions for mock
def get_call_log():
    """Get the list of all mock function calls for debugging"""
    mock = get_mock_instance()
    return mock.call_log.copy()


def clear_call_log():
    mock = get_mock_instance()
    mock.call_log.clear()


def is_mocked():
    return True
