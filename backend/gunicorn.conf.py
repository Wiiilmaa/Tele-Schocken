"""
Gunicorn configuration for Tele-Schocken.

Runs DB migrations inside the gevent worker where the database
connection actually works (avoids caching_sha2_password auth issues
that occur outside the worker context).
"""


def post_worker_init(worker):
    """Run pending DB migrations after the gevent worker is fully initialised."""
    from flask_migrate import upgrade
    from app import app

    with app.app_context():
        try:
            upgrade()
            worker.log.info("DB migration completed successfully.")
        except Exception as e:
            worker.log.warning("DB migration skipped or failed: %s", e)
