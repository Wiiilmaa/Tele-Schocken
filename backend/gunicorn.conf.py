"""
Gunicorn configuration for Tele-Schocken.

Runs DB migrations inside the gevent worker where the database
connection actually works (avoids caching_sha2_password auth issues
that occur outside the worker context).
"""
import sys


def post_worker_init(worker):
    """Run pending DB migrations after the gevent worker is fully initialised."""
    print("[gunicorn.conf] post_worker_init: starting DB migration...", file=sys.stderr, flush=True)
    try:
        from teleschocken import app
        from flask_migrate import upgrade

        print("[gunicorn.conf] Flask app imported, running upgrade...", file=sys.stderr, flush=True)
        with app.app_context():
            upgrade()
        print("[gunicorn.conf] DB migration completed successfully.", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[gunicorn.conf] DB migration failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
