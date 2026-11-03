"""Loopback-only UI acceptance: actual navigation service, isolated in-memory SQLite."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.system import navigation_config_service as service
from app.system.navigation_config_models import NavigationConfig, NavigationVersion, NavigationConfigAudit
from app.system.navigation_config_schemas import NavigationDraftSave, NavigationPublish, NavigationPrecondition
engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
for model in (NavigationConfig, NavigationVersion, NavigationConfigAudit):
    model.__table__.create(engine)
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:8890'], allow_methods=['*'], allow_headers=['*'])
def call(method, *args):
    with Session(engine) as db:
        return {'code': 200, 'message': 'ok', 'data': method(db, *args)}
@app.get('/api/system/navigation-config/catalog')
def catalog(): return {'code': 200, 'data': service.catalog()}
@app.get('/api/system/navigation-config/draft')
def draft(): return call(service.get_draft)
@app.get('/api/system/navigation-config/effective')
def effective(): return call(service.effective)
@app.put('/api/system/navigation-config/draft')
def save(payload: NavigationDraftSave): return call(service.save_draft, payload, 7)
@app.post('/api/system/navigation-config/publish')
def publish(payload: NavigationPublish): return call(service.publish, payload, 7)
@app.get('/api/system/navigation-config/versions')
def versions(): return call(service.versions)
@app.post('/api/system/navigation-config/versions/{id}/restore-draft')
def restore(id: int, payload: NavigationPrecondition): return call(service.restore, id, payload, 7)
