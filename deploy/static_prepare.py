"""Prepare independent hosts concurrently; activation remains coordinated/serial."""
from concurrent.futures import ThreadPoolExecutor
import threading

from desktop_events import step
import static_sync


def prepare_all(targets, outputs, state):
    groups = {}
    for index, target in enumerate(targets):
        groups.setdefault(target['host'], []).append((index, target))
    results = [None] * len(targets)
    failed = threading.Event()

    def host_group(items):
        for index, target in items:
            if failed.is_set():
                return
            try:
                # Hosts may publish identical artifacts: keep local tar files
                # isolated so concurrent SCP cannot observe a partial archive.
                results[index] = step('static-prepare:' + target['domain'], '增量准备 ' + target['domain'],
                    static_sync.prepare, outputs[target['component']], target['host'], target['root'],
                    state / str(index), target['domain'])
            except BaseException:
                failed.set()
                raise

    # At most two hosts, sequential targets per host. Executor shutdown waits
    # for already started writes, even on failure; no background staging leaks
    # across the caller's publication lock or into activation.
    with ThreadPoolExecutor(max_workers=min(2, len(groups) or 1)) as pool:
        futures = [pool.submit(host_group, items) for items in groups.values()]
        for future in futures:
            future.result()
    if any(value is None for value in results):
        raise RuntimeError('Static preparation did not complete')
    return results
