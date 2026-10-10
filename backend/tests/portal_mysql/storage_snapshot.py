"""Only hashes stored definitions; never returns SQL bodies or definer secrets."""
import hashlib
import json


def stored_objects_snapshot(connection):
    from sqlalchemy import text
    result = []
    queries = (
        ('VIEW', "SELECT TABLE_NAME FROM information_schema.views WHERE TABLE_SCHEMA=DATABASE()"),
        ('TRIGGER', "SELECT TRIGGER_NAME FROM information_schema.triggers WHERE TRIGGER_SCHEMA=DATABASE()"),
        ('EVENT', "SELECT EVENT_NAME FROM information_schema.events WHERE EVENT_SCHEMA=DATABASE()"),
        ('PROCEDURE', "SELECT ROUTINE_NAME FROM information_schema.routines WHERE ROUTINE_SCHEMA=DATABASE() AND ROUTINE_TYPE='PROCEDURE'"),
        ('FUNCTION', "SELECT ROUTINE_NAME FROM information_schema.routines WHERE ROUTINE_SCHEMA=DATABASE() AND ROUTINE_TYPE='FUNCTION'"),
    )
    for kind, query in queries:
        for name in sorted(connection.execute(text(query)).scalars()):
            row = connection.execute(text('SHOW CREATE ' + kind + ' `' + name.replace('`', '``') + '`')).mappings().one()
            # Trigger creation timestamps necessarily change on restore. Its SQL,
            # definer, character sets and modes must still be byte-identical.
            fields = {key: hashlib.sha256(json.dumps(value, ensure_ascii=True, default=str).encode()).hexdigest()
                for key, value in row.items() if key.lower() != 'created'}
            result.append({'kind': kind, 'name': name, 'fields_sha256': fields})
    return result
