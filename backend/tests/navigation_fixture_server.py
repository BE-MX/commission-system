"""Local browser acceptance only: actual navigation API backed by in-memory SQLite."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.system.models import NavigationPreference
from app.system.router import router

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
for table in [ArkUser.__table__, ArkRole.__table__, ArkPermission.__table__, ArkUserRole.__table__, ArkRolePermission.__table__, NavigationPreference.__table__]:
    table.create(engine)
Session = sessionmaker(bind=engine)
with Session() as db:
    role = ArkRole(name="nav-fixture", label="Navigation fixture", permissions=[
        ArkPermission(code=code, module=code.split(":")[0], action=code.split(":")[1], label=code)
        for code in ["invoice:read", "tracking:read", "customer:read", "festival:read"]
    ])
    db.add_all([ArkUser(id=1, username="alice", real_name="Alice", password_hash="fixture", roles=[role]), ArkUser(id=2, username="bob", real_name="Bob", password_hash="fixture", roles=[role])])
    db.commit()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3347"], allow_methods=["GET", "PUT"], allow_headers=["Authorization", "Content-Type"])
app.include_router(router, prefix="/api/system")


def fixture_db():
    with Session() as db:
        yield db


app.dependency_overrides[get_db] = fixture_db


@app.get("/fixture/users/{name}")
def fixture_user(name: str):
    if name not in ("alice", "bob"):
        raise HTTPException(404)
    user = {"id": 1 if name == "alice" else 2, "username": name, "real_name": name, "roles": [], "permissions": ["invoice:read", "tracking:read", "customer:read", "festival:read"]}
    return {"access_token": create_access_token({**user, "sub": str(user["id"])}), "user": user}
