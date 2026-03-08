"""Gunicorn configuration — hooks for intraday scheduler."""


def post_fork(server, worker):
    """Start the intraday scheduler in every worker (after fork).

    Each worker gets its own scheduler, but the job itself contains a
    timestamp-based dedup check so only the first worker to fire each
    tick does actual work.  This ensures the scheduler survives worker
    restarts (no dependency on ``worker.age``).
    """
    from wsgi import app
    from app.scheduler import init_scheduler

    init_scheduler(app)
