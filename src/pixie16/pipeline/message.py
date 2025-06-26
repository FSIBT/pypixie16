import enum
import typing


T = typing.TypeVar("T", bound="_Message")


class _Message(typing.Generic[T]):
    """
    Helper representing stateful pipeline messages.
    """

    def __init__(self, *args):
        self.args = args

    def __call__(self):
        return self.args


class Message(enum.Enum):
    """
    Stores pipelines messages.
    """

    # Pipe-to-Task
    DISCONNECT = "🔀"
    START = "▶️"
    PAUSE = "⏸️"
    STOP = "⏹️"

    class CONNECT(_Message[str]):  # "🔁"
        pass

    class CONFIGURE(_Message[dict]):  # "ℹ️"
        pass

    # Task-to-Pipe
    class REPORT(_Message[dict]):  # "🆗"
        pass

    class PRINT(_Message[dict]):  # "🔣"
        pass

    # All-to-Task
    FINISHED = "✅"

    # Task-to-Task
    class DATA(_Message[any]):  # "📶"
        pass
