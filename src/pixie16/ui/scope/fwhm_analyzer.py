"""
FWHM Analysis Module for PIXIE-16 Scope
Provides peak detection and Full Width Half Maximum analysis for spectrum data
"""

import numpy as np
from typing import Dict, List, Optional, Any, Union
import logging

try:
    from scipy import signal
    from scipy.ndimage import gaussian_filter1d
    SCIPY_AVAILABLE = True
except ImportError:
    print("Warning: scipy not available, using numpy fallbacks for FWHM analysis")
    SCIPY_AVAILABLE = False

try:
    import lmfit
    LMFIT_AVAILABLE = True
except ImportError:
    print("Warning: lmfit not available, Gaussian fitting disabled")
    LMFIT_AVAILABLE = False

logger = logging.getLogger(__name__)


class EnergyCalibration:
    def __init__(self, coefficients: List[float] = None, 
                 calibration_type: str = "polynomial", units: str = "keV"):
        self.coefficients = coefficients or [0.0, 1.0]  # Default: E = channel
        self.calibration_type = calibration_type
        self.units = units
        
    def channel_to_energy(self, channel: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        if self.calibration_type == "polynomial":
            channel = np.asarray(channel)
            energy = np.polyval(self.coefficients, channel)
            return energy.item() if energy.shape == () else energy
        elif self.calibration_type == "linear":
            # E = a * channel + b
            return self.coefficients[0] * channel + self.coefficients[1]
        else:
            return channel  # Pass-through
            


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
        
        # Gaussian fit results
        self.peak_centers = []
        self.peak_amplitudes = []
        self.peak_sigmas = []
        self.peak_fwhms = []
        self.peak_areas = []
        self.center_errors = []
        self.amplitude_errors = []
        self.sigma_errors = []
        self.background_params = {}
        self.reduced_chi2 = None
        self.fit_success = False
        
        # Energy calibration results
        self.peak_centers_energy = []
        self.peak_fwhms_energy = []
        self.energy_units = "keV"
        self.x_axis_type = "channels"  # or "energy"
        self.energy_calibration = None
        
        # Statistical analysis results
        self.peak_areas_net = []  # Background-subtracted areas
        self.peak_areas_gross = []  # Total areas
        self.peak_significances = []  # Statistical significance (sigma)
        self.detection_limits = []  # Minimum detectable amounts
        self.continuum_areas = []  # Background under each peak


class FWHMAnalyzer:
    def __init__(self):
        self.smoothing_sigma = 2.0
        self.min_peak_height_ratio = 0.1
        self.background_window = 50
        self.interpolation_factor = 10
        self.enable_gaussian_fitting = LMFIT_AVAILABLE
        self.background_types = ["linear", "quadratic", "constant"]
        self.default_background = "linear"
        self.energy_calibrations = {}  # Per-channel energy calibrations
        
        # Multi-peak decomposition settings
        self.max_peaks_auto = 10  # Maximum peaks to auto-detect
        self.peak_overlap_threshold = 2.0  # Minimum separation in sigma units
        self.enable_peak_constraints = True  # Enable intelligent parameter constraints
        
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
            peak_channels = [ch for ch, _ in sorted_pairs[:self.max_peaks_auto]]
            
            # Filter overlapping peaks for multi-peak decomposition
            if self.enable_peak_constraints and len(peak_channels) > 1:
                peak_channels = self._filter_overlapping_peaks(spectrum, peak_channels)
            
        return peak_channels
    
    def _filter_overlapping_peaks(self, spectrum: np.ndarray, peak_channels: List[int]) -> List[int]:
        filtered_peaks = []
        
        for peak_ch in peak_channels:
            # Estimate peak width
            peak_width = self._estimate_peak_width_advanced(spectrum, peak_ch)
            
            # Check if this peak is too close to existing peaks
            too_close = False
            for existing_peak in filtered_peaks:
                distance = abs(peak_ch - existing_peak)
                min_distance = self.peak_overlap_threshold * peak_width
                
                if distance < min_distance:
                    # Keep the stronger peak
                    if spectrum[peak_ch] <= spectrum[existing_peak]:
                        too_close = True
                        break
                    else:
                        # Remove the weaker existing peak
                        filtered_peaks.remove(existing_peak)
                        
            if not too_close:
                filtered_peaks.append(peak_ch)
                
        return filtered_peaks
    
    def _estimate_peak_width_advanced(self, spectrum: np.ndarray, peak_ch: int) -> float:
        # More sophisticated peak width estimation
        if peak_ch < 5 or peak_ch >= len(spectrum) - 5:
            return 5.0
            
        peak_height = spectrum[peak_ch]
        baseline = np.mean(spectrum[max(0, peak_ch-50):max(1, peak_ch-25)])
        
        # Find FWHM points
        half_max = baseline + (peak_height - baseline) / 2
        
        # Search left
        left_idx = peak_ch
        while left_idx > 0 and spectrum[left_idx] > half_max:
            left_idx -= 1
            
        # Search right
        right_idx = peak_ch
        while right_idx < len(spectrum) - 1 and spectrum[right_idx] > half_max:
            right_idx += 1
            
        fwhm = right_idx - left_idx
        return max(2.0, fwhm / 2.355)  # Convert FWHM to sigma, minimum 2.0
    
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
    
    def fit_gaussian_peaks(self, spectrum: np.ndarray, roi_start: int = None, 
                          roi_end: int = None, background_type: str = None) -> FWHMResult:
        if not LMFIT_AVAILABLE:
            return self._fallback_analysis(spectrum, roi_start, roi_end)
            
        if roi_start is None:
            roi_start = 0
        if roi_end is None:
            roi_end = len(spectrum) - 1
        if background_type is None:
            background_type = self.default_background
            
        result = FWHMResult(-1, roi_start, roi_end)
        
        peak_channels = self.find_peaks_in_roi(spectrum, roi_start, roi_end)
        if not peak_channels:
            return result
            
        roi_spectrum = spectrum[roi_start:roi_end + 1]
        x_data = np.arange(roi_start, roi_end + 1)
        
        try:
            model = self._create_model(background_type, len(peak_channels))
            params = self._init_params(model, x_data, roi_spectrum, peak_channels, background_type)
            
            weights = np.sqrt(1.0 / np.maximum(roi_spectrum, 1.0))
            fit_result = model.fit(roi_spectrum, params, x=x_data, weights=weights)
            
            result = self._extract_results(fit_result, result, len(peak_channels))
            result.fit_success = True
            
        except Exception as e:
            logger.warning(f"Gaussian fitting failed: {e}")
            return self._fallback_analysis(spectrum, roi_start, roi_end)
            
        return result
    
    def _create_model(self, background_type: str, n_peaks: int):
        if background_type == "constant":
            model = lmfit.models.ConstantModel(prefix="bg_")
        elif background_type == "quadratic": 
            model = lmfit.models.QuadraticModel(prefix="bg_")
        else:
            model = lmfit.models.LinearModel(prefix="bg_")
            
        for i in range(n_peaks):
            gauss = lmfit.models.GaussianModel(prefix=f"g{i+1}_")
            model += gauss
            
        return model
    
    def _init_params(self, model, x_data, y_data, peak_channels, background_type):
        params = model.make_params()
        
        if background_type == "constant":
            params["bg_c"].set(value=np.mean(y_data[:50]))
        elif background_type == "quadratic":
            params["bg_a"].set(value=0)
            params["bg_b"].set(value=0)
            params["bg_c"].set(value=np.mean(y_data[:50]))
        else:
            params["bg_slope"].set(value=0)
            params["bg_intercept"].set(value=np.mean(y_data[:50]))
            
        for i, peak_ch in enumerate(peak_channels):
            peak_idx = peak_ch - x_data[0]
            if 0 <= peak_idx < len(y_data):
                peak_height = y_data[peak_idx]
                
                # Advanced sigma estimation for multi-peak scenarios
                if self.enable_peak_constraints and len(peak_channels) > 1:
                    sigma_guess = self._estimate_peak_width_advanced(y_data, peak_idx)
                else:
                    sigma_guess = 5.0
                    
                amplitude_guess = peak_height * sigma_guess * np.sqrt(2 * np.pi)
                
                # Constraint limits based on peak separation for multi-peak fits
                center_tolerance = min(10.0, sigma_guess * 2)
                sigma_max = min(50.0, sigma_guess * 3)
                
                # For multi-peak fits, constrain centers more tightly
                if len(peak_channels) > 1:
                    # Find nearest neighbor distance
                    distances = [abs(peak_ch - other_ch) for other_ch in peak_channels if other_ch != peak_ch]
                    if distances:
                        min_distance = min(distances)
                        center_tolerance = min(center_tolerance, min_distance / 3)
                
                params[f"g{i+1}_center"].set(value=peak_ch, 
                                           min=peak_ch-center_tolerance, 
                                           max=peak_ch+center_tolerance)
                params[f"g{i+1}_sigma"].set(value=sigma_guess, min=1.0, max=sigma_max)
                params[f"g{i+1}_amplitude"].set(value=amplitude_guess, min=0)
                
        return params
    
    def _extract_results(self, fit_result, result: FWHMResult, n_peaks: int):
        result.reduced_chi2 = fit_result.redchi
        
        for param_name, param in fit_result.params.items():
            if param_name.startswith("bg_"):
                result.background_params[param_name] = param.value
                
        for i in range(n_peaks):
            prefix = f"g{i+1}_"
            
            center = fit_result.params[f"{prefix}center"].value
            center_err = fit_result.params[f"{prefix}center"].stderr or 0
            result.peak_centers.append(center)
            result.center_errors.append(center_err)
            
            sigma = fit_result.params[f"{prefix}sigma"].value
            sigma_err = fit_result.params[f"{prefix}sigma"].stderr or 0
            fwhm = sigma * 2.355
            result.peak_sigmas.append(sigma)
            result.peak_fwhms.append(fwhm)
            result.sigma_errors.append(sigma_err)
            
            amplitude = fit_result.params[f"{prefix}amplitude"].value
            amplitude_err = fit_result.params[f"{prefix}amplitude"].stderr or 0
            result.peak_amplitudes.append(amplitude)
            result.peak_areas.append(amplitude)
            result.amplitude_errors.append(amplitude_err)
            
            # Statistical analysis
            peak_height = amplitude / (sigma * np.sqrt(2 * np.pi))
            
            # Calculate background under peak (integrate background over FWHM)
            bg_components = fit_result.eval_components()
            bg_key = [k for k in bg_components.keys() if k.startswith('bg_') or 'linear' in k or 'quadratic' in k or 'constant' in k][0]
            
            # Estimate background counts under peak
            fwhm_channels = int(fwhm + 0.5)
            start_ch = max(0, int(center - fwhm_channels//2))
            end_ch = min(len(bg_components[bg_key]), int(center + fwhm_channels//2))
            
            if end_ch > start_ch:
                continuum_area = np.sum(bg_components[bg_key][start_ch:end_ch])
                result.continuum_areas.append(continuum_area)
                
                # Net area (background subtracted)
                net_area = amplitude - continuum_area
                result.peak_areas_net.append(max(0, net_area))
                result.peak_areas_gross.append(amplitude)
                
                # Statistical significance (Currie's approximation)
                # σ = √(gross + 2*background)
                if continuum_area > 0:
                    significance = net_area / np.sqrt(amplitude + 2 * continuum_area)
                    result.peak_significances.append(max(0, significance))
                    
                    # Detection limit (3σ criterion)
                    detection_limit = 3 * np.sqrt(continuum_area)
                    result.detection_limits.append(detection_limit)
                else:
                    result.peak_significances.append(0)
                    result.detection_limits.append(0)
            else:
                result.continuum_areas.append(0)
                result.peak_areas_net.append(amplitude)
                result.peak_areas_gross.append(amplitude)
                result.peak_significances.append(0)
                result.detection_limits.append(0)
            
        return result
    
    def _fallback_analysis(self, spectrum, roi_start, roi_end):
        result = FWHMResult(-1, roi_start, roi_end)
        peak_channels = self.find_peaks_in_roi(spectrum, roi_start, roi_end)
        
        for peak_ch in peak_channels:
            fwhm_result = self.calculate_fwhm(spectrum, peak_ch)
            if fwhm_result.fwhm_channels is not None:
                result.peak_centers.append(peak_ch)
                result.peak_fwhms.append(fwhm_result.fwhm_channels)
                result.peak_amplitudes.append(spectrum[peak_ch])
                
        return result
    
    def set_energy_calibration(self, channel: int, calibration: EnergyCalibration):
        self.energy_calibrations[channel] = calibration
        
    def get_energy_calibration(self, channel: int) -> Optional[EnergyCalibration]:
        return self.energy_calibrations.get(channel, None)
    
    def _apply_energy_calibration(self, result: FWHMResult, channel_id: int):
        calibration = self.get_energy_calibration(channel_id)
        if not calibration:
            return result
            
        result.energy_calibration = calibration
        result.energy_units = calibration.units
        result.x_axis_type = "energy"
        
        # Convert peak centers to energy
        if result.peak_centers:
            result.peak_centers_energy = [
                calibration.channel_to_energy(center) for center in result.peak_centers
            ]
            
        # Convert FWHM to energy
        if result.peak_fwhms and result.peak_centers:
            for i, (center, fwhm_ch) in enumerate(zip(result.peak_centers, result.peak_fwhms)):
                sigma_ch = fwhm_ch / 2.355
                left_ch = center - sigma_ch
                right_ch = center + sigma_ch
                left_energy = calibration.channel_to_energy(left_ch)
                right_energy = calibration.channel_to_energy(right_ch)
                fwhm_energy = abs(right_energy - left_energy)
                result.peak_fwhms_energy.append(fwhm_energy)
                
        # Convert single peak results if available
        if result.fwhm_channels and result.left_half_max and result.right_half_max:
            left_energy = calibration.channel_to_energy(result.left_half_max)
            right_energy = calibration.channel_to_energy(result.right_half_max)
            result.fwhm_energy = abs(right_energy - left_energy)
            
        return result
    
    def analyze_roi(self, spectrum: np.ndarray, roi_start: int, roi_end: int,
                    channel_id: int = -1, energy_calibration: callable = None, 
                    use_gaussian_fit: bool = None) -> List[FWHMResult]:
        
        if use_gaussian_fit is None:
            use_gaussian_fit = self.enable_gaussian_fitting
            
        if use_gaussian_fit and LMFIT_AVAILABLE:
            result = self.fit_gaussian_peaks(spectrum, roi_start, roi_end)
            result.channel = channel_id
            
            # Apply energy calibration if available
            result = self._apply_energy_calibration(result, channel_id)
            
            # Legacy energy_calibration callable support
            if energy_calibration and result.peak_centers:
                try:
                    for i, center in enumerate(result.peak_centers):
                        energy_center = energy_calibration(center)
                        if i < len(result.peak_fwhms):
                            fwhm_ch = result.peak_fwhms[i] / 2.355
                            left_ch = center - fwhm_ch
                            right_ch = center + fwhm_ch
                            left_energy = energy_calibration(left_ch)
                            right_energy = energy_calibration(right_ch)
                            result.peak_fwhms[i] = abs(right_energy - left_energy)
                except Exception as e:
                    logger.warning(f"Energy calibration failed: {e}")
                    
            return [result] if result.peak_centers else []
        else:
            results = []
            peak_channels = self.find_peaks_in_roi(spectrum, roi_start, roi_end)
            
            for peak_ch in peak_channels:
                result = self.calculate_fwhm(spectrum, peak_ch, interpolate=True)
                result.channel = channel_id
                result.roi_start = roi_start  
                result.roi_end = roi_end
                
                # Apply energy calibration if available
                result = self._apply_energy_calibration(result, channel_id)
                
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
    
    # Add some background noise and linear background
    spectrum += np.random.poisson(10, size=4096)
    spectrum += 5 + 0.001 * channels  # Linear background
    
    # Add Gaussian peaks including some overlapping ones
    peaks = [
        (800, 5000, 15),    # Isolated peak
        (850, 2000, 12),    # Overlapping with first
        (1200, 8000, 20),   # Strong peak
        (1250, 3000, 18),   # Overlapping with strong peak
        (2000, 3000, 25),   # Isolated peak
        (2100, 1500, 15),   # Weak overlapping peak
    ]
    for center, height, sigma in peaks:
        spectrum += height * np.exp(-0.5 * ((channels - center) / sigma) ** 2)
        
    return spectrum.astype(int)


if __name__ == "__main__":
    analyzer = FWHMAnalyzer()
    test_spectrum = create_test_spectrum()
    
    print(f"Testing FWHM analyzer with LMfit available: {LMFIT_AVAILABLE}")
    
    # Test basic FWHM analysis
    results = analyzer.analyze_roi(test_spectrum, 750, 850, channel_id=0)
    print(f"\nBasic FWHM analysis found {len(results)} peaks:")
    for i, result in enumerate(results):
        if hasattr(result, 'peak_channel') and result.peak_channel:
            print(f"  Peak {i+1} at channel {result.peak_channel}:")
            print(f"    FWHM: {result.fwhm_channels:.2f} channels")
            print(f"    Resolution: {result.resolution_percent:.2f}%")
            print(f"    SNR: {result.snr:.1f}")
    
    # Test Gaussian fitting if available
    if LMFIT_AVAILABLE:
        print("\nTesting Gaussian fitting:")
        fit_result = analyzer.fit_gaussian_peaks(test_spectrum, 750, 850)
        print(f"Fit success: {fit_result.fit_success}")
        print(f"Found {len(fit_result.peak_centers)} fitted peaks:")
        for i, (center, fwhm, amp, net_area, significance) in enumerate(zip(
            fit_result.peak_centers, fit_result.peak_fwhms, fit_result.peak_amplitudes,
            fit_result.peak_areas_net, fit_result.peak_significances
        )):
            print(f"  Peak {i+1}: center={center:.1f}, FWHM={fwhm:.2f}, amplitude={amp:.0f}")
            print(f"    Net area={net_area:.0f}, significance={significance:.1f}σ")
        if fit_result.reduced_chi2:
            print(f"Reduced chi-squared: {fit_result.reduced_chi2:.3f}")
            
        # Test energy calibration
        if fit_result.peak_centers:
            print("\nTesting energy calibration:")
            # Create a simple linear calibration (keV = 0.5 * channel + 100)
            cal = EnergyCalibration([0.5, 100], "linear", "keV")
            analyzer.set_energy_calibration(0, cal)
            
            # Re-analyze with energy calibration
            cal_results = analyzer.analyze_roi(test_spectrum, 750, 850, channel_id=0)
            if cal_results and cal_results[0].peak_centers_energy:
                print(f"Peak energies: {[f'{e:.1f} keV' for e in cal_results[0].peak_centers_energy]}")
                print(f"FWHM energies: {[f'{f:.2f} keV' for f in cal_results[0].peak_fwhms_energy]}")
    else:
        print("\nLMfit not available - Gaussian fitting disabled")