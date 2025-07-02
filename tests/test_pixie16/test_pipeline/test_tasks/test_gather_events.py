import time

import pixie16


class Test_GatherEvents:
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

            if pipe.status == pixie16.pipeline.Status.READY:
                break

            if pipe.status == pixie16.pipeline.Status.ERROR:
                assert False

        pipe.quit()
