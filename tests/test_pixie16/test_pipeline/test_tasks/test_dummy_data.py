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

            if pipe.status == pixie16.pipeline.Status.WAITING:
                break

            if pipe.status == pixie16.pipeline.Status.PANICKING:
                assert False

        pipe.quit()
