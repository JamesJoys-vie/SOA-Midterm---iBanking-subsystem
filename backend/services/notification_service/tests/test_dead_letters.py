"""shared/events.consume end to end on a real stream: ack on success, retries, dead letters."""
import json
import threading
import time
from shared import events

TYPE = "test.event"
GROUP = "test-group"


def run_consumer(r, handler, until, max_deliveries=3, timeout_s=10):
    """Runs consume() in a thread (no reclaim wait) until `until()` is true; returns whether it got there."""
    stop = threading.Event()
    t = threading.Thread(target=events.consume, daemon=True,
                         kwargs=dict(r=r, group=GROUP, event_types=[TYPE], handler=handler, consumer="c1",
                                     block_ms=50, reclaim_idle_ms=0, max_deliveries=max_deliveries, stop=stop))
    t.start()
    deadline = time.time() + timeout_s
    while time.time() < deadline and not until():
        time.sleep(0.05)
    stop.set()
    t.join(timeout=5)
    return until()


def pending(r) -> int:
    return r.xpending(events.stream_name(TYPE), GROUP)["pending"]


def dead(r) -> list:
    return r.xrange(events.dead_stream_name(TYPE))


def test_success_is_acked(r):
    seen = []
    events.publish(r, TYPE, {"n": 1})
    assert run_consumer(r, lambda t, p, i: seen.append((t, p)), until=lambda: seen)
    assert seen == [(TYPE, {"n": 1})]
    assert pending(r) == 0 and dead(r) == []


def test_handler_gets_the_stream_id(r):
    ids = []
    entry_id = events.publish(r, TYPE, {"n": 1})
    assert run_consumer(r, lambda t, p, i: ids.append(i), until=lambda: ids)
    assert ids == [entry_id]
    assert 0 <= events.message_age_s(entry_id) < 10


def test_always_failing_is_dead_lettered_after_max_deliveries(r):
    calls = []

    def fail(t, p, i):
        calls.append(1)
        raise RuntimeError("smtp down")

    entry_id = events.publish(r, TYPE, {"n": 1})
    assert run_consumer(r, fail, until=lambda: dead(r), max_deliveries=3)
    assert len(calls) == 3
    assert pending(r) == 0
    (_, fields), = dead(r)
    assert fields["source_id"] == entry_id and fields["group"] == GROUP and fields["type"] == TYPE
    assert json.loads(fields["payload"]) == {"n": 1}
    assert "gave up after 3 deliveries" in fields["error"] and "smtp down" in fields["error"]


def test_failure_then_success_is_not_dead_lettered(r):
    calls = []

    def flaky(t, p, i):
        calls.append(1)
        if len(calls) < 2:
            raise events.RetryLater("busy")

    events.publish(r, TYPE, {"n": 1})
    assert run_consumer(r, flaky, until=lambda: len(calls) == 2 and pending(r) == 0)
    assert dead(r) == []


def test_permanent_error_is_dead_lettered_at_once(r):
    calls = []

    def reject(t, p, i):
        calls.append(1)
        raise events.PermanentError("bad payload")

    events.publish(r, TYPE, {"n": 1})
    assert run_consumer(r, reject, until=lambda: dead(r))
    assert len(calls) == 1 and pending(r) == 0
    assert dead(r)[0][1]["error"] == "permanent: bad payload"


def test_undecodable_entry_is_dead_lettered(r):
    calls = []
    r.xadd(events.stream_name(TYPE), {"type": TYPE, "payload": "{not json"})
    assert run_consumer(r, lambda t, p, i: calls.append(1), until=lambda: dead(r))
    assert calls == [] and pending(r) == 0
    assert dead(r)[0][1]["error"].startswith("undecodable entry")


def test_one_poison_message_does_not_block_the_next(r):
    seen = []

    def handler(t, p, i):
        if p["n"] == 1:
            raise RuntimeError("poison")
        seen.append(p["n"])

    events.publish(r, TYPE, {"n": 1})
    events.publish(r, TYPE, {"n": 2})
    assert run_consumer(r, handler, until=lambda: seen and dead(r))
    assert seen == [2] and pending(r) == 0
