"""
Channel control widgets for PIXIE-16 scope interface.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QCheckBox,
    QPushButton,
    QLabel,
    QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt

import logging

logger = logging.getLogger(__name__)


class ChannelDisplayControls(QGroupBox):
    channels_changed = pyqtSignal(list)

    def __init__(self, channels=None, channel_names=None, title="Channel Controls"):
        super().__init__(title)

        if channels is None:
            self.channels = list(range(16))
        elif isinstance(channels[0], tuple):
            # Extract just the channel numbers from (module, channel) tuples
            self.channels = [ch for (mod, ch) in channels]
            self.module_channel_pairs = channels  # Keep the original format
        else:
            # Plain channel numbers
            self.channels = channels
            self.module_channel_pairs = [(0, ch) for ch in channels]  # Default module 0

        self.channel_names = channel_names or [f"Ch {ch}" for ch in self.channels]
        self.selected_channels = self.channels.copy()  # Start with all selected

        self.channel_checkboxes = {}
        self.channel_stats_labels = {}

        print(f"ChannelControls: Initialized with channels: {self.channels}")
        print(f"ChannelControls: Module-channel pairs: {self.module_channel_pairs}")

        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        main_layout = QVBoxLayout()

        # Channel selection
        channel_group = self.create_channel_selection_group()
        main_layout.addWidget(channel_group)

        # Quick selection buttons
        quick_group = self.create_quick_selection_group()
        main_layout.addWidget(quick_group)

        main_layout.addStretch()
        self.setLayout(main_layout)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def create_channel_selection_group(self):
        group = QGroupBox("Channel Selection")
        grid_layout = QGridLayout()

        colors = [
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

        for i, channel in enumerate(self.channels):
            row = i // 2
            col = i % 2

            # Container for each channel
            container = QWidget()
            container_layout = QHBoxLayout()
            container_layout.setContentsMargins(2, 2, 2, 2)
            container_layout.setSpacing(5)

            # Color indicator
            color = colors[i % len(colors)]
            color_label = QLabel("●")
            color_label.setStyleSheet(
                f"color: {color}; font-size: 14px; font-weight: bold;"
            )
            color_label.setFixedWidth(15)

            # Channel checkbox
            checkbox = QCheckBox(self.channel_names[i])
            checkbox.setChecked(True)  # All channels selected at start
            checkbox.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )

            # Statistics label
            stats_label = QLabel("0")
            stats_label.setStyleSheet(
                "font-size: 10px; color: gray; font-family: monospace;"
            )
            stats_label.setFixedWidth(40)
            stats_label.setAlignment(Qt.AlignmentFlag.AlignRight)

            # Assemble container
            container_layout.addWidget(color_label)
            container_layout.addWidget(checkbox)
            container_layout.addStretch()
            container_layout.addWidget(stats_label)
            container.setLayout(container_layout)

            grid_layout.addWidget(container, row, col)

            # Store references
            self.channel_checkboxes[channel] = checkbox
            self.channel_stats_labels[channel] = stats_label

        group.setLayout(grid_layout)
        return group

    def create_quick_selection_group(self):
        group = QGroupBox("Quick Select")
        layout = QGridLayout()

        # All/None buttons
        all_btn = QPushButton("All")
        all_btn.clicked.connect(self.select_all_channels)
        all_btn.setMaximumWidth(60)

        none_btn = QPushButton("None")
        none_btn.clicked.connect(self.select_no_channels)
        none_btn.setMaximumWidth(60)

        layout.addWidget(all_btn, 0, 0)
        layout.addWidget(none_btn, 0, 1)

        group.setLayout(layout)
        return group

    def connect_signals(self):
        """Connect checkbox signals with proper channel identification"""
        for channel, checkbox in self.channel_checkboxes.items():
            checkbox.toggled.connect(
                lambda checked, ch=channel: self.on_channel_toggled(ch, checked)
            )

    def on_channel_toggled(self, channel, checked):
        """Handle individual channel toggle"""
        print(f"ChannelControls: Channel {channel} toggled to {checked}")

        # Update selected channels list
        self.update_selected_channels()

        print(f"ChannelControls: Selected channels now: {self.selected_channels}")
        print(f"ChannelControls: Emitting channels_changed signal")

        self.channels_changed.emit(self.selected_channels)

    def update_selected_channels(self):
        """Update the list of selected channels"""
        old_selected = self.selected_channels.copy()

        self.selected_channels = [
            channel
            for channel, checkbox in self.channel_checkboxes.items()
            if checkbox.isChecked()
        ]

        print(
            f"ChannelControls: Updated selected channels: {old_selected} -> {self.selected_channels}"
        )

    def select_all_channels(self):
        """Select all available channels"""
        print("ChannelControls: Selecting all channels")

        # Block signals during bulk update to avoid multiple emissions
        for checkbox in self.channel_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(True)
            checkbox.blockSignals(False)

        self.update_selected_channels()
        self.channels_changed.emit(self.selected_channels)

    def select_no_channels(self):
        """Deselect all channels"""
        print("ChannelControls: Deselecting all channels")

        # Block signals during bulk update
        for checkbox in self.channel_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)

        self.update_selected_channels()
        self.channels_changed.emit(self.selected_channels)

    def select_channel_range(self, start, end):
        """Select a specific range of channels"""
        print(f"ChannelControls: Selecting channels {start} to {end - 1}")

        # First deselect all
        for checkbox in self.channel_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)

        # Then select the range
        for channel in range(start, end):
            if channel in self.channel_checkboxes:
                checkbox = self.channel_checkboxes[channel]
                checkbox.blockSignals(True)
                checkbox.setChecked(True)
                checkbox.blockSignals(False)

        self.update_selected_channels()
        self.channels_changed.emit(self.selected_channels)

    def update_channel_statistics(self, channel_stats):
        """Update the statistics display for each channel"""
        for channel, count in channel_stats.items():
            if channel in self.channel_stats_labels:
                if isinstance(count, int):
                    if count >= 1000000:
                        text = f"{count / 1000000:.1f}M"
                    elif count >= 1000:
                        text = f"{count / 1000:.1f}k"
                    else:
                        text = str(count)
                else:
                    text = str(count)

                self.channel_stats_labels[channel].setText(text)

    def get_display_channels(self):
        """Get the currently selected channels for display"""
        return self.selected_channels.copy()

    def set_channel_enabled(self, channel, enabled):
        """Enable/disable a specific channel"""
        if channel in self.channel_checkboxes:
            checkbox = self.channel_checkboxes[channel]
            checkbox.setEnabled(enabled)
            if not enabled:
                checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(False)
                self.update_selected_channels()
                self.channels_changed.emit(self.selected_channels)

    def get_selected_module_channel_pairs(self):
        """Get selected channels as (module, channel) tuples for hardware calls"""
        selected_pairs = []
        for mod_ch_pair in self.module_channel_pairs:
            if isinstance(mod_ch_pair, tuple):
                module, channel = mod_ch_pair
                if channel in self.selected_channels:
                    selected_pairs.append((module, channel))
        return selected_pairs
