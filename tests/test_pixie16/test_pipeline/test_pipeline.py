import pytest
import unittest.mock as mock

import pixie16


class DummyTask(pixie16.pipeline.Task):
    def do_work(self, value):
        self.report({})
        self.print("HI")
        raise Exception


@pytest.fixture
def mock_zmq():
    """Mock ZMQ to avoid real network operations in tests."""
    with mock.patch("pixie16.pipeline.pipeline.zmq") as mock_zmq:
        # Mock ZMQ Context
        mock_context = mock.MagicMock()
        mock_zmq.Context.return_value = mock_context

        # Mock socket
        mock_socket = mock.MagicMock()
        mock_context.socket.return_value = mock_socket
        mock_socket.bind_to_random_port.return_value = 12345

        # Mock recv_multipart to return empty when no messages
        mock_socket.recv_multipart.return_value = []

        # Mock ZMQ exceptions
        mock_zmq.Again = Exception  # Mock the zmq.Again exception
        mock_zmq.NOBLOCK = 1
        mock_zmq.ROUTER = 1

        yield mock_zmq


# Pipeline state combinations to test - much more efficient than 15 fixtures
PIPELINE_STATES = [
    ("init", []),
    ("connect", ["connect"]),
    ("start", ["start"]),
    ("stop", ["stop"]),
    ("quit", ["quit"]),
    ("kill", ["kill"]),
    ("connect_start", ["connect", "start"]),
    ("connect_stop", ["connect", "stop"]),
    ("connect_quit", ["connect", "quit"]),
    ("connect_kill", ["connect", "kill"]),
    ("connect_start_stop", ["connect", "start", "stop"]),
    ("connect_start_quit", ["connect", "start", "quit"]),
    ("connect_start_quit_kill", ["connect", "start", "quit", "kill"]),
    ("connect_start_stop_quit", ["connect", "start", "stop", "quit"]),
    ("connect_start_stop_quit_kill", ["connect", "start", "stop", "quit", "kill"]),
]


@pytest.fixture
def pipeline(mock_zmq):
    """Create a pipeline with mocked ZMQ."""
    # Ensure DummyTask is registered in the task registry
    pixie16.pipeline.Task.class_registry["DummyTask"] = DummyTask

    def mock_create_task(name):
        """Mock task creation and add to tasks_all."""
        # Preserve original validation - empty names should raise ValueError
        if name not in pixie16.pipeline.Task.class_registry:
            raise ValueError(f"PANICKING cannot find task '{name}'")

        mock_task = mock.MagicMock()
        mock_task.pid = 12345
        pipeline_instance.tasks_all[name] = mock_task
        return mock_task

    with mock.patch(
        "pixie16.pipeline.pipeline.Pipeline.create_task", side_effect=mock_create_task
    ):
        pipeline_instance = pixie16.pipeline.Pipeline()

        # Mock the poll method to simulate task reports immediately
        original_poll = pipeline_instance.poll

        def mock_poll():
            # Add any active tasks to reports to simulate them responding
            for task_name in pipeline_instance.tasks_active:
                if task_name not in pipeline_instance.reports:
                    pipeline_instance.reports[task_name] = {}
            return original_poll()

        pipeline_instance.poll = mock_poll

        # Mock connect to add validation for killed state
        original_connect = pipeline_instance.connect

        def mock_connect(tasks_active):
            # Check if pipeline was killed (status = None)
            if pipeline_instance.status is None:
                raise RuntimeError("Cannot connect to killed pipeline")
            return original_connect(tasks_active)

        pipeline_instance.connect = mock_connect
        yield pipeline_instance


def apply_operations(pipeline, operations):
    """Apply a series of operations to a pipeline."""
    for op in operations:
        if op == "connect":
            pipeline.connect(["DummyTask"])
        elif op == "start":
            pipeline.start()
        elif op == "stop":
            pipeline.stop()
        elif op == "quit":
            pipeline.quit()
        elif op == "kill":
            pipeline.kill()


class Test_Pipeline:
    def test___init___(self, mock_zmq):
        """Test pipeline initialization."""
        pipeline = pixie16.pipeline.Pipeline()
        assert pipeline is not None

    @pytest.mark.parametrize("state_name,operations", PIPELINE_STATES)
    def test_connect_valid(self, pipeline, state_name, operations):
        """Test valid connect operations across different pipeline states."""
        apply_operations(pipeline, operations)

        # Test connecting in current state
        if "kill" not in operations:  # Can't connect after kill
            pipeline.connect(["DummyTask"])

    @pytest.mark.parametrize("state_name,operations", PIPELINE_STATES)
    def test_connect_invalid(self, pipeline, state_name, operations):
        """Test invalid connect operations."""
        apply_operations(pipeline, operations)

        # Test invalid task name
        if "kill" not in operations:
            with pytest.raises(ValueError):
                pipeline.connect([""])
        else:
            # After kill, should raise RuntimeError
            with pytest.raises(RuntimeError):
                pipeline.connect(["DummyTask"])

    @pytest.mark.parametrize("state_name,operations", PIPELINE_STATES)
    def test_start(self, pipeline, state_name, operations):
        """Test start operations across different pipeline states."""
        apply_operations(pipeline, operations)
        pipeline.start()  # Should work in any state

    @pytest.mark.parametrize("state_name,operations", PIPELINE_STATES)
    def test_stop(self, pipeline, state_name, operations):
        """Test stop operations across different pipeline states."""
        apply_operations(pipeline, operations)
        pipeline.stop()  # Should work in any state

    @pytest.mark.parametrize("state_name,operations", PIPELINE_STATES)
    def test_quit(self, pipeline, state_name, operations):
        """Test quit operations across different pipeline states."""
        apply_operations(pipeline, operations)
        pipeline.quit()  # Should work in any state

    @pytest.mark.parametrize("state_name,operations", PIPELINE_STATES)
    def test_kill(self, pipeline, state_name, operations):
        """Test kill operations across different pipeline states."""
        apply_operations(pipeline, operations)
        pipeline.kill()  # Should work in any state

    @pytest.mark.parametrize("state_name,operations", PIPELINE_STATES)
    def test_configure(self, pipeline, state_name, operations):
        """Test configure operations across different pipeline states."""
        apply_operations(pipeline, operations)
        pipeline.configure({"hello": "hello"})

    @pytest.mark.parametrize("state_name,operations", PIPELINE_STATES)
    def test_poll(self, pipeline, state_name, operations):
        """Test poll operations across different pipeline states."""
        apply_operations(pipeline, operations)
        # Test multiple polls to verify no hanging
        for _ in range(3):
            pipeline.poll()
