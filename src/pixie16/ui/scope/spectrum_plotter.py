"""
Real-time spectrum plotter for PIXIE-16 list mode (binary) data.
"""

import json
import pyqtgraph as pg
import numpy as np
from collections import deque, defaultdict
import time

from PyQt6 import QtCore
from PyQt6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QDoubleSpinBox,
    QPushButton,
    QCheckBox,
    QSpinBox,
    QWidget,
    QSplitter,
    QTabWidget,
    QMainWindow,
)
from PyQt6.QtCore import Qt

# Import FWHM analysis components
try:
    from .fwhm_widget import FWHMAnalysisWidget
    from .fwhm_analyzer import FWHMAnalyzer, EnergyCalibration
    FWHM_AVAILABLE = True
except ImportError as e:
    print(f"FWHM analysis not available: {e}")
    FWHM_AVAILABLE = False

import logging

logger = logging.getLogger(__name__)


class ContinuousSpectrumPlotter(QWidget):
    def __init__(
        self,
        app=None,
        instrument_name="pixie16",
        display_name="PIXIE Energy Spectra",
        channels=None,
        channel_names=None,
        energy_range=(0, 4096),
        bins=1000,
        bkg_color="w",
        update_hooks=None,
    ):
        super().__init__()

        self.app = app
        self.instrument = instrument_name
        self.channels = channels or list(range(16))
        self.channel_names = channel_names or [f"Ch{ch}" for ch in self.channels]
        self.energy_range = energy_range
        self.bins = bins
        self.update_hooks = update_hooks or []
        self.display_channels = self.channels.copy()

        # Energy data storage - use deque for efficient append/pop operations
        self.energy_data = defaultdict(lambda: deque(maxlen=50000))
        self.last_update = time.time()
        self.update_rate = 0.5  # seconds
        
        # Gaussian fitting
        self.fwhm_analyzer = FWHMAnalyzer() if FWHM_AVAILABLE else None
        self.show_gaussian_fits = False
        self.show_background_subtracted = False
        self.fit_results = {}  # Store latest fit results per channel
        self.background_estimates = {}  # Store background estimates per channel
        
        # Energy calibration
        self.use_energy_axis = False
        self.energy_axis_label = "Energy (keV)"

        # Update timer
        self.update_timer = QtCore.QTimer()
        self.update_timer.timeout.connect(self.update_display)

        # Channel colors
        self.channel_colors = [
            "#1f77b4",
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
            "#9467bd",
            "#8c564b",
            "#e377c2",
            "#7f7f7f",
            "#bcbd22",
            "#17becf",
            "#aec7e8",
            "#ffbb78",
            "#98df8a",
            "#ff9896",
            "#c5b0d5",
            "#c49c94",
        ]

        self.setWindowTitle(display_name)
        self.setup_ui(bkg_color)

    def setup_ui(self, bkg_color):
        main_layout = QVBoxLayout()

        # Controls
        self.control_group = self.create_control_group()
        main_layout.addWidget(self.control_group)

        # Plot area (full width now)
        self.display = pg.PlotWidget()
        self.display.setBackground(bkg_color)
        self.display.setLabel("left", "Counts")
        self.display.setLabel("bottom", "Energy", "a.u.")
        self.display.setTitle("PIXIE-16 List Mode Energy Spectra")
        self.display.showGrid(x=True, y=True)
        
        # Initialize with proper axis ranges - Y starts at 0
        self.display.setXRange(*self.energy_range)
        self.display.setYRange(0, 100, padding=0)  # Start Y at 0, no padding
        
        # Disable auto-range by default (user can manually zoom with mouse/controls)
        self.display.enableAutoRange('x', False)
        self.display.enableAutoRange('y', False)
        self.display.setMenuEnabled(enableMenu=True)
        self.display.addLegend()

        # Store reference to plot widget for FWHM integration
        self.plot_widget = self.display

        # Create plot items for each channel
        self.plot_items = {}
        for i, channel in enumerate(self.channels):
            color = self.channel_colors[i % len(self.channel_colors)]
            pen = pg.mkPen(color=color, width=2)
            curve = pg.PlotCurveItem(pen=pen, name=self.channel_names[i])
            self.plot_items[channel] = curve
            self.display.addItem(curve)

        main_layout.addWidget(self.display)

        # Statistics display
        self.stats_widget = self.create_stats_widget()
        main_layout.addWidget(self.stats_widget)
        
        if FWHM_AVAILABLE:
            self.fwhm_window = None  # Will be created on demand
            self.setup_fwhm_menu()
        else:
            self.fwhm_window = None
        self.setLayout(main_layout)

    def setup_fwhm_menu(self):
        if hasattr(self, 'control_group') and self.control_group:
            layout = self.control_group.layout()
            if layout:
                self.fwhm_btn = QPushButton("FWHM")
                self.fwhm_btn.setToolTip("Open FWHM Peak Analysis Window")
                self.fwhm_btn.clicked.connect(self.toggle_fwhm_window)
                self.fwhm_btn.setMaximumWidth(100)  # Keep it compact
                layout.addWidget(self.fwhm_btn)
        
    def toggle_fwhm_window(self):
        if self.fwhm_window is None:
            self.create_fwhm_window()
        
        if self.fwhm_window.isVisible():
            self.fwhm_window.hide()
            self.fwhm_btn.setText("FWHM")
        else:
            self.fwhm_window.show()
            self.fwhm_window.raise_()  # Bring to front
            self.fwhm_window.activateWindow()
            self.fwhm_btn.setText("Hide FWHM")
            
    def create_fwhm_window(self):
        # Create floating window
        self.fwhm_window = QMainWindow()
        self.fwhm_window.setWindowTitle("FWHM Peak Analysis")
        self.fwhm_window.setWindowFlags(
            Qt.WindowType.Window | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        
        # Set window size and position
        self.fwhm_window.resize(600, 800)
        
        # Position window to the right of main window if possible
        if self.parent():
            main_pos = self.parent().pos()
            main_size = self.parent().size()
            self.fwhm_window.move(main_pos.x() + main_size.width() + 10, main_pos.y())
        
        # Create FWHM widget and set as central widget
        self.fwhm_widget = FWHMAnalysisWidget(spectrum_plotter=self)
        self.fwhm_widget.connect_to_plotter(self)
        self.fwhm_window.setCentralWidget(self.fwhm_widget)
        
        # Handle window close event
        self.fwhm_window.closeEvent = self.on_fwhm_window_close
        
    def on_fwhm_window_close(self, event):
        self.fwhm_btn.setText("FWHM")
        event.accept()

    def create_control_widgets(self):
        self.energy_min_label = QLabel("Energy Min (a.u.):")
        self.energy_min_spin = QDoubleSpinBox()
        self.energy_min_spin.setRange(0, 10000)
        self.energy_min_spin.setValue(self.energy_range[0])
        self.energy_min_spin.valueChanged.connect(self.update_energy_range)

        self.energy_max_label = QLabel("Energy Max (a.u.):")
        self.energy_max_spin = QDoubleSpinBox()
        self.energy_max_spin.setRange(0, 100000)
        self.energy_max_spin.setValue(self.energy_range[1])
        self.energy_max_spin.valueChanged.connect(self.update_energy_range)

        self.bins_label = QLabel("Bins:")
        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(10, 100000)
        self.bins_spin.setValue(self.bins)
        self.bins_spin.valueChanged.connect(self.update_bins)

        self.log_scale_cb = QCheckBox("Log Scale")
        self.log_scale_cb.toggled.connect(self.toggle_log_scale)

        self.auto_scale_cb = QCheckBox("Auto Scale")
        self.auto_scale_cb.setChecked(False)  # Disable auto-scale by default
        self.auto_scale_cb.toggled.connect(self.toggle_auto_scale)

        self.clear_btn = QPushButton("Clear Spectra")
        self.clear_btn.clicked.connect(self.clear_data)

    def create_control_group(self):
        self.create_control_widgets()

        group = QGroupBox("Plot Controls")
        group.setMaximumHeight(80)  # Make more compact
        layout = QHBoxLayout()  # Use horizontal layout
        layout.setSpacing(5)

        # Energy range controls
        layout.addWidget(QLabel("Min:"))
        self.energy_min_spin.setMaximumWidth(80)
        layout.addWidget(self.energy_min_spin)

        layout.addWidget(QLabel("Max:"))
        self.energy_max_spin.setMaximumWidth(80)
        layout.addWidget(self.energy_max_spin)

        # Bins control
        layout.addWidget(QLabel("Bins:"))
        self.bins_spin.setMaximumWidth(70)
        layout.addWidget(self.bins_spin)

        # Checkboxes with shorter text
        self.log_scale_cb.setText("Log")
        layout.addWidget(self.log_scale_cb)

        self.auto_scale_cb.setText("Auto")
        layout.addWidget(self.auto_scale_cb)

        # Clear button
        self.clear_btn.setText("Clear")
        self.clear_btn.setMaximumWidth(60)
        layout.addWidget(self.clear_btn)

        # Gaussian fit checkbox
        if FWHM_AVAILABLE:
            self.gaussian_fit_cb = QCheckBox("Fits")
            self.gaussian_fit_cb.setToolTip("Show Gaussian fits")
            self.gaussian_fit_cb.toggled.connect(self.toggle_gaussian_fits)
            layout.addWidget(self.gaussian_fit_cb)
            
            # Background subtraction checkbox
            self.bg_subtract_cb = QCheckBox("BG Sub")
            self.bg_subtract_cb.setToolTip("Show background-subtracted spectrum")
            self.bg_subtract_cb.toggled.connect(self.toggle_background_subtraction)
            layout.addWidget(self.bg_subtract_cb)
            
            # Reset Y-axis button
            reset_y_btn = QPushButton("Y=0")
            reset_y_btn.setMaximumWidth(40)
            reset_y_btn.setToolTip("Force Y-axis to start at 0")
            reset_y_btn.clicked.connect(self.reset_y_axis_to_zero)
            layout.addWidget(reset_y_btn)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def create_stats_widget(self):
        self.stats_labels = {}

        stats_group = QGroupBox("Channel Statistics")
        stats_group.setMaximumHeight(60)  # More compact
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(3)

        # Only show first 8 channels to save space, or use scrollable area
        display_channels = (
            self.channels[:8] if len(self.channels) > 8 else self.channels
        )

        for ch in display_channels:
            label = QLabel(f"Ch{ch}: 0")
            label.setStyleSheet("QLabel { font-size: 10px; }")  # Smaller font
            self.stats_labels[ch] = label
            stats_layout.addWidget(label)

        if len(self.channels) > 8:
            more_label = QLabel(f"...+{len(self.channels) - 8} more")
            more_label.setStyleSheet("QLabel { font-size: 10px; color: gray; }")
            stats_layout.addWidget(more_label)

        stats_layout.addStretch()
        stats_group.setLayout(stats_layout)
        return stats_group

    def start_live_updates(self):
        if not self.update_timer.isActive():
            self.update_timer.start(int(self.update_rate * 1000))
            print("List Mode Plotter: Started live updates")

    def stop_live_updates(self):
        if self.update_timer.isActive():
            self.update_timer.stop()
            print("List Mode Plotter: Stopped live updates")

    def add_energy_event(self, channel, energy):
        if channel in self.channels:
            self.energy_data[channel].append(energy)

    def add_energy_events(self, channel, energies):
        if channel in self.channels:
            if isinstance(energies, list | np.ndarray):
                self.energy_data[channel].extend(energies)
            else:
                self.energy_data[channel].append(energies)

    def update_display(self):
        current_time = time.time()
        if current_time - self.last_update < self.update_rate:
            return

        self.last_update = current_time
        total_events = 0

        # Process ALL channels but only display selected ones
        for channel in self.channels:
            event_count = (
                len(self.energy_data[channel]) if channel in self.energy_data else 0
            )
            total_events += event_count

            # Update statistics for ALL channels (even hidden ones)
            if channel in self.stats_labels:
                self.stats_labels[channel].setText(f"Ch{channel}: {event_count} events")

            # Only display data for selected channels
            if channel not in self.display_channels:
                # Channel not selected for display - hide it
                self.plot_items[channel].setData([], [])
                continue

            # Channel is selected for display
            if event_count == 0:
                # No data for this channel
                self.plot_items[channel].setData([], [])
                continue

            # Display the channel data
            try:
                energies = list(self.energy_data[channel])

                # Create histogram
                counts, bin_edges = np.histogram(
                    energies, bins=self.bins, range=self.energy_range
                )

                # Calculate bin centers
                bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
                
                # Apply background subtraction if enabled
                if self.show_background_subtracted and self.fwhm_analyzer and len(energies) > 100:
                    plot_counts = self._apply_background_subtraction(channel, counts, bin_centers)
                else:
                    plot_counts = counts

                # Apply log scale if enabled
                if self.log_scale_cb.isChecked():
                    plot_counts = np.where(plot_counts > 0, plot_counts, 0.1)
                    plot_counts = np.log10(plot_counts)

                self.plot_items[channel].setData(bin_centers, plot_counts)
                
                # Add Gaussian fits if enabled
                if self.show_gaussian_fits and self.fwhm_analyzer and len(energies) > 100:
                    self._update_gaussian_fits(channel, counts, bin_centers)

            except Exception as e:
                print(f"Error updating channel {channel}: {e}")
                self.plot_items[channel].setData([], [])

        # Set proper axis ranges
        if self.auto_scale_cb.isChecked() and total_events > 0:
            self.display.enableAutoRange('x', True)
            self.display.enableAutoRange('y', False)
            if not self.log_scale_cb.isChecked():
                # Find max Y value across all channels
                max_counts = 0
                for channel in self.display_channels:
                    if channel in self.energy_data and len(self.energy_data[channel]) > 0:
                        energies = list(self.energy_data[channel])
                        if len(energies) > 0:
                            counts, _ = np.histogram(energies, bins=self.bins, range=self.energy_range)
                            max_counts = max(max_counts, np.max(counts))
                
                if max_counts > 0:
                    self.display.setYRange(0, max_counts * 1.1)  # 10% margin above max
                else:
                    self.display.setYRange(0, 100)  # Default range
        else:
            self.display.enableAutoRange('x', False)
            self.display.enableAutoRange('y', False)
            
            if not self.log_scale_cb.isChecked():
                current_range = self.display.getViewBox().viewRange()[1]
                y_max = max(current_range[1], 100)
                self.display.setYRange(0, y_max, padding=0)  # No padding to ensure exact 0 start

    def update_energy_range(self):
        self.energy_range = (self.energy_min_spin.value(), self.energy_max_spin.value())

    def update_bins(self):
        self.bins = self.bins_spin.value()

    def toggle_log_scale(self, checked):
        if checked:
            self.display.setLabel("left", "Log10(Counts)")
        else:
            self.display.setLabel("left", "Counts")

    def toggle_auto_scale(self, checked):
        if not checked:
            self.display.enableAutoRange('x', False)
            self.display.enableAutoRange('y', False)
            self.display.setXRange(*self.energy_range)
            if not self.log_scale_cb.isChecked():
                current_range = self.display.getViewBox().viewRange()[1]
                y_max = max(current_range[1], 100)
                self.display.setYRange(0, y_max, padding=0)
        else:
            # Auto mode handled in update_display
            pass
    
    def toggle_gaussian_fits(self, checked):
        self.show_gaussian_fits = checked
        self.update_display()
    
    def toggle_background_subtraction(self, checked):
        self.show_background_subtracted = checked
        self.update_display()
    
    def reset_y_axis_to_zero(self):
        """Force Y-axis to start at 0 - call this if axis is floating"""
        if not self.log_scale_cb.isChecked():
            current_range = self.display.getViewBox().viewRange()[1]
            y_max = max(current_range[1], 100)
            
            # Multiple attempts to force the range
            self.display.enableAutoRange('y', False)
            self.display.setYRange(0, y_max, padding=0)
            self.display.getViewBox().setYRange(0, y_max, padding=0)
            
            # Force immediate update
            self.display.getViewBox().updateViewRange()

    def set_display_channels(self, channels):
        print(f"List Mode Plotter: set_display_channels called with {channels}")
        self.display_channels = channels if channels else []

        # hide unselected channels
        for channel in self.channels:
            if channel not in self.display_channels:
                self.plot_items[channel].setData([], [])
                print(f"List Mode: Hiding channel {channel}")
            else:
                print(f"List Mode: Will show channel {channel}")

        self.update_display()

    def clear_data(self):
        for channel in self.channels:
            self.energy_data[channel].clear()

        # Clear plots immediately
        for channel in self.channels:
            self.plot_items[channel].setData([], [])
            if channel in self.stats_labels:
                self.stats_labels[channel].setText(f"Ch{channel}: 0 events")

    def get_spectrum_data(self):
        data = {}
        for channel in self.channels:
            if len(self.energy_data[channel]) > 0:
                data[channel] = list(self.energy_data[channel])
        return data
        
    def get_histogram_data(self):
        histogram_data = {}
        for channel in self.channels:
            if len(self.energy_data[channel]) > 0:
                energies = list(self.energy_data[channel])
                # Create histogram matching current display parameters
                hist, bin_edges = np.histogram(energies, bins=self.bins, range=self.energy_range)
                histogram_data[channel] = hist
        return histogram_data
    
    def _update_gaussian_fits(self, channel: int, histogram: np.ndarray, bin_centers: np.ndarray):
        try:
            # Skip if too few counts
            if np.sum(histogram) < 1000:
                return
                
            # Perform Gaussian fitting on histogram
            roi_start = 0
            roi_end = len(histogram) - 1
            
            # Find significant peaks first to avoid fitting noise
            peak_channels = self.fwhm_analyzer.find_peaks_in_roi(histogram, roi_start, roi_end)
            if not peak_channels:
                return
                
            # Limit to top 3 peaks for real-time performance
            peak_channels = peak_channels[:3]
            
            fit_result = self.fwhm_analyzer.fit_gaussian_peaks(histogram, roi_start, roi_end)
            
            if fit_result.fit_success and fit_result.peak_centers:
                self.fit_results[channel] = fit_result
                
                # Plot fitted Gaussians
                self._plot_gaussian_components(channel, fit_result, bin_centers, histogram)
                
        except Exception as e:
            logger.warning(f"Gaussian fitting failed for channel {channel}: {e}")
    
    def _apply_background_subtraction(self, channel: int, histogram: np.ndarray, 
                                     bin_centers: np.ndarray) -> np.ndarray:
        try:
            # Use existing fit result if available
            if channel in self.fit_results and self.fit_results[channel].background_params:
                background_params = self.fit_results[channel].background_params
                background = np.zeros_like(histogram, dtype=float)
                
                # Reconstruct background from fit parameters
                for param_name, value in background_params.items():
                    if "slope" in param_name:
                        background += value * np.arange(len(histogram))
                    elif "intercept" in param_name or "c" in param_name:
                        background += value
                
                # Subtract background
                bg_subtracted = histogram - background
                return np.maximum(bg_subtracted, 0)  # Don't allow negative counts
            else:
                # Quick background estimation using edge averaging
                edge_points = min(50, len(histogram) // 10)
                left_bg = np.mean(histogram[:edge_points])
                right_bg = np.mean(histogram[-edge_points:])
                background = np.linspace(left_bg, right_bg, len(histogram))
                
                bg_subtracted = histogram - background
                self.background_estimates[channel] = background
                
                return np.maximum(bg_subtracted, 0)
                
        except Exception as e:
            logger.warning(f"Background subtraction failed for channel {channel}: {e}")
            return histogram
    
    def _plot_gaussian_components(self, channel: int, fit_result, bin_centers: np.ndarray, 
                                 original_histogram: np.ndarray):
        # Remove old fit plots for this channel
        fit_items_key = f"fit_{channel}"
        if hasattr(self, 'fit_plot_items'):
            if fit_items_key in self.fit_plot_items:
                for item in self.fit_plot_items[fit_items_key]:
                    self.display.removeItem(item)
                del self.fit_plot_items[fit_items_key]
        else:
            self.fit_plot_items = {}
            
        # Create fit plots
        self.fit_plot_items[fit_items_key] = []
        
        # Plot individual Gaussian components
        for i, (center, sigma, amplitude) in enumerate(zip(
            fit_result.peak_centers, fit_result.peak_sigmas, fit_result.peak_amplitudes
        )):
            # Generate Gaussian curve
            x_fine = np.linspace(center - 4*sigma, center + 4*sigma, 100)
            # Convert bin centers to channel space for fitting
            channel_spacing = (bin_centers[-1] - bin_centers[0]) / len(bin_centers)
            x_fine_bins = (x_fine - bin_centers[0]) / channel_spacing
            
            # Only plot if within our display range
            mask = (x_fine_bins >= 0) & (x_fine_bins < len(bin_centers))
            if np.any(mask):
                x_plot = x_fine[mask]
                
                # Calculate Gaussian values
                gaussian_vals = (amplitude / (sigma * np.sqrt(2 * np.pi)) * 
                               np.exp(-0.5 * ((x_fine[mask] - center) / sigma) ** 2))
                
                # Apply log scale if enabled
                if self.log_scale_cb.isChecked():
                    gaussian_vals = np.log10(np.maximum(gaussian_vals, 0.1))
                
                # Plot Gaussian component
                color = pg.mkColor(255, 0, 0, 150)  # Semi-transparent red
                pen = pg.mkPen(color=color, width=1, style=pg.Qt.PenStyle.DashLine)
                curve = pg.PlotCurveItem(pen=pen)
                curve.setData(x_plot, gaussian_vals)
                self.display.addItem(curve)
                self.fit_plot_items[fit_items_key].append(curve)
        
        # Plot total fit
        if len(fit_result.peak_centers) > 0:
            # Calculate total fitted curve (background + all peaks)
            total_fit = np.zeros_like(original_histogram, dtype=float)
            
            # Add background
            for param_name, value in fit_result.background_params.items():
                if "slope" in param_name:
                    total_fit += value * np.arange(len(original_histogram))
                elif "intercept" in param_name or "c" in param_name:
                    total_fit += value
                    
            # Add Gaussians
            for center, sigma, amplitude in zip(
                fit_result.peak_centers, fit_result.peak_sigmas, fit_result.peak_amplitudes
            ):
                x_channels = np.arange(len(original_histogram))
                gaussian = (amplitude / (sigma * np.sqrt(2 * np.pi)) * 
                           np.exp(-0.5 * ((x_channels - center) / sigma) ** 2))
                total_fit += gaussian
            
            # Apply log scale if enabled
            if self.log_scale_cb.isChecked():
                total_fit = np.log10(np.maximum(total_fit, 0.1))
            
            # Plot total fit
            color = pg.mkColor(0, 255, 0, 200)  # Semi-transparent green
            pen = pg.mkPen(color=color, width=2)
            curve = pg.PlotCurveItem(pen=pen)
            curve.setData(bin_centers, total_fit)
            self.display.addItem(curve)
            self.fit_plot_items[fit_items_key].append(curve)

    def cleanup(self):
        if hasattr(self, 'fwhm_window') and self.fwhm_window:
            self.fwhm_window.close()
            self.fwhm_window = None
        
        # Clean up fit plots
        if hasattr(self, 'fit_plot_items'):
            for items in self.fit_plot_items.values():
                for item in items:
                    self.display.removeItem(item)
            self.fit_plot_items.clear()

    def set_channels(self, channels):
        # Remove old plot items
        for channel in self.channels:
            if channel in self.plot_items:
                self.display.removeItem(self.plot_items[channel])

        # Update channels
        self.channels = channels
        self.display_channels = channels.copy()

        # Preserve existing data, create empty deques for new channels
        new_energy_data = {}
        for ch in self.channels:
            new_energy_data[ch] = self.energy_data.get(ch, deque(maxlen=50000))
        self.energy_data = new_energy_data

        # Create new plot items
        self.plot_items = {}
        for i, channel in enumerate(self.channels):
            color = self.channel_colors[i % len(self.channel_colors)]
            pen = pg.mkPen(color=color, width=2)
            curve = pg.PlotCurveItem(pen=pen, name=f"Ch {channel}")
            self.plot_items[channel] = curve
            self.display.addItem(curve)

        # Update statistics labels
        self.update_stats_labels()

    def update_stats_labels(self):
        # Clear old layout
        layout = self.stats_widget.layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Create new labels
        self.stats_labels = {}
        for ch in self.channels:
            label = QLabel(f"Ch{ch}: 0 events")
            self.stats_labels[ch] = label
            layout.addWidget(label)

        layout.addStretch()

    # def get_channel_statistics(self):
    #     """Get statistics for all channels"""
    #     stats = {}
    #     for channel in self.channels:
    #         event_count = len(self.energy_data[channel])
    #         if event_count > 0:
    #             energies = list(self.energy_data[channel])
    #             stats[channel] = {
    #                 "count": event_count,
    #                 "mean": np.mean(energies),
    #                 "std": np.std(energies),
    #                 "min": np.min(energies),
    #                 "max": np.max(energies),
    #             }
    #         else:
    #             stats[channel] = {
    #                 "count": 0,
    #                 "mean": 0,
    #                 "std": 0,
    #                 "min": 0,
    #                 "max": 0,
    #             }
    #     return stats
