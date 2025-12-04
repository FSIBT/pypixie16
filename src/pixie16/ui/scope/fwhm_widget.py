"""
FWHM Analysis Widget for PIXIE-16 Scope
Provides UI for ROI selection and FWHM analysis integration with spectrum plotters
"""

import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QSpinBox, QDoubleSpinBox, QPushButton, QComboBox,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QTextEdit, QMessageBox, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
import pyqtgraph as pg

from .fwhm_analyzer import FWHMAnalyzer, FWHMResult

class ROISelector:    
    def __init__(self, plot_widget, parent_widget=None):
        self.plot_widget = plot_widget
        self.parent_widget = parent_widget  # Reference to FWHM widget for button updates
        self.roi_regions = []  # List of pyqtgraph LinearRegionItem
        self.roi_data = []     # List of (start, end, name) tuples
        self.roi_counter = 1
        self.roi_colors = [
            (255, 255, 0, 80),   # Yellow
            (255, 0, 255, 80),   # Magenta  
            (0, 255, 255, 80),   # Cyan
            (255, 165, 0, 80),   # Orange
            (0, 255, 0, 80),     # Green
            (255, 0, 0, 80),     # Red
            (128, 0, 128, 80),   # Purple
            (0, 128, 255, 80),   # Blue
        ]
        
        # Interactive ROI creation mode
        self.interactive_mode = False
        self.temp_roi = None
        
    def add_roi(self, start: int, end: int, name: str = None) -> int:
        if name is None:
            name = f"ROI {self.roi_counter}"
            self.roi_counter += 1
            
        # Get color for this ROI (cycle through colors)
        color_idx = len(self.roi_regions) % len(self.roi_colors)
        roi_color = self.roi_colors[color_idx]
        
        # Create visual ROI on plot with unique color
        roi_region = pg.LinearRegionItem(
            values=(start, end),
            brush=pg.mkBrush(*roi_color),
            pen=pg.mkPen(roi_color[:3], width=2)  # Same color but opaque for border
        )
        self.plot_widget.addItem(roi_region)
        
        # Store ROI data
        roi_id = len(self.roi_regions)
        self.roi_regions.append(roi_region)
        self.roi_data.append((start, end, name))
        
        return roi_id
        
    def remove_roi(self, roi_id: int):
        if 0 <= roi_id < len(self.roi_regions):
            self.plot_widget.removeItem(self.roi_regions[roi_id])
            del self.roi_regions[roi_id]
            del self.roi_data[roi_id]
            
    def clear_all_rois(self):
        for region in self.roi_regions:
            self.plot_widget.removeItem(region)
        self.roi_regions.clear()
        self.roi_data.clear()
        self.roi_counter = 1
        
    def get_roi_bounds(self, roi_id: int) -> Tuple[int, int]:
        if 0 <= roi_id < len(self.roi_regions):
            region = self.roi_regions[roi_id]
            start, end = region.getRegion()
            return int(start), int(end)
        return 0, 0
        
    def get_all_rois(self) -> List[Tuple[int, int, str]]:
        current_rois = []
        for i, (_, _, name) in enumerate(self.roi_data):
            start, end = self.get_roi_bounds(i)
            current_rois.append((start, end, name))
        return current_rois
    
    def start_interactive_mode(self):
        self.interactive_mode = True
        if hasattr(self.plot_widget, 'scene'):
            self.plot_widget.scene().sigMouseClicked.connect(self.on_plot_click)
            
    def stop_interactive_mode(self):
        self.interactive_mode = False
        if hasattr(self.plot_widget, 'scene'):
            try:
                self.plot_widget.scene().sigMouseClicked.disconnect(self.on_plot_click)
            except:
                pass  # Already disconnected
                
        # Clean up temp ROI if exists
        if self.temp_roi:
            self.plot_widget.removeItem(self.temp_roi)
            self.temp_roi = None
    
    def on_plot_click(self, event):
        if not self.interactive_mode:
            return
            
        pos = event.pos()
        if hasattr(self.plot_widget, 'plotItem'):
            plot_pos = self.plot_widget.plotItem.vb.mapSceneToView(pos)
            x_pos = int(plot_pos.x())
            
            if self.temp_roi is None:
                # First click - start ROI
                self.create_temp_roi(x_pos)
            else:
                # Second click - finish ROI  
                self.finish_roi(x_pos)
                
    def create_temp_roi(self, start_x):
        color_idx = len(self.roi_regions) % len(self.roi_colors)
        roi_color = self.roi_colors[color_idx]
        
        # Create temporary ROI (will be updated on mouse move)
        self.temp_roi = pg.LinearRegionItem(
            values=(start_x, start_x + 50),  # Small default width
            brush=pg.mkBrush(*roi_color),
            pen=pg.mkPen(roi_color[:3], width=2, style=pg.QtCore.Qt.PenStyle.DashLine)  # Dashed for temp
        )
        self.plot_widget.addItem(self.temp_roi)
        self.temp_start = start_x
        
    def finish_roi(self, end_x):
        if self.temp_roi:
            # Remove temp ROI
            self.plot_widget.removeItem(self.temp_roi)
            
            # Create final ROI with proper bounds
            start = min(self.temp_start, end_x)
            end = max(self.temp_start, end_x)
            
            # Ensure minimum width
            if end - start < 10:
                end = start + 10
                
            self.add_roi(start, end)
            
            # Clean up
            self.temp_roi = None
            self.stop_interactive_mode()
            
            # Reset button if parent widget available
            if self.parent_widget and hasattr(self.parent_widget, 'click_roi_btn'):
                self.parent_widget.click_roi_btn.setText("Click to Add ROI")
                self.parent_widget.click_roi_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
                self.parent_widget.update_roi_status()
                self.parent_widget.roi_changed.emit()


class FWHMResultsTable(QTableWidget):    
    def __init__(self):
        super().__init__()
        self.setup_table()
        
    def setup_table(self):
        headers = [
            "Channel", "ROI", "Peak", "FWHM (ch)", "FWHM (keV)", 
            "Resolution (%)", "Counts", "SNR", "Quality"
        ]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        
        # Set column widths
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        
        # Styling
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
    def add_result(self, result: FWHMResult, roi_name: str = ""):
        row = self.rowCount()
        self.insertRow(row)
        
        # Format data for display
        items = [
            str(result.channel) if result.channel >= 0 else "N/A",
            roi_name,
            f"{result.peak_channel}" if result.peak_channel is not None else "N/A",
            f"{result.fwhm_channels:.2f}" if result.fwhm_channels is not None else "N/A",
            f"{result.fwhm_energy:.1f}" if result.fwhm_energy is not None else "N/A", 
            f"{result.resolution_percent:.2f}" if result.resolution_percent is not None else "N/A",
            f"{result.peak_counts}" if result.peak_counts is not None else "N/A",
            f"{result.snr:.1f}" if result.snr is not None else "N/A",
            f"{result.fit_quality:.2f}" if result.fit_quality is not None else "N/A"
        ]
        
        for col, item_text in enumerate(items):
            item = QTableWidgetItem(item_text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Read-only
            self.setItem(row, col, item)
            
    def clear_results(self):
        self.setRowCount(0)


class FWHMAnalysisWidget(QWidget):
    # Signals
    analysis_completed = pyqtSignal(list)  # Emits List[FWHMResult]
    roi_changed = pyqtSignal()
    
    def __init__(self, spectrum_plotter=None):
        super().__init__()
        self.spectrum_plotter = spectrum_plotter
        self.analyzer = FWHMAnalyzer()
        self.roi_selector = None
        self.current_results = []
        self.auto_update_enabled = False
        
        # Analysis settings
        self.min_peak_height_ratio = 0.1
        self.background_window = 50
        self.smoothing_sigma = 2.0
        
        self.init_ui()
        self.setup_connections()
        
        # Auto-update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.run_analysis)
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # ROI Controls
        roi_group = self.create_roi_controls()
        layout.addWidget(roi_group)
        
        # Analysis Controls  
        analysis_group = self.create_analysis_controls()
        layout.addWidget(analysis_group)
        
        # Results Display
        results_group = self.create_results_display()
        layout.addWidget(results_group)
        
        self.setLayout(layout)
        
    def create_roi_controls(self) -> QGroupBox:
        group = QGroupBox("Region of Interest (ROI)")
        layout = QGridLayout()
        
        # ROI bounds input
        layout.addWidget(QLabel("ROI Start:"), 0, 0)
        self.roi_start_spin = QSpinBox()
        self.roi_start_spin.setRange(0, 65535)
        self.roi_start_spin.setValue(100)
        layout.addWidget(self.roi_start_spin, 0, 1)
        
        layout.addWidget(QLabel("ROI End:"), 0, 2)
        self.roi_end_spin = QSpinBox()
        self.roi_end_spin.setRange(0, 65535)
        self.roi_end_spin.setValue(1000)
        layout.addWidget(self.roi_end_spin, 0, 3)
        
        # ROI management buttons
        self.add_roi_btn = QPushButton("Add ROI")
        self.add_roi_btn.setToolTip("Add ROI using values above")
        layout.addWidget(self.add_roi_btn, 1, 0)
        
        self.click_roi_btn = QPushButton("Click to Add ROI")
        self.click_roi_btn.setToolTip("Click twice on plot to create ROI interactively")
        self.click_roi_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        layout.addWidget(self.click_roi_btn, 1, 1)
        
        self.clear_roi_btn = QPushButton("Clear All")
        layout.addWidget(self.clear_roi_btn, 1, 2)
        
        # ROI list/status
        self.roi_status_label = QLabel("No ROIs defined")
        layout.addWidget(self.roi_status_label, 2, 0, 1, 3)  # Span across all columns on row 2
        
        group.setLayout(layout)
        return group
        
    def create_analysis_controls(self) -> QGroupBox:
        group = QGroupBox("Analysis Parameters")
        layout = QGridLayout()
        
        # Peak detection settings
        layout.addWidget(QLabel("Min Peak Height:"), 0, 0)
        self.peak_height_spin = QDoubleSpinBox()
        self.peak_height_spin.setRange(0.01, 1.0)
        self.peak_height_spin.setValue(self.min_peak_height_ratio)
        self.peak_height_spin.setSingleStep(0.05)
        self.peak_height_spin.setSuffix(" (fraction)")
        layout.addWidget(self.peak_height_spin, 0, 1)
        
        layout.addWidget(QLabel("Background Window:"), 0, 2)
        self.background_spin = QSpinBox()
        self.background_spin.setRange(10, 500)
        self.background_spin.setValue(self.background_window)
        self.background_spin.setSuffix(" channels")
        layout.addWidget(self.background_spin, 0, 3)
        
        # Analysis actions
        self.analyze_btn = QPushButton("Run Analysis")
        self.analyze_btn.setStyleSheet("QPushButton { font-weight: bold; }")
        layout.addWidget(self.analyze_btn, 1, 0)
        
        self.auto_update_check = QCheckBox("Auto Update")
        layout.addWidget(self.auto_update_check, 1, 1)
        
        # Progress indicator
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar, 1, 2, 1, 2)
        
        group.setLayout(layout)
        return group
        
    def create_results_display(self) -> QGroupBox:
        group = QGroupBox("FWHM Analysis Results")
        layout = QVBoxLayout()
        
        # Results table
        self.results_table = FWHMResultsTable()
        layout.addWidget(self.results_table)
        
        # Summary/export controls
        button_layout = QHBoxLayout()
        
        self.export_btn = QPushButton("Export Results")
        button_layout.addWidget(self.export_btn)
        
        self.clear_results_btn = QPushButton("Clear Results")
        button_layout.addWidget(self.clear_results_btn)
        
        button_layout.addStretch()
        
        # Statistics label
        self.stats_label = QLabel("No analysis results")
        self.stats_label.setFont(QFont("monospace", 9))
        button_layout.addWidget(self.stats_label)
        
        layout.addLayout(button_layout)
        group.setLayout(layout)
        return group
        
    def setup_connections(self):
        self.add_roi_btn.clicked.connect(self.add_roi)
        self.click_roi_btn.clicked.connect(self.start_interactive_roi)
        self.clear_roi_btn.clicked.connect(self.clear_all_rois)
        self.analyze_btn.clicked.connect(self.run_analysis)
        self.auto_update_check.toggled.connect(self.toggle_auto_update)
        self.clear_results_btn.clicked.connect(self.clear_results)
        self.export_btn.clicked.connect(self.export_results)
        
        # Parameter change connections
        self.peak_height_spin.valueChanged.connect(self.update_parameters)
        self.background_spin.valueChanged.connect(self.update_parameters)
        
    def connect_to_plotter(self, spectrum_plotter):
        self.spectrum_plotter = spectrum_plotter
        
        # Initialize ROI selector with the plotter's plot widget
        if hasattr(spectrum_plotter, 'plot_widget'):
            self.roi_selector = ROISelector(spectrum_plotter.plot_widget)
            
        # Update the status to show connection
        self.update_roi_status()
            
    def add_roi(self):
        if not self.roi_selector:
            QMessageBox.warning(self, "No Plot", "No spectrum plot connected")
            return
            
        start = self.roi_start_spin.value()
        end = self.roi_end_spin.value()
        
        if start >= end:
            QMessageBox.warning(self, "Invalid ROI", "ROI start must be less than end")
            return
            
        roi_id = self.roi_selector.add_roi(start, end)
        self.update_roi_status()
        self.roi_changed.emit()
        
    def start_interactive_roi(self):
        """Start interactive ROI creation mode"""
        if not self.roi_selector:
            QMessageBox.warning(self, "No Plot", "No spectrum plot connected")
            return
            
        # Update button to show active state
        self.click_roi_btn.setText("Click on Plot (2x)")
        self.click_roi_btn.setStyleSheet("QPushButton { background-color: #FF5722; color: white; }")
        
        # Show instruction
        QMessageBox.information(self, "Interactive ROI", 
            "Click twice on the spectrum plot to define ROI bounds:\n"
            "• First click: Start position\n"
            "• Second click: End position\n\n"
            "Click OK, then click on the plot.")
        
        # Start interactive mode
        self.roi_selector.start_interactive_mode()
        
        # Reset button after ROI creation (will be handled by ROI selector)
        
    def clear_all_rois(self):
        if self.roi_selector:
            self.roi_selector.clear_all_rois()
        self.update_roi_status()
        self.roi_changed.emit()
        
    def update_roi_status(self):
        if not self.roi_selector:
            self.roi_status_label.setText("No plot connected")
            return
            
        rois = self.roi_selector.get_all_rois()
        if not rois:
            self.roi_status_label.setText("No ROIs defined")
        else:
            self.roi_status_label.setText(f"{len(rois)} ROI(s) defined")
            
    def update_parameters(self):
        self.min_peak_height_ratio = self.peak_height_spin.value()
        self.background_window = self.background_spin.value()
        
        # Update analyzer settings
        self.analyzer.min_peak_height_ratio = self.min_peak_height_ratio
        self.analyzer.background_window = self.background_window
        
    def toggle_auto_update(self, enabled: bool):
        self.auto_update_enabled = enabled
        if enabled:
            self.update_timer.start(2000)  # Update every 2 seconds
        else:
            self.update_timer.stop()
            
    def get_current_spectrum_data(self) -> Dict[int, np.ndarray]:
        if not self.spectrum_plotter:
            return {}
            
        # Use the plotter's built-in histogram method if available
        if hasattr(self.spectrum_plotter, 'get_histogram_data'):
            return self.spectrum_plotter.get_histogram_data()
        
        # Fallback: manual histogram creation
        spectrum_data = {}
        if hasattr(self.spectrum_plotter, 'energy_data'):
            for channel, energy_deque in self.spectrum_plotter.energy_data.items():
                if len(energy_deque) > 0:
                    energies = list(energy_deque)
                    # Convert energy values to histogram
                    energy_range = getattr(self.spectrum_plotter, 'energy_range', (0, 65535))
                    bins = getattr(self.spectrum_plotter, 'bins', 4096)
                    
                    hist, bin_edges = np.histogram(energies, bins=bins, range=energy_range)
                    spectrum_data[channel] = hist
                    
        return spectrum_data
        
    def run_analysis(self):
        if not self.roi_selector:
            return
            
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        
        try:
            # Get current spectrum data
            spectrum_data = self.get_current_spectrum_data()
            if not spectrum_data:
                self.stats_label.setText("No spectrum data available")
                return
                
            # Get current ROIs
            rois = self.roi_selector.get_all_rois()
            if not rois:
                self.stats_label.setText("No ROIs defined for analysis")
                return
                
            # Clear previous results
            self.current_results.clear()
            self.results_table.clear_results()
            
            # Run analysis for each channel and ROI
            total_peaks = 0
            for channel, spectrum in spectrum_data.items():
                for roi_start, roi_end, roi_name in rois:
                    results = self.analyzer.analyze_roi(
                        spectrum, roi_start, roi_end, channel_id=channel
                    )
                    
                    # Add results to table
                    for result in results:
                        result.timestamp = datetime.now()
                        self.results_table.add_result(result, roi_name)
                        total_peaks += 1
                        
                    self.current_results.extend(results)
                    
            # Update statistics
            if total_peaks > 0:
                avg_resolution = np.mean([r.resolution_percent for r in self.current_results 
                                        if r.resolution_percent is not None])
                self.stats_label.setText(f"Found {total_peaks} peaks, Avg Resolution: {avg_resolution:.2f}%")
            else:
                self.stats_label.setText("No peaks found in ROIs")
                
            # Emit signal with results
            self.analysis_completed.emit(self.current_results)
            
        except Exception as e:
            QMessageBox.critical(self, "Analysis Error", f"FWHM analysis failed:\n{str(e)}")
            
        finally:
            self.progress_bar.setVisible(False)
            
    def clear_results(self):
        self.current_results.clear()
        self.results_table.clear_results()
        self.stats_label.setText("Results cleared")
        
    def export_results(self):
        if not self.current_results:
            QMessageBox.information(self, "No Data", "No analysis results to export")
            return
            
        try:
            # Import DataSaver components
            from .data_manager import DataSaver, DataSettingsManager
            
            # Create data saver
            settings_manager = DataSettingsManager()
            data_saver = DataSaver(settings_manager)
            
            # Get analysis data in the format expected by DataSaver
            fwhm_data = self.get_analysis_data()
            
            # Create metadata
            metadata = {
                'instrument': 'pixie16',
                'analysis_type': 'fwhm_peak_analysis',
                'channels_analyzed': list(set(r.channel for r in self.current_results if r.channel >= 0)),
                'total_rois': len(self.roi_selector.get_all_rois()) if self.roi_selector else 0,
                'data_source': 'list_mode_histogram'
            }
            
            # Save the data
            success = data_saver.save_fwhm_analysis_data(fwhm_data, metadata, parent=self)
            
            if success:
                # Clear the current results since they've been saved
                # (User can choose to keep them if they want)
                reply = QMessageBox.question(self, "Results Saved", 
                    "FWHM analysis results saved successfully!\n\n"
                    "Clear current results?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    
                if reply == QMessageBox.StandardButton.Yes:
                    self.clear_results()
                    
        except ImportError as e:
            QMessageBox.critical(self, "Export Error", 
                f"Could not access save system:\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", 
                f"Failed to export FWHM results:\n{str(e)}")
            
    def get_analysis_data(self) -> Dict[str, Any]:
        return {
            'fwhm_results': [
                {
                    'channel': r.channel,
                    'roi_start': r.roi_start,
                    'roi_end': r.roi_end,
                    'peak_channel': r.peak_channel,
                    'peak_counts': r.peak_counts,
                    'fwhm_channels': r.fwhm_channels,
                    'fwhm_energy': r.fwhm_energy,
                    'resolution_percent': r.resolution_percent,
                    'snr': r.snr,
                    'fit_quality': r.fit_quality,
                    'timestamp': r.timestamp.isoformat() if r.timestamp else None
                }
                for r in self.current_results
            ],
            'analysis_parameters': {
                'min_peak_height_ratio': self.min_peak_height_ratio,
                'background_window': self.background_window,
                'smoothing_sigma': self.analyzer.smoothing_sigma
            },
            'rois': self.roi_selector.get_all_rois() if self.roi_selector else []
        }