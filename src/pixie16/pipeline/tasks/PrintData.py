from .. import task


class PrintData(task.Task):
    """
    Prints from the pipeline.
    """

    def do_work(self, datum: str):
        """
        Works for the task.

        Notes:
            This methods extends ``Task.do_work``.
        """

        print(datum)
        return datum
