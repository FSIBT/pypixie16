import enum


class Status(enum.Enum):
    """
    Represents ``Task`` states.
    """

    WAITING = "⏸️"
    RUNNING = "▶️"
    PANICKING = "🆘"
    DYING = "⏏️"
