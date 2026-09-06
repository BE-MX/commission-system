"""Route administration must preserve production references and bounded query cost."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.domestic.models import DomesticCraftRoute, DomesticRouteRule
from app.production.models import Process, ProcessRoute, ProcessRouteStep, ProductProcessRoute
from app.production.route_service import list_routes
from app.production import route_service
from app.production.router import router


@pytest.fixture
def route_client(db):
    app = FastAPI()
    app.include_router(router, prefix='/api/production')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        'sub': '1', 'roles': [], 'permissions': ['production:admin'],
    }
    with TestClient(app) as client:
        yield client, app


def test_route_delete_contract_removes_only_unused_route_and_steps(db, route_client):
    route = ProcessRoute(name='Unused route')
    process = Process(name='Test process')
    db.add_all([route, process])
    db.flush()
    route_id = route.id
    db.add(ProcessRouteStep(route_id=route_id, process_id=process.id, step_order=1))
    db.commit()
    response = route_client[0].delete(f'/api/production/process-routes/{route_id}')
    assert response.status_code == 200
    assert response.json()['code'] == 200
    assert db.get(ProcessRoute, route_id) is None
    assert db.query(ProcessRouteStep).filter_by(route_id=route_id).count() == 0
    assert db.get(Process, process.id) is not None


def test_route_delete_requires_admin_and_missing_route_is_404(db, route_client):
    client, app = route_client
    assert client.delete('/api/production/process-routes/987654').status_code == 404
    app.dependency_overrides[get_current_user] = lambda: {
        'sub': '1', 'roles': [], 'permissions': ['production_route:read'],
    }
    assert client.delete('/api/production/process-routes/987654').status_code == 403


@pytest.mark.parametrize('kind', ['external_product', 'domestic_craft'])
def test_referenced_routes_are_preserved(db, route_client, kind):
    route = ProcessRoute(name='Referenced route')
    db.add(route)
    db.flush()
    route_id = route.id
    reference = (ProductProcessRoute(product_id=987, route_id=route_id) if kind == 'external_product'
                 else DomesticCraftRoute(product_type='cap', craft='test', route_id=route_id))
    db.add(reference)
    db.commit()
    response = route_client[0].delete(f'/api/production/process-routes/{route_id}')
    assert response.status_code == 409
    assert db.get(ProcessRoute, route_id) is not None


def test_route_counts_do_not_grow_per_row(db):
    routes = [ProcessRoute(name=f'Batch route {i}') for i in range(20)]
    db.add_all(routes)
    db.flush()
    process = Process(name='Count process')
    db.add(process)
    db.flush()
    db.add(ProcessRouteStep(route_id=routes[0].id, process_id=process.id, step_order=1))
    db.add(ProductProcessRoute(product_id=789, route_id=routes[0].id))
    db.flush()
    statements = []
    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)
    event.listen(db.get_bind(), 'before_cursor_execute', record)
    try:
        rows, total = list_routes(db)
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', record)
    assert total == len(rows) == 20
    assert rows[0]['step_count'] == rows[0]['product_count'] == 1
    assert rows[-1]['step_count'] == rows[-1]['product_count'] == 0
    assert len(statements) == 4


def test_route_with_domestic_rule_cannot_be_deleted(db, route_client):
    route = ProcessRoute(name='Conditional route')
    process = Process(name='Conditional process')
    db.add_all([route, process])
    db.flush()
    db.add(ProcessRouteStep(route_id=route.id, process_id=process.id, step_order=1))
    rule = DomesticRouteRule(route_id=route.id, process_id=process.id,
                             rule_type='optional', config_json={})
    db.add(rule)
    db.commit()
    response = route_client[0].delete(f'/api/production/process-routes/{route.id}')
    assert response.status_code == 409
    assert '内贸条件规则' in response.json()['detail']
    assert db.get(ProcessRoute, route.id) is not None
    assert db.get(DomesticRouteRule, rule.id) is not None


def test_concurrent_reference_conflict_rolls_back_delete(db, route_client, monkeypatch):
    route = ProcessRoute(name='Concurrent route')
    db.add(route)
    db.commit()
    route_id = route.id
    original_delete = route_service.delete_route
    def conflicting_delete(session, identifier):
        original_delete(session, identifier)
        raise IntegrityError('DELETE', {}, Exception('foreign key conflict'))
    monkeypatch.setattr(route_service, 'delete_route', conflicting_delete)
    response = route_client[0].delete(f'/api/production/process-routes/{route_id}')
    assert response.status_code == 409
    assert db.get(ProcessRoute, route_id) is not None
    assert db.is_active
