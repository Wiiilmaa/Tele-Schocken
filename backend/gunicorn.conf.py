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
        from flask_migrate import upgrade, stamp
        from sqlalchemy import text

        with app.app_context():
            # Warm up: establish a connection through Flask-SQLAlchemy first.
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

            # Fix stale alembic_version: if the DB points to a revision
            # that no longer exists in the migration files, reset it to
            # the last known revision before our new migration.
            try:
                result = db.session.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                row = result.fetchone()
                if row:
                    current = row[0]
                    print(f"[gunicorn.conf] Current DB revision: {current}",
                          file=sys.stderr, flush=True)
                db.session.remove()
            except Exception:
                current = None
                db.session.remove()

            # Run Alembic migrations first (table might not exist on fresh DB)
            try:
                upgrade()
                print("[gunicorn.conf] DB migration completed successfully.",
                      file=sys.stderr, flush=True)
            except BaseException as e:
                err_msg = str(e)
                print(f"[gunicorn.conf] DB migration failed: "
                      f"{type(e).__name__}: {err_msg}",
                      file=sys.stderr, flush=True)

                # If the current revision is unknown, stamp to the last
                # known revision and retry.
                if "Can't locate revision" in err_msg or "No such revision" in err_msg:
                    print("[gunicorn.conf] Stale revision detected. "
                          "Stamping DB to '2c71994ad95b' and retrying...",
                          file=sys.stderr, flush=True)
                    try:
                        db.session.execute(
                            text("UPDATE alembic_version SET version_num = '2c71994ad95b'")
                        )
                        db.session.commit()
                        db.session.remove()
                        upgrade()
                        print("[gunicorn.conf] DB migration completed successfully (after stamp).",
                              file=sys.stderr, flush=True)
                    except BaseException as e2:
                        print(f"[gunicorn.conf] DB migration retry failed: "
                              f"{type(e2).__name__}: {e2}",
                              file=sys.stderr, flush=True)
                        import traceback
                        traceback.print_exc(file=sys.stderr)
                        sys.stderr.flush()
                        if isinstance(e2, SystemExit):
                            return
                elif isinstance(e, SystemExit):
                    return

            # Safety net: ensure status ENUM has uppercase NAMES incl. PLAYFINAL.
            # SQLAlchemy 2.0 uses enum NAMES for db.Enum(PEP435Enum).
            # A previous migration may have set lowercase values, so fix both.
            try:
                # Step 1: expand ENUM to include both lowercase and uppercase
                # for mismatched pairs (roundfinish≠ROUNDFINISCH, gamefinish≠GAMEFINISCH)
                db.session.execute(text(
                    "ALTER TABLE game MODIFY COLUMN status "
                    "ENUM('WAITING','STARTED','ROUNDFINISCH','PLAYFINAL','GAMEFINISCH',"
                    "'roundfinish','gamefinish') NULL"
                ))
                # Step 2: convert any lowercase to uppercase NAMES
                db.session.execute(text(
                    "UPDATE game SET status = 'ROUNDFINISCH' WHERE status = 'roundfinish'"
                ))
                db.session.execute(text(
                    "UPDATE game SET status = 'GAMEFINISCH' WHERE status = 'gamefinish'"
                ))
                # Step 3: shrink to final uppercase NAMES only
                db.session.execute(text(
                    "ALTER TABLE game MODIFY COLUMN status "
                    "ENUM('WAITING','STARTED','ROUNDFINISCH','PLAYFINAL','GAMEFINISCH') NULL"
                ))
                db.session.commit()
                db.session.remove()
                print("[gunicorn.conf] Status enum values verified/normalized.",
                      file=sys.stderr, flush=True)
            except Exception as e:
                db.session.rollback()
                db.session.remove()
                print(f"[gunicorn.conf] Status enum fix skipped: {e}",
                      file=sys.stderr, flush=True)

    except BaseException as e:
        print(f"[gunicorn.conf] post_worker_init error: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        if isinstance(e, SystemExit):
            return
