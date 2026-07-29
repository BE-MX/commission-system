"""serve_spa 静态托管:目录斜杠重定向与 SPA fallback 回归测试"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bootstrap import static_files


def _build_app(tmp_path, monkeypatch) -> FastAPI:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>SPA</title>", encoding="utf-8")
    sub = dist / "caigoujie"
    sub.mkdir()
    (sub / "index.html").write_text("<title>ENTRY</title>", encoding="utf-8")
    (sub / "xiangsu.html").write_text("<title>PIXEL</title>", encoding="utf-8")
    monkeypatch.setattr(static_files, "FRONTEND_DIST", dist)
    app = FastAPI()
    static_files.mount_frontend(app)
    return app


def test_dir_without_slash_redirects(tmp_path, monkeypatch):
    """/caigoujie 必须 307 到 /caigoujie/,否则页面内相对链接解析到根路径"""
    app = _build_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        resp = client.get("/caigoujie", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "/caigoujie/"


def test_dir_with_slash_serves_index(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        resp = client.get("/caigoujie/")
        assert resp.status_code == 200
        assert "ENTRY" in resp.text


def test_file_in_subdir_served(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        resp = client.get("/caigoujie/xiangsu.html")
        assert resp.status_code == 200
        assert "PIXEL" in resp.text


def test_unknown_path_falls_back_to_spa(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        resp = client.get("/some/vue/route")
        assert resp.status_code == 200
        assert "SPA" in resp.text


def test_api_path_returns_404_json(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        resp = client.get("/api/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["code"] == 404
