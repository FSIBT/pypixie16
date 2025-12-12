import pixie16


class Test__Message:
    def test__init(self):
        data = "Hi"

        msg = pixie16.pipeline.Message.DATA(data)

        assert msg.args == (data,)

    def test_call(self):
        data = "Hi"

        msg = pixie16.pipeline.Message.DATA(data)

        assert msg.args == msg()
