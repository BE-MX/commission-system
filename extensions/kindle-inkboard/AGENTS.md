# Kindle Ark Dashboard

- Scope: PW3 firmware 5.15.1.1; battery operation; personal tasks, notes and messages. Usage metering is deferred.
- Keep client code in `client/`, reproducible tools in `scripts/`, tests in `tests/`; downloads, virtualenvs, generated ZIPs and private device backups are ignored.
- Pin Tinta to the revision in `scripts/prepare_runtime.py`. Apply adaptations to generated copies and keep upstream untouched.
- Do not commit credentials, device JSON/Lua configuration, SQLite databases, device identifiers, logs, book files or personal backup manifests.
- Use verified HTTPS and distinguish native device observations from stubbed font/layout tests and isolated service tests.
- Follow the repository deployment entry point and authorization rules for Ark service changes; Git integration is not deployment.
