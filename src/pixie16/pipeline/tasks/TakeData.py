import time

from .. import task
from ... import control
from .. import status
from .. import message

# Anything that talks to the pixie16

class TakeData(task.Task):
    """Example Task to aquire data, each binary blob from the FPGA 
    will be put in the queue.

    A second task can then convert the binary blob to events and from
    there perhaps another task can convert to pandas.

    One tricky part is that we also need to initialize and boot the
    pixie, since this will run in another process. However, we cannot
    do this in the init, since the init will still be executed in the
    main thread, so this has to happen in `do_work`.

    We also check the runtime in `do_work` and then stop the process
    and end the run during the cleanup phase. We also read out the
    remaining events from the buffer and send them on during cleanup.

    """
    def __init__(self):
        """
        Initializes the ``TakeData`` task.

        Parameters:
            name: Task name.
        """
        super().__init__()
        
       
    def handle_configure(self, config):
        """
        Handle configuration for the task.
        """  
        super().handle_configure(config)
        self.modules = self.config.get("modules", [2])  # default to module 2
        self.runtime = self.config.get("runtime", 10) 

    def do_startup(self):
        """
        Stuff that would normally be done in __init__.
        
        Prepare the data and configuration
        DATA should come from pixie16 control module.
        px.control.read_list_mode_fifo(threshold=64 * 1024)
        configuration is a dicionaty with the settings for he different modes
        px.control.change_setting_from_dict(settings, call_pixie=True)
        """
        self.started_acquisition = False
        self.config |= {
            "modules": [2],  # default to module 2
            "runtime": 10,  # default runtime in seconds
        }
        
        self.start_time = None
        self.runtime = 10  # default runtime in seconds
        
        # Boot the pixie16
        control.init_and_boot(modules=self.modules, verbose=False, boot_pattern=0x7F)
        self.set_defaults()
        control.adjust_offsets()
        control.unset_sync_mode()
        control.empty_all_fifos()
    
    def do_work(self, value):
        """
        Here we should return the data that is going to be send over
        """
            # this would be a good spot to save the initial settings
        self.start_time = time.time()
        control.start_list_mode_run()
        now = time.time()
        if now - self.start_time > self.config["runtime"]:
            return control.read_list_mode_fifo(threshold=64*1024)
        
    def set_defaults(self):
        """Set defaults for the pixie16."""
        for m, _ in enumerate(self.modules):
            control.set_defaults_for_module(m)
