import enum


class Status(enum.Enum):
    """
    Represents ``Task`` states.
    """

    WAITING = "⏸️"
    RUNNING = "▶️"
    FINISHED = "🏁"
    DYING = "⏏️"
    PANICKING = "🆘"
