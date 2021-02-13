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
