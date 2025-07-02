import enum


class Status(enum.Enum):
    """
    Represents ``Task`` states.
    """

    READY = "⏸️"
    RUNNING = "▶️"
    ERROR = "🆘"
    DYING = "⏏️"
