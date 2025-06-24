import time

import pixie16


class Test_DummyData:
    def test(self):
        pipeline = pixie16.pipeline.Pipeline()
        dummy = pixie16.pipeline.tasks.DummyData("Dummy Data", pipeline.address_router)
        printer = pixie16.pipeline.tasks.PrintData("Print Data", pipeline.address_router)
        pipeline.task_append(dummy)
        pipeline.task_append(printer)
        pipeline.init(["Dummy Data", "Print Data"])
        pipeline.start()

        while dummy.is_alive() and printer.is_alive():
            pipeline.poll()

            if pipeline.reports["Dummy Data"]["status"] == pixie16.pipeline.Status.FINISHED:
                pipeline.task_pause("Print Data")
                break

            for report in pipeline.reports.values():
                if report["status"] == pixie16.pipeline.Status.ERROR:
                    assert False

            time.sleep(0.1)

        pipeline.task_remove("Dummy Data")
        pipeline.task_remove("Print Data")
