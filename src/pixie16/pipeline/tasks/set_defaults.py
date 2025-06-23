from .. import task


class SetDefaults(task.Task):
    """Set defaults for parameters in the pixie."""

    def __init__(self, pipeline_address):
        modules = [0]
        super().__init__(pipeline_address)
        self.name = "Set defaults"
        self.modules = modules

    def do_work(self, value):
        self.done = True
        control.init_and_boot(modules=self.modules)
        for m, _ in enumerate(self.modules):
            control.set_defaults_for_module(m)
