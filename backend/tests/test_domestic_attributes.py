"""内贸订单头与产品属性的结构契约。"""

import importlib.util
import itertools
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.auth.models import ArkUser
from app.core.database import Base
from app.domestic import attribute_service, order_service, product_service, report_service
from app.domestic import constants as C
from app.domestic.models import (
    DomesticCraftRoute,
    DomesticBasePrice,
    DomesticCustomer,
    DomesticOrder,
    DomesticOrderItem,
    DomesticProduct,
)
from app.domestic.schemas import (
    OrderCreate,
    OrderItemAppend,
    OrderItemInput,
    OrderUpdate,
    ProductAttrs,
)
from app.production.models import Process, ProcessRoute, ProcessRouteStep
from app.system.models import SysDict


_ITEM_KEYS = itertools.count(1)


def _expected_quote():
    return {
        "original_price": Decimal("1000.00"),
        "base_price_version": 1,
        "discount_price": Decimal("1000.00"),
        "membership_level": None,
        "pricing_rule": "base_price",
        "pricing_version": "domestic-member-v1",
    }


def _order_item(*, attrs, order_qty, **kwargs):
    return OrderItemInput(
        client_key=f"attributes-line-{next(_ITEM_KEYS)}",
        attrs=attrs,
        order_qty=order_qty,
        expected_quote=_expected_quote(),
        **kwargs,
    )


def _append_item(db, *, attrs, order_qty, **kwargs):
    _ensure_base_price(db, attrs)
    return OrderItemAppend(
        client_key=f"attributes-line-{next(_ITEM_KEYS)}",
        attrs=attrs,
        order_qty=order_qty,
        expected_quote=_expected_quote(),
        **kwargs,
    )


def _canonical_price_code(db, dict_type, value):
    rows = db.query(SysDict).filter(
        SysDict.type.in_((dict_type, f"{dict_type}_special")),
        SysDict.is_active.is_(True),
    ).all()
    return next((row.code for row in rows if row.code.casefold() == value.casefold()), value)


def _ensure_base_price(db, attrs):
    attrs = attrs if isinstance(attrs, ProductAttrs) else ProductAttrs.model_validate(attrs)
    craft = _canonical_price_code(
        db, C.ATTR_DICTS[attrs.product_type]["craft"], attrs.craft
    )
    length = _canonical_price_code(
        db, C.ATTR_DICTS[attrs.product_type]["length"], attrs.length
    )
    row = db.query(DomesticBasePrice).filter_by(
        product_type=attrs.product_type, craft=craft, length=length
    ).first()
    if row is None:
        db.add(DomesticBasePrice(
            product_type=attrs.product_type,
            craft=craft,
            length=length,
            original_price=Decimal("1000.00"),
            version=1,
        ))
        db.flush()


def _cap_attrs(**overrides):
    values = {
        "product_type": "cap",
        "craft": "递旋",
        "net_color": "紫网全头套",
        "size": "M",
        "length": "15厘米",
        "density": "80%",
        "hair_style_series": "直发",
    }
    values.update(overrides)
    return values


def _order_payload(**overrides):
    values = {
        "request_id": "attributes-test-1",
        "order_no": "DOM-ATTR-001",
        "order_date": date(2026, 9, 1),
        "required_ship_date": date(2026, 9, 10),
        "customer_id": 1,
        "order_category": "special",
        "order_type": "first_order",
        "order_channel": "wechat",
        "items": [
            _order_item(
                attrs=ProductAttrs(**_cap_attrs()),
                order_qty=1,
            )
        ],
    }
    values.update(overrides)
    return values


def test_new_order_fields_are_required():
    order = OrderCreate(**_order_payload())
    assert order.order_category == "special"
    assert order.order_type == "first_order"
    assert order.order_channel == "wechat"

    for field_name in ("order_type", "order_channel"):
        payload = _order_payload()
        payload.pop(field_name)
        with pytest.raises(ValidationError):
            OrderCreate(**payload)


def test_order_type_and_channel_are_extensible_non_blank_strings():
    order = OrderCreate(**_order_payload(order_type="  future_order  ", order_channel="  live_stream  "))
    assert order.order_type == "future_order"
    assert order.order_channel == "live_stream"

    assert C.ORDER_CATEGORIES == {"normal": "普货", "special": "特单"}
    assert C.ORDER_TYPE_DICT == "domestic_order_type"
    assert C.ORDER_CHANNEL_DICT == "domestic_order_channel"

    for field_name in ("order_type", "order_channel"):
        with pytest.raises(ValidationError):
            OrderCreate(**_order_payload(**{field_name: "   "}))


def test_order_update_keeps_patch_semantics():
    partial = OrderUpdate(remark="只改备注")
    assert partial.model_dump(exclude_unset=True) == {"remark": "只改备注"}

    update = OrderUpdate(order_type="  repurchase  ", order_channel="  phone  ")
    assert update.order_type == "repurchase"
    assert update.order_channel == "phone"

    with pytest.raises(ValidationError):
        OrderUpdate(order_type="   ")
    for field_name in ("order_type", "order_channel"):
        with pytest.raises(ValidationError):
            OrderUpdate(**{field_name: None})
    with pytest.raises(ValidationError):
        OrderUpdate(order_category=None)


def test_mysql_dictionary_code_comparison_is_binary_exact():
    statements = [
        select(SysDict.id).where(
            attribute_service._exact_code_predicate("mysql", "FIRST_ORDER")
        ),
        select(DomesticProduct.id).where(
            product_service._exact_text_predicate(
                "mysql", DomesticProduct.attrs_key, '["cap","ABC"]'
            )
        ),
        select(DomesticCraftRoute.id).where(
            product_service._exact_text_predicate(
                "mysql", DomesticCraftRoute.craft, "ABC"
            )
        ),
    ]

    sql = [str(statement.compile(
        dialect=mysql.dialect(),
        compile_kwargs={"literal_binds": True},
    )) for statement in statements]

    assert "CAST(sys_dict.code AS BINARY) = 'FIRST_ORDER'" in sql[0]
    assert "CAST(ark_domestic_products.attrs_key AS BINARY)" in sql[1]
    assert "CAST(ark_domestic_craft_routes.craft AS BINARY) = 'ABC'" in sql[2]


class _FakeDictQuery:
    def __init__(self, row):
        self.row = row

    def filter(self, *_conditions):
        return self

    def populate_existing(self):
        return self

    def with_for_update(self):
        return self

    def order_by(self, *_columns):
        return self

    def first(self):
        return self.row

    def all(self):
        return [] if self.row is None else [self.row]


class _FakeSavepoint:
    def rollback(self):
        return None


class _FakeMySQLDictDb:
    def __init__(self, rows, *, conflict="unique conflict"):
        self.queries = iter(_FakeDictQuery(row) for row in rows)
        self.conflict = conflict

    def query(self, _model):
        return next(self.queries)

    def get_bind(self):
        return type("Bind", (), {"dialect": type("Dialect", (), {"name": "mysql"})()})()

    def begin_nested(self):
        return _FakeSavepoint()

    def add(self, _row):
        return None

    def flush(self):
        raise IntegrityError("INSERT", {}, Exception(self.conflict))


def test_active_value_rejects_case_different_row_even_if_database_returns_it():
    wrong_case = _dict_row(C.ORDER_TYPE_DICT, "FIRST_ORDER")

    assert attribute_service._active_value(
        _FakeMySQLDictDb([wrong_case]), C.ORDER_TYPE_DICT, "first_order"
    ) is None


def test_special_value_unique_race_reuses_case_different_canonical_row():
    active_wrong_case = _dict_row(f"{C.DICT_CAP_SIZE}_special", "SS")
    db = _FakeMySQLDictDb([
        None,
        None,
        active_wrong_case,
        active_wrong_case,
    ])

    row = attribute_service._create_special_value(
        db, f"{C.DICT_CAP_SIZE}_special", "ss"
    )

    assert row is active_wrong_case
    assert row.code == "SS"


def test_special_value_unique_race_reports_exact_inactive_winner():
    exact_inactive = _dict_row(
        f"{C.DICT_CAP_SIZE}_special", "ss", active=False
    )
    db = _FakeMySQLDictDb(
        [None, None, None, None, exact_inactive], conflict="inactive unique race"
    )

    with pytest.raises(ValueError, match="已停用"):
        attribute_service._create_special_value(
            db, f"{C.DICT_CAP_SIZE}_special", "ss"
        )


def test_piece_has_one_combined_craft_size_attribute():
    attrs = ProductAttrs(
        product_type="piece",
        craft="U型13*15",
        length="20厘米",
        net_color="紫网全头套",
        size="13*15",
        density="90%",
        hair_style_series="直发",
    )

    assert attrs.craft == "U型13*15"
    assert attrs.net_color is None
    assert attrs.size is None
    assert attrs.density is None
    assert attrs.hair_style_series is None


def test_15cm_cap_requires_density():
    with pytest.raises(ValidationError, match="15厘米"):
        ProductAttrs(**_cap_attrs(density=None))


def test_non_15cm_cap_clears_residual_density():
    attrs = ProductAttrs(**_cap_attrs(length="20厘米", density="90%"))
    assert attrs.density is None


@pytest.mark.parametrize("net_color", [None, "   "])
def test_cap_net_color_is_optional_and_blank_normalizes_to_none(net_color):
    values = _cap_attrs()
    if net_color is None:
        values.pop("net_color")
    else:
        values["net_color"] = net_color

    attrs = ProductAttrs(**values)
    assert attrs.net_color is None


@pytest.mark.parametrize("field_name", ["craft", "length", "size", "hair_style_series"])
def test_cap_rejects_blank_required_strings(field_name):
    with pytest.raises(ValidationError):
        ProductAttrs(**_cap_attrs(**{field_name: "   "}))


@pytest.mark.parametrize("missing_field", ["size", "hair_style_series"])
def test_cap_requires_size_and_hair_style_series(missing_field):
    values = _cap_attrs()
    values.pop(missing_field)
    with pytest.raises(ValidationError):
        ProductAttrs(**values)


def test_models_expose_new_nullable_database_contract():
    order_columns = DomesticOrder.__table__.c
    assert order_columns.order_category.nullable is False
    assert order_columns.order_type.nullable is True
    assert order_columns.order_channel.nullable is True

    product_columns = DomesticProduct.__table__.c
    assert product_columns.size.nullable is True
    assert product_columns.density.nullable is True
    assert product_columns.hair_style_series.nullable is True


def test_downgrade_normalizes_null_product_attrs_before_not_null(monkeypatch):
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "129_domestic_order_attributes.py"
    )
    spec = importlib.util.spec_from_file_location("domestic_attributes_129", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    calls = []
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: calls.append(("execute", str(statement), {})),
    )
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda table, column, **kwargs: calls.append(
            ("alter_column", f"{table}.{column}", kwargs)
        ),
    )
    monkeypatch.setattr(migration.op, "drop_column", lambda *args, **kwargs: None)

    migration.downgrade()

    for column in ("density", "size"):
        update_indexes = [
            index
            for index, (operation, statement, _) in enumerate(calls)
            if operation == "execute"
            and f"SET {column} = ''" in statement
            and f"WHERE {column} IS NULL" in statement
        ]
        assert update_indexes, f"downgrade must normalize NULL {column} values"
        alter_index = next(
            index
            for index, (operation, target, kwargs) in enumerate(calls)
            if operation == "alter_column"
            and target == f"ark_domestic_products.{column}"
            and kwargs.get("nullable") is False
        )
        assert update_indexes[0] < alter_index


def _dict_row(dict_type: str, code: str, *, label: str | None = None, active: bool = True):
    return SysDict(
        type=dict_type,
        code=code,
        label=label or code,
        sort=1,
        is_active=active,
    )


def _seed_attribute_context(db, *, piece_route: bool = True):
    user = ArkUser(
        username=f"domestic-attrs-{id(db)}",
        password_hash="x",
        real_name="属性测试员",
        is_active=True,
    )
    db.add(user)
    db.flush()
    customer = DomesticCustomer(
        shop_name=f"属性测试客户-{id(db)}",
        owner_user_id=user.id,
        balance=Decimal("999999.00"),
        status=1,
        created_by=user.id,
    )
    db.add(customer)

    process = Process(name=f"属性测试工序-{id(db)}", status=1)
    cap_route = ProcessRoute(name=C.DEFAULT_ROUTE_NAMES["cap"], status=1)
    db.add_all([process, cap_route])
    db.flush()
    db.add(ProcessRouteStep(route_id=cap_route.id, process_id=process.id, step_order=1))

    routes = {"cap": cap_route}
    if piece_route:
        piece = ProcessRoute(name=C.DEFAULT_ROUTE_NAMES["piece"], status=1)
        db.add(piece)
        db.flush()
        db.add(ProcessRouteStep(route_id=piece.id, process_id=process.id, step_order=1))
        routes["piece"] = piece

    standard_codes = {
        C.DICT_CAP_CRAFT: "递旋",
        C.DICT_CAP_NET_COLOR: "紫网全头套",
        C.DICT_CAP_SIZE: "M",
        C.DICT_CAP_LENGTH: "15厘米",
        C.DICT_CAP_DENSITY: "80%",
        C.DICT_CAP_HAIR_STYLE_SERIES: "直发",
        C.DICT_PIECE_CRAFT_SIZE: "U型13*15",
        C.DICT_PIECE_LENGTH: "20厘米",
        C.ORDER_TYPE_DICT: "future_order",
        C.ORDER_CHANNEL_DICT: "live_stream",
    }
    db.add_all([_dict_row(dict_type, code) for dict_type, code in standard_codes.items()])
    db.commit()
    return {"db": db, "user": user, "customer": customer, "routes": routes}


def _service_order(context, *, request_id: str, order_category="special", items=None, **overrides):
    payload = _order_payload(
        request_id=request_id,
        order_no=request_id,
        customer_id=context["customer"].id,
        order_category=order_category,
        order_type="future_order",
        order_channel="live_stream",
    )
    if items is not None:
        payload["items"] = items
    for item in payload["items"]:
        _ensure_base_price(context["db"], item.attrs)
    payload.update(overrides)
    return OrderCreate(**payload)


def test_normal_order_rejects_custom_attribute(db):
    context = _seed_attribute_context(db)
    payload = _service_order(
        context,
        request_id="normal-custom-attrs",
        order_category="normal",
        items=[_order_item(
            attrs=ProductAttrs(**_cap_attrs(craft="自定义工艺")),
            order_qty=1,
        )],
    )

    with pytest.raises(ValueError, match="第 1 行.*工艺.*切换为特单"):
        order_service.create_order(db, payload, context["user"].id)


def test_special_order_creates_and_reuses_only_special_option_and_route(db):
    context = _seed_attribute_context(db)
    attrs = ProductAttrs(**_cap_attrs(craft="自定义工艺"))

    first = order_service.create_order(
        db,
        _service_order(
            context,
            request_id="special-custom-first",
            items=[_order_item(attrs=attrs, order_qty=1)],
        ),
        context["user"].id,
    )
    second = order_service.create_order(
        db,
        _service_order(
            context,
            request_id="special-custom-second",
            items=[_order_item(attrs=attrs, order_qty=1)],
        ),
        context["user"].id,
    )

    assert first["id"] != second["id"]
    assert db.query(SysDict).filter_by(
        type=f"{C.DICT_CAP_CRAFT}_special", code="自定义工艺", is_active=True
    ).count() == 1
    assert db.query(SysDict).filter_by(
        type=C.DICT_CAP_CRAFT, code="自定义工艺"
    ).count() == 0
    mapping = db.query(DomesticCraftRoute).filter_by(
        product_type="cap", craft="自定义工艺"
    ).one()
    assert mapping.route_id == context["routes"]["cap"].id


def test_existing_special_craft_mapping_survives_disabled_default_route(db):
    context = _seed_attribute_context(db)
    custom_craft = "已配置非默认路线的工艺"
    db.add(_dict_row(f"{C.DICT_CAP_CRAFT}_special", custom_craft))
    process = Process(name=f"特单专属工序-{id(db)}", status=1)
    custom_route = ProcessRoute(name=f"特单专属路线-{id(db)}", status=1)
    db.add_all([process, custom_route])
    db.flush()
    db.add_all([
        ProcessRouteStep(route_id=custom_route.id, process_id=process.id, step_order=1),
        DomesticCraftRoute(
            product_type="cap",
            craft=custom_craft,
            route_id=custom_route.id,
            updated_by=context["user"].id,
        ),
    ])
    context["routes"]["cap"].status = 0
    db.commit()

    result = order_service.create_order(
        db,
        _service_order(
            context,
            request_id="existing-custom-route",
            items=[_order_item(
                attrs=ProductAttrs(**_cap_attrs(craft=custom_craft)),
                order_qty=1,
            )],
        ),
        context["user"].id,
    )

    mapping = db.query(DomesticCraftRoute).filter_by(
        product_type="cap", craft=custom_craft
    ).one()
    item = db.query(DomesticOrderItem).filter_by(order_id=result["id"]).one()
    assert mapping.route_id == custom_route.id
    assert item.route_id == custom_route.id


def test_special_craft_mapping_race_keeps_winning_route(monkeypatch):
    default_route = ProcessRoute(id=11, name="默认路线", status=1)
    winning_mapping = DomesticCraftRoute(
        id=22,
        product_type="cap",
        craft="竞争工艺",
        route_id=99,
        updated_by=7,
    )

    class FakeSavepoint:
        def commit(self):
            raise AssertionError("flush 冲突后不应提交 savepoint")

        def rollback(self):
            return None

    class FakeQuery:
        def __init__(self, result):
            self.result = result
            self.populate_existing_called = False
            self.with_for_update_called = False

        def filter(self, *_args):
            return self

        def populate_existing(self):
            self.populate_existing_called = True
            return self

        def with_for_update(self):
            self.with_for_update_called = True
            return self

        def first(self):
            return self.result

    class FakeDb:
        def __init__(self):
            self.queries = [FakeQuery(None), FakeQuery(winning_mapping)]
            self.query_index = 0

        def query(self, _model):
            query = self.queries[self.query_index]
            self.query_index += 1
            return query

        def get_bind(self):
            return type("Bind", (), {"dialect": type("Dialect", (), {"name": "mysql"})()})()

        def begin_nested(self):
            return FakeSavepoint()

        def add(self, _row):
            return None

        def flush(self):
            raise IntegrityError("INSERT", {}, Exception("duplicate mapping"))

    fake_db = FakeDb()
    monkeypatch.setattr(attribute_service, "_default_route", lambda *_args: default_route)

    attribute_service._ensure_special_craft_route(
        fake_db,
        product_type="cap",
        craft="竞争工艺",
        user_id=8,
    )

    refetch = fake_db.queries[1]
    assert refetch.populate_existing_called is True
    assert refetch.with_for_update_called is True
    assert winning_mapping.route_id == 99
    assert winning_mapping.updated_by == 7


def test_route_lookup_and_race_never_reuse_case_different_mapping(monkeypatch):
    wrong_case = DomesticCraftRoute(
        id=23,
        product_type="cap",
        craft="CustomCraft",
        route_id=99,
        updated_by=7,
    )
    lookup_db = _FakeMySQLDictDb([wrong_case])
    assert product_service.resolve_route_id(lookup_db, "cap", "customcraft") is None

    race_db = _FakeMySQLDictDb([wrong_case, wrong_case])
    monkeypatch.setattr(
        attribute_service,
        "_default_route",
        lambda *_args: ProcessRoute(id=11, name="默认路线", status=1),
    )
    with pytest.raises(ValueError, match="工艺映射.*大小写"):
        attribute_service._ensure_special_craft_route(
            race_db,
            product_type="cap",
            craft="customcraft",
            user_id=8,
        )


def test_sqlite_concurrent_append_converges_on_one_special_option(tmp_path):
    database_path = tmp_path / "domestic-special-race.sqlite3"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
        poolclass=NullPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_concurrency(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA busy_timeout = 5000")

    seen_index_names: set[str] = set()
    for table in Base.metadata.tables.values():
        for index in list(table.indexes):
            if index.name in seen_index_names:
                table.indexes.discard(index)
            else:
                seen_index_names.add(index.name)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    setup_db = Session()
    try:
        context = _seed_attribute_context(setup_db)
        created = order_service.create_order(
            setup_db,
            _service_order(
                context,
                request_id="concurrent-append-base",
                is_draft=True,
            ),
            context["user"].id,
        )
        order_id = created["id"]
        user_id = context["user"].id
        _ensure_base_price(
            setup_db,
            ProductAttrs(**_cap_attrs(craft="并发特单工艺")),
        )
        setup_db.commit()
    finally:
        setup_db.close()

    start = threading.Barrier(2)

    def append(request_id: str) -> dict:
        thread_db = Session()
        try:
            start.wait(timeout=5)
            return order_service.add_item(
                thread_db,
                order_id,
                _append_item(thread_db,
                    request_id=request_id,
                    attrs=ProductAttrs(**_cap_attrs(craft="并发特单工艺")),
                    order_qty=1,
                ),
                user_id,
            )
        finally:
            thread_db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(append, ("concurrent-a", "concurrent-b")))

        verify_db = Session()
        try:
            assert len({result["id"] for result in results}) == 2
            assert verify_db.query(SysDict).filter_by(
                type=f"{C.DICT_CAP_CRAFT}_special",
                code="并发特单工艺",
                is_active=True,
            ).count() == 1
            assert verify_db.query(DomesticCraftRoute).filter_by(
                product_type="cap", craft="并发特单工艺"
            ).count() == 1
        finally:
            verify_db.close()
    finally:
        engine.dispose()


def test_order_dimensions_use_active_dictionary_values(db):
    context = _seed_attribute_context(db)
    result = order_service.create_order(
        db,
        _service_order(context, request_id="dynamic-order-dimensions"),
        context["user"].id,
    )
    order = db.get(DomesticOrder, result["id"])
    assert (order.order_type, order.order_channel) == ("future_order", "live_stream")

    db.add(_dict_row(C.ORDER_TYPE_DICT, "disabled_type", active=False))
    db.commit()
    for field_name, value, expected in (
        ("order_type", "missing_type", "订单类型"),
        ("order_type", "disabled_type", "订单类型"),
        ("order_channel", "missing_channel", "订单渠道"),
    ):
        payload = _service_order(
            context,
            request_id=f"invalid-{field_name}-{value}",
            **{field_name: value},
        )
        with pytest.raises(ValueError, match=f"{expected}.*数据字典"):
            order_service.create_order(db, payload, context["user"].id)


def test_normal_order_rejects_case_different_order_type_and_size(db):
    context = _seed_attribute_context(db)
    db.add_all([
        _dict_row(C.ORDER_TYPE_DICT, "FIRST_ORDER"),
        _dict_row(C.DICT_CAP_SIZE, "SS"),
    ])
    db.commit()

    wrong_type = _service_order(
        context,
        request_id="case-sensitive-type",
        order_category="normal",
        order_type="first_order",
    )
    with pytest.raises(ValueError, match="订单类型.*数据字典"):
        order_service.create_order(db, wrong_type, context["user"].id)

    wrong_size = _service_order(
        context,
        request_id="case-sensitive-size",
        order_category="normal",
        items=[_order_item(
            attrs=ProductAttrs(**_cap_attrs(size="ss")),
            order_qty=1,
        )],
    )
    with pytest.raises(ValueError, match="尺码.*切换为特单"):
        order_service.create_order(db, wrong_size, context["user"].id)


def test_special_order_canonicalizes_case_different_standard_value(db):
    context = _seed_attribute_context(db)
    db.add(_dict_row(C.DICT_CAP_SIZE, "SS"))
    db.commit()

    result = order_service.create_order(
        db,
        _service_order(
            context,
            request_id="case-sensitive-special-size",
            items=[_order_item(
                attrs=ProductAttrs(**_cap_attrs(size="ss")),
                order_qty=1,
            )],
        ),
        context["user"].id,
    )

    assert result["id"]
    order = db.get(DomesticOrder, result["id"])
    item = db.query(DomesticOrderItem).filter_by(order_id=order.id).one()
    product = db.get(DomesticProduct, item.product_id)
    assert item.attrs_snapshot["size"] == "SS"
    assert product.size == "SS"
    assert db.query(SysDict).filter_by(
        type=f"{C.DICT_CAP_SIZE}_special", is_active=True
    ).count() == 0


def test_special_piece_canonicalizes_standard_craft_before_route_and_product(db):
    context = _seed_attribute_context(db)
    db.add(DomesticCraftRoute(
        product_type="piece",
        craft="U型13*15",
        route_id=context["routes"]["piece"].id,
        updated_by=context["user"].id,
    ))
    db.commit()

    result = order_service.create_order(
        db,
        _service_order(
            context,
            request_id="case-sensitive-piece-craft",
            items=[_order_item(
                attrs=ProductAttrs(
                    product_type="piece",
                    craft="u型13*15",
                    length="20厘米",
                ),
                order_qty=1,
            )],
        ),
        context["user"].id,
    )

    item = db.query(DomesticOrderItem).filter_by(order_id=result["id"]).one()
    product = db.get(DomesticProduct, item.product_id)
    assert item.attrs_snapshot["craft"] == "U型13*15"
    assert product.craft == "U型13*15"
    assert product.route_id == context["routes"]["piece"].id
    assert db.query(SysDict).filter_by(
        type=f"{C.DICT_PIECE_CRAFT_SIZE}_special", is_active=True
    ).count() == 0


def test_special_order_reuses_case_different_custom_canonical_value(db):
    context = _seed_attribute_context(db)
    db.add(_dict_row(f"{C.DICT_CAP_SIZE}_special", "CustomSize"))
    db.commit()

    result = order_service.create_order(
        db,
        _service_order(
            context,
            request_id="case-sensitive-custom-size",
            items=[_order_item(
                attrs=ProductAttrs(**_cap_attrs(size="customsize")),
                order_qty=1,
            )],
        ),
        context["user"].id,
    )

    item = db.query(DomesticOrderItem).filter_by(order_id=result["id"]).one()
    product = db.get(DomesticProduct, item.product_id)
    assert item.attrs_snapshot["size"] == "CustomSize"
    assert product.size == "CustomSize"
    assert db.query(SysDict).filter_by(
        type=f"{C.DICT_CAP_SIZE}_special", is_active=True
    ).count() == 1


def test_order_read_contract_uses_dynamic_labels_and_keeps_missing_history_blank(db):
    context = _seed_attribute_context(db)
    db.query(SysDict).filter_by(type=C.ORDER_TYPE_DICT, code="future_order").update(
        {"label": "未来订单"}
    )
    db.query(SysDict).filter_by(type=C.ORDER_CHANNEL_DICT, code="live_stream").update(
        {"label": "直播"}
    )
    created = order_service.create_order(
        db,
        _service_order(context, request_id="read-contract"),
        context["user"].id,
    )
    historical = DomesticOrder(
        domestic_no="DO20260901-999",
        order_no="HISTORY-NULL",
        order_date=date(2026, 9, 1),
        customer_id=context["customer"].id,
        order_category="normal",
        order_type=None,
        order_channel=None,
        status=C.ORDER_PRODUCING,
        total_amount=0,
        charged_amount=0,
        next_line_no=1,
        item_count=0,
        total_unit_qty=0,
        created_by=context["user"].id,
        deleted_flag=0,
    )
    db.add(historical)
    db.commit()

    rows, total = order_service.list_orders(
        db,
        page_size=10,
        order_category="special",
        order_type="future_order",
        order_channel="live_stream",
    )
    assert total == 1
    assert {
        key: rows[0][key]
        for key in (
            "order_category",
            "order_category_label",
            "order_type",
            "order_type_label",
            "order_channel",
            "order_channel_label",
        )
    } == {
        "order_category": "special",
        "order_category_label": "特单",
        "order_type": "future_order",
        "order_type_label": "未来订单",
        "order_channel": "live_stream",
        "order_channel_label": "直播",
    }

    detail = order_service.get_order_detail(db, created["id"])
    assert (
        detail["order_category_label"],
        detail["order_type_label"],
        detail["order_channel_label"],
    ) == ("特单", "未来订单", "直播")

    history = order_service.get_order_detail(db, historical.id)
    assert history["order_type"] is None
    assert history["order_channel"] is None
    assert history["order_type_label"] == "未填写"
    assert history["order_channel_label"] == "未填写"


def test_scan_result_returns_all_three_order_dimensions(db):
    context = _seed_attribute_context(db)
    db.query(SysDict).filter_by(type=C.ORDER_TYPE_DICT, code="future_order").update(
        {"label": "未来订单"}
    )
    db.query(SysDict).filter_by(type=C.ORDER_CHANNEL_DICT, code="live_stream").update(
        {"label": "直播"}
    )
    created = order_service.create_order(
        db,
        _service_order(context, request_id="scan-dimensions"),
        context["user"].id,
    )
    item = db.query(DomesticOrderItem).filter_by(order_id=created["id"]).one()

    result = report_service.scan_item(db, item.id, context["user"].id)

    assert result["order_category"] == "special"
    assert result["order_category_label"] == "特单"
    assert result["order_type"] == "future_order"
    assert result["order_type_label"] == "未来订单"
    assert result["order_channel"] == "live_stream"
    assert result["order_channel_label"] == "直播"


def test_create_order_replay_uses_saved_hash_after_dimension_is_disabled(db):
    context = _seed_attribute_context(db)
    payload = _service_order(context, request_id="dimension-replay")
    first = order_service.create_order(db, payload, context["user"].id)
    order_type = db.query(SysDict).filter_by(
        type=C.ORDER_TYPE_DICT,
        code="future_order",
    ).one()
    order_type.is_active = False
    db.commit()

    replay = order_service.create_order(db, payload, context["user"].id)

    assert replay["id"] == first["id"]
    assert replay["replayed"] is True


def test_failed_later_item_rolls_back_special_options_and_mapping(db):
    context = _seed_attribute_context(db, piece_route=False)
    payload = _service_order(
        context,
        request_id="special-attrs-rollback",
        items=[
            _order_item(
                attrs=ProductAttrs(**_cap_attrs(craft="事务头套工艺")),
                order_qty=1,
            ),
            _order_item(
                attrs=ProductAttrs(
                    product_type="piece",
                    craft="事务发片工艺",
                    length="20厘米",
                ),
                order_qty=1,
            ),
        ],
    )

    with pytest.raises(ValueError, match="发片网底.*不存在"):
        order_service.create_order(db, payload, context["user"].id)

    assert db.query(SysDict).filter(SysDict.code.in_(["事务头套工艺", "事务发片工艺"])).count() == 0
    assert db.query(DomesticCraftRoute).filter(
        DomesticCraftRoute.craft.in_(["事务头套工艺", "事务发片工艺"])
    ).count() == 0
    assert db.query(DomesticOrder).filter_by(request_id="special-attrs-rollback").count() == 0


def test_failed_order_rolls_back_inline_customer(db):
    context = _seed_attribute_context(db, piece_route=False)
    payload = _service_order(
        context,
        request_id="inline-customer-rollback",
        customer_id=None,
        customer_shop_name="不应残留的客户",
        items=[_order_item(
            attrs=ProductAttrs(
                product_type="piece",
                craft="无路线发片工艺",
                length="20厘米",
            ),
            order_qty=1,
        )],
    )

    with pytest.raises(ValueError, match="发片网底.*不存在"):
        order_service.create_order(db, payload, context["user"].id)

    assert db.query(DomesticCustomer).filter_by(shop_name="不应残留的客户").count() == 0


def test_failed_append_rolls_back_special_option(db):
    context = _seed_attribute_context(db, piece_route=False)
    created = order_service.create_order(
        db,
        _service_order(context, request_id="append-rollback-base"),
        context["user"].id,
    )
    payload = _append_item(db,
        request_id="append-special-rollback",
        attrs=ProductAttrs(
            product_type="piece",
            craft="追加无路线工艺",
            length="20厘米",
        ),
        order_qty=1,
    )

    with pytest.raises(ValueError, match="发片网底.*不存在"):
        order_service.add_item(db, created["id"], payload, context["user"].id)

    assert db.query(SysDict).filter_by(code="追加无路线工艺").count() == 0


def test_special_order_with_custom_attrs_cannot_be_changed_to_normal(db):
    context = _seed_attribute_context(db)
    created = order_service.create_order(
        db,
        _service_order(
            context,
            request_id="category-downgrade",
            items=[_order_item(
                attrs=ProductAttrs(**_cap_attrs(craft="不能降级的工艺")),
                order_qty=1,
            )],
        ),
        context["user"].id,
    )

    with pytest.raises(ValueError, match="第 1 行.*切换为特单"):
        order_service.update_order(
            db,
            created["id"],
            OrderUpdate(order_category="normal"),
        )


def test_update_order_requires_complete_active_final_dimensions(db):
    context = _seed_attribute_context(db)
    historical = DomesticOrder(
        domestic_no="DO20260901-998",
        order_no="HISTORY-EDIT-NULL",
        order_date=date(2026, 9, 1),
        customer_id=context["customer"].id,
        order_category="normal",
        order_type=None,
        order_channel=None,
        status=C.ORDER_DRAFT,
        total_amount=0,
        charged_amount=0,
        next_line_no=1,
        item_count=0,
        total_unit_qty=0,
        created_by=context["user"].id,
        deleted_flag=0,
    )
    db.add(historical)
    db.commit()

    with pytest.raises(ValueError, match="订单类型.*必填"):
        order_service.update_order(db, historical.id, OrderUpdate(remark="只改备注"))
    with pytest.raises(ValueError, match="订单渠道.*必填"):
        order_service.update_order(
            db,
            historical.id,
            OrderUpdate(order_type="future_order"),
        )

    updated = order_service.update_order(
        db,
        historical.id,
        OrderUpdate(order_type="future_order", order_channel="live_stream"),
    )
    assert (updated.order_type, updated.order_channel) == (
        "future_order", "live_stream"
    )


def test_update_order_revalidates_unchanged_dimension_is_still_active(db):
    context = _seed_attribute_context(db)
    created = order_service.create_order(
        db,
        _service_order(context, request_id="update-disabled-final-dimension", is_draft=True),
        context["user"].id,
    )
    row = db.query(SysDict).filter_by(
        type=C.ORDER_CHANNEL_DICT, code="live_stream"
    ).one()
    row.is_active = False
    db.commit()

    with pytest.raises(ValueError, match="订单渠道.*启用选项"):
        order_service.update_order(
            db,
            created["id"],
            OrderUpdate(remark="仍需校验已有值"),
        )


def test_options_separate_standard_and_special_values_and_only_valid_routes(db):
    context = _seed_attribute_context(db, piece_route=False)
    db.add(_dict_row(f"{C.DICT_CAP_CRAFT}_special", "特单工艺"))
    disabled_piece_route = ProcessRoute(name=C.DEFAULT_ROUTE_NAMES["piece"], status=0)
    db.add(disabled_piece_route)
    db.commit()

    options = attribute_service.get_order_options(db)

    assert options["order_categories"] == [
        {"value": "normal", "label": "普货"},
        {"value": "special", "label": "特单"},
    ]
    assert options["attr_dicts"] == C.ATTR_DICTS
    assert options["special_attr_dicts"]["cap"]["craft"] == f"{C.DICT_CAP_CRAFT}_special"
    assert options["standard_values"][C.DICT_CAP_CRAFT] == ["递旋"]
    assert options["special_values"][f"{C.DICT_CAP_CRAFT}_special"] == ["特单工艺"]
    assert "特单工艺" not in options["standard_values"][C.DICT_CAP_CRAFT]
    assert options["default_routes"]["cap"] == {
        "id": context["routes"]["cap"].id,
        "name": C.DEFAULT_ROUTE_NAMES["cap"],
        "step_count": 1,
    }
    assert "piece" not in options["default_routes"]


def test_product_identity_and_list_include_hair_series_without_piece_placeholders(db):
    cap_attrs = ProductAttrs(**_cap_attrs())
    piece_attrs = ProductAttrs(
        product_type="piece",
        craft="U型13*15",
        length="20厘米",
    )

    assert json.loads(product_service.build_attrs_key(cap_attrs))[-1] == "直发"
    assert product_service.build_display_name(cap_attrs).endswith("/直发")
    assert product_service.build_attrs_key(piece_attrs) == '["piece","U型13*15","","","20厘米","",""]'
    assert product_service.build_display_name(piece_attrs) == "发片/U型13*15/20厘米"

    cap = product_service.find_or_create_product(db, cap_attrs)
    piece = product_service.find_or_create_product(db, piece_attrs)
    db.flush()
    assert cap.hair_style_series == "直发"
    assert piece.hair_style_series is None

    rows, total = product_service.list_products(db, page_size=10)
    assert total == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[cap.id]["hair_style_series"] == "直发"
    assert by_id[piece.id]["size"] is None
    assert by_id[piece.id]["density"] is None
    assert by_id[piece.id]["hair_style_series"] is None


def test_product_key_cannot_collide_when_special_values_contain_separator():
    first = ProductAttrs(
        product_type="cap",
        craft="a|b",
        net_color="c",
        size="M",
        length="20厘米",
        hair_style_series="直发",
    )
    second = ProductAttrs(
        product_type="cap",
        craft="a",
        net_color="b|c",
        size="M",
        length="20厘米",
        hair_style_series="直发",
    )

    assert product_service.build_attrs_key(first) != product_service.build_attrs_key(second)


def test_product_race_refetch_uses_locking_current_read(monkeypatch):
    attrs = ProductAttrs(**_cap_attrs())
    winner = DomesticProduct(
        id=99,
        attrs_key=product_service.build_attrs_key(attrs),
        name="并发胜方产品",
        product_type="cap",
        craft=attrs.craft,
        size=attrs.size,
        length=attrs.length,
        hair_style_series=attrs.hair_style_series,
        status=1,
        use_count=0,
    )

    class FakeSavepoint:
        def commit(self):
            raise AssertionError("flush 冲突后不应提交 savepoint")

        def rollback(self):
            return None

    class FakeQuery:
        def __init__(self, result):
            self.result = result
            self.populate_existing_called = False
            self.with_for_update_called = False

        def filter(self, *_args):
            return self

        def populate_existing(self):
            self.populate_existing_called = True
            return self

        def with_for_update(self):
            self.with_for_update_called = True
            return self

        def first(self):
            return self.result

    class FakeDb:
        def __init__(self):
            self.queries = [FakeQuery(None), FakeQuery(winner)]
            self.query_index = 0

        def query(self, _model):
            query = self.queries[self.query_index]
            self.query_index += 1
            return query

        def get_bind(self):
            return type("Bind", (), {"dialect": type("Dialect", (), {"name": "mysql"})()})()

        def begin_nested(self):
            return FakeSavepoint()

        def add(self, _row):
            return None

        def flush(self):
            raise IntegrityError("INSERT", {}, Exception("duplicate attrs_key"))

    fake_db = FakeDb()
    monkeypatch.setattr(product_service, "resolve_route_id", lambda *_args: None)

    product = product_service.find_or_create_product(fake_db, attrs)

    refetch = fake_db.queries[1]
    assert product is winner
    assert refetch.populate_existing_called is True
    assert refetch.with_for_update_called is True


def test_product_case_collision_never_reuses_wrong_product(monkeypatch):
    attrs = ProductAttrs(**_cap_attrs(craft="customcraft"))
    wrong_key = product_service.build_attrs_key(
        ProductAttrs(**_cap_attrs(craft="CustomCraft"))
    )
    wrong_case = DomesticProduct(
        id=100,
        attrs_key=wrong_key,
        name="大小写不同的产品",
        product_type="cap",
        craft="CustomCraft",
        size=attrs.size,
        length=attrs.length,
        hair_style_series=attrs.hair_style_series,
        status=1,
        use_count=0,
    )
    db = _FakeMySQLDictDb([wrong_case, wrong_case])
    monkeypatch.setattr(product_service, "resolve_route_id", lambda *_args: None)

    with pytest.raises(ValueError, match="产品属性组合.*大小写"):
        product_service.find_or_create_product(db, attrs)
