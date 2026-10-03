"""zsync HTTP 服务层: 单 Handler 双角色, 由入口决定身份。

角色(v0.4 拆分, 取代旧"每机一节点"):
  - server(中央服务器): 接收客户端推送的存档、响应拉取请求、提供 Web GUI。
    仅暴露仓库/任务/日志/静态页/上传接收等端点, 不读写本机 zcode 目录。
  - agent(客户端本机代理): 127.0.0.1:8643, 读写本机 zcode 目录,
    带 CORS 头供中央服务器页面跨源调用; 客户端桌面 GUI 也由它同源伺服。
    「项目备份」= 把本机项目构建成单压缩包(.ztar)并推送到配置的远端仓库。
    「远端仓库/恢复」= 浏览远端(或本机)存档, 拉取到本机恢复(含路径重映射、
    tasks-index 会话列表索引写入)。

API(均返回 {"ok": bool, ...}; [A]=仅 agent, [S]=仅 server):
  GET  /api/state                       节点状态(角色/本地 zcode 信息 + 远端配置)
  POST /api/settings [A]                {zcode_home?, remote_url?, remote_token?}
  GET  /api/projects [A]                本节点本地项目清单
  GET  /api/project-detail?project_id= [A] 项目详情: git 状态 + 会话列表(只读)
  GET  /api/session?sid=&offset=&limit= [A] 会话内容浏览(消息/part, 只读, 尾部分页)
  POST /api/git-fetch [A]               {project_id} 显式联网 git fetch(仅更新远端引用)
  POST /api/project-config [A]          {project_id, components?, source_filter?}
  GET  /api/filetree?project_id=..&rel=.. [A] 项目文件树(带忽略标记, 供筛选器)
  POST /api/build [A]                   {project_id, archive_id?, live?, push?} -> job
  POST /api/push [A]                    {archive_id}  推送本地存档到远端 -> job
  GET  /api/archives                    本机 store 存档
  GET  /api/archives/{id}/manifest | /download
  POST /api/archives/{id}/delete
  POST /api/restore [A]                 {archive_id | remote{url,token,archive_id},
                                          target_path, components} -> job
  POST /api/remote/list [A]             {url?, token?}  浏览远端存档(默认用节点配置)
  POST /api/upload/{id}/manifest | /ztar   接收节点推送 [S 实际使用]
  POST /api/watch / GET /api/watch [A]  实时备份
  GET  /api/jobs /api/jobs/{id} /api/logs
  GET  /tool.zip [S]                    工具自身打包(目标机引导; 无头启动脚本必带,
                                        ?bin=win|linux|macos|all 额外打入 bin/ 内对应平台单文件产物)
  GET  /api/downloads [S]               bin/ 内可下发的单文件产物清单(名称/大小/sha256/平台)
  GET  /dl/{name} [S]                   直链下发 bin/ 内某个单文件产物
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

from . import zclayout, bundle, client, jobs, watcher, nodeconfig, vmpkg, probe
from .bundle import BundleStore, BundleBuilder, Components, RestoreOptions, restore_bundle
from .nodeconfig import NodeConfig, source_ignored, dir_fully_ignored, DEFAULT_SOURCE_IGNORES

DEFAULT_PORT = 8642
AGENT_PORT = 8643
MAX_JSON_BODY = 8 * 1024 * 1024
# manifest 内嵌全部打包文件的逐条记录(~100B/文件), 大项目几十万文件时可达数十 MB,
# 上传 manifest 单独放宽; 普通 API 仍用 MAX_JSON_BODY
MAX_MANIFEST_BODY = 256 * 1024 * 1024

# 角色门控: server(中央服务器)不暴露读写本机 zcode 的客户端端点
AGENT_ONLY_GET = {"/api/projects", "/api/project-detail", "/api/session",
                  "/api/session-trace", "/api/session-system", "/api/filetree",
                  "/api/watch"}
AGENT_ONLY_POST = {"/api/settings", "/api/build", "/api/push", "/api/restore",
                   "/api/watch", "/api/remote/list", "/api/project-config",
                   "/api/git-fetch"}
SERVER_ONLY_GET = {"/tool.zip", "/api/downloads"}


def _artifact_platform(name: str) -> str | None:
    """按 Releases 产物命名惯例归类平台(zsync-client-windows-x86_64.exe → windows)。"""
    n = name.lower()
    if "windows" in n or n.endswith(".exe"):
        return "windows"
    if "linux" in n:
        return "linux"
    if "darwin" in n or "macos" in n or "osx" in n:
        return "macos"
    return None


def _gate(ctx: "ServerContext", path: str, method: str) -> str | None:
    """返回拒绝理由(None=放行)。server 角色拒绝客户端专属端点, 反之亦然。"""
    if ctx.mode == "server":
        if method == "GET" and path in AGENT_ONLY_GET:
            return "该端点属客户端 agent, 服务器不读写本机 zcode 目录"
        if method == "POST" and path in AGENT_ONLY_POST:
            return "该端点属客户端 agent, 服务器不读写本机 zcode 目录"
    else:
        if method == "GET" and path in SERVER_ONLY_GET:
            return "该端点属中央服务器"
    return None


class ServerContext:
    def __init__(self, store_dir: str, port: int, token: str | None = None,
                 web_dir: str | None = None, tool_root: str | None = None,
                 mode: str = "server"):
        self.store = BundleStore(store_dir)
        self.cfg = NodeConfig(store_dir)
        self.port = port
        self.token = token
        self.mode = mode  # server=中央服务器 / agent=客户端本机代理(供服务器页面或桌面 GUI 调用)
        self.jobman = jobs.JobManager()
        self.layout = zclayout.ZcodeLayout(self.cfg.zcode_home)
        self.watchman = watcher.WatchManager(
            self.layout, self.store, self._on_watch_rebuild,
            state_path=os.path.join(store_dir, "watch.json"),
        )
        self.watchman.start()
        self.logs: list[str] = []
        self._loglock = threading.Lock()
        self.web_dir = web_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
        self.tool_root = tool_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # bin/ = 服务端部署时附带的单文件产物(各平台 client exe 等), 供引导页直链下发;
        # 可选目录, 缺失时引导包只含 Python 源码 + 无头启动脚本。
        # 冻结态单文件 server 的 tool_root 在临时解包目录, 改挂到 exe 旁才可部署 bin/
        bin_base = (os.path.dirname(os.path.abspath(sys.executable))
                    if getattr(sys, "frozen", False) else self.tool_root)
        self.bin_dir = os.path.join(bin_base, "bin")
        self._bin_cache: dict[str, tuple[float, int, str]] = {}
        self._bin_lock = threading.Lock()
        self.started_at = time.time()

    def bin_artifacts(self) -> list[dict]:
        """bin/ 内可下发产物清单; sha256 按 (mtime, size) 懒计算缓存。"""
        out: list[dict] = []
        if not os.path.isdir(self.bin_dir):
            return out
        for name in sorted(os.listdir(self.bin_dir)):
            p = os.path.join(self.bin_dir, name)
            if not os.path.isfile(p):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            with self._bin_lock:
                cached = self._bin_cache.get(name)
            if not cached or cached[0] != st.st_mtime or cached[1] != st.st_size:
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                        h.update(chunk)
                cached = (st.st_mtime, st.st_size, h.hexdigest())
                with self._bin_lock:
                    self._bin_cache[name] = cached
            low = name.lower()
            out.append({
                "name": name, "size": st.st_size, "sha256": cached[2],
                "platform": _artifact_platform(name),
                "kind": ("client" if low.startswith("zsync-client")
                         else "server" if low.startswith("zsync-server") else "other"),
            })
        return out

    def reload_layout(self) -> None:
        """设置变更后刷新本节点 zcode 布局(并重启 watcher 用新路径)。"""
        self.layout = zclayout.ZcodeLayout(self.cfg.zcode_home)
        self.watchman.layout = self.layout

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        with self._loglock:
            self.logs.append(line)
            self.logs = self.logs[-500:]
        print(line, flush=True)

    def _on_watch_rebuild(self, w: watcher.ProjectWatcher) -> None:
        archive_id = _live_archive_id(w.label or w.project_id)
        project = {"project_id": w.project_id, "path": w.project_path}
        comps = w.components
        sf = self.cfg.project_config(w.project_id).get("source_filter")
        push_to = self.cfg.remote_url if self.cfg.remote_url else None

        def run(job: jobs.Job):
            job.prog("watch-build", 0, f"实时重建 {archive_id}")
            m = BundleBuilder(self.layout, self.store).build(
                archive_id, project, comps, source_filter=sf,
                keep_staging=True, progress=job.prog)
            out = {"archive_id": archive_id, "stats": m["stats"]}
            if push_to:
                job.prog("push", 95, f"推送至 {push_to}")
                client.upload_ztar(push_to, archive_id, self.store.ztar_path(archive_id),
                                   m, token=self.cfg.remote_token, progress=job.prog)
                out["pushed_to"] = push_to
            return out

        self.jobman.start("build", f"实时备份 {w.label or w.project_id}", run)
        self.log(f"watch 触发重建: {archive_id}" + (f" -> {push_to}" if push_to else ""))

    def projects_map(self) -> dict:
        return {p.project_id: p for p in zclayout.list_projects(self.layout)}


def _live_archive_id(label: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", label).strip("_") or "project"
    return f"{safe}_live"


def _ts_archive_id(label: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", label).strip("_") or "project"
    return f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}"


def _check_token(ctx: ServerContext, handler: BaseHTTPRequestHandler) -> bool:
    if not ctx.token:
        return True
    supplied = handler.headers.get("X-ZSync-Token") or ""
    if not supplied:
        q = parse_qs(urlparse(handler.path).query)
        supplied = (q.get("token") or [""])[0]
    return supplied == ctx.token


class Handler(BaseHTTPRequestHandler):
    ctx: ServerContext = None  # type: ignore[assignment]
    protocol_version = "HTTP/1.1"
    server_version = "zsync/0.4"

    def log_message(self, fmt, *args):
        pass

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        # 允许局域网服务器页面(私有地址空间)访问本机 loopback agent
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send_json(self, obj, status: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _send_error_json(self, msg: str, status: int = 400) -> None:
        self._send_json({"ok": False, "error": msg}, status)

    def _read_json(self, max_bytes: int = MAX_JSON_BODY) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > max_bytes:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _send_file(self, path: str, ctype: str, download: str | None = None) -> None:
        if not os.path.isfile(path):
            self._send_error_json("文件不存在", 404)
            return
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        # GUI 三件套始终走协商缓存, 避免 Python/前端改动后浏览器拿旧资源
        if ctype.startswith("text/html") or "javascript" in ctype or "css" in ctype:
            self.send_header("Cache-Control", "no-cache")
        self._cors_headers()
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 4 * 1024 * 1024)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-ZSync-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        try:
            u = urlparse(self.path)
            q = parse_qs(u.query)
            path = unquote(u.path)
            if path == "/" or path == "/index.html":
                self._send_file(os.path.join(self.ctx.web_dir, "index.html"), "text/html; charset=utf-8")
                return
            if path == "/app.js":
                self._send_file(os.path.join(self.ctx.web_dir, "app.js"), "application/javascript; charset=utf-8")
                return
            if path == "/style.css":
                self._send_file(os.path.join(self.ctx.web_dir, "style.css"), "text/css; charset=utf-8")
                return
            if path == "/icon.png":
                self._send_file(os.path.join(self.ctx.web_dir, "icon.png"), "image/png")
                return
            if path == "/tool.zip":
                if self.ctx.mode != "server":
                    self._send_error_json("该端点属中央服务器", 404)
                    return
                self._send_tool_zip(q)
                return
            m = re.match(r"^/dl/([^/]+)$", path)
            if m:
                if self.ctx.mode != "server":
                    self._send_error_json("该端点属中央服务器", 404)
                    return
                self._send_bin_file(m.group(1))
                return
            if not path.startswith("/api/"):
                self._send_error_json("未知路径", 404)
                return
            if not _check_token(self.ctx, self):
                self._send_error_json("token 校验失败", 401)
                return
            denied = _gate(self.ctx, path, "GET")
            if denied:
                self._send_error_json(denied, 404)
                return

            if path == "/api/state":
                self._api_state()
            elif path == "/api/projects":
                self._send_json({"ok": True, "projects": [
                    {**p.to_dict(), "config": self.ctx.cfg.project_config(p.project_id)}
                    for p in zclayout.list_projects(self.ctx.layout)]})
            elif path == "/api/archives":
                self._send_json({"ok": True, "archives": self.ctx.store.list_archives()})
            elif path == "/api/jobs":
                self._send_json({"ok": True, "jobs": self.ctx.jobman.list_jobs()})
            elif path == "/api/logs":
                with self.ctx._loglock:
                    self._send_json({"ok": True, "logs": self.ctx.logs[-200:]})
            elif path == "/api/watch":
                self._send_json({"ok": True, "watchers": self.ctx.watchman.list()})
            elif path == "/api/filetree":
                self._api_filetree(q)
            elif path == "/api/project-detail":
                self._api_project_detail(q)
            elif path == "/api/session":
                self._api_session(q)
            elif path == "/api/session-trace":
                self._api_session_trace(q)
            elif path == "/api/session-system":
                self._api_session_system(q)
            elif path == "/api/downloads":
                self._send_json({"ok": True, "downloads": self.ctx.bin_artifacts()})
            elif path == "/api/vmpkg":
                self._api_vmpkg_list()
            else:
                m = re.match(r"^/api/jobs/([0-9a-f]+)$", path)
                if m:
                    job = self.ctx.jobman.get(m.group(1))
                    self._send_json(job.to_dict() if job else {"ok": False, "error": "任务不存在"}, 200 if job else 404)
                    return
                m = re.match(r"^/api/archives/([^/]+)/manifest$", path)
                if m:
                    man = self.ctx.store.manifest(m.group(1))
                    self._send_json({"ok": True, "manifest": man} if man else {"ok": False, "error": "归档不存在"}, 200 if man else 404)
                    return
                m = re.match(r"^/api/archives/([^/]+)/download$", path)
                if m:
                    self._send_file(self.ctx.store.ztar_path(m.group(1)), "application/gzip")
                    return
                m = re.match(r"^/api/vmpkg/([^/]+)/(download|manifest)$", path)
                if m:
                    if m.group(2) == "manifest":
                        self._vmpkg_manifest(m.group(1))
                    else:
                        self._vmpkg_download(m.group(1))
                    return
                self._send_error_json("未知 API", 404)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            self.ctx.log(f"GET {self.path} 异常: {e}")
            try:
                self._send_error_json(str(e), 500)
            except OSError:
                pass

    def do_POST(self):  # noqa: N802
        try:
            u = urlparse(self.path)
            path = unquote(u.path)
            if not path.startswith("/api/"):
                self._send_error_json("未知路径", 404)
                return
            if not _check_token(self.ctx, self):
                self._send_error_json("token 校验失败", 401)
                return
            denied = _gate(self.ctx, path, "POST")
            if denied:
                self._send_error_json(denied, 404)
                return

            m = re.match(r"^/api/upload/([^/]+)/ztar$", path)
            if m:
                self._recv_upload_ztar(m.group(1))
                return
            if path.endswith("/manifest") and path.startswith("/api/upload/"):
                aid = path[len("/api/upload/"):-len("/manifest")]
                self._recv_upload_manifest(unquote(aid))
                return

            body = self._read_json()
            if path == "/api/settings":
                self._api_settings(body)
            elif path == "/api/build":
                self._api_build(body)
            elif path == "/api/push":
                self._api_push(body)
            elif path == "/api/watch":
                self._api_watch(body)
            elif path == "/api/restore":
                self._api_restore(body)
            elif path == "/api/remote/list":
                self._api_remote_list(body)
            elif path == "/api/project-config":
                self._api_project_config(body)
            elif path == "/api/git-fetch":
                self._api_git_fetch(body)
            elif path == "/api/vmpkg":
                self._api_vmpkg(body)
            else:
                m = re.match(r"^/api/archives/([^/]+)/delete$", path)
                if m:
                    ok = self.ctx.store.delete(m.group(1))
                    self.ctx.log(f"删除归档 {m.group(1)}: {'ok' if ok else '不存在'}")
                    self._send_json({"ok": ok})
                    return
                self._send_error_json("未知 API", 404)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except json.JSONDecodeError:
            self._send_error_json("请求体不是合法 JSON")
        except Exception as e:  # noqa: BLE001
            self.ctx.log(f"POST {self.path} 异常: {e}")
            try:
                self._send_error_json(str(e), 500)
            except OSError:
                pass

    # ---------- 节点状态/设置 ----------
    def _api_state(self):
        ctx = self.ctx
        layout = ctx.layout
        pub = ctx.cfg.public()
        # 不在此处探测远端健康: 远端不可达时曾把 /api/state 拖到超时,
        # 连通性由设置页「测试连接」(/api/remote/list) 显式检查
        self._send_json({
            "ok": True,
            "version": "0.4.1",
            "mode": ctx.mode,
            "server": {
                "port": ctx.port,
                "started_at": ctx.started_at,
                "store_dir": ctx.store.dir,
                "token_required": bool(ctx.token),
                "hostname": _hostname(),
                "lan_ips": _lan_ips(),
            },
            "local": {
                "zcode_home": layout.home,
                "default_zcode_home": pub["default_zcode_home"],
                "home_exists": pub["home_exists"],
                "db_exists": layout.exists(),
                "cli_version": zclayout.zcode_cli_version(),
                "hostname": _hostname(),
                "platform": f"{os.name}/{sys.platform}",
            },
            "remote": {"url": ctx.cfg.remote_url, "token_set": bool(ctx.cfg.remote_token)},
            "projects_count": len(zclayout.list_projects(layout)),
            "archives_count": len(ctx.store.list_archives()),
            "watchers": ctx.watchman.list(),
            "jobs_recent": ctx.jobman.list_jobs()[:5],
        })

    def _api_settings(self, body: dict):
        try:
            cfg = self.ctx.cfg.update(
                zcode_home=body.get("zcode_home"),
                remote_url=body.get("remote_url"),
                remote_token=body.get("remote_token"),
            )
        except ValueError as e:
            self._send_error_json(str(e))
            return
        self.ctx.reload_layout()
        self.ctx.log(f"节点设置已更新: zcode_home={cfg['zcode_home']} remote={cfg['remote']['url'] or '(无)'}")
        self._send_json({"ok": True, "settings": cfg,
                         "local": {"zcode_home": self.ctx.layout.home,
                                   "db_exists": self.ctx.layout.exists()}})

    def _api_project_config(self, body: dict):
        pid = body.get("project_id")
        if not pid:
            self._send_error_json("缺少 project_id")
            return
        cfg = self.ctx.cfg.set_project_config(
            pid, components=body.get("components"), source_filter=body.get("source_filter"))
        self._send_json({"ok": True, "config": cfg})

    def _api_filetree(self, q: dict):
        pid = (q.get("project_id") or [""])[0]
        rel = (q.get("rel") or [""])[0]
        p = self.ctx.projects_map().get(pid)
        if not p or not p.path:
            self._send_error_json(f"本地项目不存在: {pid}")
            return
        base = os.path.normpath(os.path.join(p.path, rel)) if rel else p.path
        if not base.lower().startswith(os.path.normpath(p.path).lower()):
            self._send_error_json("非法路径")
            return
        sf = self.ctx.cfg.project_config(pid).get("source_filter") or {}
        entries = []
        try:
            for name in sorted(os.listdir(base)):
                full = os.path.join(base, name)
                relp = (rel + "/" + name) if rel else name
                if os.path.isdir(full):
                    ignored = dir_fully_ignored(relp, sf)
                    n_children = 0
                    try:
                        n_children = len(os.listdir(full))
                    except OSError:
                        pass
                    entries.append({"name": name, "type": "dir", "rel": relp,
                                    "ignored": ignored, "children": n_children,
                                    "size": _dir_size(full, limit=20000)})
                else:
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        size = 0
                    entries.append({"name": name, "type": "file", "rel": relp,
                                    "ignored": source_ignored(relp, sf), "size": size})
        except OSError as e:
            self._send_error_json(f"读取目录失败: {e}")
            return
        self._send_json({"ok": True, "rel": rel, "entries": entries,
                         "filter": sf, "preset_ignores": DEFAULT_SOURCE_IGNORES})

    # ---------- 项目详情(只读探测: git/会话) ----------
    def _api_project_detail(self, q: dict):
        pid = (q.get("project_id") or [""])[0]
        p = self.ctx.projects_map().get(pid)
        if not p:
            self._send_error_json(f"本地项目不存在: {pid}")
            return
        self._send_json({
            "ok": True,
            "project": p.to_dict(),
            "git": probe.probe_git(p.path),
            "sessions": probe.project_sessions(self.ctx.layout, pid) or [],
        })

    def _api_session(self, q: dict):
        sid = (q.get("sid") or [""])[0]
        if not sid:
            self._send_error_json("缺少 sid")
            return
        try:
            offset = max(0, int((q.get("offset") or ["0"])[0]))
            limit = min(500, max(1, int((q.get("limit") or ["150"])[0])))
        except ValueError:
            offset, limit = 0, 150
        r = probe.read_session(self.ctx.layout, sid, offset_from_end=offset, limit=limit)
        if not r:
            self._send_error_json(f"会话不存在: {sid}", 404)
            return
        self._send_json({"ok": True, **r})

    def _api_session_system(self, q: dict):
        sid = (q.get("sid") or [""])[0]
        if not sid:
            self._send_error_json("缺少 sid")
            return
        self._send_json({"ok": True, **probe.session_system(self.ctx.layout, sid)})

    def _api_session_trace(self, q: dict):
        sid = (q.get("sid") or [""])[0]
        if not sid:
            self._send_error_json("缺少 sid")
            return
        if (q.get("line") or [""])[0]:
            try:
                line_no = int(q["line"][0])
            except ValueError:
                self._send_error_json("line 需为整数")
                return
            d = probe.session_trace_detail(self.ctx.layout, sid, line_no)
            if not d:
                self._send_error_json("轨迹行不存在", 404)
                return
            self._send_json({"ok": True, "detail": d})
            return
        self._send_json({"ok": True, **probe.session_trace_summary(self.ctx.layout, sid)})

    def _api_git_fetch(self, body: dict):
        pid = body.get("project_id")
        p = self.ctx.projects_map().get(pid)
        if not p or not p.path:
            self._send_error_json(f"本地项目不存在: {pid}")
            return
        self.ctx.log(f"git fetch(显式): {p.path}")
        self._send_json(probe.fetch_remote(p.path))

    # ---------- 构建/推送 ----------
    def _api_build(self, body: dict):
        ctx = self.ctx
        pid = body.get("project_id")
        if not pid:
            self._send_error_json("缺少 project_id")
            return
        p = ctx.projects_map().get(pid)
        if not p or not p.path:
            self._send_error_json(f"本机不存在该项目: {pid} (备份只能备份本节点机器上的项目)")
            return
        pcfg = ctx.cfg.project_config(pid)
        comps = Components.from_dict((body.get("components") or pcfg.get("components")))
        sf = body.get("source_filter") or pcfg.get("source_filter")
        live = bool(body.get("live"))
        archive_id = body.get("archive_id") or (
            _live_archive_id(p.name) if live else _ts_archive_id(p.name))
        project = {"project_id": pid, "path": p.path}
        # 推送目标: 请求体显式指定 > 节点配置(中央服务器页面会把 agent 的推送指向自身)
        push_to = body.get("push_url") or ctx.cfg.remote_url or None
        push_token = body.get("push_token") if body.get("push_token") is not None else ctx.cfg.remote_token
        push = body.get("push")
        if push is None:
            push = bool(push_to)
        if not push:
            push_to = None

        def run(job: jobs.Job):
            job.prog("build", 0, f"构建 {archive_id}")
            m = BundleBuilder(ctx.layout, ctx.store).build(
                archive_id, project, comps, source_filter=sf,
                keep_staging=live, progress=job.prog)
            out = {"archive_id": archive_id, "stats": m["stats"],
                   "ztar_bytes": m["ztar_bytes"]}
            if push_to:
                job.prog("push", 95, f"推送至 {push_to}")
                client.upload_ztar(push_to, archive_id, ctx.store.ztar_path(archive_id),
                                   m, token=push_token, progress=job.prog)
                out["pushed_to"] = push_to
            return out

        job = ctx.jobman.start("build", f"备份 {p.name} -> {archive_id}", run)
        ctx.log(f"开始备份 {p.name} -> {archive_id}" + (f" 并推送 {push_to}" if push_to else ""))
        self._send_json({"ok": True, "job_id": job.id, "archive_id": archive_id,
                         "push_to": push_to})

    def _api_push(self, body: dict):
        ctx = self.ctx
        archive_id = body.get("archive_id")
        if not archive_id or not ctx.store.manifest(archive_id):
            self._send_error_json(f"本地归档不存在: {archive_id}")
            return
        base = body.get("url") or ctx.cfg.remote_url
        if not base:
            self._send_error_json("未指定远端(设置页或请求体 url)")
            return
        tok = body.get("token") if body.get("token") is not None else ctx.cfg.remote_token
        m = ctx.store.manifest(archive_id)
        zt = ctx.store.ztar_path(archive_id)

        def run(job: jobs.Job):
            r = client.upload_ztar(base, archive_id, zt, m, token=tok, progress=job.prog)
            return {"archive_id": archive_id, "pushed_to": base, "remote": r}

        job = ctx.jobman.start("push", f"推送 {archive_id} -> {base}", run)
        self._send_json({"ok": True, "job_id": job.id})

    # ---------- 恢复 ----------
    def _api_restore(self, body: dict):
        ctx = self.ctx
        remote = body.get("remote")
        archive_id = body.get("archive_id") or (remote or {}).get("archive_id")
        target_path = body.get("target_path")
        if not archive_id or not target_path:
            self._send_error_json("缺少 archive_id / target_path")
            return
        if not nodeconfig.is_abs_path(target_path):
            self._send_error_json("target_path 需为绝对路径(如 D:\\Project\\xxx 或 /home/me/xxx)")
            return
        comps = Components.from_dict(body.get("components"))
        opts = RestoreOptions(target_path=os.path.abspath(target_path), components=comps)

        if remote:
            rbase = (remote.get("url") or ctx.cfg.remote_url or "").rstrip("/")
            rtoken = remote.get("token") or ctx.cfg.remote_token
            if not rbase:
                self._send_error_json("缺少远端地址(设置页或请求体)")
                return
            pull_dir = os.path.join(ctx.store.dir, "pulls", archive_id)
            zt = os.path.join(pull_dir, "package.ztar")

            def run(job: jobs.Job):
                job.prog("download", 0, f"从 {rbase} 拉取 {archive_id}")
                if os.path.isfile(zt):
                    try:
                        os.remove(zt)
                    except OSError:
                        pass
                client.download_ztar(rbase, archive_id, zt, rtoken, job.prog)
                job.prog("extract", 62, "解包")
                shutil.rmtree(pull_dir + "_x", ignore_errors=True)
                manifest = ctx.store.extract_to(zt, pull_dir + "_x")
                job.prog("restore", 68, "恢复到本机 zcode")
                rep = restore_bundle(pull_dir + "_x", ctx.layout, opts, job.prog)
                return {"manifest": {k: manifest.get(k) for k in ("source", "stats", "components")},
                        "restore": {"db_counts": rep.db_counts,
                                    "tasks_index_rows": rep.tasks_index_rows,
                                    "files_copied": rep.files_copied,
                                    "source_files": rep.source_files,
                                    "verify": rep.verify,
                                    "tasks_verify": rep.tasks_verify,
                                    "warnings": rep.warnings}}

            job = ctx.jobman.start("restore", f"拉取恢复 {archive_id} -> {target_path}", run)
        else:
            bdir = os.path.join(ctx.store.dir, "pulls", archive_id + "_local")
            if not ctx.store.manifest(archive_id):
                self._send_error_json(f"本机存档不存在: {archive_id}")
                return

            def run(job: jobs.Job):
                job.prog("extract", 0, "解包本机存档")
                shutil.rmtree(bdir, ignore_errors=True)
                ctx.store.extract_to(ctx.store.ztar_path(archive_id), bdir)
                job.prog("restore", 10, "恢复到本机 zcode")
                rep = restore_bundle(bdir, ctx.layout, opts, job.prog)
                return {"restore": {"db_counts": rep.db_counts,
                                    "tasks_index_rows": rep.tasks_index_rows,
                                    "files_copied": rep.files_copied,
                                    "source_files": rep.source_files,
                                    "verify": rep.verify,
                                    "tasks_verify": rep.tasks_verify,
                                    "warnings": rep.warnings}}

            job = ctx.jobman.start("restore", f"恢复 {archive_id} -> {target_path}", run)
        ctx.log(f"开始恢复 {archive_id} -> {target_path} (remote={bool(remote)})")
        self._send_json({"ok": True, "job_id": job.id})

    def _api_remote_list(self, body: dict):
        url = (body.get("url") or self.ctx.cfg.remote_url or "").rstrip("/")
        token = body.get("token") if body.get("token") is not None else self.ctx.cfg.remote_token
        if not url:
            self._send_json({"ok": False, "error": "未配置远端服务器"})
            return
        try:
            archives = client.list_remote_archives(url, token)
            self._send_json({"ok": True, "url": url, "archives": archives})
        except client.RemoteError as e:
            self._send_error_json(str(e))

    # ---------- watch ----------
    def _api_watch(self, body: dict):
        ctx = self.ctx
        pid = body.get("project_id")
        enabled = bool(body.get("enabled"))
        if not pid:
            self._send_error_json("缺少 project_id")
            return
        if enabled:
            p = ctx.projects_map().get(pid)
            project_path = body.get("project_path") or (p.path if p else None)
            if not project_path:
                self._send_error_json("无法确定项目路径")
                return
            label = body.get("label") or (p.name if p else pid)
            pcfg = ctx.cfg.project_config(pid)
            comps = Components.from_dict(body.get("components") or pcfg.get("components"))
        else:
            project_path = None
            label = body.get("label", "")
            comps = Components()
        r = ctx.watchman.set_watch(
            pid, project_path, enabled,
            components=comps.to_dict() if enabled else None,
            interval=float(body.get("interval", 20)),
            label=label,
        )
        ctx.log(f"实时备份 {pid}: {'开启' if enabled else '关闭'}")
        self._send_json({"ok": True, **r, "watchers": ctx.watchman.list()})

    # ---------- 上传接收(远端仓库角色) ----------
    def _recv_upload_manifest(self, archive_id: str):
        body = self._read_json(MAX_MANIFEST_BODY)
        manifest = body.get("manifest") or {}
        if not manifest:
            self._send_error_json("缺少 manifest")
            return
        if manifest.get("archive_id") != archive_id:
            self._send_error_json("archive_id 与 manifest 不一致")
            return
        pend = self.ctx.store.manifest_path(archive_id) + ".pending"
        with open(pend, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        self._send_json({"ok": True})

    def _recv_upload_ztar(self, archive_id: str):
        pend = self.ctx.store.manifest_path(archive_id) + ".pending"
        if not os.path.isfile(pend):
            self._send_error_json("请先上传 manifest", 400)
            return
        length = int(self.headers.get("Content-Length") or 0)
        zt = self.ctx.store.ztar_path(archive_id)
        os.makedirs(os.path.dirname(zt), exist_ok=True)
        remaining = length
        with open(zt + ".part", "wb") as out:
            while remaining > 0:
                chunk = self.rfile.read(min(4 * 1024 * 1024, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        if remaining > 0:
            os.remove(zt + ".part")
            self._send_error_json(f"上传不完整: 缺 {remaining} 字节")
            return
        os.replace(zt + ".part", zt)
        os.replace(pend, self.ctx.store.manifest_path(archive_id))
        with open(self.ctx.store.manifest_path(archive_id), encoding="utf-8") as f:
            manifest = json.load(f)
        self.ctx.log(f"接收推送: {archive_id} ({fmt_mb(manifest.get('ztar_bytes', 0))})")
        self._send_json({"ok": True, "archive_id": archive_id,
                         "bytes": manifest.get("ztar_bytes")})

    # ---------- 免 Python 迁移包 ----------
    def _vmpkg_dir(self, pkg_id: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", pkg_id)
        return os.path.join(self.ctx.store.dir, "vmprep", safe)

    def _api_vmpkg(self, body: dict):
        archive_id = body.get("archive_id")
        target_path = body.get("target_path")
        if not archive_id or not target_path:
            self._send_error_json("缺少 archive_id / target_path")
            return
        manifest = self.ctx.store.manifest(archive_id)
        if not manifest:
            self._send_error_json(f"本机存档不存在: {archive_id}")
            return
        pkg_id = body.get("pkg_id") or f"{archive_id}_{time.strftime('%Y%m%d_%H%M%S')}"
        base_db = body.get("base_db") or None
        if base_db and not os.path.isfile(base_db):
            self._send_error_json(f"base_db 不存在: {base_db}")
            return
        base_tasks = body.get("base_tasks_index") or None
        out_dir = self._vmpkg_dir(pkg_id)
        ctx = self.ctx

        def run(job: jobs.Job):
            m = vmpkg.build_migration_package(
                ctx.store, archive_id, os.path.abspath(target_path), out_dir,
                base_db=base_db, base_tasks_index=base_tasks,
                components=body.get("components"), progress=job.prog)
            return {"pkg_id": pkg_id, "package": m,
                    "download": f"/api/vmpkg/{pkg_id}/download"}

        job = ctx.jobman.start("vmpkg", f"迁移包 {archive_id} -> {target_path}", run)
        ctx.log(f"构建迁移包: {pkg_id}")
        self._send_json({"ok": True, "job_id": job.id, "pkg_id": pkg_id})

    def _vmpkg_manifest(self, pkg_id: str) -> None:
        p = os.path.join(self._vmpkg_dir(pkg_id), "package.json")
        if not os.path.isfile(p):
            self._send_error_json("迁移包不存在", 404)
            return
        with open(p, encoding="utf-8") as f:
            self._send_json({"ok": True, "package": json.load(f)})

    def _vmpkg_download(self, pkg_id: str) -> None:
        p = os.path.join(self._vmpkg_dir(pkg_id), "package.tgz")
        if not os.path.isfile(p):
            self._send_error_json("迁移包不存在", 404)
            return
        self._send_file(p, "application/gzip")

    def _api_vmpkg_list(self) -> None:
        base = os.path.join(self.ctx.store.dir, "vmprep")
        out = []
        if os.path.isdir(base):
            for name in os.listdir(base):
                p = os.path.join(base, name, "package.json")
                if os.path.isfile(p):
                    try:
                        with open(p, encoding="utf-8") as f:
                            m = json.load(f)
                        m["pkg_id"] = name
                        m["tgz_exists"] = os.path.isfile(os.path.join(base, name, "package.tgz"))
                        out.append(m)
                    except (OSError, json.JSONDecodeError):
                        continue
        out.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        self._send_json({"ok": True, "packages": out})

    def _send_bin_file(self, name: str):
        """直链下发 bin/ 内产物; 只接受 bin_artifacts() 列出的真实文件名, 杜绝穿越。"""
        if name not in {a["name"] for a in self.ctx.bin_artifacts()}:
            self._send_error_json("产物不存在", 404)
            return
        self._send_file(os.path.join(self.ctx.bin_dir, name),
                        "application/octet-stream", download=name)

    def _send_tool_zip(self, q: dict | None = None):
        """引导包: 共享核心 + web 资产 + 客户端入口 + 启动器, 保持仓库相对布局。

        无头启动脚本永远随包; ?bin=win|linux|macos|all 额外把 bin/ 内对应平台的
        单文件产物打到包根(启动器会优先用它), 产物本身已压缩故以 STORED 写入。
        """
        q = q or {}
        want = (q.get("bin") or [""])[0].lower()
        plat = {"win": "windows", "windows": "windows",
                "linux": "linux", "macos": "macos", "darwin": "macos",
                "all": "all"}.get(want)
        root = self.ctx.tool_root
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for sub in ("zsync", "web", "client"):
                d = os.path.join(root, sub)
                for froot, _d, files in os.walk(d):
                    if "__pycache__" in froot:
                        continue
                    for f in files:
                        if f.endswith((".pyc", ".spec")) or os.path.basename(f) in (
                                "build_exe.py", "build_exe.cmd", "BUILD.md"):
                            continue
                        full = os.path.join(froot, f)
                        zf.write(full, os.path.relpath(full, root))
            for launcher in ("start-agent.cmd", "start-agent.sh"):
                p = os.path.join(root, launcher)
                if os.path.isfile(p):
                    zf.write(p, launcher)
            readme = os.path.join(root, "README.md")
            if os.path.isfile(readme):
                zf.write(readme, "README.md")
            if plat:
                arts = [a for a in self.ctx.bin_artifacts()
                        if plat == "all" or a["platform"] == plat]
                for a in arts:
                    zf.write(os.path.join(self.ctx.bin_dir, a["name"]), a["name"],
                             compress_type=zipfile.ZIP_STORED)
                if not arts:
                    self.ctx.log(f"tool.zip?bin={want} 未命中 bin/ 产物, 已按纯源码包下发")
        data = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def fmt_mb(n: float) -> str:
    return f"{n/1e6:.0f}MB"


def _dir_size(path: str, limit: int = 100000) -> int:
    total = 0
    n = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
            n += 1
            if n > limit:
                return total
    return total


def _lan_ips() -> list[str]:
    ips = []
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def _hostname() -> str:
    return os.environ.get("COMPUTERNAME") or socket.gethostname()


def build_server(port: int | None = None, bind: str | None = None, store_dir: str | None = None,
                 token: str | None = None, mode: str = "server"):
    """构建(但不进入事件循环)HTTP 服务, 返回 (httpd, ctx)。
    供桌面壳等需要自行控制 serve_forever/shutdown 的调用方使用。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    store_dir = store_dir or os.path.join(root, "data")
    if port is None:
        port = AGENT_PORT if mode == "agent" else DEFAULT_PORT
    if bind is None:
        bind = "127.0.0.1" if mode == "agent" else "0.0.0.0"
    ctx = ServerContext(store_dir, port, token, mode=mode)
    Handler.ctx = ctx
    httpd = ThreadingHTTPServer((bind, port), Handler)
    httpd.daemon_threads = True
    ctx.log(f"zsync 已启动[{mode}]: http://{bind}:{port}  (store={store_dir})")
    ctx.log(f"本机 zcode 目录: {ctx.layout.home}  db={'OK' if ctx.layout.exists() else '缺失'}")
    if ctx.cfg.remote_url:
        ctx.log(f"远端仓库: {ctx.cfg.remote_url}")
    for ip in _lan_ips():
        ctx.log(f"  局域网访问: http://{ip}:{port}")
    if mode == "agent":
        ctx.log("  agent 模式: 供本机浏览器跨源访问中央服务器页面 / 桌面 GUI 同源调用")
    else:
        arts = ctx.bin_artifacts()
        if arts:
            ctx.log(f"  bin/ 下发产物: {', '.join(a['name'] for a in arts)}")
        if not token:
            ctx.log("  警告: 未设置 token, 局域网内任何机器都可访问(开发模式)")
    return httpd, ctx


def serve(port: int | None = None, bind: str | None = None, store_dir: str | None = None,
          token: str | None = None, mode: str = "server") -> None:
    """前台运行。mode: server=中央服务器(默认 0.0.0.0:8642, 接收推送/拉取+Web GUI);
    agent=客户端本机代理(默认 127.0.0.1:8643, 读写本机 zcode 目录,
    供中央服务器页面经浏览器跨源调用, 亦为桌面 GUI 的同源后端)。"""
    httpd, ctx = build_server(port, bind, store_dir, token, mode)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        ctx.log("服务停止")
    finally:
        ctx.watchman.stop()
        httpd.server_close()
