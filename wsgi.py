import os

from app import create_app

app = create_app()


# When running outside Gunicorn (e.g. `flask run` in development),
# start the scheduler in the reloader child process only.
if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    from app.scheduler import init_scheduler
    init_scheduler(app)
