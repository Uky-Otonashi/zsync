"""zcode 数据目录布局与项目标识推导。

约定(经 0.16.9 版实测验证):
  zcode home       ~/.zcode                    (环境变量 ZCODE_HOME 可覆盖)
  会话数据库       ~/.zcode/cli/db/db.sqlite   (WAL 模式, 伴随 -wal/-shm)
  模型调用轨迹     ~/.zcode/cli/rollout/model-io-<session_id>.jsonl
  子代理数据       ~/.zcode/cli/agents/<session_id>/ 及 *.md
  工具产物         ~/.zcode/cli/artifacts/<session_id>/
  工具执行日志     ~/.zcode/cli/exec/<session_id>/
  项目记忆         ~/.zcode/cli/memories/projects/<slug>/memory/
  全局技能         ~/.zcode/skills/
  插件开关         ~/.zcode/cli/config.json
  全局约束文件     ~/.zcode/AGENTS.md / CLAUDE.md (如存在)

  project_id = 'proj_' + 小写完整路径, 其中反斜杠/正斜杠/冒号均替换为 '-'
  memory slug = 路径最后一段(小写) + '-' + sha256(小写完整路径)[:16]

  subagent_child 会话的 project_id 由其运行目录推导, 可能是项目内部子目录
  (如 _render/_tmp/dist); 项目定义与统计只认根会话, subagent 按 parent 链
  归属根项目(见 session_owner_map)。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field


def zcode_home() -> str:
    home = os.environ.get("ZCODE_HOME")
    if home:
        return os.path.abspath(home)
    return os.path.join(os.path.expanduser("~"), ".zcode")


def win_norm(path: str) -> str:
    """归一化为反斜杠小写形式, 用于推导标识。"""
    return path.replace("/", "\\").lower()


def project_id_for(path: str) -> str:
    # 实测规则: 去掉盘符冒号, 反斜杠替换为 '-', 例 d:\project\x -> proj_d-project-x
    return "proj_" + win_norm(path).replace(":", "").replace("\\", "-")


def memory_slug_for(path: str) -> str:
    norm = path.replace("/", "\\").rstrip("\\")
    base = os.path.basename(norm).lower()
    return f"{base}-{hashlib.sha256(win_norm(path).encode('utf-8')).hexdigest()[:16]}"


@dataclass
class ZcodeLayout:
    home: str

    @property
    def cli_dir(self) -> str:
        return os.path.join(self.home, "cli")

    @property
    def db_path(self) -> str:
        return os.path.join(self.cli_dir, "db", "db.sqlite")

    @property
    def rollout_dir(self) -> str:
        return os.path.join(self.cli_dir, "rollout")

    @property
    def agents_dir(self) -> str:
        return os.path.join(self.cli_dir, "agents")

    @property
    def artifacts_dir(self) -> str:
        return os.path.join(self.cli_dir, "artifacts")

    @property
    def exec_dir(self) -> str:
        return os.path.join(self.cli_dir, "exec")

    @property
    def memories_dir(self) -> str:
        return os.path.join(self.cli_dir, "memories", "projects")

    def memory_dir_for(self, path: str) -> str:
        return os.path.join(self.memories_dir, memory_slug_for(path), "memory")

    @property
    def skills_dir(self) -> str:
        return os.path.join(self.home, "skills")

    @property
    def plugins_config(self) -> str:
        return os.path.join(self.cli_dir, "config.json")

    def global_constraint_files(self) -> list[str]:
        found = []
        for name in ("AGENTS.md", "CLAUDE.md"):
            p = os.path.join(self.home, name)
            if os.path.isfile(p):
                found.append(p)
        return found

    def exists(self) -> bool:
        return os.path.isfile(self.db_path)


def default_layout() -> ZcodeLayout:
    return ZcodeLayout(zcode_home())


def open_ro(db_path: str) -> tuple[sqlite3.Connection, str | None]:
    """只读打开(兼容 WAL). 若被锁则回退为快照副本, 返回 (conn, 临时目录或None)."""
    uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=20)
        con.execute("SELECT count(*) FROM session").fetchone()
        return con, None
    except sqlite3.Error:
        tmp = tempfile.mkdtemp(prefix="zsync_snap_")
        for suffix in ("", "-wal", "-shm"):
            src = db_path + suffix
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(tmp, os.path.basename(src)))
        con = sqlite3.connect(os.path.join(tmp, os.path.basename(db_path)))
        return con, tmp


@dataclass
class ProjectInfo:
    project_id: str
    path: str | None
    name: str
    sessions: int = 0
    last_active: int | None = None
    rollout_bytes: int = 0
    memory_files: int = 0
    versions: list[str] = field(default_factory=list)
    in_sidebar: int = 0   # 会话列表索引中的会话数; 0 且 sessions>0 = 已移出侧边栏的"幽灵"项目

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "path": self.path,
            "name": self.name,
            "sessions": self.sessions,
            "last_active": self.last_active,
            "rollout_bytes": self.rollout_bytes,
            "memory_files": self.memory_files,
            "versions": self.versions,
            "in_sidebar": self.in_sidebar,
            "memory_slug": memory_slug_for(self.path) if self.path else None,
        }


def _trusted_dir(directory: str | None) -> str | None:
    """session.directory 可信当且仅当是绝对路径(Windows 盘符或 Unix 根)。"""
    if not directory:
        return None
    if re.match(r"^[A-Za-z]:[\\/]", directory):
        return directory
    if directory.startswith("/"):
        return directory
    return None


def session_owner_map(con: sqlite3.Connection) -> dict[str, str]:
    """返回 {session_id: 归属 project_id}。

    subagent_child 会话的 project_id 由其运行目录推导, 常是项目内部子目录
    (如 _render/_tmp/dist), 不代表真实项目; 将其归属到 parent 链上最近的
    非 subagent 祖先会话所在项目。链断裂或成环时回退自身 project_id
    (仍按独立项目处理, 保证数据不丢)。
    """
    try:
        rows = con.execute(
            "SELECT id, parent_id, task_type, project_id FROM session"
        ).fetchall()
    except sqlite3.OperationalError:
        # 旧版库无 parent_id/task_type 列: 全部按自身 project_id
        return {sid: pid for sid, pid in con.execute(
            "SELECT id, project_id FROM session").fetchall()}
    meta = {sid: (parent, ttype, pid) for sid, parent, ttype, pid in rows}

    def root_project(sid: str) -> str | None:
        seen: set[str] = set()
        cur = sid
        while True:
            if cur in seen or cur not in meta:
                return meta[sid][2]
            seen.add(cur)
            parent, ttype, pid = meta[cur]
            if ttype != "subagent_child" or not parent:
                return pid
            cur = parent

    return {sid: root_project(sid) for sid in meta}


def _sidebar_session_ids(zcode_home: str) -> set:
    """侧边栏会话列表索引中出现的全部会话 id(读不到返回空集)。"""
    from . import tasksindex
    idx = tasksindex.tasks_index_path(zcode_home)
    if not os.path.isfile(idx):
        return set()
    try:
        uri = "file:" + idx.replace("\\", "/") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            return {r[0] for r in con.execute("SELECT task_id FROM tasks")}
        finally:
            con.close()
    except sqlite3.Error:
        return set()


def list_projects(layout: ZcodeLayout | None = None) -> list[ProjectInfo]:
    """从会话数据库读取全部项目及统计信息(只读, 不打扰运行中的 zcode)。

    以主库 session 表为准 —— 侧边栏列表里已移除、但会话/记忆仍在的项目也会列出
    (in_sidebar=0 标记)。
    """
    layout = layout or default_layout()
    if not layout.exists():
        return []
    con, tmp = open_ro(layout.db_path)
    try:
        cur = con.cursor()
        try:
            cur.execute(
                "SELECT id, project_id, parent_id, task_type, directory, version, "
                "time_updated FROM session ORDER BY time_updated DESC"
            )
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            # 旧版库无 parent_id/task_type 列
            cur.execute(
                "SELECT id, project_id, NULL, NULL, directory, version, "
                "time_updated FROM session ORDER BY time_updated DESC"
            )
            rows = cur.fetchall()
        owner = session_owner_map(con)
        # 项目只由根会话(非 subagent_child)定义; 派生到子目录的 subagent
        # 会话按 owner 归并, 不再产生 "_render" 之类的伪项目。
        info: dict[str, ProjectInfo] = {}
        vers: dict[str, set] = {}
        sessions_of: dict[str, list[str]] = {}
        last_of: dict[str, int] = {}
        for sid, pid, _parent, ttype, directory, version, updated in rows:
            opid = owner.get(sid) or pid
            sessions_of.setdefault(opid, []).append(sid)
            vers.setdefault(opid, set()).add(version)
            if updated and (opid not in last_of or updated > last_of[opid]):
                last_of[opid] = updated
            if ttype != "subagent_child" and opid not in info:
                path = _trusted_dir(directory)
                info[opid] = ProjectInfo(
                    project_id=opid,
                    path=path,
                    name=os.path.basename(path.replace("/", "\\").rstrip("\\")) if path else opid,
                )
        # 孤儿 subagent(链断裂回退自身)兜底为独立项目, 数据不丢
        for opid in sessions_of:
            if opid not in info:
                info[opid] = ProjectInfo(project_id=opid, path=None, name=opid)
        sidebar = _sidebar_session_ids(layout.home)
        for pid, p in info.items():
            p.sessions = len(sessions_of.get(pid, ()))
            p.last_active = last_of.get(pid)
            p.versions = sorted(vers.get(pid, set()))
            if p.path:
                # 统计该项目会话(含归并的 subagent)的 rollout 体积(仅存在的文件)
                total = 0
                for sid in sessions_of.get(pid, ()):
                    if sid in sidebar:
                        p.in_sidebar += 1
                    f = os.path.join(layout.rollout_dir, f"model-io-{sid}.jsonl")
                    try:
                        total += os.path.getsize(f)
                    except OSError:
                        pass
                p.rollout_bytes = total
                md = layout.memory_dir_for(p.path)
                if os.path.isdir(md):
                    p.memory_files = sum(
                        len(fs) for _, _, fs in os.walk(md)
                    )
        return sorted(info.values(), key=lambda p: p.last_active or 0, reverse=True)
    finally:
        con.close()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def project_session_ids(con: sqlite3.Connection, project_id: str) -> list[str]:
    """项目名下的全部会话 id, 含派生到项目内子目录的 subagent 会话。"""
    owner = session_owner_map(con)
    return [sid for sid, pid in owner.items() if pid == project_id]


def zcode_cli_version() -> str | None:
    """尽力探测本机 zcode CLI 版本: 优先数据库, 回退安装目录探测。"""
    layout = default_layout()
    if layout.exists():
        try:
            con, tmp = open_ro(layout.db_path)
            try:
                row = con.execute(
                    "SELECT version FROM session ORDER BY time_updated DESC LIMIT 1"
                ).fetchone()
                if row:
                    return row[0]
            finally:
                con.close()
                if tmp:
                    shutil.rmtree(tmp, ignore_errors=True)
        except sqlite3.Error:
            pass
    for base in (
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "ZCode"),
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "ZCode"),
    ):
        cjs = os.path.join(base, "resources", "glm", "zcode.cjs")
        if os.path.isfile(cjs):
            return "installed:" + base
    return None
