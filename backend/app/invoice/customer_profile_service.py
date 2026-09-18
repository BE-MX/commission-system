"""Customer grades saved atomically with the invoice transaction."""
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.invoice.models import CustomerProfile


def get_customer_grade(db, customer_id):
    return db.query(CustomerProfile.customer_grade).filter_by(customer_id=str(customer_id)).scalar()


def save_customer_grade(db, customer_id, grade, user_id):
    values = dict(customer_id=str(customer_id), customer_grade=grade, updated_by=user_id)
    # An atomic upsert also covers two first invoices for the same customer.
    if db.get_bind().dialect.name == "sqlite":
        statement = sqlite_insert(CustomerProfile).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["customer_id"], set_={"customer_grade": grade, "updated_by": user_id})
    else:
        statement = mysql_insert(CustomerProfile).values(**values)
        statement = statement.on_duplicate_key_update(customer_grade=grade, updated_by=user_id)
    db.execute(statement)
