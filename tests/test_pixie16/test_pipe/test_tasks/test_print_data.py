import time

import pixie16


class Test_PrintData:
    @staticmethod
    def test():
        printer = pixie16.pipeline.tasks.PrintData("Print Data")
        pipeline = pixie16.pipeline.Pipeline(printer)
        pipeline.init(["Print Data"])
        pipeline.start()

        while True:
            pipeline.poll()

            if (
                pipeline.reports["Print Data"]["status"]
                == pixie16.pipeline.Status.PAUSED
            ):
                break
            if (
                pipeline.reports["Print Data"]["status"]
                == pixie16.pipeline.Status.ERROR
            ):
                assert False

            pipeline.pause()

        pipeline.stop()
