import enum


class Status(enum.Enum):
    """
    Represents ``Task`` states.
    """

    RUNNING = "▶️"
    PAUSED = "⏸️"
    FINISHED = "✅"
    ERROR = "🆘"
