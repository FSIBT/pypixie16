import enum


class Status(enum.Enum):
    """
    Represents ``Task`` states.
    """

    READY = "⏸️"
    RUNNING = "▶️"
    FINISHED = "✅"
    ERROR = "🆘"
    DYING = "⏏️"
