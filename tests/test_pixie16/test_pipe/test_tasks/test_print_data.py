import time

import pixie16


class Test_PrintData:
    @staticmethod
    def test():
        task0 = pixie16.pipeline.tasks.PrintData("Print")
        pipe = pixie16.pipeline.Pipeline(task0)
        pipe.init(["Print"])
        pipe.start()
        pipe.poll()
        pipe.stop()
