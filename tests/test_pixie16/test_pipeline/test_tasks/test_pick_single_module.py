import time

import pixie16


class Test_PickSingleModule:
    @staticmethod
    def test():
        pipe = pixie16.pipeline.Pipeline()
        pipe.init(["DummyData", "PickSingleModule", "PrintData"])
        pipe.start()

        while True:
            pipe.poll()

            if pipe.status == pixie16.pipeline.Status.FINISHED:
                break

            if pipe.status == pixie16.pipeline.Status.ERROR:
                assert False

        pipe.quit()
