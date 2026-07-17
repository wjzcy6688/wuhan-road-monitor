#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
武汉市道路病害智能监测平台 — 多用户协作服务

职责:
  1. 静态托管 index.html(前端原型)
  2. POST /api/deepseek -> 转发到 DeepSeek OpenAI 兼容接口
  3. RESTful 道路数据 CRUD API (多用户协作):
     GET    /api/roads       获取全部道路
     POST   /api/roads       新增道路
     PUT    /api/roads/<id>  更新指定道路
     DELETE /api/roads/<id>  删除指定道路
     数据持久化到 roads_data.json 文件

启动:  python server.py   (默认 http://0.0.0.0:8777)
"""
import http.server
import json
import os
import socketserver
import threading
import urllib.request
import urllib.error
import time
from datetime import datetime

DEEPSEEK_API = "https://api.deepseek.com/chat/completions"
API_KEY = "sk-abb99d75f549411188a795bc90692821"
PORT = 8777
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(ROOT, "roads_data.json")

# ---- 数据存储层 (JSON 文件) ----
_data_lock = threading.Lock()

def _load_roads():
    """从文件加载道路列表, 文件不存在则返回空列表"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[存储] 加载失败: {e}")
    return []

def _save_roads(roads):
    """将道路列表写入文件(原子写)"""
    try:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(roads, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)  # 原子替换
    except Exception as e:
        print(f"[存储] 保存失败: {e}")


class Handler(http.server.BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # 静默日志

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ==================== 静态文件托管 ====================
    def do_GET(self):
        # API 路由优先
        if self.path.startswith("/api/"):
            return self._handle_api_get()

        # 静态文件托管(含 index.html 及 vendor/ 等子目录), 防目录穿越
        rel = self.path.split("?", 1)[0].split("#", 1)[0]
        if rel in ("", "/"):
            rel = "/index.html"
        safe = os.path.normpath(rel).lstrip("/\\")
        full = os.path.join(ROOT, safe)
        if not os.path.abspath(full).startswith(os.path.abspath(ROOT)):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Forbidden")
            return
        try:
            with open(full, "rb") as f:
                data = f.read()
        except (FileNotFoundError, IsADirectoryError):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return
        ctype = self._guess_type(full)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _guess_type(self, path):
        ext = os.path.splitext(path)[1].lower()
        return {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
        }.get(ext, "application/octet-stream")

    # ==================== API: GET ====================
    def _handle_api_get(self):
        if self.path == "/api/roads" or self.path == "/api/roads/":
            with _data_lock:
                roads = _load_roads()
                counter = len(roads)
            self._json_response(200, {
                "roads": roads,
                "roadCounter": counter,
                "serverTime": datetime.now().isoformat(),
                "totalRoads": len(roads)
            })
        else:
            self._json_response(404, {"error": "Not Found"})

    # ==================== API: POST / PUT / DELETE ====================
    def do_POST(self):
        # DeepSeek 代理
        if self.path == "/api/deepseek":
            return self._handle_deepseek()
        # 新增道路
        if self.path == "/api/roads" or self.path == "/api/roads/":
            return self._handle_add_road()
        self._json_response(404, {"error": "Not Found"})

    def do_PUT(self):
        # 更新道路: PUT /api/roads/<id>
        prefix = "/api/roads/"
        if self.path.startswith(prefix):
            road_id = self.path[len(prefix):]
            return self._handle_update_road(road_id)
        self._json_response(404, {"error": "Not Found"})

    def do_DELETE(self):
        # 删除道路: DELETE /api/roads/<id>
        prefix = "/api/roads/"
        if self.path.startswith(prefix):
            road_id = self.path[len(prefix):]
            return self._handle_delete_road(road_id)
        self._json_response(404, {"error": "Not Found"})

    # ---- 道路 CRUD 实现 ----

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))
        return {}

    def _handle_add_road(self):
        """新增一条道路"""
        try:
            road_data = self._read_body()
            if not road_data.get("name"):
                return self._json_response(400, {"error": "道路名称不能为空"})
            with _data_lock:
                roads = _load_roads()
                # 重名检查
                if any(r["name"] == road_data["name"] for r in roads):
                    return self._json_response(409, {"error": f"已存在同名道路: {road_data['name']}"})
                # 补充字段
                road_data["createdAt"] = datetime.now().isoformat()
                road_data["updatedAt"] = road_data["createdAt"]
                roads.append(road_data)
                _save_roads(roads)
            return self._json_response(201, {
                "success": True,
                "road": road_data,
                "message": f"道路「{road_data['name']}」已添加"
            })
        except json.JSONDecodeError as e:
            return self._json_response(400, {"error": f"请求体 JSON 解析失败: {e}"})
        except Exception as e:
            return self._json_response(500, {"error": str(e)})

    def _handle_update_road(self, road_id):
        """更新指定 ID 的道路"""
        try:
            update_data = self._read_body()
            with _data_lock:
                roads = _load_roads()
                idx = None
                for i, r in enumerate(roads):
                    if r.get("id") == road_id:
                        idx = i
                        break
                if idx is None:
                    return self._json_response(404, {"error": f"未找到道路: {road_id}"})
                # 合并更新（保留 id 和 createdAt）
                roads[idx].update(update_data)
                roads[idx]["id"] = road_id  # 确保 ID 不被覆盖
                if "createdAt" not in roads[idx]:
                    roads[idx]["createdAt"] = datetime.now().isoformat()
                roads[idx]["updatedAt"] = datetime.now().isoformat()
                _save_roads(roads)
            return self._json_response(200, {
                "success": True,
                "road": roads[idx],
                "message": f"道路「{roads[idx].get('name', road_id)}」已更新"
            })
        except json.JSONDecodeError as e:
            return self._json_response(400, {"error": f"请求体 JSON 解析失败: {e}"})
        except Exception as e:
            return self._json_response(500, {"error": str(e)})

    def _handle_delete_road(self, road_id):
        """删除指定 ID 的道路"""
        with _data_lock:
            roads = _load_roads()
            idx = None
            name = None
            for i, r in enumerate(roads):
                if r.get("id") == road_id:
                    idx = i
                    name = r.get("name", road_id)
                    break
            if idx is None:
                return self._json_response(404, {"error": f"未找到道路: {road_id}"})
            deleted = roads.pop(idx)
            _save_roads(roads)
        return self._json_response(200, {
            "success": True,
            "deleted": deleted,
            "message": f"道路「{name}」已删除"
        })

    # ---- DeepSeek 代理 (保持不变) ----
    def _handle_deepseek(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
            messages = payload.get("messages", [])
        except Exception as e:
            self._json_response(400, {"error": f"请求体解析失败: {e}"})
            return

        body = json.dumps({
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        req_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        }

        try:
            req = urllib.request.Request(
                DEEPSEEK_API, data=body, headers=req_headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = resp.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(result)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"DeepSeek {e.code}: {detail}"}).encode("utf-8"))
        except Exception as e:
            self._json_response(502, {"error": f"代理转发失败: {e}"})


if __name__ == "__main__":
    # 确保数据文件存在
    if not os.path.exists(DATA_FILE):
        _save_roads([])

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"=" * 55)
        print(f"  武汉市道路病害智能监测平台 — 多用户协作版")
        print(f"=" * 55)
        print(f"  本地访问:  http://localhost:{PORT}")
        print(f"  局域网访问: http://0.0.0.0:{PORT}")
        print(f"  ── API 端点 ──")
        print(f"  GET    /api/roads       获取全部道路")
        print(f"  POST   /api/roads       新增道路")
        print(f"  PUT    /api/roads/<id>  更新道路")
        print(f"  DELETE /api/roads/<id>  删除道路")
        print(f"  POST   /api/deepseek     AI 深度诊断代理")
        print(f"  数据文件: {DATA_FILE}")
        print(f"  按 Ctrl+C 停止。")
        print(f"=" * 55)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务已停止。")
