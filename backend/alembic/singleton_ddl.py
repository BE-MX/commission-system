"""Honor explicit singleton CHECKs when compiling MySQL migration DDL.

MySQL 8 rejects an AUTO_INCREMENT column referenced by CHECK(id=1). Older
revisions left SQLAlchemy's implicit integer-PK default in place. Enforce their
explicit singleton intent at the DDL boundary without editing those revisions
or changing already installed tables. Ordinary primary keys are unaffected.
"""
import re
from sqlalchemy import CheckConstraint, Integer, Table, event


def enforce_singleton_primary_key(table, connection, **_kwargs):
    if connection.dialect.name != 'mysql':
        return
    keys = list(table.primary_key.columns)
    if len(keys) != 1 or keys[0].name != 'id' or not isinstance(keys[0].type, Integer):
        return
    explicit = any(isinstance(rule, CheckConstraint) and
        re.fullmatch(r'id\s*=\s*1', str(rule.sqltext).strip().strip('()'), re.IGNORECASE)
        for rule in table.constraints)
    if explicit and keys[0].autoincrement == 'auto':
        keys[0].autoincrement = False


def install():
    if not event.contains(Table, 'before_create', enforce_singleton_primary_key):
        event.listen(Table, 'before_create', enforce_singleton_primary_key)
