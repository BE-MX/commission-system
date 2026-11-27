"""Current authority reads at write boundaries and nonlocking reads for display."""


def authority_query(db, *entities, lock, shared=False):
    query = db.query(*entities).populate_existing()
    return query.with_for_update(read=shared) if lock else query
