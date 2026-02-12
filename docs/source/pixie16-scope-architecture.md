# PIXIE-16 Scope Architecture

## System Overview

The PIXIE-16 Scope is designed as a modular, real-time data acquisition system with a clear separation between hardware management, data processing, and user interface components.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    PixieScopeApp (QMainWindow)                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  Parameter      │  │   Channel       │  │  Data Manager   │  │
│  │  Controls       │  │   Controls      │  │                 │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ MCA Spectrum    │  │ Traces Plotter  │  │ List Mode       │  │
│  │ Plotter         │  │                 │  │ Analysis        │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │ Hardware Manager  │
                    │ + Validator       │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │   PIXIE-16        │
                    │   Hardware        │
                    └───────────────────┘
```

## Component Interactions

### Data Flow

1. **Hardware → Application**
   ```
   PIXIE-16 Hardware → DynamicPixieHardwareManager → LiveDataReader → UI Components
   ```

2. **Parameter Updates**
   ```
   UI Widget → ParameterValidator → ParameterChangeManager → HardwareManager → PIXIE-16
   ```

3. **Real-time Display**
   ```
   Hardware Data → Data Processing → Plot Widgets → Qt Graphics System
   ```

## Core Subsystems

### 1. Hardware Management Layer

#### DynamicPixieHardwareManager
- **Purpose**: Abstraction layer for PIXIE-16 hardware communication
- **Key Features**:
  - Thread-safe parameter updates
  - Mode-specific configuration templates
  - Parameter caching for performance
  - Dummy mode simulation
  - State tracking and recovery

#### HardwareState (dataclass)
```python
@dataclass
class HardwareState:
    is_initialized: bool = False
    is_running: bool = False
    current_mode: str | None = None
    enabled_channels: list[int] = None
    current_parameters: dict[str, dict[str, any]] = None
```

### 2. Parameter Management Layer

#### PixieParameterValidator
- **Purpose**: Validate parameters before hardware updates
- **Features**:
  - Module-specific constraints (100MHz/250MHz/500MHz)
  - Parameter specification definitions
  - Range checking and type validation
  - Unit conversion and normalization

#### ParameterChangeManager
- **Purpose**: Manage parameter update workflow
- **Features**:
  - Debounced updates (300ms delay)
  - Batch parameter updates
  - Change callbacks and notifications
  - Threading coordination

### 3. User Interface Layer

#### Main Application (PixieScopeApp)
- **Layout**: QSplitter-based with resizable panels
- **Coordination**: Signal/slot communication between components
- **Features**:
  - Mode switching (MCA/List/Traces)
  - Real-time status updates
  - Error handling and user feedback
  - Resource management and cleanup

#### UI Component Communication
```python
# Signal connections example
parameter_controls.parameter_changed.connect(hardware_manager.update_parameter)
channel_controls.channels_changed.connect(plotters.update_displayed_channels)
hardware_manager.data_ready.connect(plotters.update_data)
```

### 4. Visualization Layer

#### Plotting Architecture
All plotting components inherit from QWidget and use PyQtGraph for performance:

- **MCASpectrumPlotter**: Histogram display with log scaling
- **TracesPlotter**: Waveform display with analysis overlays
- **SpectrumPlotter**: Continuous spectrum accumulation

#### Common Plotting Features
- Real-time data updates via QTimer
- Configurable update intervals
- Memory-efficient data handling
- Export capabilities (PNG, CSV)

## Data Processing Pipeline

### MCA Mode Data Flow
```
Hardware Histograms → Rebinning (optional) → Log Scaling → Plot Display
                                ↓
                        Statistics Calculation → UI Status Updates
```

### Traces Mode Data Flow  
```
Raw ADC Traces → Digital Filter Processing → Trigger Analysis → Plot Display
                            ↓                      ↓
                    Energy Calculation    Time Alignment
                            ↓                      ↓
                    Validation Overlay    Coincidence Detection
```

### List Mode Data Flow
```
Event Stream → Energy Calculation → Histogram Binning → Spectrum Display
                     ↓                      ↓
              Coincidence Analysis    Statistics Updates
```

## Thread Safety

### Threading Model
- **Main Thread**: UI updates and user interactions
- **Hardware Thread**: Data acquisition and parameter updates  
- **Worker Threads**: Data processing and analysis

### Synchronization Mechanisms
- `threading.Lock()` for parameter updates
- Qt signals/slots for thread communication
- Atomic operations for state changes
- Queue-based data passing

## Configuration System

### Module Type Configuration
Parameters are automatically adjusted based on module type:
- **100MHz**: 10ns timing resolution, specific range limits
- **250MHz**: 8ns timing resolution, adjusted constraints
- **500MHz**: 10ns timing resolution, extended ranges

### Parameter Specifications
Each parameter includes:
```python
ParameterSpec(
    name="TRIGGER_THRESHOLD",
    data_type=int,
    min_value=1,
    max_value=65535,
    unit="ADC units", 
    description="Threshold for event detection",
    dsp_variable="FASTTHRESH"
)
```

## Memory Management

### Data Retention Strategies
- **Circular Buffers**: For trace data to prevent memory growth
- **Configurable Limits**: User-defined data retention periods
- **Auto-cleanup**: Automatic garbage collection triggers
- **Memory Monitoring**: Real-time memory usage tracking

### Performance Optimizations
- **Remote Desktop Detection**: Reduced update rates for RDP
- **Data Throttling**: Configurable update intervals
- **Selective Updates**: Only update changed parameters
- **Lazy Loading**: Load data on demand

## Error Handling Strategy

### Hardware Error Recovery
1. **Detection**: Monitor hardware communication errors
2. **Logging**: Comprehensive error logging with context
3. **Recovery**: Attempt automatic reconnection
4. **Fallback**: Switch to dummy mode if hardware fails
5. **User Notification**: Clear error messages and options

### UI Error Handling
- **Exception Hooks**: Global exception handling for UI crashes
- **State Recovery**: Restore UI state after errors
- **Resource Cleanup**: Proper cleanup on shutdown/errors
- **User Feedback**: Informative error dialogs

## Extension Points

### Adding New Acquisition Modes
1. Define mode template in `DynamicPixieHardwareManager.mode_parameter_templates`
2. Create specialized plotter widget
3. Add mode selection in main UI
4. Implement data processing pipeline

### Custom Parameter Types
1. Add parameter specification in `PixieParameterValidator._initialize_parameter_specs()`
2. Create custom UI widget in `parameter_controls.py`
3. Add hardware mapping in `hardware_manager.py`
4. Update validation tests

### New Visualization Components
1. Inherit from QWidget
2. Implement data update methods
3. Connect to data signals from hardware manager
4. Add to main application layout

## Development Workflows

### Testing Strategy
- **Unit Tests**: Individual component testing
- **Integration Tests**: Hardware interaction testing
- **UI Tests**: Widget interaction testing
- **Performance Tests**: Memory and timing validation

### Code Organization Principles
- **Single Responsibility**: Each module has a clear purpose
- **Interface Segregation**: Clean APIs between components
- **Dependency Injection**: Hardware manager passed to components
- **Event-Driven**: Qt signals for component communication

### Debugging Tools
- **Logging**: Comprehensive logging throughout the application
- **Dummy Mode**: Test UI without hardware dependencies
- **Parameter Validation**: Immediate feedback for invalid inputs
- **State Inspection**: Hardware state monitoring and display