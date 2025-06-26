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
    FINISHED = "✅"


# Define message classes outside the enum
class CONNECT(_Message[str]):  # "🔁"
    pass

class CONFIGURE(_Message[dict]):  # "ℹ️"
    pass

class REPORT(_Message[dict]):  # "🆗"
    pass

class PRINT(_Message[dict]):  # "🔣"
    pass

class DATA(_Message[typing.Any]):  # "📶"
    pass

# Add them to Message as class attributes
Message.CONNECT = CONNECT
Message.CONFIGURE = CONFIGURE  
Message.REPORT = REPORT
Message.PRINT = PRINT
Message.DATA = DATA