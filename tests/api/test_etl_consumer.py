import asyncio
import importlib
import sys
from types import SimpleNamespace


class Message:
    def __init__(self):
        self.retries = 0

    def retry(self):
        self.retries += 1


def consumer_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "workers", SimpleNamespace(WorkerEntrypoint=object))
    return importlib.import_module("etl_consumer")


def test_queue_retries_failed_message_and_recovers(monkeypatch):
    consumer = consumer_module(monkeypatch)
    consumer._cb_record_success()
    handled = []

    async def handle(env, message):
        handled.append(message)
        if len(handled) == 1:
            raise RuntimeError("temporary AI failure")

    monkeypatch.setattr(consumer, "handle_queue_message", handle)
    first, second = Message(), Message()
    worker = consumer.Default()
    asyncio.run(worker.queue(SimpleNamespace(messages=[first, second]), env=object()))
    assert first.retries == 1
    assert second.retries == 0
    assert consumer._CB_FAILURE_COUNT == 0


def test_open_circuit_retries_without_processing(monkeypatch):
    consumer = consumer_module(monkeypatch)
    consumer._CB_FAILURE_COUNT = consumer.CIRCUIT_OPEN_THRESHOLD
    consumer._CB_OPEN_AT = consumer.time.time()
    handled = []

    async def handle(env, message):
        handled.append(message)

    monkeypatch.setattr(consumer, "handle_queue_message", handle)
    message = Message()
    asyncio.run(consumer.Default().queue(SimpleNamespace(messages=[message]), env=object()))
    assert handled == []
    assert message.retries == 1
    consumer._cb_record_success()
