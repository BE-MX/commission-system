"""Input-only isolated process. Run: python -m app.commerce_shadow.cli --help.

Bootstrap runs before ANY domain/database imports. Inherited environment and
backend/.env are not configuration sources; only a restricted target URL and
an immutable input bundle are accepted. No source Session is constructed.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from functools import lru_cache


def _bootstrap(target_url, output_directory, bank_profile=None):
    # This clears ONLY this dedicated child process, never the calling shell.
    # Do not read/copy the inherited environment (including proxies/secrets).
    os.environ.clear()
    safe_environment = {"PYTHONUTF8": "1"}
    if sys.platform == "win32":
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer)):
            safe_environment.update(SYSTEMROOT=buffer.value, WINDIR=buffer.value)
    os.environ.update(safe_environment)
    from app.core import config

    class IsolatedSettings(config.Settings):
        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
            return (init_settings,)

    values = {name: field.get_default(call_default_factory=True) for name, field in config.Settings.model_fields.items()
              if not field.is_required()}
    for name, value in list(values.items()):
        upper = name.upper()
        if isinstance(value, bool):
            values[name] = False
        if isinstance(value, (str, dict, list)) and any(marker in upper for marker in ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "ENCRYPTION_KEY", "HASH_KEY")):
            values[name] = {} if isinstance(value, dict) else [] if isinstance(value, list) else ""
        if upper.endswith(("_STORAGE_ROOT", "_CACHE_ROOT")):
            values[name] = str(output_directory / "isolated-files")
    values.update(APP_ENV="development", COMMERCE_PHASE="local_only", TRANSACTION_MODE="local",
        COMMERCE_SHADOW_ENABLED=False, COMMERCE_SHADOW_WORKER_ENABLED=True, COMMERCE_SHADOW_EXECUTION_ONLY=True,
        COMMERCE_SHADOW_DATABASE_URL=target_url, COMMISSION_DB_HOST="shadow-disabled.invalid", COMMISSION_DB_PORT=3306,
        COMMISSION_DB_USER="inert-shadow", COMMISSION_DB_PASSWORD="", COMMISSION_DB_NAME="commerce_shadow_inert",
        BUSINESS_DB_NAME="commerce_shadow_no_mirror", COS_ENABLED_DOMAINS=[], COS_MANAGED_DOMAINS=[],
        SCHEDULER_ENABLED=False, RECEIPT_SYNC_ENABLED=False)
    if bank_profile:
        values.update(COMMERCE_RECEIVING_ENTITY_KEY=bank_profile[0], COMMERCE_BANK_CHANNEL=bank_profile[1])
    settings = IsolatedSettings(_env_file=None, **values)
    if any(getattr(settings, name) for name, value in values.items() if isinstance(value, (str, dict, list))
            and any(marker in name for marker in ("PASSWORD", "SECRET", "API_KEY", "ENCRYPTION_KEY", "HASH_KEY"))):
        raise ValueError("isolated worker settings retained external credentials")

    @lru_cache
    def isolated_settings():
        return settings

    # Process-local dependency injection, before app.core.database/domain import.
    # The public configuration module/file is not modified.
    config.get_settings = isolated_settings
    return settings, tuple(safe_environment)


def _deny_http(*args, **kwargs):
    raise RuntimeError("HTTP is unavailable in the isolated commerce worker")


def _restrict_http():
    import httpx
    from importlib.util import find_spec
    if find_spec("requests") is not None:
        import requests
        requests.sessions.Session.request = _deny_http
    httpx.Client.send = _deny_http
    httpx.AsyncClient.send = _deny_http


def _target_engine(url):
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        if not parsed.database or parsed.database == ":memory:":
            raise ValueError("isolated target must be a persistent SQLite file")
        candidate = Path(parsed.database).resolve()
        if not candidate.is_file() or not candidate.name.lower().startswith(("shadow", "commerce_shadow", "ark_shadow", "candidate", "test_")):
            raise ValueError("isolated SQLite target must be an explicitly prepared candidate file")
    elif parsed.get_backend_name() == "mysql":
        if not (parsed.database or "").startswith(("commerce_shadow_", "ark_shadow_", "test_")):
            raise ValueError("isolated target schema name is not allowed")
        if not (parsed.username or "").startswith("shadow_") or not parsed.password:
            raise ValueError("isolated MySQL target requires a dedicated shadow_ user")
    else:
        raise ValueError("unsupported isolated target driver")
    engine = create_engine(parsed, hide_parameters=True, pool_pre_ping=True)
    if parsed.get_backend_name() == "sqlite":
        @event.listens_for(engine, "connect")
        def collation(connection, _record):
            connection.create_collation("utf8mb4_unicode_ci", lambda left, right:
                (left.casefold() > right.casefold()) - (left.casefold() < right.casefold()))
            # SQLite may spill index/RETURNING work to a temp file. The child
            # intentionally has no inherited TEMP/USERPROFILE; keep scratch
            # pages private in memory rather than reaching outside its target.
            connection.execute("PRAGMA temp_store=MEMORY")
    else:
        @event.listens_for(engine, "connect")
        def timezone(connection, _record):
            with connection.cursor() as cursor:
                cursor.execute("SET time_zone = '+08:00'")
        with engine.connect() as connection:
            grants = connection.exec_driver_sql("SHOW GRANTS FOR CURRENT_USER").scalars().all()
            target = f"`{parsed.database}`."
            for grant in grants:
                text = grant.upper()
                if " WITH GRANT OPTION" in text:
                    raise ValueError("isolated MySQL credentials cannot grant privileges")
                if text.startswith("GRANT USAGE ON *.*"):
                    continue
                if " WITH GRANT OPTION" in text or " ON " not in text or target.upper() not in text.split(" ON ", 1)[1].split(" TO ", 1)[0]:
                    raise ValueError("isolated MySQL credentials have privileges outside the target")
    return engine


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--audit-settings", action="store_true")
    args = parser.parse_args(argv)
    destination = args.report.resolve().parent if args.report else Path.cwd()
    bundle, bank_profile = None, None
    if not args.audit_settings:
        if not args.input or not args.report or args.input.resolve() == args.report.resolve():
            parser.error("distinct --input and --report paths are required")
        if args.input.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("input bundle exceeds bounded worker size")
        bundle = json.loads(args.input.read_text(encoding="utf-8"))
        profiles = {(row["subject_key"], row["channel"]) for row in bundle.get("checkpoint", {}).get("bank_domains", [])}
        if len(profiles) > 1:
            raise ValueError("a worker dataset requires one explicit receiving subject/channel profile")
        bank_profile = next(iter(profiles), None)
    settings, safe_environment = _bootstrap(args.target_url, destination, bank_profile)
    _restrict_http()
    if args.audit_settings:
        print(json.dumps({"execution_only": settings.COMMERCE_SHADOW_EXECUTION_ONLY,
            "scheduler_enabled": settings.SCHEDULER_ENABLED, "source_credentials_present": False,
            "external_credentials_present": False, "backend_env_loaded": False,
            "process_environment_keys": list(safe_environment)}, ensure_ascii=False))
        return 0
    engine = _target_engine(args.target_url)
    try:
        from app.commerce_shadow.transport import execute_input_bundle
        result = execute_input_bundle(engine, bundle)
        pending = args.report.with_name(args.report.name + ".pending")
        pending.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        pending.replace(args.report)
        return 2 if result["missing_dependencies"] else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Isolated commerce worker interrupted; committed receipts remain retryable", file=sys.stderr, flush=True)
        raise SystemExit(130)
    except Exception as failure:
        # Never print URLs, SQL parameters or inherited environment values.
        print(f"Isolated commerce worker failed ({type(failure).__name__})", file=sys.stderr, flush=True)
        raise SystemExit(1)
