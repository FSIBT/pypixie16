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
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(2)

        # Channel selection
        channel_group = self.create_channel_selection_group()
        main_layout.addWidget(channel_group)

        # Quick selection buttons
        quick_group = self.create_quick_selection_group()
        main_layout.addWidget(quick_group)

        self.setLayout(main_layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def create_channel_selection_group(self):
        # Create a container with a clickable header
        main_container = QWidget()
        main_container_layout = QVBoxLayout()
        main_container_layout.setContentsMargins(0, 0, 0, 0)

        # Clickable header button
        self.channel_header_btn = QPushButton("▶ Channel Selection")
        self.channel_header_btn.setCheckable(True)
        self.channel_header_btn.setChecked(False)
        self.channel_header_btn.clicked.connect(self.toggle_channel_selection)
        self.channel_header_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 5px;
                font-weight: bold;
                border: 1px solid gray;
                background-color: #f0f0f0;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)

        # The actual content group
        self.channel_content_group = QGroupBox()
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

            # Container for each channel (unique variable names)
            channel_widget = QWidget()
            channel_layout = QHBoxLayout()
            channel_layout.setContentsMargins(2, 2, 2, 2)
            channel_layout.setSpacing(5)

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

            # Assemble channel widget
            channel_layout.addWidget(color_label)
            channel_layout.addWidget(checkbox)
            channel_layout.addStretch()
            channel_layout.addWidget(stats_label)
            channel_widget.setLayout(channel_layout)

            grid_layout.addWidget(channel_widget, row, col)

            # Store references
            self.channel_checkboxes[channel] = checkbox
            self.channel_stats_labels[channel] = stats_label

        self.channel_content_group.setLayout(grid_layout)
        self.channel_content_group.setVisible(False)

        # Assemble the collapsible container
        main_container_layout.addWidget(self.channel_header_btn)
        main_container_layout.addWidget(self.channel_content_group)
        main_container.setLayout(main_container_layout)

        return main_container

    def create_quick_selection_group(self):
        # Create collapsible container
        container = QWidget()
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0, 0, 0, 0)

        # Clickable header
        self.quick_header_btn = QPushButton("▶ Quick Select")
        self.quick_header_btn.setCheckable(True)
        self.quick_header_btn.setChecked(False)
        self.quick_header_btn.clicked.connect(self.toggle_quick_selection)
        self.quick_header_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 5px;
                font-weight: bold;
                border: 1px solid gray;
                background-color: #f0f0f0;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)

        # Content group
        self.quick_content_group = QGroupBox()
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

        self.quick_content_group.setLayout(layout)
        self.quick_content_group.setVisible(False)

        container_layout.addWidget(self.quick_header_btn)
        container_layout.addWidget(self.quick_content_group)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container.setLayout(container_layout)
        container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )

        return container

    def toggle_channel_selection(self, checked):
        self.channel_content_group.setVisible(checked)
        if checked:
            self.channel_header_btn.setText("▼ Channel Selection")
        else:
            self.channel_header_btn.setText("▶ Channel Selection")

    def toggle_quick_selection(self, checked):
        self.quick_content_group.setVisible(checked)
        if checked:
            self.quick_header_btn.setText("▼ Quick Select")
        else:
            self.quick_header_btn.setText("▶ Quick Select")

    def connect_signals(self):
        for channel, checkbox in self.channel_checkboxes.items():
            checkbox.toggled.connect(
                lambda checked, ch=channel: self.on_channel_toggled(ch, checked)
            )

    def on_channel_toggled(self, channel, checked):
        print(f"ChannelControls: Channel {channel} toggled to {checked}")

        # Update selected channels list
        self.update_selected_channels()

        print(f"ChannelControls: Selected channels now: {self.selected_channels}")
        print(f"ChannelControls: Emitting channels_changed signal")

        self.channels_changed.emit(self.selected_channels)

    def update_selected_channels(self):
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
        print("ChannelControls: Selecting all channels")

        # Block signals during bulk update to avoid multiple emissions
        for checkbox in self.channel_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(True)
            checkbox.blockSignals(False)

        self.update_selected_channels()
        self.channels_changed.emit(self.selected_channels)

    def select_no_channels(self):
        print("ChannelControls: Deselecting all channels")

        # Block signals during bulk update
        for checkbox in self.channel_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)

        self.update_selected_channels()
        self.channels_changed.emit(self.selected_channels)

    def update_channel_statistics(self, channel_stats):
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
        return self.selected_channels.copy()

    def set_channel_enabled(self, channel, enabled):
        if channel in self.channel_checkboxes:
            checkbox = self.channel_checkboxes[channel]
            checkbox.setEnabled(enabled)
            if not enabled:
                checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(False)
                self.update_selected_channels()
                self.channels_changed.emit(self.selected_channels)

