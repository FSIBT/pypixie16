import enum


class Status(enum.Enum):
    """
    Represents ``Task`` states.
    """

    DONE = "🆒"
    READY = "⏸️"
    RUNNING = "▶️"
    FINISHED = "✅"
    ERROR = "🆘"
