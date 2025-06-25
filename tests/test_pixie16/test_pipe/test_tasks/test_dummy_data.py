import time

import pixie16


class Test_DummyData:
    @staticmethod
    def test():
        pipe = pixie16.pipeline.Pipeline()
        pipe.init(["DummyData", "PrintData"])
        pipe.start()

        while True:
            pipe.poll()

            if pipe._status == pixie16.pipeline.Status.FINISHED:
                break

            time.sleep(0.3)

        pipe.stop()
