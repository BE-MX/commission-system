"""Hold the shared MySQL release lock until the parent activation finishes."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))


def main():
    from sqlalchemy import create_engine, text
    from app.core.config import get_settings
    engine = create_engine(get_settings().commission_db_url, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as connection:
            if connection.execute(text("SELECT GET_LOCK('leshine-schema-release',0)")).scalar() != 1:
                raise RuntimeError("Database release lock is held")
            try:
                print("READY", flush=True)
                sys.stdin.readline()
            finally:
                connection.execute(text("SELECT RELEASE_LOCK('leshine-schema-release')"))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("LOCK_FAILED:" + type(error).__name__, flush=True)
        sys.exit(1)
