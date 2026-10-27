"""Run the actual Lua client against the actual FastAPI routes using an isolated SQLite app."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--ark-backend", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.ark_backend.resolve()))
sys.path.insert(0, str(ROOT / ".venv/Lib/site-packages"))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from lupa.luajit21 import LuaRuntime
from app.core.database import get_db
from app.inkboard import service
from app.inkboard.router import router
from app.inkboard.models import InkReceipt
from app.task.models import TaskItem
from tests.test_inkboard import board

fixture = board.__wrapped__()
db, owner, _, _ = next(fixture)
try:
    issued = service.create_device(db, owner, "PW3 integration")
    service.create_note(db, owner, "备忘", "明天核对项目进度")
    message = service.publish_message(db, owner, "项目提醒", "请查看待办", "high", "integration-001")
    db.add(TaskItem(id=1, owner_id=owner, title="核对项目进度", status="todo")); db.commit()
    app = FastAPI(); app.include_router(router, prefix="/api/inkboard")
    app.dependency_overrides[get_db] = lambda: db
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().CLIENT_ROOT = ROOT.as_posix()
    with TestClient(app) as client:
        def convert(value):
            if isinstance(value, dict):
                return lua.table_from({k: convert(v) for k, v in value.items()})
            if isinstance(value, list):
                return lua.table_from([convert(v) for v in value])
            return value
        def send(method, url, body):
            # Transport is separately tested. No socket or production URL is accessed in this bridge.
            path = url.replace("https://example.com", "")
            payload = {"ids": list(body["ids"].values()), "read": bool(body["read"])} if body is not None else None
            result = client.request(method, path, json=payload, headers={"Authorization": f'Bearer {issued["token"]}'})
            if result.status_code == 401:
                return None, "unauthorized"
            if result.status_code != 200:
                raise AssertionError(f"Unexpected local HTTP status: {result.status_code}")
            return convert(result.json()), None
        lua.globals().bridge = send
        lua.globals().TOKEN = issued["token"]
        lua.execute('''
            package.path = CLIENT_ROOT .. "/client/?.lua;" .. package.path
            for _, name in ipairs({"logic", "strings", "view", "net"}) do
                package.preload["apps/ark_board/" .. name] = function() return assert(loadfile(CLIENT_ROOT .. "/client/ark_board/" .. name .. ".lua"))() end
            end
            local callbacks, cache, state, popup = {}, nil, nil, nil
            local App = assert(loadfile(CLIENT_ROOT .. "/client/ark_board/init.lua"))()
            CTX = {
                now = function() return 1000 end, wake_at = function() end, redraw = function() end,
                settings = { get = function(_, k) return k == "url" and "https://example.com/api/inkboard" or TOKEN end },
                cache = { get = function() return cache end, put = function(_, value) cache = value end },
                data = { get = function() return state end, set = function(_, _, value) state = value end },
                ark_net = { get_json = function(url) return bridge("GET", url, nil) end,
                    post_json = function(url, body) return bridge("POST", url, body) end },
                after_commit = function(fn) callbacks[#callbacks + 1] = fn end,
                is_durable = function() return true end,
                dismiss_popup = function() popup = nil end,
                i18n = { t = function(k) return require("apps/ark_board/strings").en[k] or k end },
                notify = function() return 1 end, toast = function() end,
                confirm = function(title, body, label, fn) popup = { title = title, body = body, fn = fn } end,
            }
            function RUN() callbacks = {}; App.refresh(CTX, function(ok, why) assert(ok, why) end); for _, fn in ipairs(callbacks) do fn() end end
            function ACK() assert(popup); popup.fn() end
            function CACHE() return cache end
            function POPUP() return popup end
            RUN()
        ''')
        assert lua.globals().CACHE()["tasks"][1]["title"] == "核对项目进度"
        assert lua.globals().CACHE()["notes"][1]["body"] == "明天核对项目进度"
        assert lua.globals().POPUP()["title"] == "项目提醒"
        receipt = db.get(InkReceipt, (issued["id"], message["id"]))
        assert receipt and receipt.read_at is None
        lua.globals().ACK(); lua.globals().RUN()
        db.expire_all()
        assert db.get(InkReceipt, (issued["id"], message["id"])).read_at is not None
        service.withdraw_message(db, owner, message["id"])
        lua.globals().RUN()
        assert len(lua.globals().CACHE()["messages"]) == 0 and lua.globals().POPUP() is None
    print("integration: real Lua client + FastAPI + isolated SQLite passed")
finally:
    try:
        next(fixture)
    except StopIteration:
        pass
