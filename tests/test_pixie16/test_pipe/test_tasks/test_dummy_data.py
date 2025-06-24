import time

import pixie16


class Test_DummyData:
    @staticmethod
    def test():
        dummy = pixie16.pipeline.tasks.DummyData("Dummy Data")
        printer = pixie16.pipeline.tasks.PrintData("Print Data")
        pipeline = pixie16.pipeline.Pipeline(dummy, printer)
        pipeline.init(["Dummy Data", "Print Data"])
        pipeline.start()

        while dummy.is_alive() and printer.is_alive():
            pipeline.poll()

            if "finished" in pipeline.reports["Dummy Data"]:
                pipeline.pause()

            for report in pipeline.reports.values():
                if report["status"] == pixie16.pipeline.Status.ERROR:
                    assert False

            time.sleep(0.1)

        pipeline.stop()
