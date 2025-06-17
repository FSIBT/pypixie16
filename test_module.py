#!/usr/bin/env python3
"""
PIXIE-16 MCA Data Debug Test
Run this script to debug MCA data without modifying your scope
"""

import sys
import numpy as np
import matplotlib.pyplot as plt

# Add your pixie16 path if needed
sys.path.insert(0, "/home/carbon/code/pypixie16/src")

try:
    import pixie16 as px
except ImportError as e:
    print(f"Error importing pixie16: {e}")
    sys.exit(1)


def test_mca_data():
    """Test MCA data collection and visualization"""

    print("=== PIXIE-16 MCA Data Debug Test ===")

    # Your exact working settings
    channels = [(0, 4), (0, 9)]
    module_number = 2

    settings = {
        "channels": channels,
        "TRACE_LENGTH": 1.0,
        "TRIGGER_THRESHOLD": 100,
        "TRACE_DELAY": 0.2,
        "MultiplicityMaskL": 0.0,
        "MultiplicityMaskH": 0.0,
        "TRIGGER_RISETIME": 0.02,
        "TRIGGER_FLATTOP": 0.02,
        "FAST_FILTER_RANGE": 0,
        "MODULE_CSRB": 0,
        "BackplanePullup": True,
        "TrigConfig0": 0,
        "TrigConfig1": 0,
        "TrigConfig2": 0,
        "TrigConfig3": 0,
        "Polarity": "positive",
        "CaptureTrace": True,
        "EnableChannelVal": False,
        "EnableCFD": False,
    }

    try:
        # Initialize PIXIE
        print(f"Booting PIXIE-16 module {module_number}...")
        px.control.init_and_boot(modules=[module_number])
        print("✓ PIXIE booted successfully")

        # Apply settings
        print("Applying settings...")
        px.control.change_setting_from_dict(settings, call_pixie=True)
        print("✓ Settings applied")

        # Test different durations
        durations = [0.1, 1.0, 5.0]

        for duration in durations:
            print(f"\n--- Testing {duration}s MCA collection ---")

            histogram_result = px.control.take_MCA_spectra(
                channels=channels, duration=duration, verbose=True
            )

            print(f"Result type: {type(histogram_result)}")
            print(
                f"Result length: {len(histogram_result) if hasattr(histogram_result, '__len__') else 'No length'}"
            )

            if isinstance(histogram_result, list):
                for i, hist_data in enumerate(histogram_result):
                    channel_name = f"Ch{[4, 9][i]}"  # Map to actual channel numbers

                    print(f"\n{channel_name} Analysis:")
                    print(f"  Data type: {type(hist_data)}")
                    print(
                        f"  Shape: {hist_data.shape if hasattr(hist_data, 'shape') else len(hist_data)}"
                    )

                    # Convert to numpy array
                    arr = np.array(hist_data)

                    # Basic statistics
                    print(f"  Total counts: {np.sum(arr):,}")
                    print(f"  Max value: {np.max(arr)}")
                    print(f"  Non-zero bins: {np.count_nonzero(arr)}")
                    print(f"  Mean: {np.mean(arr):.3f}")

                    # Range analysis
                    total_bins = len(arr)
                    print(f"  Total bins: {total_bins}")

                    # Divide into 8 equal sections and check counts
                    section_size = total_bins // 8
                    print(f"  Data distribution (each section = {section_size} bins):")
                    for j in range(8):
                        start = j * section_size
                        end = (j + 1) * section_size if j < 7 else total_bins
                        section_counts = np.sum(arr[start:end])
                        print(
                            f"    Section {j + 1} (bins {start:,}-{end - 1:,}): {section_counts:,} counts"
                        )

                    # Find peak location
                    if np.max(arr) > 0:
                        peak_bin = np.argmax(arr)
                        peak_value = arr[peak_bin]
                        print(f"  Peak: {peak_value} counts at bin {peak_bin}")

                        # Show region around peak
                        start_region = max(0, peak_bin - 50)
                        end_region = min(len(arr), peak_bin + 50)
                        region_sum = np.sum(arr[start_region:end_region])
                        print(
                            f"  Region around peak ({start_region}-{end_region}): {region_sum} counts"
                        )

                    # Create plots
                    plt.figure(figsize=(15, 10))

                    # Full spectrum
                    plt.subplot(2, 3, 1)
                    plt.plot(arr)
                    plt.title(f"{channel_name} - Full Spectrum ({duration}s)")
                    plt.xlabel("Bin")
                    plt.ylabel("Counts")
                    plt.yscale("log")
                    plt.grid(True)

                    # First 4096 bins
                    plt.subplot(2, 3, 2)
                    plt.plot(arr[:4096])
                    plt.title(f"{channel_name} - First 4K Bins")
                    plt.xlabel("Bin")
                    plt.ylabel("Counts")
                    plt.grid(True)

                    # Middle range
                    mid_start = len(arr) // 4
                    mid_end = mid_start + 4096
                    plt.subplot(2, 3, 3)
                    plt.plot(arr[mid_start:mid_end])
                    plt.title(f"{channel_name} - Middle Range ({mid_start}-{mid_end})")
                    plt.xlabel("Bin")
                    plt.ylabel("Counts")
                    plt.grid(True)

                    # High range
                    high_start = len(arr) // 2
                    high_end = high_start + 4096
                    plt.subplot(2, 3, 4)
                    plt.plot(arr[high_start:high_end])
                    plt.title(f"{channel_name} - High Range ({high_start}-{high_end})")
                    plt.xlabel("Bin")
                    plt.ylabel("Counts")
                    plt.grid(True)

                    # Histogram of non-zero values
                    plt.subplot(2, 3, 5)
                    nonzero_indices = np.nonzero(arr)[0]
                    if len(nonzero_indices) > 0:
                        plt.hist(nonzero_indices, bins=50, alpha=0.7)
                        plt.title(f"{channel_name} - Distribution of Non-Zero Bins")
                        plt.xlabel("Bin Number")
                        plt.ylabel("Frequency")
                    else:
                        plt.text(
                            0.5,
                            0.5,
                            "No Data",
                            ha="center",
                            va="center",
                            transform=plt.gca().transAxes,
                        )
                        plt.title(f"{channel_name} - No Data Found")
                    plt.grid(True)

                    # Cumulative sum
                    plt.subplot(2, 3, 6)
                    cumsum = np.cumsum(arr)
                    plt.plot(cumsum)
                    plt.title(f"{channel_name} - Cumulative Sum")
                    plt.xlabel("Bin")
                    plt.ylabel("Cumulative Counts")
                    plt.grid(True)

                    plt.tight_layout()
                    plt.suptitle(
                        f"PIXIE MCA Analysis - {channel_name} - {duration}s Collection",
                        y=1.02,
                    )
                    plt.show()

                    # Save data for inspection
                    filename = f"pixie_mca_ch{[4, 9][i]}_duration{duration}s.npy"
                    np.save(filename, arr)
                    print(f"  Data saved to: {filename}")

            else:
                print(f"Unexpected result format: {histogram_result}")

        # Test with different threshold
        print(f"\n--- Testing with lower threshold ---")
        low_threshold_settings = settings.copy()
        low_threshold_settings["TRIGGER_THRESHOLD"] = 10  # Much lower

        px.control.change_setting_from_dict(low_threshold_settings, call_pixie=True)

        histogram_result = px.control.take_MCA_spectra(
            channels=channels, duration=2.0, verbose=True
        )

        if isinstance(histogram_result, list):
            for i, hist_data in enumerate(histogram_result):
                arr = np.array(hist_data)
                channel_name = f"Ch{[4, 9][i]}"
                print(f"{channel_name} (low threshold): {np.sum(arr):,} total counts")

        # Clean exit
        px.control.exit_system()
        print("\n✓ Test completed successfully")

    except Exception as e:
        print(f"\n✗ Error during test: {e}")
        import traceback

        traceback.print_exc()

        try:
            px.control.exit_system()
        except:
            pass


if __name__ == "__main__":
    test_mca_data()
