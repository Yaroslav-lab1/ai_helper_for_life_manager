from __future__ import annotations

import asyncio
import logging

from backend.billing.service import due_subscription_ids, process_due_subscription
from backend.billing.yookassa_client import get_billing_client
from backend.config import settings
from backend.database import SessionLocal

logger = logging.getLogger(__name__)


def run_subscription_cycle() -> int:
    with SessionLocal() as db:
        identifiers = due_subscription_ids(db)
    processed = 0
    for subscription_id in identifiers:
        with SessionLocal() as db:
            try:
                processed += int(process_due_subscription(db, subscription_id, get_billing_client()))
            except Exception:
                db.rollback()
                logger.exception("Subscription renewal failed (%s)", subscription_id)
    return processed


class SubscriptionWorker:
    def __init__(self) -> None:
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(run_subscription_cycle)
            except Exception:
                logger.exception("Subscription worker cycle failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=settings.subscription_worker_poll_interval_seconds
                )
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()
