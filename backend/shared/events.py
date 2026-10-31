"""Event bus on Redis Streams (no separate message broker).

Delivery model: at-least-once.
  * Producer:  XADD events:<type> {type, payload}        (stream trimmed to ~MAXLEN entries)
  * Consumer:  XREADGROUP in a consumer group, XACK only after the handler succeeds.
  * Recovery:  messages left un-acked (consumer crashed / handler raised) are re-claimed with XAUTOCLAIM
               after `reclaim_idle_ms` and handled again  ->  handlers MUST be idempotent.
  * Dead letters: after `max_deliveries` failed attempts, or at once on PermanentError, the entry is copied to
               events:dead:<type> {type, payload, error, source_id, group} and acked, so it stops retrying.
               Inspect with  XRANGE events:dead:<type> - +
Redis runs with AOF (appendonly) so streams survive a restart.
"""
import json
import logging
import socket
import threading
import time

import redis

log = logging.getLogger(__name__)

OTP_REQUESTED = "otp.requested"          # payload: {email, full_name, otp, transaction_id, expires_in}
PAYMENT_COMPLETED = "payment.completed"  # payload: {email, full_name, transaction_id, student_id, amount, balance_after}

STREAM_PREFIX = "events:"
DEAD_PREFIX = "events:dead:"
MAXLEN = 10_000


class PermanentError(Exception):
    """Raised by a handler when retrying can never succeed (bad payload, rejected address) -> dead-letter now."""


class RetryLater(Exception):
    """Raised by a handler for an expected, temporary refusal (e.g. another consumer is busy with it): no traceback."""


def stream_name(event_type: str) -> str:
    return STREAM_PREFIX + event_type


def dead_stream_name(event_type: str) -> str:
    return DEAD_PREFIX + event_type


def message_age_s(msg_id: str) -> float:
    """Seconds since the entry was added (the id starts with the Redis server time in ms)."""
    return time.time() - int(msg_id.split("-")[0]) / 1000


def publish(r: redis.Redis, event_type: str, payload: dict) -> str:
    """Append an event; returns the stream entry id."""
    return r.xadd(stream_name(event_type), {"type": event_type, "payload": json.dumps(payload, default=str)},
                  maxlen=MAXLEN, approximate=True)


def ensure_group(r: redis.Redis, stream: str, group: str) -> None:
    try:
        r.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):  # group already exists -> fine
            raise


def _times_delivered(r, stream, group, msg_id) -> int:
    pending = r.xpending_range(stream, group, min=msg_id, max=msg_id, count=1)
    return pending[0]["times_delivered"] if pending else 1


def _dead_letter(r, stream, group, msg_id, fields, error: str) -> None:
    """Copy the entry to the dead-letter stream and ack it, in one MULTI so it is never lost or doubled."""
    event_type = fields.get("type") or stream[len(STREAM_PREFIX):]
    pipe = r.pipeline(transaction=True)
    pipe.xadd(dead_stream_name(event_type), {**fields, "error": error[:500], "source_id": msg_id, "group": group},
              maxlen=MAXLEN, approximate=True)
    pipe.xack(stream, group, msg_id)
    pipe.execute()
    log.error("dead-lettered %s %s: %s", stream, msg_id, error)


def _handle(r, stream, group, messages, handler, max_deliveries) -> None:
    for msg_id, fields in messages:
        if not fields:  # entry was trimmed/deleted
            r.xack(stream, group, msg_id)
            continue
        try:
            event_type, payload = fields["type"], json.loads(fields["payload"])
        except (KeyError, ValueError) as e:  # not an event this bus wrote -> no retry can fix it
            _dead_letter(r, stream, group, msg_id, fields, f"undecodable entry: {e!r}")
            continue
        try:
            handler(event_type, payload, msg_id)
            r.xack(stream, group, msg_id)
        except PermanentError as e:
            _dead_letter(r, stream, group, msg_id, fields, f"permanent: {e}")
        except Exception as e:
            deliveries = _times_delivered(r, stream, group, msg_id)
            if deliveries >= max_deliveries:
                _dead_letter(r, stream, group, msg_id, fields, f"gave up after {deliveries} deliveries: {e!r}")
            elif isinstance(e, RetryLater):
                log.info("retry later %s %s (delivery %d/%d): %s", stream, msg_id, deliveries, max_deliveries, e)
            else:  # left pending -> retried after reclaim_idle_ms
                log.exception("handler failed for %s %s (delivery %d/%d)", stream, msg_id, deliveries, max_deliveries)


def consume(r: redis.Redis, group: str, event_types: list[str], handler, consumer: str | None = None,
            block_ms: int = 5000, reclaim_idle_ms: int = 60_000, max_deliveries: int = 5,
            stop: threading.Event | None = None) -> None:
    """Blocking consume loop; run it in a background thread.
    handler(event_type, payload, msg_id): return = done (acked); raise = retry later; PermanentError = dead-letter."""
    consumer = consumer or socket.gethostname()
    streams = {stream_name(t): ">" for t in event_types}
    for s in streams:
        ensure_group(r, s, group)
    while not (stop and stop.is_set()):
        for s in streams:  # 1) take over messages stuck with a crashed consumer, or whose handler raised
            claimed = r.xautoclaim(s, group, consumer, min_idle_time=reclaim_idle_ms, start_id="0-0", count=10)[1]
            _handle(r, s, group, claimed, handler, max_deliveries)
        for s, messages in r.xreadgroup(group, consumer, streams, count=10, block=block_ms) or []:  # 2) new messages
            _handle(r, s, group, messages, handler, max_deliveries)
