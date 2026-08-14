"""Small Mem0 V3 REST client with bounded retries and event polling."""

import json
import random
import time
import urllib.error
import urllib.request


SEARCH_TOP_K = 5
SEARCH_THRESHOLD = 0.4


class SyncError(RuntimeError):
    pass


class RetryableSyncError(SyncError):
    pass


class Mem0Client(object):
    def __init__(self, api_key, base_url, retry_attempts=4):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.retry_attempts = int(retry_attempts)

    def request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": "Token %s" % self.api_key,
                "Content-Type": "application/json",
                "User-Agent": "leshine-claude-mem-sync/1",
            },
        )
        last_error = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read()
                    return json.loads(raw.decode("utf-8")) if raw else {}
            except urllib.error.HTTPError as error:
                if error.code not in (408, 425, 429) and error.code < 500:
                    raise SyncError("Mem0 HTTP %s" % error.code)
                last_error = "Mem0 HTTP %s" % error.code
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = "Mem0 network error: %s" % error.__class__.__name__
            if attempt < self.retry_attempts:
                time.sleep(min(8.0, (2 ** (attempt - 1)) + random.random()))
        raise RetryableSyncError(last_error or "Mem0 request failed")

    def source_exists(self, user_id, unique_source_key):
        response = self.request(
            "POST",
            "/v3/memories/search/",
            {
                "query": unique_source_key,
                "filters": {
                    "AND": [
                        {"user_id": user_id},
                        {"metadata": {"source_key": unique_source_key}},
                    ]
                },
                "top_k": 1,
                "threshold": 0.0,
                "rerank": False,
            },
        )
        for result in response.get("results", []):
            if result.get("metadata", {}).get("source_key") == unique_source_key:
                return True
        return False

    def add(self, user_id, unique_source_key, text, metadata):
        return self.request(
            "POST",
            "/v3/memories/add/",
            {
                "messages": [{"role": "user", "content": text}],
                "user_id": user_id,
                "run_id": unique_source_key,
                "metadata": metadata,
                "infer": False,
            },
        )

    def event_status(self, event_id):
        response = self.request("GET", "/v1/event/%s/" % event_id)
        status = response.get("status")
        if not status and isinstance(response.get("event"), dict):
            status = response["event"].get("status")
        return str(status or "UNKNOWN").upper()

    def search(self, query, user_id, project=None):
        filters = {"user_id": user_id}
        if project:
            filters = {
                "AND": [
                    {"user_id": user_id},
                    {"metadata": {"project": project}},
                ]
            }
        return self.request(
            "POST",
            "/v3/memories/search/",
            {
                "query": query,
                "filters": filters,
                "top_k": SEARCH_TOP_K,
                "threshold": SEARCH_THRESHOLD,
                "rerank": True,
            },
        ).get("results", [])


def wait_for_event(client, event_id, attempts):
    for attempt in range(1, int(attempts) + 1):
        status = client.event_status(event_id)
        if status == "SUCCEEDED":
            return
        if status == "FAILED":
            raise SyncError("Mem0 event failed")
        if attempt < int(attempts):
            time.sleep(min(5.0, 0.5 * attempt))
    raise RetryableSyncError("Mem0 event still pending")
