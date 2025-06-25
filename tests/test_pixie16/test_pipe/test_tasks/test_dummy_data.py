import time

import pixie16


class Test_DummyData:
    @staticmethod
    def test():
        task0 = pixie16.pipeline.tasks.DummyData("Dummy")
        task1 = pixie16.pipeline.tasks.PrintData("Print")
        pipe = pixie16.pipeline.Pipeline(task0, task1)
        pipe.init(["Dummy", "Print"])
        pipe.start()

        while True:
            pipe.poll()

            if pipe._status == pixie16.pipeline.Status.FINISHED:
                break

            time.sleep(0.3)

        pipe.stop()
