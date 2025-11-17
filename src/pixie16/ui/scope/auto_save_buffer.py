"""
Auto-Save Buffer System with Cache Management
Handles automatic saving of data buffers to disk with size management and cleanup.
"""

import json
import time
import shutil
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from collections import defaultdict, deque
import numpy as np

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QMutex, QMutexLocker
from PyQt6.QtWidgets import QMessageBox

import logging
logger = logging.getLogger(__name__)


class BufferCacheManager:
    """Manages disk cache with size limits and LRU cleanup"""
    
    def __init__(self, cache_dir: Path, max_cache_size_mb: int = 500):
        self.cache_dir = Path(cache_dir)
        self.max_cache_size_bytes = max_cache_size_mb * 1024 * 1024
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Track file access times for LRU
        self.access_times = {}
        self.mutex = threading.Lock()
        
    def get_cache_size(self) -> int: #bytes
        total_size = 0
        try:
            for file_path in self.cache_dir.rglob('*'):
                if file_path.is_file():
                    total_size += file_path.stat().st_size
        except Exception as e:
            logger.warning(f"Error calculating cache size: {e}")
        return total_size
    
    def cleanup_cache(self, target_size_ratio: float = 0.8):
        with self.mutex:
            current_size = self.get_cache_size()
            target_size = int(self.max_cache_size_bytes * target_size_ratio)
            
            if current_size <= target_size:
                return
                
            logger.info(f"Cache cleanup: {current_size/1024/1024:.1f}MB -> target {target_size/1024/1024:.1f}MB")
            
            # Get all files with their access times
            files_with_times = []
            for file_path in self.cache_dir.rglob('*'):
                if file_path.is_file():
                    # Use last access time, or creation time if never accessed
                    access_time = self.access_times.get(str(file_path), file_path.stat().st_ctime)
                    files_with_times.append((access_time, file_path, file_path.stat().st_size))
            
            # Sort by access time (oldest first)
            files_with_times.sort(key=lambda x: x[0])
            
            # Delete oldest files until we reach target size
            bytes_to_remove = current_size - target_size
            bytes_removed = 0
            
            for access_time, file_path, file_size in files_with_times:
                try:
                    file_path.unlink()
                    bytes_removed += file_size
                    self.access_times.pop(str(file_path), None)
                    logger.debug(f"Removed cache file: {file_path.name}")
                    
                    if bytes_removed >= bytes_to_remove:
                        break
                except Exception as e:
                    logger.warning(f"Error removing cache file {file_path}: {e}")
    
    def mark_accessed(self, file_path: Path):
        with self.mutex:
            self.access_times[str(file_path)] = time.time()


class AutoSaveBufferService(QObject):
    """
    Background service that automatically saves buffer data to disk with overflow handling
    """
    
    # Signals
    cache_status_changed = pyqtSignal(str)  # Status message
    data_auto_saved = pyqtSignal(str, int)  # data_type, count
    cache_cleaned = pyqtSignal(int, int)    # old_size_mb, new_size_mb
    
    def __init__(self, data_storage_manager, parent=None):
        super().__init__(parent)
        self.data_storage_manager = data_storage_manager
        self.is_active = True
        self.mutex = QMutex()
        
        # Auto-save configuration
        self.auto_save_interval_ms = 30000  # 30 seconds
        self.max_cache_size_mb = 500       # 500MB cache limit
        self.cleanup_interval_ms = 300000   # 5 minutes cleanup check
        
        # Cache directory setup
        cache_base = self.data_storage_manager.get_data_directory() / ".cache"
        self.cache_manager = BufferCacheManager(cache_base, self.max_cache_size_mb)
        
        # Timers
        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self.auto_save_all_buffers)
        
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.cleanup_cache)
        
        # Data references (will be set by parent app)
        self.data_sources = {}  # Will hold references to plotters/data sources
        
        # Buffer overflow tracking
        self.buffer_stats = {}  # Track overflow counts per data source
        self.last_buffer_check = time.time()
        
    def start_service(self):
        if not self.is_active:
            return
            
        logger.info("Starting auto-save buffer service...")
        self.auto_save_timer.start(self.auto_save_interval_ms)
        self.cleanup_timer.start(self.cleanup_interval_ms)
        self.cache_status_changed.emit("Auto-save service started")
    
    def stop_service(self):
        logger.info("Stopping auto-save buffer service...")
        self.auto_save_timer.stop()
        self.cleanup_timer.stop()
        self.cache_status_changed.emit("Auto-save service stopped")
    
    def register_data_source(self, source_name: str, data_source: Any):
        with QMutexLocker(self.mutex):
            self.data_sources[source_name] = data_source
            logger.info(f"Registered data source: {source_name}")
    
    def auto_save_all_buffers(self):
        if not self.is_active:
            return
            
        try:
            with QMutexLocker(self.mutex):
                saved_count = 0
                
                # Check for buffer overflows first
                self.check_buffer_overflows()
                
                for source_name, data_source in self.data_sources.items():
                    if self.auto_save_data_source(source_name, data_source):
                        saved_count += 1
                
                if saved_count > 0:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    self.cache_status_changed.emit(f"Auto-saved {saved_count} buffers at {timestamp}")
                    
        except Exception as e:
            logger.error(f"Error in auto-save: {e}")
            self.cache_status_changed.emit(f"Auto-save error: {str(e)}")
    
    def check_buffer_overflows(self):
        current_time = time.time()
        
        for source_name, data_source in self.data_sources.items():
            try:
                overflow_info = self.get_buffer_overflow_info(data_source)
                if overflow_info:
                    # Update stats
                    if source_name not in self.buffer_stats:
                        self.buffer_stats[source_name] = {'last_overflow_count': 0}
                    
                    total_overflows = sum(overflow_info.values())
                    last_count = self.buffer_stats[source_name]['last_overflow_count']
                    
                    if total_overflows > last_count:
                        new_overflows = total_overflows - last_count
                        self.buffer_stats[source_name]['last_overflow_count'] = total_overflows
                        
                        # Log significant overflow events
                        if new_overflows >= 10:
                            logger.info(f"Buffer overflows detected in {source_name}: {new_overflows} new overflows")
                            self.cache_status_changed.emit(f"Buffer overflow: {source_name} ({new_overflows} items)")
                            
            except Exception as e:
                logger.warning(f"Error checking overflow for {source_name}: {e}")
        
        self.last_buffer_check = current_time
    
    def get_buffer_overflow_info(self, data_source) -> Optional[Dict]:
        overflow_info = {}
        
        try:
            # Check TracesPlotter overflow counters
            if hasattr(data_source, 'trace_overflow_count'):
                overflow_info.update(data_source.trace_overflow_count)
            
            if hasattr(data_source, 'timestamp_overflow_count'):
                for ch, count in data_source.timestamp_overflow_count.items():
                    overflow_info[f'timestamps_ch_{ch}'] = count
            
            if hasattr(data_source, 'single_persistence_overflow_count'):
                for ch, count in data_source.single_persistence_overflow_count.items():
                    overflow_info[f'persistence_ch_{ch}'] = count
            
            # Check other plotter types
            if hasattr(data_source, 'energy_overflow_count'):
                overflow_info.update(data_source.energy_overflow_count)
                
            if hasattr(data_source, 'mca_overflow_count'):
                overflow_info.update(data_source.mca_overflow_count)
                
            return overflow_info if overflow_info else None
            
        except Exception as e:
            logger.warning(f"Error getting overflow info: {e}")
            return None
    
    def auto_save_data_source(self, source_name: str, data_source: Any) -> bool:
        try:
            timestamp = int(time.time())
            cache_dir = self.cache_manager.cache_dir / source_name
            cache_dir.mkdir(exist_ok=True)
            
            # Determine data source type and extract data
            data_saved = False
            
            if hasattr(data_source, 'trace_data') and hasattr(data_source, 'trace_timestamps'):
                # TracesPlotter
                data_saved = self.save_traces_buffer(cache_dir, data_source, timestamp)
                
            elif hasattr(data_source, 'mca_data'):
                # MCASpectrumPlotter  
                data_saved = self.save_mca_buffer(cache_dir, data_source, timestamp)
                
            elif hasattr(data_source, 'energy_data'):
                # EnergySpectrumPlotter
                data_saved = self.save_energy_buffer(cache_dir, data_source, timestamp)
            
            return data_saved
            
        except Exception as e:
            logger.warning(f"Error auto-saving {source_name}: {e}")
            return False
    
    def save_traces_buffer(self, cache_dir: Path, traces_plotter, timestamp: int) -> bool:
        try:
            # Check if there's data to save
            total_traces = sum(len(traces_plotter.trace_data.get(ch, [])) 
                             for ch in traces_plotter.channels)
            
            if total_traces == 0:
                return False
            
            # Prepare data for saving
            traces_data = {}
            timestamps_data = {}
            
            for ch in traces_plotter.channels:
                if ch in traces_plotter.trace_data and len(traces_plotter.trace_data[ch]) > 0:
                    traces_data[f'channel_{ch}'] = list(traces_plotter.trace_data[ch])
                    timestamps_data[f'channel_{ch}_timestamps'] = list(
                        traces_plotter.trace_timestamps.get(ch, [])
                    )
            
            # Save metadata including overflow stats
            overflow_stats = {}
            if hasattr(traces_plotter, 'trace_overflow_count'):
                overflow_stats['trace_overflows'] = dict(traces_plotter.trace_overflow_count)
            if hasattr(traces_plotter, 'timestamp_overflow_count'):
                overflow_stats['timestamp_overflows'] = dict(traces_plotter.timestamp_overflow_count)
                
            metadata = {
                'timestamp': timestamp,
                'data_type': 'traces_buffer',
                'channels': traces_plotter.channels,
                'total_traces': total_traces,
                'sampling_period_ns': getattr(traces_plotter, 'sampling_period_ns', 10.0),
                'buffer_overflow_stats': overflow_stats
            }
            
            # Save files
            json_file = cache_dir / f"traces_buffer_{timestamp}.json"
            npz_file = cache_dir / f"traces_buffer_{timestamp}.npz"
            
            with open(json_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            np.savez_compressed(npz_file, **traces_data, **timestamps_data)
            
            self.data_auto_saved.emit('traces', total_traces)
            return True
            
        except Exception as e:
            logger.warning(f"Error saving traces buffer: {e}")
            return False
    
    def save_mca_buffer(self, cache_dir: Path, mca_plotter, timestamp: int) -> bool:
        try:
            if not hasattr(mca_plotter, 'mca_data') or not mca_plotter.mca_data:
                return False
                
            # Check if there's actual data
            total_counts = sum(np.sum(data) for data in mca_plotter.mca_data.values() if len(data) > 0)
            if total_counts == 0:
                return False
            
            # Prepare metadata
            metadata = {
                'timestamp': timestamp,
                'data_type': 'mca_buffer',
                'channels': list(mca_plotter.mca_data.keys()),
                'total_counts': int(total_counts),
                'target_bins': getattr(mca_plotter, 'target_bins', 32768)
            }
            
            # Save files
            json_file = cache_dir / f"mca_buffer_{timestamp}.json"
            npz_file = cache_dir / f"mca_buffer_{timestamp}.npz"
            
            with open(json_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Save histogram data
            mca_arrays = {f'channel_{k}': v for k, v in mca_plotter.mca_data.items() if len(v) > 0}
            np.savez_compressed(npz_file, **mca_arrays)
            
            self.data_auto_saved.emit('mca', len(mca_arrays))
            return True
            
        except Exception as e:
            logger.warning(f"Error saving MCA buffer: {e}")
            return False
    
    def save_energy_buffer(self, cache_dir: Path, energy_plotter, timestamp: int) -> bool:
        try:
            if not hasattr(energy_plotter, 'energy_data') or not energy_plotter.energy_data:
                return False
                
            total_events = sum(len(events) for events in energy_plotter.energy_data.values())
            if total_events == 0:
                return False
            
            # Prepare metadata
            metadata = {
                'timestamp': timestamp,
                'data_type': 'energy_buffer', 
                'channels': list(energy_plotter.energy_data.keys()),
                'total_events': total_events
            }
            
            # Save files
            json_file = cache_dir / f"energy_buffer_{timestamp}.json"
            npz_file = cache_dir / f"energy_buffer_{timestamp}.npz"
            
            with open(json_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Save energy data
            energy_arrays = {}
            for ch, events in energy_plotter.energy_data.items():
                if len(events) > 0:
                    energy_arrays[f'channel_{ch}'] = np.array(list(events))
            
            if energy_arrays:
                np.savez_compressed(npz_file, **energy_arrays)
                self.data_auto_saved.emit('energy', len(energy_arrays))
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"Error saving energy buffer: {e}")
            return False
    
    def cleanup_cache(self):
        try:
            old_size = self.cache_manager.get_cache_size()
            self.cache_manager.cleanup_cache()
            new_size = self.cache_manager.get_cache_size()
            
            if old_size != new_size:
                old_mb = old_size / 1024 / 1024
                new_mb = new_size / 1024 / 1024
                self.cache_cleaned.emit(int(old_mb), int(new_mb))
                self.cache_status_changed.emit(f"Cache cleaned: {old_mb:.1f}MB -> {new_mb:.1f}MB")
                
        except Exception as e:
            logger.warning(f"Error during cache cleanup: {e}")
    
    def get_cache_info(self) -> Dict[str, Any]:
        try:
            cache_size = self.cache_manager.get_cache_size()
            cache_files = len(list(self.cache_manager.cache_dir.rglob('*.json')))
            
            return {
                'cache_size_mb': cache_size / 1024 / 1024,
                'max_size_mb': self.max_cache_size_mb,
                'usage_percent': (cache_size / self.cache_manager.max_cache_size_bytes) * 100,
                'cached_files': cache_files,
                'auto_save_interval_sec': self.auto_save_interval_ms / 1000,
                'is_active': self.is_active
            }
        except Exception:
            return {'error': 'Unable to get cache info'}
    
    def set_auto_save_interval(self, interval_seconds: int):
        if interval_seconds < 10:
            interval_seconds = 10  # Minimum 10 seconds
        if interval_seconds > 3600:
            interval_seconds = 3600  # Maximum 1 hour
            
        self.auto_save_interval_ms = interval_seconds * 1000
        
        if self.auto_save_timer.isActive():
            self.auto_save_timer.stop()
            self.auto_save_timer.start(self.auto_save_interval_ms)
        
        self.cache_status_changed.emit(f"Auto-save interval set to {interval_seconds}s")
    
    def set_max_cache_size(self, size_mb: int):
        if size_mb < 50:
            size_mb = 50  # Minimum 50MB
        if size_mb > 2000:
            size_mb = 5000  # Maximum 5GB
            
        self.max_cache_size_mb = size_mb
        self.cache_manager.max_cache_size_bytes = size_mb * 1024 * 1024
        
        # Trigger cleanup if we're over the new limit
        self.cleanup_cache()
        
        self.cache_status_changed.emit(f"Cache size limit set to {size_mb}MB")