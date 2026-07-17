#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
武汉市道路病害智能监测平台 — 生产版 (Flask + SQLite)

部署目标: Render / Railway / 任何支持 Python 的 PaaS 平台
特性:
  - Flask 框架 (轻量, PaaS 兼容性好)
  - SQLite 持久化存储 (跨重启数据不丢失)
  - 同时托管前端静态文件 + REST API (单服务, 无跨域问题)
  - DeepSeek AI 代理 (从环境变量读取 Key, 安全)
  - 健康检查端点 (/health) 供平台探活

环境变量:
  PORT        — 监听端口 (默认 8777, PaaS 平台通常通过此变量注入)
  DEEPSEEK_API_KEY — DeepSeek API Key (默认用内置值, 生产环境应设此变量)
"""

import json
import os
import sqlite3
import threading
import urllib.request
import urllib.error
from datetime import datetime
from flask import (
    Flask, request, jsonify, send_from_directory,
    send_file, abort
)

# ---- 配置 ----
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 8777))
DEEPSEEK_API = "https://api.deepseek.com/chat/completions"
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")  # 必须通过环境变量设置, 留空则AI功能不可用
ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "roads.db")  # 或 /tmp/roads.db (某些 PaaS)

# ---- SQLite 数据存储层 ----
_db_lock = threading.Lock()

def _get_db():
    """获取数据库连接(线程安全)"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    # 允许按列名访问
    conn.execute("PRAGMA journal_mode=WAL")   # 提高并发性能
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS roads (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            data_json   TEXT NOT NULL,       -- 完整道路数据的 JSON
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_roads_name ON roads(name);
    """)
    conn.commit()
    conn.close()
    print(f"[存储] 数据库初始化完成: {DB_PATH}")


# ---- 道路 CRUD 操作 ----

def db_get_all_roads():
    """获取全部道路"""
    conn = _get_db()
    rows = conn.execute("SELECT data_json FROM roads ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [json.loads(r["data_json"]) for r in rows]


def db_get_road(road_id):
    """按 ID 获取单条道路"""
    conn = _get_db()
    row = conn.execute("SELECT data_json FROM roads WHERE id=?", (road_id,)).fetchone()
    conn.close()
    return json.loads(row["data_json"]) if row else None


def db_get_road_by_name(name):
    """按名称获取道路"""
    conn = _get_db()
    row = conn.execute("SELECT data_json FROM roads WHERE name=?", (name,)).fetchone()
    conn.close()
    return json.loads(row["data_json"]) if row else None


def db_insert_road(road_data):
    """插入新道路, 返回 (success, error_msg)"""
    name = road_data.get("name", "")
    if not name:
        return False, "道路名称不能为空"
    now = datetime.now().isoformat()
    road_data["createdAt"] = now
    road_data["updatedAt"] = now
    try:
        conn = _get_db()
        conn.execute(
            "INSERT INTO roads (id, name, data_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (road_data["id"], name, json.dumps(road_data, ensure_ascii=False), now, now)
        )
        conn.commit()
        conn.close()
        return True, None
    except sqlite3.IntegrityError:
        return False, f"已存在同名道路: {name}"
    except Exception as e:
        return False, str(e)


def db_update_road(road_id, update_data):
    """更新指定 ID 的道路(合并字段), 返回 (success, road_or_None, error_msg)"""
    conn = _get_db()
    row = conn.execute("SELECT data_json FROM roads WHERE id=?", (road_id,)).fetchone()
    if not row:
        conn.close()
        return False, None, f"未找到道路: {road_id}"

    road = json.loads(row["data_json"])
    road.update(update_data)
    road["id"] = road_id  # 确保 ID 不被覆盖
    if "createdAt" not in road:
        road["createdAt"] = datetime.now().isoformat()
    road["updatedAt"] = datetime.now().isoformat()

    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE roads SET data_json=?, name=?, updated_at=? WHERE id=?",
        (json.dumps(road, ensure_ascii=False), road.get("name", ""), now, road_id)
    )
    conn.commit()
    conn.close()
    return True, road, None


def db_delete_road(road_id):
    """删除指定 ID 的道路, 返回 (success, deleted_road_or_None, error_msg)"""
    conn = _get_db()
    row = conn.execute("SELECT data_json FROM roads WHERE id=?", (road_id,)).fetchone()
    if not row:
        conn.close()
        return False, None, f"未找到道路: {road_id}"

    deleted = json.loads(row["data_json"])
    conn.execute("DELETE FROM roads WHERE id=?", (road_id,))
    conn.commit()
    conn.close()
    return True, deleted, None


# ---- 路由定义 ----

@app.route("/health")
def health():
    """健康检查端点 — PaaS 平台探活用"""
    try:
        conn = _get_db()
        count = conn.execute("SELECT COUNT(*) FROM roads").fetchone()[0]
        conn.close()
        return jsonify({
            "status": "ok",
            "service": "武汉道路病害监测平台",
            "db": "connected",
            "totalRoads": count,
            "serverTime": datetime.now().isoformat(),
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 503


@app.route("/api/roads", methods=["GET"])
def api_list_roads():
    """GET /api/roads — 获取全部道路"""
    with _db_lock:
        roads = db_get_all_roads()
    return jsonify({
        "roads": roads,
        "roadCounter": len(roads),
        "serverTime": datetime.now().isoformat(),
        "totalRoads": len(roads),
    }), 200


@app.route("/api/roads", methods=["POST"])
def api_add_road():
    """POST /api/roads — 新增道路"""
    data = request.get_json(silent=True) or {}
    with _db_lock:
        ok, err = db_insert_road(data)
        if not ok:
            return jsonify({"error": err}), 409 if "已存在" in err else 400
    return jsonify({
        "success": True,
        "road": data,
        "message": f"道路「{data['name']}」已添加",
    }), 201


@app.route("/api/roads/<path:road_id>", methods=["PUT"])
def api_update_road(road_id):
    """PUT /api/roads/<id> — 更新道路"""
    data = request.get_json(silent=True) or {}
    with _db_lock:
        ok, road, err = db_update_road(road_id, data)
        if not ok:
            return jsonify({"error": err}), 404
    return jsonify({
        "success": True,
        "road": road,
        "message": f"道路「{road.get('name', road_id)}」已更新",
    }), 200


@app.route("/api/roads/<path:road_id>", methods=["DELETE"])
def api_delete_road(road_id):
    """DELETE /api/roads/<id> — 删除道路"""
    with _db_lock:
        ok, deleted, err = db_delete_road(road_id)
        if not ok:
            return jsonify({"error": err}), 404
    return jsonify({
        "success": True,
        "deleted": deleted,
        "message": f"道路「{deleted.get('name', road_id)}」已删除",
    }), 200


@app.route("/api/deepseek", methods=["POST", "OPTIONS"])
def api_deepseek():
    """POST /api/deepseek — DeepSeek AI 代理"""
    if request.method == "OPTIONS":
        resp = app.make_response("")
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp, 204

    try:
        payload = request.get_json(silent=True) or {}
        messages = payload.get("messages", [])
    except Exception as e:
        return jsonify({"error": f"请求体解析失败: {e}"}), 400

    body = json.dumps({
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_KEY}",
    }

    try:
        req = urllib.request.Request(
            DEEPSEEK_API, data=body, headers=req_headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = resp.read()
        response = app.make_response(result)
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response, 200
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        return jsonify({"error": f"DeepSeek {e.code}: {detail}"}), e.code
    except Exception as e:
        return jsonify({"error": f"代理转发失败: {e}"}), 502


# ==================== 静态文件托管 ====================

STATIC_EXTENSIONS = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    """静态文件托管 — 前端页面、vendor/ 目录等"""
    # 安全检查：防止目录穿越
    safe_path = os.path.normpath(path).lstrip("/\\")
    if safe_path == "" or safe_path == ".":
        safe_path = "index.html"

    full_path = os.path.join(ROOT, safe_path)

    # 防目录穿越
    if not os.path.abspath(full_path).startswith(os.path.abspath(ROOT)):
        abort(403)

    # 文件存在则返回，否则 404
    if os.path.isfile(full_path):
        ext = os.path.splitext(full_path)[1].lower()
        ctype = STATIC_EXTENSIONS.get(ext, "application/octet-stream")
        return send_file(full_path, mimetype=ctype, download_name=os.path.basename(full_path))

    # 尝试目录下的 index.html
    if os.path.isdir(full_path):
        idx = os.path.join(full_path, "index.html")
        if os.path.isfile(idx):
            return send_file(idx, mimetype="text/html; charset=utf-8", download_name="index.html")

    abort(404)


@app.errorhandler(404)
def handle_404(e):
    return jsonify({"error": "Not Found"}), 404


@app.errorhandler(403)
def handle_403(e):
    return jsonify({"error": "Forbidden"}), 403


# ---- 启动入口 ----

if __name__ == "__main__":
    init_db()

    # 打印启动信息
    banner = f"""
{'='*60}
  武汉市道路病害智能监测平台 — 生产版 (Flask + SQLite)
{'='*60}
  监听端口:     http://0.0.0.0:{PORT}
  健康检查:     http://localhost:{PORT}/health
  ── API 端点 ──
  GET    /api/roads           获取全部道路
  POST   /api/roads           新增道路
  PUT    /api/roads/<id>      更新道路
  DELETE /api/roads/<id>      删除道路
  POST   /api/deepseek        AI 深度诊断代理
  GET    /health              健康检查
  ── 存储 ──
  数据库: {DB_PATH}
  引擎:   SQLite 3 (WAL模式)
{'='*60}
    """
    print(banner)

    # Render/Railway 等 PaaS 通过 $PORT 注入端口
    app.run(host="0.0.0.0", port=PORT, debug=False)
