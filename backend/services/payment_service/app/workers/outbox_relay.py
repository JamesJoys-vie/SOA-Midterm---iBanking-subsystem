"""Outbox relay: publishes rows of outbox_events to Redis Streams (shared/events.py), then marks them published.

payment.completed -> notification-service sends the "payment successful" email (section 4 of the assignment).
At-least-once: a crash between XADD and the UPDATE re-sends the event; the consumer skips duplicates.
"""
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from shared import events
from app.domain.models import OutboxEvent
from app.workers.periodic import PeriodicWorker

BATCH = 50


class OutboxRelay(PeriodicWorker):
    name = "outbox-relay"

    def __init__(self, session_factory: sessionmaker, redis_client, interval_s: float):
        super().__init__(interval_s)
        self.session_factory, self.redis = session_factory, redis_client

    def run_once(self) -> int:
        with self.session_factory() as db:
            rows = db.scalars(select(OutboxEvent).where(OutboxEvent.published.is_(False))
                              .order_by(OutboxEvent.created_at).limit(BATCH)
                              .with_for_update(skip_locked=True)).all()  # replicas take different rows
            for row in rows:
                events.publish(self.redis, row.type, row.payload)
                row.published = True
            db.commit()
        return len(rows)
