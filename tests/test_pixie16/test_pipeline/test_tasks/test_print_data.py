import time

import pixie16


class Test_PrintData:
    @staticmethod
    def test():
        pipe = pixie16.pipeline.Pipeline()
        pipe.init(["PrintData"])
        pipe.start()
        pipe.poll()
        pipe.quit()
