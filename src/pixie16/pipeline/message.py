import typing


T = typing.TypeVar("T", bound="_Message")


class _Message(typing.Generic[T]):
    """
    Helper representing stateful pipeline messages.

    Attributes:
        args: Message arguments.
    """

    def __init__(self, *args):
        self.args = args

    def __call__(self):
        return self.args


class Message:
    """
    Stores pipelines messages.
    """

    START = "▶️"
    STOP = "⏹️"
    QUIT = "⏏️"

    class CONNECT(_Message[str]):  # "🔁"
        pass

    class CONFIGURE(_Message[dict]):  # "ℹ️"
        pass

    class REPORT(_Message[dict]):  # "🆗"
        pass

    class DATA(_Message[typing.Any]):  # "📶"
        pass
