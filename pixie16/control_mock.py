print("*" * 80)
print("*" + " " * 78 + "*")
print(
    "* Mocking pixie library: this is only useful for debugging                     *"
)
print(
    "*  If you see this message you are trying to run pixie control code in 64 bit  *"
)
print(
    "*  but you need to run this in 32 bit using a 32 bit python install            *"
)
print("*" + " " * 78 + "*")
print("*" * 80)


class dummy:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.name = self.args[0]
        self.kwargs = kwargs

    def __getattr__(self, *args, **kwargs):
        print(self.args[0])

    def __call__(self, *args, **kwargs):
        print(f"called {self.name}")
        print(f"    args:  {args} ")
        for k, v in kwargs.items():
            print(f"    kwargs: {k} {v}")

    def __enter__(self):
        pass

    def __exit__(self):
        pass


def __getattr__(*args, **kwargs):
    return dummy(*args, **kwargs)
