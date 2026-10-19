from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_access_request_mysql_ddl_is_additive_and_employee_fk_matches():
    backend = Path(__file__).resolve().parents[2]
    spec = spec_from_file_location("access_request_migration", backend / "alembic/versions/201_portal_access_requests.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})
    module.op = Operations(context)
    module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE ark_order_portal_access_requests" in sql
    assert "reviewed_by INTEGER UNSIGNED" in sql
    assert "FOREIGN KEY(reviewed_by) REFERENCES ark_users (id)" in sql
    assert "DROP TABLE" not in sql and "UPDATE" not in sql
