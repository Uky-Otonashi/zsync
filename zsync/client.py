"""远程传输: 与远端仓库(zsync server)之间的单包(.ztar)上传/下载。"""
from __future__ import annotations

import http.client
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request


class RemoteError(RuntimeError):
    pass


# 直连: 忽略环境代理(http_proxy 等可能指向不在线的本地代理), 目标均为本机/局域网地址
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _req(method: str, url: str, body: bytes | None = None,
         headers: dict | None = None, timeout: int = 60) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        raise RemoteError(f"HTTP {e.code} {url}: {e.read()[:300]!r}") from e
    except urllib.error.URLError as e:
        raise RemoteError(f"无法连接 {url}: {e.reason}") from e
    except OSError as e:  # 读阶段 socket.timeout 等不包装为 URLError
        raise RemoteError(f"访问 {url} 失败: {e}") from e


def json_api(method: str, base: str, path: str, payload: dict | None = None,
             token: str | None = None, timeout: int = 60) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-ZSync-Token"] = token
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    status, data = _req(method, base.rstrip("/") + path, body, headers, timeout)
    try:
        return json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "raw": data[:500].decode("utf-8", "replace")}


def list_remote_archives(base: str, token: str | None = None) -> list[dict]:
    r = json_api("GET", base, "/api/archives", token=token)
    if not r.get("ok"):
        raise RemoteError(r.get("error", "远端返回异常"))
    return r.get("archives", [])


def remote_state(base: str, token: str | None = None, timeout: int = 60) -> dict:
    r = json_api("GET", base, "/api/state", token=token, timeout=timeout)
    if not r.get("ok"):
        raise RemoteError(r.get("error", "远端返回异常"))
    return r


def download_ztar(base: str, archive_id: str, dest_file: str,
                  token: str | None = None, progress=None) -> dict:
    """下载远端 .ztar 到 dest_file, 返回 manifest。"""
    r = json_api("GET", base,
                 f"/api/archives/{urllib.parse.quote(archive_id)}/manifest", token)
    if not r.get("ok"):
        raise RemoteError(r.get("error", "归档不存在"))
    manifest = r.get("manifest", {})
    q = urllib.parse.quote(archive_id)
    url = base.rstrip("/") + f"/api/archives/{q}/download"
    headers = {"X-ZSync-Token": token} if token else {}
    req = urllib.request.Request(url, headers=headers)
    total = manifest.get("ztar_bytes", 0)
    done = 0
    os.makedirs(os.path.dirname(dest_file) or ".", exist_ok=True)
    try:
        with _opener.open(req, timeout=600) as resp, open(dest_file + ".part", "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress("download", 60 * done / total,
                             f"下载 {done/1e6:.0f}/{total/1e6:.0f}MB")
    except urllib.error.URLError as e:
        if os.path.exists(dest_file + ".part"):
            os.remove(dest_file + ".part")
        raise RemoteError(f"下载失败: {e}") from e
    os.replace(dest_file + ".part", dest_file)
    actual = os.path.getsize(dest_file)
    if total and actual != total:
        os.remove(dest_file)
        raise RemoteError(f"下载不完整: {actual}/{total} 字节")
    if progress:
        progress("download", 60, f"下载完成 {actual/1e6:.0f}MB")
    return manifest


def upload_ztar(base: str, archive_id: str, ztar_file: str, manifest: dict,
                token: str | None = None, progress=None) -> dict:
    """把本地 .ztar 上传到远端仓库: 先传 manifest(JSON), 再流式传包体。"""
    if not os.path.isfile(ztar_file):
        raise RemoteError(f"归档包不存在: {ztar_file}")
    r = json_api("POST", base, f"/api/upload/{urllib.parse.quote(archive_id)}/manifest",
                 {"manifest": manifest}, token)
    if not r.get("ok"):
        raise RemoteError(r.get("error", "manifest 上传失败"))
    size = os.path.getsize(ztar_file)
    u = urllib.parse.urlparse(base)
    path = f"/api/upload/{urllib.parse.quote(archive_id)}/ztar?size={size}"
    if u.scheme == "https":
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=1800,
                                           context=ssl._create_unverified_context())
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=1800)
    try:
        conn.putrequest("POST", path)
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(size))
        if token:
            conn.putheader("X-ZSync-Token", token)
        conn.endheaders()
        sent = 0
        with open(ztar_file, "rb") as fh:
            while True:
                chunk = fh.read(4 * 1024 * 1024)
                if not chunk:
                    break
                conn.send(chunk)
                sent += len(chunk)
                if progress:
                    progress("upload", 95 * sent / max(size, 1),
                             f"上传 {sent/1e6:.0f}/{size/1e6:.0f}MB")
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != 200:
            raise RemoteError(f"上传失败 HTTP {resp.status}: {body[:300]!r}")
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RemoteError(f"远端响应异常: {e}") from e
    finally:
        conn.close()
