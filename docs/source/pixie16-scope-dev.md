# PIXIE-16 Scope Developer Documentation

## Overview

The PIXIE-16 Scope (pixiescope) is a real-time data acquisition and visualization application built with PyQt6. It provides three main acquisition modes with live parameter control and comprehensive hardware management.

## Architecture

### Core Components

The scope application follows a modular architecture with clear separation of concerns:

```
pixie16.ui.scope/
├── app.py                    # Main application and UI coordination
├── hardware_manager.py       # Hardware interface and state management  
├── parameter_validation.py   # Parameter validation and change management
├── parameter_controls.py     # UI widgets for parameter adjustment
├── channel_controls.py       # Channel selection and display controls
├── mca_spectrum_plotter.py   # MCA histogram visualization
├── traces_plotter.py         # Trace waveform visualization  
├── spectrum_plotter.py       # Continuous spectrum plotting
├── data_manager.py           # Data storage and export functionality
└── binary_loader.py          # Binary file loading and replay
```

### Key Classes

#### PixieScopeApp (app.py)
Main application window that orchestrates all components.

**Key features:**
- Multi-mode acquisition (MCA, List, Traces)
- Real-time parameter updates
- Hardware state management
- Signal coordination between UI components

#### DynamicPixieHardwareManager (hardware_manager.py)
Handles all hardware communication and state tracking.

**Features:**
- Thread-safe parameter updates
- Dummy mode for testing without hardware
- Mode-specific parameter templates
- Parameter caching for performance
- Real-time acquisition control

**Key methods:**
- `initialize_system()` - Hardware initialization
- `start_mode(mode)` - Start acquisition (histogram/list/traces)
- `update_parameter(name, value, module, channel)` - Live parameter updates
- `stop_acquisition()` - Stop current acquisition

#### PixieParameterValidator (parameter_validation.py)
Comprehensive parameter validation system with module-specific constraints.

**Features:**
- Module type awareness (100MHz, 250MHz, 500MHz)
- Parameter range validation
- Timing constraint verification
- Change debouncing and batching

**Parameter categories:**
- Trigger parameters (threshold, rise/fall times)
- Energy filter parameters (rise time, flat top, tau)
- Trace parameters (length, delay)
- Voltage parameters (offset)

## Acquisition Modes

### MCA (Multi-Channel Analyzer) Mode
- Real-time histogram accumulation
- 32k+ bin resolution
- Log/linear scaling
- Multi-channel overlay display
- Export capabilities

**Implementation:** `MCASpectrumPlotter`

### List Mode  
- Event-by-event data recording
- Real-time event rate monitoring
- Energy spectrum generation from events
- Coincidence analysis capabilities

**Implementation:** Integrated in `app.py` with `LiveDataReader`

### Traces Mode
- Raw ADC trace capture and display
- Real-time filter visualization
- Energy calculation verification
- Trigger validation display
- Coincidence logic analysis

**Implementation:** `TracesPlotter` with extensive analysis features

## Real-Time Features

### Parameter Updates
All parameter changes are applied in real-time without stopping acquisition:
- Debounced updates (300ms delay)
- Validation before hardware write
- Visual feedback for invalid ranges
- Automatic hardware synchronization

### Live Data Processing
- Continuous data polling from hardware
- Real-time plot updates (configurable intervals)
- Memory management for long acquisitions
- Performance optimization for remote desktop

### Hardware State Management
Thread-safe state tracking includes:
- Initialization status
- Current acquisition mode
- Enabled channels
- Parameter cache

## UI Components

### Parameter Controls
- Module/channel selector
- Grouped parameter widgets (Trigger, Energy, etc.)
- Real-time validation feedback
- Save/load parameter presets
- Apply to all channels functionality

### Channel Controls  
- Individual channel enable/disable
- Quick selection patterns (All, None, Even, Odd)
- Visual channel status indicators
- Per-channel statistics display

### Data Management
- Auto-save buffer system
- Manual data export (CSV, JSON)
- Binary file loading and replay
- Data persistence between sessions

## Performance Optimizations

### Remote Desktop Detection
Automatic detection and optimization for remote desktop environments:
- Reduced update frequencies
- Optimized rendering settings
- Memory usage monitoring

### Memory Management
- Circular buffers for trace data
- Configurable data retention periods
- Automatic garbage collection triggers
- Memory usage monitoring

### Threading
- Separate threads for data acquisition
- Non-blocking UI updates
- Thread-safe parameter updates
- Background data processing

## Configuration

### Module Type Support
- 100MHz modules (10ns timing resolution)
- 250MHz modules (8ns timing resolution) 
- 500MHz modules (10ns timing resolution)

### Dummy Mode
Complete simulation mode for development and testing:
- Synthetic data generation
- All UI functionality available
- No hardware dependencies
- Reproducible test data

## Error Handling

### Hardware Errors
- Connection failure detection
- Parameter validation at hardware level
- Graceful degradation to dummy mode
- Comprehensive error logging

### UI Error Recovery
- Exception handling with user feedback
- Automatic state recovery
- Memory cleanup on errors
- Graceful shutdown procedures

## Testing

The scope includes comprehensive integration tests in `tests/test_pixie_scope_integration.py`:

### Test Categories
- Hardware connection verification
- Parameter synchronization testing
- Real-time update validation
- Acquisition mode testing
- Error handling verification
- Performance benchmarking

### Test Execution
```python
# Run all tests
python tests/test_pixiescope.py all

# Run specific test categories  
python tests/test_pixiescope.py validation
python tests/test_pixiescope.py hardware
python tests/test_pixiescope.py integration

# Run with coverage
python tests/test_pixiescope.py coverage
```

## Development Guidelines

### Adding New Parameters
1. Add parameter spec in `parameter_validation.py`
2. Create UI widget in `parameter_controls.py`
3. Add hardware mapping in `hardware_manager.py`
4. Update validation tests

### Extending Acquisition Modes
1. Define mode template in `hardware_manager.py`
2. Add plotting components as needed
3. Update UI mode selection
4. Add integration tests

### Performance Considerations
- Use Qt signals for thread communication
- Implement data throttling for high rates
- Cache parameter values when possible
- Profile memory usage regularly