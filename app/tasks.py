"""
Lightweight background tasks using threading.

No external broker (Celery / Redis) required — tasks run in daemon threads.
"""

import logging
import threading

logger = logging.getLogger(__name__)

# Simple lock to prevent concurrent backfill runs
_backfill_lock = threading.Lock()


def run_backfill_async(app):
    """
    Process pending backfill queue items and recompute snapshots for all
    affected users in a background thread.

    Safe to call repeatedly — a lock ensures only one backfill runs at a time.
    If a backfill is already running, the call is silently skipped.
    """
    if not _backfill_lock.acquire(blocking=False):
        logger.info("[tasks] Backfill already running, skipping.")
        return

    def _run():
        try:
            with app.app_context():
                from app.market.services import process_backfill_queue
                from app.portfolio.services import compute_snapshots
                from app.models import Transaction

                result = process_backfill_queue()
                processed = result.get("processed", 0)

                if processed > 0:
                    # Recompute snapshots for every user who has transactions
                    user_ids = [
                        uid
                        for (uid,) in Transaction.query.with_entities(
                            Transaction.user_id
                        )
                        .distinct()
                        .all()
                    ]
                    for uid in user_ids:
                        try:
                            compute_snapshots(uid)
                        except Exception as e:
                            logger.error(
                                "[tasks] snapshot recompute failed for user %d: %s",
                                uid,
                                e,
                            )

                logger.info("[tasks] Backfill done — %d item(s) processed.", processed)
        except Exception as e:
            logger.error("[tasks] Backfill failed: %s", e)
        finally:
            _backfill_lock.release()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
