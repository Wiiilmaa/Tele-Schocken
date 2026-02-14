"""
Gunicorn configuration for Tele-Schocken.

Runs DB migrations inside the gevent worker where the database
connection actually works (avoids caching_sha2_password auth issues
that occur outside the worker context).
"""
import sys
import time


def post_worker_init(worker):
    """Run pending DB migrations after the gevent worker is fully initialised."""
    print("[gunicorn.conf] post_worker_init: starting DB migration...",
          file=sys.stderr, flush=True)
    try:
        from teleschocken import app
        from app import db
        from flask_migrate import upgrade
        from sqlalchemy import text

        with app.app_context():
            # Warm up: establish a connection through Flask-SQLAlchemy first.
            # This primes MySQL's caching_sha2_password cache so that
            # subsequent connections (including Alembic's) use fast-auth.
            for attempt in range(5):
                try:
                    db.session.execute(text("SELECT 1"))
                    db.session.remove()
                    print("[gunicorn.conf] DB warm-up connection succeeded.",
                          file=sys.stderr, flush=True)
                    break
                except Exception as e:
                    wait = 2 * (attempt + 1)
                    print(f"[gunicorn.conf] DB warm-up attempt {attempt+1} failed: {e}  "
                          f"– retrying in {wait}s...",
                          file=sys.stderr, flush=True)
                    db.session.remove()
                    time.sleep(wait)
            else:
                print("[gunicorn.conf] All warm-up attempts failed, "
                      "trying migration anyway...",
                      file=sys.stderr, flush=True)

            # Now run Alembic migrations
            try:
                upgrade()
                print("[gunicorn.conf] DB migration completed successfully.",
                      file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[gunicorn.conf] DB migration failed: "
                      f"{type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc(file=sys.stderr)
                sys.stderr.flush()

    except Exception as e:
        print(f"[gunicorn.conf] post_worker_init error: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
