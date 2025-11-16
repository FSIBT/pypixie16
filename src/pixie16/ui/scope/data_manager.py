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