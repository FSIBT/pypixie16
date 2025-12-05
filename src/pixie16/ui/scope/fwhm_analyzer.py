"""
FWHM Analysis Module for PIXIE-16 Scope
Provides peak detection and Full Width Half Maximum analysis for spectrum data
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Any
import logging

try:
    from scipy import signal
    from scipy.ndimage import gaussian_filter1d
    SCIPY_AVAILABLE = True
except ImportError:
    print("Warning: scipy not available, using numpy fallbacks for FWHM analysis")
    SCIPY_AVAILABLE = False

logger = logging.getLogger(__name__)


def numpy_gaussian_filter1d(data, sigma):
    kernel_size = int(4 * sigma + 0.5)
    if kernel_size % 2 == 0:
        kernel_size += 1
    
    x = np.arange(kernel_size) - kernel_size // 2
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel = kernel / np.sum(kernel)
    
    return np.convolve(data, kernel, mode='same')


def numpy_find_peaks(data, height=None, prominence=None, distance=None):
    peaks = []
    
    if height is None:
        height = 0
    if distance is None:
        distance = 1
        
    for i in range(1, len(data) - 1):
        if (data[i] > data[i-1] and data[i] > data[i+1] and 
            data[i] >= height):
            
            # Check distance constraint
            if distance > 1 and peaks:
                if i - peaks[-1] < distance:
                    continue
                    
            peaks.append(i)
            
    return np.array(peaks), {}


class FWHMResult:
    def __init__(self, channel: int, roi_start: int, roi_end: int):
        self.channel = channel
        self.roi_start = roi_start
        self.roi_end = roi_end
        self.peak_channel = None
        self.peak_counts = None
        self.fwhm_channels = None
        self.fwhm_energy = None
        self.left_half_max = None
        self.right_half_max = None
        self.resolution_percent = None
        self.background_level = None
        self.snr = None
        self.fit_quality = None
        self.timestamp = None


class FWHMAnalyzer:
    def __init__(self):
        self.smoothing_sigma = 2.0  # Gaussian smoothing parameter
        self.min_peak_height_ratio = 0.1  # Minimum peak height as fraction of max
        self.background_window = 50  # Channels for background estimation
        self.interpolation_factor = 10  # Sub-channel interpolation for precision
        
    def find_peaks_in_roi(self, spectrum: np.ndarray, roi_start: int, roi_end: int, 
                          min_height_ratio: float = None) -> List[int]:
        if roi_end <= roi_start or roi_start < 0 or roi_end >= len(spectrum):
            return []
            
        roi_data = spectrum[roi_start:roi_end + 1]
        roi_max = np.max(roi_data)
        
        if roi_max == 0:
            return []
            
        height_threshold = roi_max * (min_height_ratio or self.min_peak_height_ratio)
        
        # Smooth data for peak finding
        if SCIPY_AVAILABLE:
            smoothed = gaussian_filter1d(roi_data.astype(float), sigma=self.smoothing_sigma)
            # Find peaks with minimum height and prominence
            peaks, properties = signal.find_peaks(
                smoothed, 
                height=height_threshold,
                prominence=height_threshold * 0.5,
                distance=10  # Minimum separation between peaks
            )
        else:
            smoothed = numpy_gaussian_filter1d(roi_data.astype(float), sigma=self.smoothing_sigma)
            # Use numpy fallback peak finding
            peaks, properties = numpy_find_peaks(
                smoothed,
                height=height_threshold,
                distance=10
            )
        
        # Convert back to full spectrum coordinates
        peak_channels = [roi_start + peak for peak in peaks]
        
        # Sort by height (strongest peaks first)
        if peak_channels:
            peak_heights = [spectrum[ch] for ch in peak_channels]
            sorted_pairs = sorted(zip(peak_channels, peak_heights), 
                                key=lambda x: x[1], reverse=True)
            peak_channels = [ch for ch, _ in sorted_pairs]
            
        return peak_channels
    
    def estimate_background(self, spectrum: np.ndarray, peak_channel: int, 
                           window: int = None) -> float:
        window = window or self.background_window
        start = max(0, peak_channel - window)
        end = min(len(spectrum), peak_channel + window)
        
        # Take minimum values in windows on either side of peak
        left_bg = np.min(spectrum[start:max(start+1, peak_channel-window//2)]) if start < peak_channel-window//2 else 0
        right_bg = np.min(spectrum[min(peak_channel+window//2, end):end]) if peak_channel+window//2 < end else 0
        
        return (left_bg + right_bg) / 2
    
    def calculate_fwhm(self, spectrum: np.ndarray, peak_channel: int, 
                       background: float = None, interpolate: bool = True) -> FWHMResult:
        result = FWHMResult(channel=-1, roi_start=0, roi_end=len(spectrum)-1)
        result.peak_channel = peak_channel
        result.peak_counts = int(spectrum[peak_channel])
        
        if background is None:
            background = self.estimate_background(spectrum, peak_channel)
        result.background_level = background
        
        # Background-subtracted peak height
        peak_height = result.peak_counts - background
        if peak_height <= 0:
            logger.warning(f"Peak at channel {peak_channel} has no height above background")
            return result
            
        half_max = background + peak_height / 2
        result.snr = peak_height / max(1, np.sqrt(background)) if background > 0 else peak_height
        
        if interpolate:
            # High-precision FWHM with interpolation
            return self._calculate_fwhm_interpolated(spectrum, peak_channel, half_max, result)
        else:
            # Simple FWHM calculation
            return self._calculate_fwhm_simple(spectrum, peak_channel, half_max, result)
    
    def _calculate_fwhm_simple(self, spectrum: np.ndarray, peak_channel: int, 
                              half_max: float, result: FWHMResult) -> FWHMResult:
        
        # Find left half-max point
        left_half = None
        for i in range(peak_channel, max(0, peak_channel - 200), -1):
            if spectrum[i] <= half_max:
                left_half = i
                break
                
        # Find right half-max point  
        right_half = None
        for i in range(peak_channel, min(len(spectrum), peak_channel + 200)):
            if spectrum[i] <= half_max:
                right_half = i
                break
                
        if left_half is not None and right_half is not None:
            result.left_half_max = left_half
            result.right_half_max = right_half
            result.fwhm_channels = right_half - left_half
            result.resolution_percent = (result.fwhm_channels / peak_channel) * 100
            result.fit_quality = 1.0  # Simple method always "perfect"
            
        return result
    
    def _calculate_fwhm_interpolated(self, spectrum: np.ndarray, peak_channel: int,
                                   half_max: float, result: FWHMResult) -> FWHMResult:
        
        search_range = min(200, peak_channel, len(spectrum) - peak_channel)
        if search_range < 10:
            return self._calculate_fwhm_simple(spectrum, peak_channel, half_max, result)
        
        # Create interpolated data around the peak
        start_ch = peak_channel - search_range
        end_ch = peak_channel + search_range
        channels = np.arange(start_ch, end_ch)
        counts = spectrum[start_ch:end_ch]
        
        # Interpolate with higher resolution
        interp_channels = np.linspace(start_ch, end_ch-1, len(channels) * self.interpolation_factor)
        interp_counts = np.interp(interp_channels, channels, counts)
        
        # Find interpolated peak position
        interp_peak_idx = np.argmax(interp_counts)
        interp_peak_ch = interp_channels[interp_peak_idx]
        
        # Find half-max crossings
        left_indices = np.where((interp_channels < interp_peak_ch) & (interp_counts <= half_max))[0]
        right_indices = np.where((interp_channels > interp_peak_ch) & (interp_counts <= half_max))[0]
        
        if len(left_indices) > 0 and len(right_indices) > 0:
            left_half_ch = interp_channels[left_indices[-1]]  # Closest to peak on left
            right_half_ch = interp_channels[right_indices[0]]  # Closest to peak on right
            
            result.left_half_max = left_half_ch
            result.right_half_max = right_half_ch
            result.fwhm_channels = right_half_ch - left_half_ch
            result.resolution_percent = (result.fwhm_channels / peak_channel) * 100
            result.fit_quality = 0.9  # Good interpolation quality
            
        return result
    
    def analyze_roi(self, spectrum: np.ndarray, roi_start: int, roi_end: int,
                    channel_id: int = -1, energy_calibration: callable = None) -> List[FWHMResult]:
        results = []
        
        # Find peaks in ROI
        peak_channels = self.find_peaks_in_roi(spectrum, roi_start, roi_end)
        
        for peak_ch in peak_channels:
            # Calculate FWHM for this peak
            result = self.calculate_fwhm(spectrum, peak_ch, interpolate=True)
            result.channel = channel_id
            result.roi_start = roi_start  
            result.roi_end = roi_end
            
            # Apply energy calibration if provided
            if energy_calibration and result.fwhm_channels is not None:
                try:
                    peak_energy = energy_calibration(peak_ch)
                    left_energy = energy_calibration(result.left_half_max)
                    right_energy = energy_calibration(result.right_half_max)
                    result.fwhm_energy = abs(right_energy - left_energy)
                except Exception as e:
                    logger.warning(f"Energy calibration failed: {e}")
                    
            results.append(result)
            
        return results


def create_test_spectrum():
    channels = np.arange(4096)
    spectrum = np.zeros(4096)
    
    # Add some background noise
    spectrum += np.random.poisson(10, size=4096)
    
    # Add Gaussian peaks
    peaks = [(800, 5000, 15), (1200, 8000, 20), (2000, 3000, 25)]
    for center, height, sigma in peaks:
        spectrum += height * np.exp(-0.5 * ((channels - center) / sigma) ** 2)
        
    return spectrum.astype(int)


if __name__ == "__main__":
    analyzer = FWHMAnalyzer()
    test_spectrum = create_test_spectrum()
    
    results = analyzer.analyze_roi(test_spectrum, 750, 850, channel_id=0)
    
    for result in results:
        print(f"Peak at channel {result.peak_channel}:")
        print(f"  FWHM: {result.fwhm_channels:.2f} channels")
        print(f"  Resolution: {result.resolution_percent:.2f}%")
        print(f"  SNR: {result.snr:.1f}")