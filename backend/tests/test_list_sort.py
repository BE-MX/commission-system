from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base

from app.core.list_sort import apply_items_sort, apply_list_sort

Base = declarative_base()


class SortRow(Base):
    __tablename__ = "sort_rows"
    id = Column(Integer, primary_key=True)
    value = Column(Integer, nullable=True)
    name = Column(String)


def test_sort_before_pagination_and_missing_values_last():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([SortRow(id=1, value=None), SortRow(id=2, value=2),
                    SortRow(id=3, value=2), SortRow(id=4, value=100), SortRow(id=5, value=0)])
        db.commit()
        for order, expected in [("asc", [5, 2, 3, 4, 1]), ("desc", [4, 2, 3, 5, 1])]:
            query = apply_list_sort(db.query(SortRow), "value", order, {"value": SortRow.value},
                                    tie_breakers=(SortRow.id.asc(),))
            actual = [row.id for page in range(3) for row in query.offset(page * 2).limit(2)]
            assert actual == expected
        query = apply_list_sort(db.query(SortRow), "id; DROP TABLE sort_rows", "asc", {},
                                default=(SortRow.id.desc(),))
        assert [row.id for row in query] == [5, 4, 3, 2, 1]


def test_materialized_full_dataset_sort_is_stable_and_preserves_source():
    rows = [{"id": 5, "value": None}, {"id": 3, "value": 20},
            {"id": 2, "value": 20}, {"id": 1, "value": 2}]
    assert [row["id"] for row in apply_items_sort(rows, "value", "desc", {"value": "value"})] == [2, 3, 1, 5]
    assert [row["id"] for row in apply_items_sort(rows, "value", "asc", {"value": lambda row: row["value"]})] == [1, 2, 3, 5]
    assert apply_items_sort(rows, "invalid", "asc", {}) == rows
    assert rows[0]["id"] == 5


def test_sql_text_empty_values_are_last_without_treating_numeric_zero_as_empty():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([SortRow(id=1, name='', value=0), SortRow(id=2, name='Beta', value=2),
                    SortRow(id=3, name=None, value=None), SortRow(id=4, name='Alpha', value=1)])
        db.commit()
        for direction, expected in [('asc', [4, 2]), ('desc', [2, 4])]:
            rows = apply_list_sort(db.query(SortRow), 'name', direction, {'name': SortRow.name}, tie_breakers=(SortRow.id.asc(),)).all()
            assert [r.id for r in rows[:2]] == expected
            assert {r.id for r in rows[2:]} == {1, 3}
        rows = apply_list_sort(db.query(SortRow), 'value', 'asc', {'value': SortRow.value}, tie_breakers=(SortRow.id.asc(),)).all()
        assert [r.id for r in rows] == [1, 4, 2, 3]
