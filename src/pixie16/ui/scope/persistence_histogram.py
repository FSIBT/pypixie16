import numpy as np
from fast_histogram import histogram2d


class PersistenceHistogram:
    
    def __init__(self, x_bins=1000, y_bins=400):
        self.x_bins = x_bins
        self.y_bins = y_bins
        self.histogram = np.zeros((y_bins, x_bins), dtype=np.uint32)
        self.x_range = None
        self.y_range = None
        self.trace_count = 0
        
    def reset(self):
        self.histogram.fill(0)
        self.x_range = None
        self.y_range = None
        self.trace_count = 0
        
    def add_trace(self, time_axis, trace_data):
        if len(time_axis) != len(trace_data):
            return
            
        if self.x_range is None:
            self.x_range = [float(time_axis.min()), float(time_axis.max())]
            self.y_range = [float(trace_data.min() * 0.85), float(trace_data.max() * 1.15)]
        else: # expand ranges if needed
            self.x_range[0] = min(self.x_range[0], float(time_axis.min()))
            self.x_range[1] = max(self.x_range[1], float(time_axis.max()))
            self.y_range[0] = min(self.y_range[0], float(trace_data.min() * 0.85))
            self.y_range[1] = max(self.y_range[1], float(trace_data.max() * 1.15))
        
        # Add trace to histogram
        hist_2d = histogram2d(
            time_axis, trace_data,
            bins=(self.x_bins, self.y_bins),
            range=(self.x_range, self.y_range)
        ).T
        
        self.histogram += hist_2d.astype(np.uint32)
        self.trace_count += 1
        
    def get_image_data(self, log_scale=True):
        if self.trace_count == 0 or self.x_range is None:
            return None, None, None
            
        if log_scale:
            # Add 1 to avoid log(0)
            img_data = np.log10(self.histogram + 1)
        else:
            img_data = self.histogram.copy()
            
        return img_data, self.x_range, self.y_range