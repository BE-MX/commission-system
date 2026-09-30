"""Bounded fair scans for background queues with permanently blocked rows."""

_cursors = {}


def take(query, identity_column, key, limit):
    """Advance the scan even if selected jobs remain eligible after processing."""
    cursor = _cursors.get(key, 0)
    ids = [identity for (identity,) in query.filter(identity_column > cursor).order_by(
        identity_column).limit(limit)]
    if len(ids) < limit and cursor:
        ids.extend(identity for (identity,) in query.filter(identity_column <= cursor).order_by(
            identity_column).limit(limit - len(ids)))
    if ids:
        _cursors[key] = ids[-1]
    return ids
