"""Read-only protocol observation / dedicated legacy rollback fence. No app startup."""
import hashlib
import json
from pathlib import Path
import re
import sys

MODE='outbound-worker-v1'
LOCK='ark-okki-outbound-poller'


def validate(value):
    if (not isinstance(value,dict) or set(value)!={'mode','database_fingerprint'}
            or value.get('mode') not in {'legacy',MODE}
            or not isinstance(value.get('database_fingerprint'),str)
            or not re.fullmatch(r'[0-9a-f]{64}',value['database_fingerprint'])):
        raise RuntimeError('Rollback protocol observation cannot be confirmed')
    return value


def observe(connection):
    identity=connection.exec_driver_sql('SELECT @@server_uuid, DATABASE()').all()
    if (len(identity)!=1 or not isinstance(identity[0][0],str)
            or not re.fullmatch(r'[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}',identity[0][0],re.I)
            or not isinstance(identity[0][1],str) or not re.fullmatch(r'[A-Za-z0-9_]+',identity[0][1])):
        raise RuntimeError('Rollback target database cannot be confirmed')
    try:
        modes=connection.exec_driver_sql('SELECT code,version FROM ark_order_portal_auth_barriers WHERE code LIKE %s',('outbound-worker-%',)).all()
    except Exception as error:
        values=getattr(getattr(error,'orig',None),'args',())
        if not values or type(values[0]) is not int or values[0]!=1146:raise
        heads=connection.exec_driver_sql('SELECT version_num FROM alembic_version').all()
        if heads not in ([('171_customer_tag_display_value',)], [('175_receipt_recovery',)]):
            raise RuntimeError('Unconfirmed pre-portal schema') from None
        modes=[]
    if not modes:mode='legacy'
    elif len(modes)==1 and modes[0][0]==MODE and type(modes[0][1]) is int and modes[0][1]==1:mode=MODE
    else:raise RuntimeError('Rollback protocol mode cannot be confirmed')
    fingerprint=hashlib.sha256(json.dumps([identity[0][0].lower(),identity[0][1]],separators=(',',':')).encode()).hexdigest()
    return {'mode':mode,'database_fingerprint':fingerprint}


def serve(connection,operation,expected=None,*,input_stream=None,output_stream=None):
    input_stream=input_stream or sys.stdin;output_stream=output_stream or sys.stdout
    def emit(phase,value):print(json.dumps({'phase':phase,**value}),file=output_stream,flush=True)
    current=observe(connection)
    if operation=='observe':emit('observed',current);return
    if operation!='hold':raise RuntimeError('Invalid rollback control operation')
    expected=validate(expected)
    if expected['mode']!= 'legacy' or current!=expected:
        raise RuntimeError('Rollback requires verified protocol compatibility')
    identity=connection.exec_driver_sql('SELECT CONNECTION_ID(),IS_USED_LOCK(%s)',(LOCK,)).one()
    connection_id,prior_owner=identity
    if type(connection_id) is not int or connection_id<1 or prior_owner==connection_id:
        raise RuntimeError('Rollback connection ownership cannot be confirmed')
    acquired=connection.exec_driver_sql('SELECT GET_LOCK(%s,0)',(LOCK,)).scalar()
    if type(acquired) is not int or acquired!=1:raise RuntimeError('Rollback executor fence unavailable')
    # The live protocol may have changed between pre-read and actual lock acquisition.
    current=observe(connection)
    if current!=expected:raise RuntimeError('Rollback protocol changed before acquisition')
    emit('ready',current)
    for line in input_stream:
        command=line.rstrip('\r\n')
        if command not in {'check','release'}:raise RuntimeError('Invalid rollback control command')
        current=observe(connection)
        owner=connection.exec_driver_sql('SELECT IS_USED_LOCK(%s)',(LOCK,)).scalar()
        if current!=expected or owner!=connection_id:raise RuntimeError('Rollback control changed')
        if command=='check':emit('checked',current);continue
        released=connection.exec_driver_sql('SELECT RELEASE_LOCK(%s)',(LOCK,)).scalar()
        owner=connection.exec_driver_sql('SELECT IS_USED_LOCK(%s)',(LOCK,)).scalar()
        if type(released) is not int or released!=1 or owner==connection_id or (owner is not None and (type(owner) is not int or owner<1)):
            raise RuntimeError('Rollback release cannot be confirmed')
        emit('released',current);return
    raise RuntimeError('Rollback control ended without release confirmation')


def main():
    # Resolve from the staged script, never an arbitrary cwd or ambient PYTHONPATH.
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
    from sqlalchemy import create_engine
    from app.core.config import get_settings
    operation=sys.argv[1]
    expected=json.loads(sys.stdin.readline()) if operation=='hold' else None
    engine=create_engine(get_settings().commission_db_url,isolation_level='AUTOCOMMIT',connect_args={'connect_timeout':10})
    connection=None
    try:
        connection=engine.connect()
        serve(connection,operation,expected)
    finally:
        try:
            if connection is not None:
                # Dedicated physical socket never returns to a pool, including unknown GET/RELEASE results.
                try:connection.invalidate()
                finally:connection.close()
        finally:engine.dispose()


if __name__=='__main__':
    try:main()
    except Exception:
        print('Rollback protocol control unavailable; writers require inspection',file=sys.stderr,flush=True)
        sys.exit(1)
