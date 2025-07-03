import time

import pixie16


class Test_GatherEvents:
    @staticmethod
    def test():
        pipe = pixie16.pipeline.Pipeline()
        pipe.connect(["DummyData", "GatherEvents", "PrintData"])
        pipe.configure(
            {
                "size": 1,
            }
        )
        pipe.start()

        while True:
            pipe.poll()

            if pipe.status == pixie16.pipeline.Status.WAITING:
                break

            if pipe.status == pixie16.pipeline.Status.PANICKING:
                assert False

        pipe.quit()
