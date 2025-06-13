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

        self.channels = channels or list(range(16))
        self.channel_names = channel_names or [f"Ch {ch}" for ch in self.channels]
        self.selected_channels = self.channels.copy()

        self.channel_checkboxes = {}
        self.channel_stats_labels = {}

        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        main_layout = QVBoxLayout()

        channel_group = self.create_channel_selection_group()
        main_layout.addWidget(channel_group)
        quick_group = self.create_quick_selection_group()
        main_layout.addWidget(quick_group)

        main_layout.addStretch()
        self.setLayout(main_layout)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def create_channel_selection_group(self):
        group = QGroupBox("Channel Selection")
        grid_layout = QGridLayout()

        colors = [
            "red",
            "green",
            "blue",
            "cyan",
            "magenta",
            "orange",
            "purple",
            "brown",
        ]

        for i, channel in enumerate(self.channels):
            row = i // 2
            col = i % 2

            # containers for each channel
            container = QWidget()
            container_layout = QHBoxLayout()
            container_layout.setContentsMargins(2, 2, 2, 2)
            container_layout.setSpacing(5)

            color = colors[i % len(colors)]
            color_label = QLabel("●")
            color_label.setStyleSheet(
                f"color: {color}; font-size: 14px; font-weight: bold;"
            )
            color_label.setFixedWidth(15)

            checkbox = QCheckBox(self.channel_names[i])
            checkbox.setChecked(True)  # all channels selected at start
            checkbox.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )

            stats_label = QLabel("0")
            stats_label.setStyleSheet(
                "font-size: 10px; color: gray; font-family: monospace;"
            )
            stats_label.setFixedWidth(40)
            stats_label.setAlignment(Qt.AlignmentFlag.AlignRight)

            container_layout.addWidget(color_label)
            container_layout.addWidget(checkbox)
            container_layout.addStretch()

            container_layout.addWidget(stats_label)
            container.setLayout(container_layout)
            grid_layout.addWidget(container, row, col)

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

        none_btn = QPushButton("None")
        none_btn.clicked.connect(self.select_no_channels)

        layout.addWidget(all_btn, 0, 0)
        layout.addWidget(none_btn, 0, 1)

        group.setLayout(layout)
        return group

    def connect_signals(self):
        for channel, checkbox in self.channel_checkboxes.items():
            checkbox.toggled.connect(
                lambda checked, ch=channel: self.on_channel_toggled(ch, checked)
            )

    def on_channel_toggled(self, channel, checked):
        # print(f"DEBUG: Channel {channel} toggled to {checked}")
        self.update_selected_channels()

        # print(f"DEBUG: Emitting channels_changed: {self.selected_channels}")
        self.channels_changed.emit(self.selected_channels)

    def update_selected_channels(self):
        self.selected_channels = [
            channel
            for channel, checkbox in self.channel_checkboxes.items()
            if checkbox.isChecked()
        ]

    def select_all_channels(self):
        # print("DEBUG: Selecting all channels")
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(True)
        self.update_selected_channels()
        self.channels_changed.emit(self.selected_channels)

    def select_no_channels(self):
        # print("DEBUG: Deselectingall")
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(False)
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
                checkbox.setChecked(False)
                self.update_selected_channels()
                self.channels_changed.emit(self.selected_channels)
