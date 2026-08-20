"""CLI entry point."""

import logging

from .adapter import DshSdkAdapter
from .client import ArkClient
from .config import WorkerConfig
from .runner import Worker


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = WorkerConfig.from_env()
    config.ensure_runtime_dirs()
    with ArkClient(config) as client:
        Worker(config, client, DshSdkAdapter(config)).serve_forever()


if __name__ == "__main__":
    main()

