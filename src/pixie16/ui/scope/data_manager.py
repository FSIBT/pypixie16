"""
Data Settings and File Management for PIXIE-16 Scope
Handles user-configurable data directories and save operations
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
import numpy as np

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QCheckBox, QFileDialog, QMessageBox, QProgressDialog
)
from PyQt6.QtCore import QSettings, QStandardPaths, pyqtSignal


class DataSettingsManager:    
    def __init__(self):
        self.settings = QSettings("BerkeleyLab", "PIXIE16Scope")
        self.load_settings()
        
    def load_settings(self):
        self.data_directory = Path(self.settings.value("data_directory", self.get_default_dir()))
        self.auto_create_subdirs = self.settings.value("auto_create_subdirs", True, type=bool)
        self.use_timestamps = self.settings.value("use_timestamps", True, type=bool)
        self.compress_files = self.settings.value("compress_files", False, type=bool)
        
    def save_settings(self):
        self.settings.setValue("data_directory", str(self.data_directory))
        self.settings.setValue("auto_create_subdirs", self.auto_create_subdirs)
        self.settings.setValue("use_timestamps", self.use_timestamps)
        self.settings.setValue("compress_files", self.compress_files)
        
    def get_default_dir(self) -> Path:
        docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        return Path(docs) / "PIXIE16Data"
        
    def get_data_directory(self) -> Path:
        return self.data_directory
        
    def set_data_directory(self, path: Path):
        self.data_directory = Path(path)
        self.save_settings()
        
    def get_save_path(self, data_type: str, filename: Optional[str] = None) -> Path:        
        subdirs = {
            'mca': 'mca_data',
            'listmode': 'listmode_data',
            'traces': 'traces_data', 
            'energy_spectrum': 'single_channel_analysis',
            'coincidence': 'coincidence_data',
            'fwhm_analysis': 'fwhm_analysis',
            'sessions': 'sessions',
            'exports': 'exports',
            'binary': 'binary_replay'
        }
        
        base_path = self.data_directory
        
        if self.auto_create_subdirs and data_type in subdirs:
            base_path = base_path / subdirs[data_type]
            
        # Create directory if it doesn't exist
        base_path.mkdir(parents=True, exist_ok=True)
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if self.use_timestamps:
                filename = f"{data_type}_{timestamp}"
            else:
                filename = data_type
                
        return base_path / filename
        
    def get_disk_usage(self) -> tuple:
        try:
            stat = self.data_directory.stat() if self.data_directory.exists() else None
            # This is a simple implementation - could be enhanced with actual disk usage
            return (0, 0)  # (used_bytes, free_bytes)
        except Exception:
            return (0, 0)


class DataStoragePanel(QGroupBox):    
    # when settings change,
    settings_changed = pyqtSignal()
    
    def __init__(self):
        super().__init__("Data Storage")
        self.settings_manager = DataSettingsManager()
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Current directory display
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Directory:"))
        
        self.dir_label = QLabel()
        self.dir_label.setStyleSheet("QLabel { background-color: #f0f0f0; padding: 2px; border: 1px solid #ccc; }")
        self.update_directory_display()
        dir_layout.addWidget(self.dir_label)
        
        # Browse button
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.browse_btn)
        
        layout.addLayout(dir_layout)
        
        # Settings checkboxes
        self.auto_subdirs_cb = QCheckBox("Auto-create subdirectories")
        self.auto_subdirs_cb.setChecked(self.settings_manager.auto_create_subdirs)
        self.auto_subdirs_cb.toggled.connect(self.on_settings_changed)
        layout.addWidget(self.auto_subdirs_cb)
        
        self.timestamps_cb = QCheckBox("Use timestamps in filenames")
        self.timestamps_cb.setChecked(self.settings_manager.use_timestamps)
        self.timestamps_cb.toggled.connect(self.on_settings_changed)
        layout.addWidget(self.timestamps_cb)
        
        # Disk usage info (placeholder for now)
        self.usage_label = QLabel("Disk usage: --")
        self.usage_label.setStyleSheet("QLabel { color: #666; font-size: 10px; }")
        layout.addWidget(self.usage_label)
        
        self.setLayout(layout)
        
    def update_directory_display(self):
        """Update the directory display label"""
        dir_str = str(self.settings_manager.get_data_directory())
        # Truncate if too long
        if len(dir_str) > 40:
            dir_str = "..." + dir_str[-37:]
        self.dir_label.setText(dir_str)
        self.dir_label.setToolTip(str(self.settings_manager.get_data_directory()))
        
    def browse_directory(self):
        current_dir = str(self.settings_manager.get_data_directory())
        new_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Data Directory",
            current_dir
        )
        
        if new_dir:
            self.settings_manager.set_data_directory(Path(new_dir))
            self.update_directory_display()
            self.settings_changed.emit()
            
    def on_settings_changed(self):
        self.settings_manager.auto_create_subdirs = self.auto_subdirs_cb.isChecked()
        self.settings_manager.use_timestamps = self.timestamps_cb.isChecked()
        self.settings_manager.save_settings()
        self.settings_changed.emit()
        
    def get_settings_manager(self) -> DataSettingsManager:
        return self.settings_manager


class DataSaver:
    def __init__(self, settings_manager: DataSettingsManager):
        self.settings_manager = settings_manager
        
    def save_mca_data(self, mca_data: Dict, metadata: Dict, parent=None) -> bool:
        try:
            # Get save path
            save_path = self.settings_manager.get_save_path('mca')
            json_path = save_path.with_suffix('.json')
            npz_path = save_path.with_suffix('.npz')
            
            # Prepare data structure
            save_data = {
                'metadata': {
                    'timestamp': datetime.now().isoformat(),
                    'data_type': 'mca',
                    'software_version': '1.0',  # Could be dynamic
                    **metadata
                },
                'settings': {
                    'channels': list(mca_data.keys()),
                    'bin_counts': {str(k): len(v) for k, v in mca_data.items()}
                }
            }
            
            # Save JSON metadata
            with open(json_path, 'w') as f:
                json.dump(save_data, f, indent=2)
                
            # Save binary data
            np.savez_compressed(npz_path, **{f'channel_{k}': v for k, v in mca_data.items()})
            
            if parent:
                QMessageBox.information(parent, "Save Successful", 
                                      f"MCA data saved to:\n{json_path}")
            return True
            
        except Exception as e:
            if parent:
                QMessageBox.critical(parent, "Save Failed", f"Error saving MCA data:\n{str(e)}")
            return False
            
    def save_traces_data(self, traces_data: Dict, metadata: Dict, parent=None) -> bool:
        try:
            save_path = self.settings_manager.get_save_path('traces')
            json_path = save_path.with_suffix('.json')
            npz_path = save_path.with_suffix('.npz')
            
            # Similar structure to MCA saving
            save_data = {
                'metadata': {
                    'timestamp': datetime.now().isoformat(),
                    'data_type': 'traces',
                    **metadata
                },
                'trace_counts': {str(k): len(v) for k, v in traces_data.items()}
            }
            
            with open(json_path, 'w') as f:
                json.dump(save_data, f, indent=2)
                
            # Convert trace data for saving
            save_arrays = {}
            for channel, traces in traces_data.items():
                if traces:
                    save_arrays[f'channel_{channel}'] = np.array(traces, dtype=object)
                    
            np.savez_compressed(npz_path, **save_arrays)
            
            if parent:
                QMessageBox.information(parent, "Save Successful", 
                                      f"Traces data saved to:\n{json_path}")
            return True
            
        except Exception as e:
            if parent:
                QMessageBox.critical(parent, "Save Failed", f"Error saving traces data:\n{str(e)}")
            return False
            
    def save_session(self, session_data: Dict, parent=None) -> bool:
        try:
            save_path = self.settings_manager.get_save_path('sessions')
            json_path = save_path.with_suffix('.json')
            
            session_data['metadata'] = {
                'timestamp': datetime.now().isoformat(),
                'data_type': 'session'
            }
            
            with open(json_path, 'w') as f:
                json.dump(session_data, f, indent=2)
                
            if parent:
                QMessageBox.information(parent, "Save Successful", 
                                      f"Session saved to:\n{json_path}")
            return True
            
        except Exception as e:
            if parent:
                QMessageBox.critical(parent, "Save Failed", f"Error saving session:\n{str(e)}")
            return False
            
    def save_energy_spectrum_data(self, energy_data: Dict, metadata: Dict, parent=None) -> bool:
        try:
            # Get save path - use a new subdirectory for single channel analysis
            save_path = self.settings_manager.get_save_path('energy_spectrum')
            json_path = save_path.with_suffix('.json')
            npz_path = save_path.with_suffix('.npz')
            
            # Prepare comprehensive metadata
            total_events = sum(len(events) if hasattr(events, '__len__') else len(list(events)) 
                             for events in energy_data.values() if events)
            
            save_data = {
                'metadata': {
                    'timestamp': datetime.now().isoformat(),
                    'data_type': 'energy_spectrum',
                    'software_version': '1.0',
                    'total_events': total_events,
                    **metadata
                },
                'channel_info': {
                    'channels': list(energy_data.keys()),
                    'event_counts': {str(k): len(v) if hasattr(v, '__len__') else len(list(v)) 
                                   for k, v in energy_data.items() if v}
                }
            }
            
            # Save JSON metadata
            with open(json_path, 'w') as f:
                json.dump(save_data, f, indent=2)
                
            # Save binary data - convert deques/lists to numpy arrays
            save_arrays = {}
            for channel, events in energy_data.items():
                if events:
                    # Convert deque or list to numpy array
                    if hasattr(events, '__len__') and len(events) > 0:
                        save_arrays[f'channel_{channel}'] = np.array(list(events))
                    
            if save_arrays:
                np.savez_compressed(npz_path, **save_arrays)
                
            if parent:
                QMessageBox.information(parent, "Save Successful", 
                                      f"Energy spectrum data saved to:\n{json_path}\n\n"
                                      f"Channels saved: {len(save_arrays)}\n"
                                      f"Total events: {total_events}")
            return True
            
        except Exception as e:
            if parent:
                QMessageBox.critical(parent, "Save Failed", f"Error saving energy spectrum data:\n{str(e)}")
            return False
            
    def save_coincidence_data(self, coincidence_data: Dict, metadata: Dict, parent=None) -> bool:
        try:
            # Get save path
            save_path = self.settings_manager.get_save_path('coincidence')
            json_path = save_path.with_suffix('.json')
            npz_path = save_path.with_suffix('.npz')
            
            # Calculate summary statistics
            total_events_a = coincidence_data.get('total_events_a', 0)
            total_events_b = coincidence_data.get('total_events_b', 0)
            total_coincidences = coincidence_data.get('total_coincidences', 0)
            
            # Prepare comprehensive metadata
            save_data = {
                'metadata': {
                    'timestamp': datetime.now().isoformat(),
                    'data_type': 'coincidence_analysis',
                    'software_version': '1.0',
                    'total_events_a': total_events_a,
                    'total_events_b': total_events_b,
                    'total_coincidences': total_coincidences,
                    'coincidence_rate': (total_coincidences / max(total_events_a, total_events_b, 1)) * 100,
                    **metadata
                },
                'acquisition_settings': {
                    'channel_a': coincidence_data.get('channel_a', 0),
                    'channel_b': coincidence_data.get('channel_b', 1),
                    'hardware_params': coincidence_data.get('hardware_params', {}),
                    'sampling_period_ns': coincidence_data.get('sampling_period_ns', 2.0),
                    'fpga_period_ns': coincidence_data.get('fpga_period_ns', 10.0)
                },
                'logic_steps': coincidence_data.get('logic_steps', []),
                'histogram_settings': {
                    'time_bins': coincidence_data.get('time_bins', 2000),
                    'time_range_ns': coincidence_data.get('time_range_ns', 4000),
                    'normalize_histograms': coincidence_data.get('normalize_histograms', False)
                }
            }
            
            # Save JSON metadata
            with open(json_path, 'w') as f:
                json.dump(save_data, f, indent=2)
                
            # Prepare binary data for saving
            save_arrays = {}
            
            # Save histogram data for each channel and logic step
            if 'histograms_a' in coincidence_data:
                for step_name, (bin_centers, hist_data) in coincidence_data['histograms_a'].items():
                    save_arrays[f'hist_a_{step_name}_bins'] = np.array(bin_centers)
                    save_arrays[f'hist_a_{step_name}_counts'] = np.array(hist_data)
                    
            if 'histograms_b' in coincidence_data:
                for step_name, (bin_centers, hist_data) in coincidence_data['histograms_b'].items():
                    save_arrays[f'hist_b_{step_name}_bins'] = np.array(bin_centers)
                    save_arrays[f'hist_b_{step_name}_counts'] = np.array(hist_data)
            
            # Save latest binary traces if available
            if 'latest_binary_data' in coincidence_data:
                latest_data = coincidence_data['latest_binary_data']
                if 'ch_a_time_axis' in latest_data and latest_data['ch_a_time_axis'] is not None:
                    save_arrays['ch_a_time_axis'] = np.array(latest_data['ch_a_time_axis'])
                if 'ch_b_time_axis' in latest_data and latest_data['ch_b_time_axis'] is not None:
                    save_arrays['ch_b_time_axis'] = np.array(latest_data['ch_b_time_axis'])
                    
                for channel in ['ch_a', 'ch_b']:
                    if channel in latest_data:
                        for step_name, binary_trace in latest_data[channel].items():
                            if binary_trace is not None:
                                save_arrays[f'{channel}_{step_name}_latest'] = np.array(binary_trace)
            
            # Save event buffer data if available
            if 'event_buffer' in coincidence_data and coincidence_data['event_buffer']:
                # Convert event buffer to structured array
                events = list(coincidence_data['event_buffer'])
                if events:
                    save_arrays['event_buffer'] = np.array(events, dtype=object)
                    
            if 'coincidence_events' in coincidence_data and coincidence_data['coincidence_events']:
                coincidences = list(coincidence_data['coincidence_events'])
                if coincidences:
                    save_arrays['coincidence_events'] = np.array(coincidences, dtype=object)
            
            # Save binary data
            if save_arrays:
                np.savez_compressed(npz_path, **save_arrays)
                
            if parent:
                QMessageBox.information(parent, "Save Successful", 
                                      f"Coincidence data saved to:\n{json_path}\n\n"
                                      f"Channel A events: {total_events_a}\n"
                                      f"Channel B events: {total_events_b}\n"
                                      f"Coincidences: {total_coincidences}\n"
                                      f"Arrays saved: {len(save_arrays)}")
            return True
            
        except Exception as e:
            if parent:
                QMessageBox.critical(parent, "Save Failed", f"Error saving coincidence data:\n{str(e)}")
            return False

    def save_fwhm_analysis_data(self, fwhm_data: Dict, metadata: Dict, parent=None) -> bool:
        """        
        Args:
            fwhm_data: Dictionary containing FWHM analysis results
            metadata: Analysis metadata (instrument info, settings, etc.)
            parent: Parent widget for error dialogs
            
        Returns:
            bool: True if save successful, False otherwise
        """
        try:
            # Get save path
            save_path = self.settings_manager.get_save_path('fwhm_analysis')
            json_path = save_path.with_suffix('.json')
            csv_path = save_path.with_suffix('.csv')
            
            # Prepare data for JSON saving
            save_data = {
                'metadata': {
                    'timestamp': datetime.now().isoformat(),
                    'data_type': 'fwhm_analysis',
                    'format_version': '1.0',
                    **metadata
                },
                'analysis_parameters': fwhm_data.get('analysis_parameters', {}),
                'roi_definitions': fwhm_data.get('rois', []),
                'fwhm_results': fwhm_data.get('fwhm_results', [])
            }
            
            # Add summary statistics
            if save_data['fwhm_results']:
                resolutions = [r['resolution_percent'] for r in save_data['fwhm_results'] 
                             if r.get('resolution_percent') is not None]
                if resolutions:
                    save_data['summary'] = {
                        'total_peaks': len(save_data['fwhm_results']),
                        'avg_resolution_percent': float(np.mean(resolutions)),
                        'best_resolution_percent': float(np.min(resolutions)),
                        'worst_resolution_percent': float(np.max(resolutions)),
                        'std_resolution_percent': float(np.std(resolutions))
                    }
            
            # Save JSON file
            with open(json_path, 'w') as f:
                json.dump(save_data, f, indent=2)
            
            # Save CSV file for easy data analysis
            if save_data['fwhm_results']:
                import csv
                with open(csv_path, 'w', newline='') as csvfile:
                    fieldnames = [
                        'channel', 'roi_start', 'roi_end', 'peak_channel', 'peak_counts',
                        'fwhm_channels', 'fwhm_energy', 'resolution_percent', 
                        'snr', 'fit_quality', 'timestamp'
                    ]
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for result in save_data['fwhm_results']:
                        # Clean data for CSV (handle None values)
                        csv_row = {}
                        for field in fieldnames:
                            value = result.get(field)
                            csv_row[field] = value if value is not None else ''
                        writer.writerow(csv_row)
            
            if parent:
                total_peaks = len(save_data['fwhm_results'])
                avg_res = save_data.get('summary', {}).get('avg_resolution_percent', 0)
                QMessageBox.information(parent, "Save Successful", 
                                      f"FWHM analysis data saved successfully!\n"
                                      f"Files: {json_path.name}, {csv_path.name}\n"
                                      f"Total peaks analyzed: {total_peaks}\n"
                                      f"Average resolution: {avg_res:.2f}%")
            return True
            
        except Exception as e:
            if parent:
                QMessageBox.critical(parent, "Save Failed", f"Error saving FWHM analysis data:\n{str(e)}")
            return False