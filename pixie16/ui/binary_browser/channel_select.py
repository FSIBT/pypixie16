from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
)


class ChannelSelect(QHBoxLayout):
    """Horizontal list of buttons that can be changed during runtime."""

    def __init__(self, main):
        super().__init__()
        self.channels = []
        self.main = main

    def clear_channels(self):
        while self.count():
            item = self.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def add_channels(self):
        self.addWidget(QLabel("Show/Hide:"))
        for channel in self.main.channels:
            tmp = QPushButton(f"Ch {channel}")
            tmp.setCheckable(True)
            tmp.toggle()
            tmp.clicked.connect(
                lambda state, channel=channel, widget=tmp: self.main.click_channel(
                    channel, widget
                )
            )

            self.channels.append(tmp)
            self.addWidget(tmp)
            # by default show all channels
            if channel not in self.main.selected_channels:
                self.main.selected_channels.append(channel)

        tmp = QPushButton("All")
        tmp.setCheckable(True)
        tmp.toggle()
        tmp.clicked.connect(
            lambda state, channel="all", widget=tmp: self.main.click_channel(
                "all", widget
            )
        )

        self.channels.append(tmp)
        self.addWidget(tmp)

    def update_button_status(self):
        for w, channel in zip(self.channels, self.main.channels):
            if not w.isChecked() and channel in self.main.selected_channels:
                w.toggle()
            if w.isChecked() and channel not in self.main.selected_channels:
                w.toggle()
