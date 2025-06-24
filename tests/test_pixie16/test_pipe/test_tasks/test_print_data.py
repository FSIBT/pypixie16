import time

import pixie16


class Test_PrintData:

    def test(self):
        pipeline = pixie16.pipeline.Pipeline()
        printer = pixie16.pipeline.tasks.PrintData("Print Data", pipeline.address_router)
        pipeline.task_append(printer)
        pipeline.init(["Print Data"])
        pipeline.start()

        while printer.is_alive():
            pipeline.poll()

            if pipeline.reports["Print Data"]["status"] == pixie16.pipeline.Status.RUNNING:
                pipeline.task_stop("Print Data")

            if pipeline.reports["Print Data"]["status"] == pixie16.pipeline.Status.FINISHED:
                break

            for report in pipeline.reports.values():
                if report["status"] == pixie16.pipeline.Status.ERROR:
                    assert False

            time.sleep(0.1)

        pipeline.task_remove("Print Data")