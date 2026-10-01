"""节点设置与项目配置持久化(<store>/node.json)。

节点 = 运行 zsync 的一台机器。设置包含:
  zcode_home   本机 zcode 配置目录(默认 ~/.zcode, 可迁移到任意盘)
  remote       远端仓库服务器 {url, token} (可选; 为空则只使用本地存储)
  projects     每项目的备份配置: 组件开关 + 源码文件筛选 + watch 设置
"""
from __future__ import annotations

import json
import os
import re
import threading

DEFAULT_SOURCE_IGNORES = [
    "node_modules", "__pycache__", ".venv", "venv", "env",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", "nuxt-dist",
    "dist", "build", "out", "target", "obj", "bin",
    ".gradle", ".idea", ".vscode/setting*", "*.pyc", "*.pyo",
    ".DS_Store", "Thumbs.db", "*.log", "*.tmp",
    ".zsync_cache", "coverage", ".nyc_output", "__MACOSX",
    "*.ztar", "*.manifest.json",
]

DEFAULT_COMPONENTS = {
    "sessions": True, "rollout": True, "artifacts": True, "agents": True,
    "exec_logs": True, "memory": True, "source": True, "include_git": True,
    "global_skills": False, "global_constraints": False,
    "global_plugins": False, "global_agents_md": False,
}


def default_zcode_home() -> str:
    return os.path.join(os.path.expanduser("~"), ".zcode")


def is_abs_path(p: str) -> bool:
    """Windows 盘符/UNC 或 Unix 绝对路径。"""
    if not p:
        return False
    if re.match(r"^[A-Za-z]:[\\/]", p.replace("/", "\\")):
        return True
    return p.startswith("//") or p.startswith("\\\\") or p.startswith("/")


class NodeConfig:
    def __init__(self, store_dir: str):
        self.path = os.path.join(store_dir, "node.json")
        self._lock = threading.RLock()  # 可重入: update() 持锁调用 public()
        self._data: dict = {
            "zcode_home": os.environ.get("ZCODE_HOME") or default_zcode_home(),
            "remote": {"url": "", "token": ""},
            "projects": {},
        }
        self._load()

    def _load(self) -> None:
        if os.path.isfile(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    saved = json.load(f)
                for k in ("zcode_home", "remote", "projects"):
                    if k in saved:
                        self._data[k] = saved[k]
            except (OSError, json.JSONDecodeError):
                pass

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---- 全局 ----
    @property
    def zcode_home(self) -> str:
        return self._data["zcode_home"] or default_zcode_home()

    @property
    def remote_url(self) -> str:
        return (self._data.get("remote") or {}).get("url", "")

    @property
    def remote_token(self) -> str:
        return (self._data.get("remote") or {}).get("token", "") or None

    def update(self, zcode_home: str | None = None, remote_url: str | None = None,
               remote_token: str | None = None) -> dict:
        with self._lock:
            if zcode_home is not None:
                if not is_abs_path(zcode_home):
                    raise ValueError("zcode_home 需为绝对路径(如 C:\\Users\\me\\.zcode 或 /home/me/.zcode)")
                self._data["zcode_home"] = os.path.abspath(zcode_home)
            if remote_url is not None:
                url = remote_url.strip().rstrip("/")
                if url and not re.match(r"^https?://", url):
                    raise ValueError("远端地址需以 http:// 或 https:// 开头")
                self._data.setdefault("remote", {})["url"] = url
            if remote_token is not None:
                self._data.setdefault("remote", {})["token"] = remote_token
            self._save()
            return self.public()

    def public(self) -> dict:
        with self._lock:
            remote = dict(self._data.get("remote") or {})
            home = self._data.get("zcode_home") or default_zcode_home()
            return {
                "zcode_home": home,
                "default_zcode_home": default_zcode_home(),
                "home_exists": os.path.isdir(home),
                "remote": {"url": remote.get("url", ""), "token_set": bool(remote.get("token"))},
            }

    # ---- 项目级 ----
    def project_config(self, project_id: str) -> dict:
        with self._lock:
            p = dict(self._data["projects"].get(project_id) or {})
        p.setdefault("components", dict(DEFAULT_COMPONENTS))
        p.setdefault("source_filter", {"preset_ignores": True, "extra_ignores": [], "forced_includes": []})
        return p

    def set_project_config(self, project_id: str, components: dict | None = None,
                           source_filter: dict | None = None) -> dict:
        with self._lock:
            p = self._data["projects"].setdefault(project_id, {})
            if components:
                c = dict(p.get("components") or DEFAULT_COMPONENTS)
                c.update({k: v for k, v in components.items() if k in DEFAULT_COMPONENTS})
                p["components"] = c
            if source_filter:
                sf = dict(p.get("source_filter") or {})
                sf.update(source_filter)
                p["source_filter"] = sf
            self._save()
            cfg = json.loads(json.dumps(p))
        cfg.setdefault("components", dict(DEFAULT_COMPONENTS))
        cfg.setdefault("source_filter", {})
        return cfg


# ---------------- 源码文件筛选 ----------------

def _match_any(rel: str, name: str, patterns) -> bool:
    import fnmatch

    rel_n = rel.replace("\\", "/")
    for pat in patterns or []:
        pat = pat.replace("\\", "/").strip()
        if not pat:
            continue
        if "*" in pat or "?" in pat:
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel_n, pat):
                return True
            # 路径中任意一段匹配 (如 site/**)
            if any(fnmatch.fnmatch(seg, pat) for seg in rel_n.split("/")):
                return True
        else:
            if name == pat or rel_n == pat or rel_n.startswith(pat + "/"):
                return True
            if any(seg == pat for seg in rel_n.split("/")):
                return True
    return False


def source_ignored(rel: str, source_filter: dict) -> bool:
    """判断项目内相对路径是否被筛选规则忽略。"""
    name = rel.replace("\\", "/").split("/")[-1]
    sf = source_filter or {}
    if _match_any(rel, name, sf.get("forced_includes")):
        return False
    if sf.get("preset_ignores", True) and _match_any(rel, name, DEFAULT_SOURCE_IGNORES):
        return True
    if _match_any(rel, name, sf.get("extra_ignores")):
        return True
    return False


def dir_fully_ignored(rel: str, source_filter: dict) -> bool:
    """目录整体被忽略(用于文件树剪枝)。"""
    name = rel.replace("\\", "/").split("/")[-1]
    sf = source_filter or {}
    if _match_any(rel, name, sf.get("forced_includes")):
        return False
    if sf.get("preset_ignores", True) and _match_any(rel, name, DEFAULT_SOURCE_IGNORES):
        return True
    return _match_any(rel, name, sf.get("extra_ignores"))
