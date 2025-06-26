import time

import pixie16


class Test_DummyData:
    @staticmethod
    def test():
        pipe = pixie16.pipeline.Pipeline()
        pipe.init(["DummyData", "GatherEvents", "PrintData"])
        pipe.configure(
            {
                "size": 1,
            }
        )
        pipe.start()

        while True:
            pipe.poll()

            if pipe._status == pixie16.pipeline.Status.FINISHED:
                break

            if pipe._status == pixie16.pipeline.Status.ERROR:
                assert False

        pipe.stop()
