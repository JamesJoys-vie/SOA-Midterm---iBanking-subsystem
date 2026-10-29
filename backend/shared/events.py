"""Event bus on Redis Streams (no separate message broker).

Delivery model: at-least-once.
  * Producer:  XADD events:<type> {type, payload}        (stream trimmed to ~MAXLEN entries)
  * Consumer:  XREADGROUP in a consumer group, XACK only after the handler succeeds.
  * Recovery:  messages left un-acked (consumer crashed / handler raised) are re-claimed with XAUTOCLAIM
               after `reclaim_idle_ms` and handled again  ->  handlers MUST be idempotent.
Redis runs with AOF (appendonly) so streams survive a restart.
"""
import json
import logging
import socket
import threading

import redis

log = logging.getLogger(__name__)

OTP_REQUESTED = "otp.requested"          # payload: {email, full_name, otp, transaction_id, expires_in}
PAYMENT_COMPLETED = "payment.completed"  # payload: {email, full_name, transaction_id, student_id, amount, balance_after}

STREAM_PREFIX = "events:"
MAXLEN = 10_000


def stream_name(event_type: str) -> str:
    return STREAM_PREFIX + event_type


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


def _handle(r, stream, group, messages, handler) -> None:
    for msg_id, fields in messages:
        if not fields:  # entry was trimmed/deleted
            r.xack(stream, group, msg_id)
            continue
        try:
            handler(fields["type"], json.loads(fields["payload"]))
            r.xack(stream, group, msg_id)
        except Exception:
            # left pending -> retried after reclaim_idle_ms. TODO: dead-letter after N deliveries (XPENDING count).
            log.exception("handler failed for %s %s", stream, msg_id)


def consume(r: redis.Redis, group: str, event_types: list[str], handler, consumer: str | None = None,
            block_ms: int = 5000, reclaim_idle_ms: int = 60_000, stop: threading.Event | None = None) -> None:
    """Blocking consume loop. handler(event_type, payload) ; run it in a background thread."""
    consumer = consumer or socket.gethostname()
    streams = {stream_name(t): ">" for t in event_types}
    for s in streams:
        ensure_group(r, s, group)
    while not (stop and stop.is_set()):
        for s in streams:  # 1) take over messages stuck with a crashed consumer
            claimed = r.xautoclaim(s, group, consumer, min_idle_time=reclaim_idle_ms, start_id="0-0", count=10)[1]
            _handle(r, s, group, claimed, handler)
        for s, messages in r.xreadgroup(group, consumer, streams, count=10, block=block_ms) or []:  # 2) new messages
            _handle(r, s, group, messages, handler)
