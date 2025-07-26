import io
import os
import time

import zmq
import pytest

import pixie16


class DummyTask(pixie16.pipeline.Task):
    def do_work(self, value):
        self.report({})
        self.print("HI")
        raise Exception


@pytest.fixture
def pipeline_i() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_ic() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyTask"])
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_is() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.start()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_it() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.stop()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_iq() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.quit()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_ik() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.kill()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_ics() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyTask"])
    pipe.start()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_ict() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyTask"])
    pipe.stop()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_icq() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyTask"])
    pipe.stop()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_ick() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyTask"])
    pipe.kill()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_icst() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyTask"])
    pipe.start()
    pipe.stop()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_icsq() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyTask"])
    pipe.start()
    pipe.quit()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_icsqk() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyTask"])
    pipe.start()
    pipe.quit()
    pipe.kill()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_icstq() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyTask"])
    pipe.start()
    pipe.stop()
    pipe.quit()
    yield pipe
    pipe.kill()


@pytest.fixture
def pipeline_icstqk() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyTask"])
    pipe.start()
    pipe.stop()
    pipe.quit()
    pipe.kill()
    yield pipe
    pipe.kill()


class Test_Pipeline:
    def test___init___(self):
        pixie16.pipeline.Pipeline()

    def test_connect_valid(
        self,
        pipeline_i: pixie16.pipeline.Pipeline,
        pipeline_ic: pixie16.pipeline.Pipeline,
        pipeline_is: pixie16.pipeline.Pipeline,
        pipeline_it: pixie16.pipeline.Pipeline,
        pipeline_iq: pixie16.pipeline.Pipeline,
        pipeline_ik: pixie16.pipeline.Pipeline,
        pipeline_ics: pixie16.pipeline.Pipeline,
        pipeline_ict: pixie16.pipeline.Pipeline,
        pipeline_icq: pixie16.pipeline.Pipeline,
        pipeline_ick: pixie16.pipeline.Pipeline,
        pipeline_icst: pixie16.pipeline.Pipeline,
        pipeline_icsq: pixie16.pipeline.Pipeline,
        pipeline_icsqk: pixie16.pipeline.Pipeline,
        pipeline_icstq: pixie16.pipeline.Pipeline,
        pipeline_icstqk: pixie16.pipeline.Pipeline,
    ):
        pipeline_i.connect(["DummyTask"])
        pipeline_ic.connect(["DummyTask"])
        pipeline_is.connect(["DummyTask"])
        pipeline_it.connect(["DummyTask"])
        pipeline_iq.connect(["DummyTask"])
        pipeline_ik.connect(["DummyTask"])
        pipeline_ics.connect(["DummyTask"])
        pipeline_ict.connect(["DummyTask"])
        pipeline_icq.connect(["DummyTask"])
        pipeline_icst.connect(["DummyTask"])
        pipeline_icsq.connect(["DummyTask"])
        pipeline_icstq.connect(["DummyTask"])

    def test_connect_invalid(
        self,
        pipeline_i: pixie16.pipeline.Pipeline,
        pipeline_ic: pixie16.pipeline.Pipeline,
        pipeline_is: pixie16.pipeline.Pipeline,
        pipeline_it: pixie16.pipeline.Pipeline,
        pipeline_iq: pixie16.pipeline.Pipeline,
        pipeline_ik: pixie16.pipeline.Pipeline,
        pipeline_ics: pixie16.pipeline.Pipeline,
        pipeline_ict: pixie16.pipeline.Pipeline,
        pipeline_icq: pixie16.pipeline.Pipeline,
        pipeline_ick: pixie16.pipeline.Pipeline,
        pipeline_icst: pixie16.pipeline.Pipeline,
        pipeline_icsq: pixie16.pipeline.Pipeline,
        pipeline_icsqk: pixie16.pipeline.Pipeline,
        pipeline_icstq: pixie16.pipeline.Pipeline,
        pipeline_icstqk: pixie16.pipeline.Pipeline,
    ):
        with pytest.raises(ValueError):
            pipeline_i.connect([""])
        with pytest.raises(ValueError):
            pipeline_ic.connect([""])
        with pytest.raises(ValueError):
            pipeline_is.connect([""])
        with pytest.raises(ValueError):
            pipeline_it.connect([""])
        with pytest.raises(ValueError):
            pipeline_iq.connect([""])
        with pytest.raises(ValueError):
            pipeline_ik.connect([""])
        with pytest.raises(ValueError):
            pipeline_ics.connect([""])
        with pytest.raises(ValueError):
            pipeline_ict.connect([""])
        with pytest.raises(ValueError):
            pipeline_icq.connect([""])
        with pytest.raises(ValueError):
            pipeline_ick.connect([""])
        with pytest.raises(ValueError):
            pipeline_icst.connect([""])
        with pytest.raises(ValueError):
            pipeline_icsq.connect([""])
        with pytest.raises(ValueError):
            pipeline_icsqk.connect([""])
        with pytest.raises(ValueError):
            pipeline_icstq.connect([""])
        with pytest.raises(ValueError):
            pipeline_icstqk.connect([""])

        with pytest.raises(RuntimeError):
            pipeline_ick.connect(["DummyTask"])
        with pytest.raises(RuntimeError):
            pipeline_icsqk.connect(["DummyTask"])
        with pytest.raises(RuntimeError):
            pipeline_icstqk.connect(["DummyTask"])

    def test_start(
        self,
        pipeline_i: pixie16.pipeline.Pipeline,
        pipeline_ic: pixie16.pipeline.Pipeline,
        pipeline_is: pixie16.pipeline.Pipeline,
        pipeline_it: pixie16.pipeline.Pipeline,
        pipeline_iq: pixie16.pipeline.Pipeline,
        pipeline_ik: pixie16.pipeline.Pipeline,
        pipeline_ics: pixie16.pipeline.Pipeline,
        pipeline_ict: pixie16.pipeline.Pipeline,
        pipeline_icq: pixie16.pipeline.Pipeline,
        pipeline_ick: pixie16.pipeline.Pipeline,
        pipeline_icst: pixie16.pipeline.Pipeline,
        pipeline_icsq: pixie16.pipeline.Pipeline,
        pipeline_icsqk: pixie16.pipeline.Pipeline,
        pipeline_icstq: pixie16.pipeline.Pipeline,
        pipeline_icstqk: pixie16.pipeline.Pipeline,
    ):
        pipeline_i.start()
        pipeline_ic.start()
        pipeline_is.start()
        pipeline_it.start()
        pipeline_iq.start()
        pipeline_ik.start()
        pipeline_ics.start()
        pipeline_ict.start()
        pipeline_icq.start()
        pipeline_ick.start()
        pipeline_icst.start()
        pipeline_icsq.start()
        pipeline_icsqk.start()
        pipeline_icstq.start()
        pipeline_icstqk.start()

    def test_stop(
        self,
        pipeline_i: pixie16.pipeline.Pipeline,
        pipeline_ic: pixie16.pipeline.Pipeline,
        pipeline_is: pixie16.pipeline.Pipeline,
        pipeline_it: pixie16.pipeline.Pipeline,
        pipeline_iq: pixie16.pipeline.Pipeline,
        pipeline_ik: pixie16.pipeline.Pipeline,
        pipeline_ics: pixie16.pipeline.Pipeline,
        pipeline_ict: pixie16.pipeline.Pipeline,
        pipeline_icq: pixie16.pipeline.Pipeline,
        pipeline_ick: pixie16.pipeline.Pipeline,
        pipeline_icst: pixie16.pipeline.Pipeline,
        pipeline_icsq: pixie16.pipeline.Pipeline,
        pipeline_icsqk: pixie16.pipeline.Pipeline,
        pipeline_icstq: pixie16.pipeline.Pipeline,
        pipeline_icstqk: pixie16.pipeline.Pipeline,
    ):
        pipeline_i.stop()
        pipeline_ic.stop()
        pipeline_is.stop()
        pipeline_it.stop()
        pipeline_iq.stop()
        pipeline_ik.stop()
        pipeline_ics.stop()
        pipeline_ict.stop()
        pipeline_icq.stop()
        pipeline_ick.stop()
        pipeline_icst.stop()
        pipeline_icsq.stop()
        pipeline_icsqk.stop()
        pipeline_icstq.stop()
        pipeline_icstqk.stop()

    def test_quit(
        self,
        pipeline_i: pixie16.pipeline.Pipeline,
        pipeline_ic: pixie16.pipeline.Pipeline,
        pipeline_is: pixie16.pipeline.Pipeline,
        pipeline_it: pixie16.pipeline.Pipeline,
        pipeline_iq: pixie16.pipeline.Pipeline,
        pipeline_ik: pixie16.pipeline.Pipeline,
        pipeline_ics: pixie16.pipeline.Pipeline,
        pipeline_ict: pixie16.pipeline.Pipeline,
        pipeline_icq: pixie16.pipeline.Pipeline,
        pipeline_ick: pixie16.pipeline.Pipeline,
        pipeline_icst: pixie16.pipeline.Pipeline,
        pipeline_icsq: pixie16.pipeline.Pipeline,
        pipeline_icsqk: pixie16.pipeline.Pipeline,
        pipeline_icstq: pixie16.pipeline.Pipeline,
        pipeline_icstqk: pixie16.pipeline.Pipeline,
    ):
        pipeline_i.quit()
        pipeline_ic.quit()
        pipeline_is.quit()
        pipeline_it.quit()
        pipeline_iq.quit()
        pipeline_ik.quit()
        pipeline_ics.quit()
        pipeline_ict.quit()
        pipeline_icq.quit()
        pipeline_ick.quit()
        pipeline_icst.quit()
        pipeline_icsq.quit()
        pipeline_icsqk.quit()
        pipeline_icstq.quit()
        pipeline_icstqk.quit()

    def test_kill(
        self,
        pipeline_i: pixie16.pipeline.Pipeline,
        pipeline_ic: pixie16.pipeline.Pipeline,
        pipeline_is: pixie16.pipeline.Pipeline,
        pipeline_it: pixie16.pipeline.Pipeline,
        pipeline_iq: pixie16.pipeline.Pipeline,
        pipeline_ik: pixie16.pipeline.Pipeline,
        pipeline_ics: pixie16.pipeline.Pipeline,
        pipeline_ict: pixie16.pipeline.Pipeline,
        pipeline_icq: pixie16.pipeline.Pipeline,
        pipeline_ick: pixie16.pipeline.Pipeline,
        pipeline_icst: pixie16.pipeline.Pipeline,
        pipeline_icsq: pixie16.pipeline.Pipeline,
        pipeline_icsqk: pixie16.pipeline.Pipeline,
        pipeline_icstq: pixie16.pipeline.Pipeline,
        pipeline_icstqk: pixie16.pipeline.Pipeline,
    ):
        pipeline_i.kill()
        pipeline_ic.kill()
        pipeline_is.kill()
        pipeline_it.kill()
        pipeline_iq.kill()
        pipeline_ik.kill()
        pipeline_ics.kill()
        pipeline_ict.kill()
        pipeline_icq.kill()
        pipeline_ick.kill()
        pipeline_icst.kill()
        pipeline_icsq.kill()
        pipeline_icsqk.kill()
        pipeline_icstq.kill()
        pipeline_icstqk.kill()

    def test_configure(
        self,
        pipeline_i: pixie16.pipeline.Pipeline,
        pipeline_ic: pixie16.pipeline.Pipeline,
        pipeline_is: pixie16.pipeline.Pipeline,
        pipeline_it: pixie16.pipeline.Pipeline,
        pipeline_iq: pixie16.pipeline.Pipeline,
        pipeline_ik: pixie16.pipeline.Pipeline,
        pipeline_ics: pixie16.pipeline.Pipeline,
        pipeline_ict: pixie16.pipeline.Pipeline,
        pipeline_icq: pixie16.pipeline.Pipeline,
        pipeline_ick: pixie16.pipeline.Pipeline,
        pipeline_icst: pixie16.pipeline.Pipeline,
        pipeline_icsq: pixie16.pipeline.Pipeline,
        pipeline_icsqk: pixie16.pipeline.Pipeline,
        pipeline_icstq: pixie16.pipeline.Pipeline,
        pipeline_icstqk: pixie16.pipeline.Pipeline,
    ):
        pipeline_i.configure({"hello": "hello"})
        pipeline_ic.configure({"hello": "hello"})
        pipeline_is.configure({"hello": "hello"})
        pipeline_it.configure({"hello": "hello"})
        pipeline_iq.configure({"hello": "hello"})
        pipeline_ik.configure({"hello": "hello"})
        pipeline_ics.configure({"hello": "hello"})
        pipeline_ict.configure({"hello": "hello"})
        pipeline_icq.configure({"hello": "hello"})
        pipeline_ick.configure({"hello": "hello"})
        pipeline_icst.configure({"hello": "hello"})
        pipeline_icsq.configure({"hello": "hello"})
        pipeline_icsqk.configure({"hello": "hello"})
        pipeline_icstq.configure({"hello": "hello"})
        pipeline_icstqk.configure({"hello": "hello"})

    def test_poll(
        self,
        pipeline_i: pixie16.pipeline.Pipeline,
        pipeline_ic: pixie16.pipeline.Pipeline,
        pipeline_is: pixie16.pipeline.Pipeline,
        pipeline_it: pixie16.pipeline.Pipeline,
        pipeline_iq: pixie16.pipeline.Pipeline,
        pipeline_ik: pixie16.pipeline.Pipeline,
        pipeline_ics: pixie16.pipeline.Pipeline,
        pipeline_ict: pixie16.pipeline.Pipeline,
        pipeline_icq: pixie16.pipeline.Pipeline,
        pipeline_ick: pixie16.pipeline.Pipeline,
        pipeline_icst: pixie16.pipeline.Pipeline,
        pipeline_icsq: pixie16.pipeline.Pipeline,
        pipeline_icsqk: pixie16.pipeline.Pipeline,
        pipeline_icstq: pixie16.pipeline.Pipeline,
        pipeline_icstqk: pixie16.pipeline.Pipeline,
    ):
        pipeline_i.poll()
        pipeline_ic.poll()
        pipeline_is.poll()
        pipeline_it.poll()
        pipeline_iq.poll()
        pipeline_ik.poll()
        pipeline_ics.poll()
        pipeline_ict.poll()
        pipeline_icq.poll()
        pipeline_ick.poll()
        pipeline_icst.poll()
        pipeline_icsq.poll()
        pipeline_icsqk.poll()
        pipeline_icstq.poll()
        pipeline_icstqk.poll()
        pipeline_i.poll()
        pipeline_ic.poll()
        pipeline_is.poll()
        pipeline_it.poll()
        pipeline_iq.poll()
        pipeline_ik.poll()
        pipeline_ics.poll()
        pipeline_ict.poll()
        pipeline_icq.poll()
        pipeline_ick.poll()
        pipeline_icst.poll()
        pipeline_icsq.poll()
        pipeline_icsqk.poll()
        pipeline_icstq.poll()
        pipeline_icstqk.poll()
        pipeline_i.poll()
        pipeline_ic.poll()
        pipeline_is.poll()
        pipeline_it.poll()
        pipeline_iq.poll()
        pipeline_ik.poll()
        pipeline_ics.poll()
        pipeline_ict.poll()
        pipeline_icq.poll()
        pipeline_ick.poll()
        pipeline_icst.poll()
        pipeline_icsq.poll()
        pipeline_icsqk.poll()
        pipeline_icstq.poll()
        pipeline_icstqk.poll()
        pipeline_i.poll()
        pipeline_ic.poll()
        pipeline_is.poll()
        pipeline_it.poll()
        pipeline_iq.poll()
        pipeline_ik.poll()
        pipeline_ics.poll()
        pipeline_ict.poll()
        pipeline_icq.poll()
        pipeline_ick.poll()
        pipeline_icst.poll()
        pipeline_icsq.poll()
        pipeline_icsqk.poll()
        pipeline_icstq.poll()
        pipeline_icstqk.poll()
        pipeline_i.poll()
        pipeline_ic.poll()
        pipeline_is.poll()
        pipeline_it.poll()
        pipeline_iq.poll()
        pipeline_ik.poll()
        pipeline_ics.poll()
        pipeline_ict.poll()
        pipeline_icq.poll()
        pipeline_ick.poll()
        pipeline_icst.poll()
        pipeline_icsq.poll()
        pipeline_icsqk.poll()
        pipeline_icstq.poll()
        pipeline_icstqk.poll()
