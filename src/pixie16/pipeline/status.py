import enum


class Status(enum.Enum):
    """
    Represents ``Task`` states.
    """

    WAITING = "⏸️"
    RUNNING = "▶️"
    DYING = "⏏️"
    PANICKING = "🆘"
