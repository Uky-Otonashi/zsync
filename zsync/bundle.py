"""归档构建 / 恢复 —— 单压缩包(.ztar = tar.gz)存储模型。

每个归档 = 一个压缩文件 <store>/archives/<id>.ztar, 内含:
  manifest.json                元数据
  project/sessions.sqlite      会话数据库行(session/entry/message/part/...)
  project/tasks-index.sqlite   侧边栏会话列表索引行(tasks 表)
  project/rollout/*.jsonl      模型原始轨迹
  project/agents|artifacts|exec/**
  project/memory/**            项目记忆
  source/**                    项目源码(经文件筛选, 含 .git 可选)
  global/**                    全局技能/约束/插件配置/代理定义

构建: 先在 staging 目录增量组装(大文件按尺寸跳过), 再一次 tar.gz 打包;
仅实时(_live)归档保留 staging 以加速后续重建。

恢复: 解包 -> 合并进目标 zcode(主库 + tasks-index, 含路径重映射) ->
复制 rollout/agents/... -> 解压源码 -> (可选)全局合并 -> 校验。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict

from . import zclayout, dbio, tasksindex, nodeconfig

BUNDLE_FORMAT = "zsync-bundle/2"


@dataclass
class Components:
    sessions: bool = True
    rollout: bool = True
    artifacts: bool = True
    agents: bool = True
    exec_logs: bool = True
    memory: bool = True
    source: bool = True
    include_git: bool = True
    global_skills: bool = False
    global_constraints: bool = False
    global_plugins: bool = False
    global_agents_md: bool = False

    @classmethod
    def from_dict(cls, d: dict | None) -> "Components":
        c = cls()
        if not d:
            return c
        for k in asdict(c):
            if k in d and d[k] is not None:
                setattr(c, k, bool(d[k]))
        return c

    def to_dict(self) -> dict:
        return asdict(self)


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}TB"


def _copy_stable(src: str, dst: str) -> bool:
    try:
        s1 = os.path.getsize(src)
        shutil.copyfile(src, dst)
        if os.path.getsize(src) != s1:
            shutil.copyfile(src, dst)
        return True
    except OSError:
        return False


def _same(src: str, dst: str) -> bool:
    try:
        return os.path.getsize(src) == os.path.getsize(dst)
    except OSError:
        return False


def _copy_tree_incremental(src_dir: str, dst_dir: str) -> int:
    copied = 0
    for root, _dirs, files in os.walk(src_dir):
        rel = os.path.relpath(root, src_dir)
        troot = os.path.join(dst_dir, rel) if rel != "." else dst_dir
        os.makedirs(troot, exist_ok=True)
        for f in files:
            s, d = os.path.join(root, f), os.path.join(troot, f)
            if not _same(s, d):
                if _copy_stable(s, d):
                    copied += 1
    return copied


def _prune_absent(dst_dir: str, src_dir: str) -> int:
    removed = 0
    for root, _dirs, files in os.walk(dst_dir):
        rel = os.path.relpath(root, dst_dir)
        sroot = os.path.join(src_dir, rel) if rel != "." else src_dir
        for f in files:
            if not os.path.exists(os.path.join(sroot, f)):
                try:
                    os.remove(os.path.join(root, f))
                    removed += 1
                except OSError:
                    pass
    for root, dirs, _files in os.walk(dst_dir, topdown=False):
        for d in list(dirs):
            p = os.path.join(root, d)
            try:
                if not os.listdir(p):
                    os.rmdir(p)
            except OSError:
                pass
    return removed


def _walk_files(path: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(path):
        for f in files:
            out.append(os.path.relpath(os.path.join(root, f), path).replace("\\", "/"))
    return sorted(out)


# ---------------- 备份前体积估算(与 build() 同口径, 只读不打扰) ----------------

_SIZES_CACHE: dict[str, tuple[float, dict]] = {}
_SIZES_TTL = 30.0  # 秒; 用户工作中数据持续增长, 展开面板时重新拉取即可

# 与 build() 的源码筛选一致: 超过此尺寸的单文件跳过
_SKIP_BIG_FILE = 512 * 1024 * 1024


def _du(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _source_bytes(project_path: str, sf: dict) -> tuple[int, int]:
    """应用文件筛选后的源码体积与文件数(不含 .git —— include_git 单独计)。"""
    total = n = 0
    for root, dirs, files in os.walk(project_path):
        rel_root = os.path.relpath(root, project_path).replace("\\", "/")
        dirs[:] = [
            d for d in dirs
            if d != ".git"
            and not nodeconfig.dir_fully_ignored((rel_root + "/" + d) if rel_root != "." else d, sf)
        ]
        for f in files:
            rel = (rel_root + "/" + f) if rel_root != "." else f
            if nodeconfig.source_ignored(rel, sf):
                continue
            try:
                sz = os.path.getsize(os.path.join(root, f))
            except OSError:
                continue
            if sz > _SKIP_BIG_FILE:
                continue
            total += sz
            n += 1
    return total, n


def _sessions_db_bytes(con: sqlite3.Connection, sids: list[str]) -> int:
    """会话数据的体积代理: 大字段(part.data/message.data)长度和。
    导出的 sessions.sqlite 还含表结构与索引, 实际略大, 作估算足够。"""
    if not sids:
        return 0
    ph = ",".join("?" * len(sids))
    total = 0
    for table in ("part", "message"):
        try:
            total += con.execute(
                f"SELECT coalesce(sum(length(data)), 0) FROM {table} "
                f"WHERE session_id IN ({ph})", sids).fetchone()[0]
        except sqlite3.Error:
            pass
    return total


def estimate_component_sizes(layout: zclayout.ZcodeLayout, project: dict,
                             source_filter: dict | None = None,
                             use_cache: bool = True) -> dict:
    """逐组件估算"执行备份会打包多少数据"(字节)。口径与 BundleBuilder.build()
    一致: 同样的 subagent 归并、同样的源码筛选规则; 区别是只累计体积不复制。

    返回 {组件key: 字节数} + {"source_files": 文件数, "computed_at": 毫秒}。
    """
    pid = project["project_id"]
    now = time.time()
    if use_cache:
        cached = _SIZES_CACHE.get(pid)
        if cached and now - cached[0] < _SIZES_TTL:
            return cached[1]

    sf = source_filter or {}
    ppath = project.get("path")
    con, tmp = zclayout.open_ro(layout.db_path)
    try:
        sids = zclayout.project_session_ids(con, pid)
        # sqlite 连接默认禁止跨线程: db 求和留在当前线程, 纯文件系统部分并行
        db_bytes = _sessions_db_bytes(con, sids)
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_src = ex.submit(_source_bytes, ppath, sf) if ppath and os.path.isdir(ppath) else None
            f_git = ex.submit(_du, os.path.join(ppath, ".git")) if ppath else None
            f_glob = ex.submit(lambda: {
                "global_skills": _du(layout.skills_dir) if os.path.isdir(layout.skills_dir) else 0,
                "global_agents_md": sum(
                    os.path.getsize(os.path.join(layout.agents_dir, f))
                    for f in os.listdir(layout.agents_dir) if f.endswith(".md")
                ) if os.path.isdir(layout.agents_dir) else 0,
                "global_constraints": sum(
                    os.path.getsize(f) for f in layout.global_constraint_files()),
                "global_plugins": os.path.getsize(layout.plugins_config)
                if os.path.isfile(layout.plugins_config) else 0,
            })
            # 会话附属目录与 rollout 在当前线程算(每个 sid 一次 stat/du, 很快)
            per_dir: dict[str, int] = {"artifacts": 0, "agents": 0, "exec_logs": 0}
            bases = {"artifacts": layout.artifacts_dir, "agents": layout.agents_dir,
                     "exec_logs": layout.exec_dir}
            rollout = 0
            for sid in sids:
                for key, base in bases.items():
                    d = os.path.join(base, sid)
                    if os.path.isdir(d):
                        per_dir[key] += _du(d)
                try:
                    rollout += os.path.getsize(
                        os.path.join(layout.rollout_dir, f"model-io-{sid}.jsonl"))
                except OSError:
                    pass
            memory = _du(layout.memory_dir_for(ppath)) if ppath else 0
            out = {
                "sessions": db_bytes,
                "rollout": rollout,
                **per_dir,
                "memory": memory,
                "source": (f_src.result()[0] if f_src else 0),
                "include_git": (f_git.result() if f_git else 0),
                **f_glob.result(),
                "source_files": (f_src.result()[1] if f_src else 0),
                "computed_at": int(now * 1000),
            }
    finally:
        con.close()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    _SIZES_CACHE[pid] = (now, out)
    return out


class BundleStore:
    """单包存储: archives/<id>.ztar + <id>.manifest.json; staging/<id>/ 组装区。"""

    def __init__(self, store_dir: str):
        self.dir = store_dir
        self.archives_dir = os.path.join(store_dir, "archives")
        self.staging_dir = os.path.join(store_dir, "staging")
        os.makedirs(self.archives_dir, exist_ok=True)

    def ztar_path(self, archive_id: str) -> str:
        return os.path.join(self.archives_dir, archive_id + ".ztar")

    def manifest_path(self, archive_id: str) -> str:
        return os.path.join(self.archives_dir, archive_id + ".manifest.json")

    def staging_path(self, archive_id: str) -> str:
        return os.path.join(self.staging_dir, archive_id)

    def list_archives(self) -> list[dict]:
        """列表摘要: 剥离 files/session_titles 等随项目规模膨胀的字段
        (大项目可达数十 MB, 会拖垮 /api/archives), 完整清单走 manifest()。"""
        out = []
        for fn in os.listdir(self.archives_dir):
            if not fn.endswith(".manifest.json"):
                continue
            aid = fn[: -len(".manifest.json")]
            try:
                with open(os.path.join(self.archives_dir, fn), encoding="utf-8") as f:
                    m = json.load(f)
                m.pop("files", None)
                m.pop("session_titles", None)
                m["archive_id"] = aid
                zt = self.ztar_path(aid)
                m["ztar_bytes"] = os.path.getsize(zt) if os.path.isfile(zt) else 0
                m["complete"] = os.path.isfile(zt)
                out.append(m)
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda m: m.get("updated_at", 0), reverse=True)

    def manifest(self, archive_id: str) -> dict | None:
        p = self.manifest_path(archive_id)
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def delete(self, archive_id: str) -> bool:
        ok = False
        for p in (self.ztar_path(archive_id), self.manifest_path(archive_id)):
            if os.path.exists(p):
                os.remove(p)
                ok = True
        st = self.staging_path(archive_id)
        if os.path.isdir(st):
            shutil.rmtree(st, ignore_errors=True)
            ok = True
        return ok

    def import_ztar(self, ztar_file: str, manifest: dict) -> str:
        """接收一个外部 .ztar 与其清单, 落到本 store。"""
        aid = manifest["archive_id"]
        os.makedirs(self.archives_dir, exist_ok=True)
        shutil.copy2(ztar_file, self.ztar_path(aid) + ".part")
        os.replace(self.ztar_path(aid) + ".part", self.ztar_path(aid))
        tmp = self.manifest_path(aid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.manifest_path(aid))
        return aid

    def extract(self, archive_id: str, dest_dir: str, progress=None) -> dict:
        """解包 .ztar 到 dest_dir, 返回 manifest。"""
        return self.extract_to(self.ztar_path(archive_id), dest_dir, progress)

    def extract_to(self, ztar_file: str, dest_dir: str, progress=None) -> dict:
        if not os.path.isfile(ztar_file):
            raise RuntimeError(f"归档包不存在: {ztar_file}")
        shutil.rmtree(dest_dir, ignore_errors=True)
        os.makedirs(dest_dir, exist_ok=True)
        with tarfile.open(ztar_file, "r:gz") as tf:
            tf.extractall(dest_dir, filter="data")
        mp = os.path.join(dest_dir, "manifest.json")
        if not os.path.isfile(mp):
            raise RuntimeError("归档包缺少 manifest.json")
        with open(mp, encoding="utf-8") as f:
            return json.load(f)


def _tar_staging(staging: str, out_tgz: str, skip_top: set[str] | None = None,
                 progress=None) -> int:
    """把 staging 目录(含 manifest.json)打包为 tar.gz。"""
    skip_top = skip_top or set()
    tmp = out_tgz + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    count = 0
    with tarfile.open(tmp, "w:gz", compresslevel=1) as tf:
        for root, dirs, files in os.walk(staging):
            rel_root = os.path.relpath(root, staging)
            top = rel_root.split("\\")[0].split("/")[0] if rel_root != "." else ""
            if rel_root != "." and top in skip_top:
                dirs[:] = []
                continue
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, staging).replace("\\", "/")
                if arc.split("/")[0] in skip_top:
                    continue
                tf.add(full, arcname=arc, recursive=False)
                count += 1
                if progress and count % 500 == 0:
                    progress("pack", 0, f"已打包 {count} 个文件")
    os.replace(tmp, out_tgz)
    return count


class BundleBuilder:
    def __init__(self, layout: zclayout.ZcodeLayout, store: BundleStore):
        self.layout = layout
        self.store = store

    def build(
        self,
        archive_id: str,
        project: dict,
        components: Components,
        source_filter: dict | None = None,
        keep_staging: bool = False,
        progress=None,
    ) -> dict:
        t0 = time.time()
        sdir = self.store.staging_path(archive_id)
        os.makedirs(sdir, exist_ok=True)

        def prog(phase, pct, detail=""):
            if progress:
                progress(phase, pct, detail)

        project_id = project["project_id"]
        project_path = project.get("path")
        con, tmp = zclayout.open_ro(self.layout.db_path)
        try:
            sids = zclayout.project_session_ids(con, project_id)
            # 会话标题摘要: 与 sids 同口径(含归并的 subagent), 最新优先取 50 条
            sid_set = set(sids)
            titles: dict = {}
            for s, t in con.execute(
                "SELECT id, title FROM session ORDER BY time_updated DESC"
            ):
                if s in sid_set:
                    titles[s] = t
                    if len(titles) >= 50:
                        break
        finally:
            con.close()
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

        counts: dict = {}
        stats: dict = {"sessions": len(sids)}

        if components.sessions:
            prog("sessions", 5, "导出会话数据库")
            dest = os.path.join(sdir, "project", "sessions.sqlite")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.exists(dest):
                os.remove(dest)
            res = dbio.export_project(self.layout.db_path, project_id, dest)
            counts = res.counts
            stats["db_rows"] = res.total_rows
            # 侧边栏会话列表索引
            tdest = os.path.join(sdir, "project", "tasks-index.sqlite")
            if os.path.exists(tdest):
                os.remove(tdest)
            if project_path:
                n = tasksindex.export_tasks(
                    tasksindex.tasks_index_path(self.layout.home), project_path, tdest)
                stats["tasks_index_rows"] = n
                prog("sessions", 12, f"会话列表索引 {n} 行")

        copied_files = 0
        if components.rollout:
            dstdir = os.path.join(sdir, "project", "rollout")
            os.makedirs(dstdir, exist_ok=True)
            for i, sid in enumerate(sids):
                fname = f"model-io-{sid}.jsonl"
                src = os.path.join(self.layout.rollout_dir, fname)
                if not os.path.exists(src):
                    continue
                dst = os.path.join(dstdir, fname)
                if not _same(src, dst) and _copy_stable(src, dst):
                    copied_files += 1
                prog("rollout", 15 + 25 * (i + 1) / max(len(sids), 1), f"rollout {sid[:16]}…")
            for f in os.listdir(dstdir):
                sid = f[len("model-io-"):-len(".jsonl")] if f.startswith("model-io-") else None
                if sid and sid not in sids:
                    try:
                        os.remove(os.path.join(dstdir, f))
                    except OSError:
                        pass

        def sync_tree(src_dir: str, sub: str, enabled: bool, per_session: bool = False) -> None:
            nonlocal copied_files
            rel_root = os.path.join(sdir, sub)
            if not enabled:
                if os.path.isdir(rel_root):
                    shutil.rmtree(rel_root, ignore_errors=True)
                return
            if per_session:
                for sid in sids:
                    s = os.path.join(src_dir, sid)
                    if os.path.isdir(s):
                        copied_files += _copy_tree_incremental(s, os.path.join(rel_root, sid))
                if os.path.isdir(rel_root):
                    for d in os.listdir(rel_root):
                        if d not in sids and os.path.isdir(os.path.join(rel_root, d)):
                            shutil.rmtree(os.path.join(rel_root, d), ignore_errors=True)
            else:
                if os.path.isdir(src_dir):
                    copied_files += _copy_tree_incremental(src_dir, rel_root)
                    _prune_absent(rel_root, src_dir)
                elif os.path.isdir(rel_root):
                    shutil.rmtree(rel_root, ignore_errors=True)

        prog("artifacts", 42, "同步工具产物")
        sync_tree(self.layout.artifacts_dir, "project/artifacts", components.artifacts, per_session=True)
        prog("agents", 46, "同步子代理数据")
        sync_tree(self.layout.agents_dir, "project/agents", components.agents, per_session=True)
        prog("exec", 50, "同步执行日志")
        sync_tree(self.layout.exec_dir, "project/exec", components.exec_logs, per_session=True)
        prog("memory", 54, "同步项目记忆")
        if components.memory and project_path:
            sync_tree(self.layout.memory_dir_for(project_path), "project/memory", True)
        else:
            sync_tree("", "project/memory", False)

        # 源码: 应用文件筛选, 直接写入 staging/source/
        if components.source and project_path and os.path.isdir(project_path):
            prog("source", 58, "筛选并复制项目源码")
            sf = source_filter or {}
            dst_root = os.path.join(sdir, "source")
            os.makedirs(dst_root, exist_ok=True)
            n_files = 0
            for root, dirs, files in os.walk(project_path):
                rel_root = os.path.relpath(root, project_path).replace("\\", "/")
                dirs[:] = [
                    d for d in dirs
                    if not (d == ".git" and not components.include_git)
                    and not nodeconfig.dir_fully_ignored((rel_root + "/" + d) if rel_root != "." else d, sf)
                ]
                for f in files:
                    rel = (rel_root + "/" + f) if rel_root != "." else f
                    if nodeconfig.source_ignored(rel, sf):
                        continue
                    if f == ".git" and not components.include_git:
                        continue
                    full = os.path.join(root, f)
                    try:
                        if os.path.getsize(full) > 512 * 1024 * 1024:
                            continue
                    except OSError:
                        continue
                    d = os.path.join(dst_root, *rel.split("/"))
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    if _copy_stable(full, d):
                        n_files += 1
                    if n_files % 2000 == 0 and n_files:
                        prog("source", 58, f"源码已复制 {n_files} 个文件")
            # 清理 staging/source 中已不存在/被忽略的文件
            _prune_absent(dst_root, project_path)
            stats["source_files"] = n_files
        elif os.path.isdir(os.path.join(sdir, "source")):
            shutil.rmtree(os.path.join(sdir, "source"), ignore_errors=True)

        prog("global", 82, "同步全局配置")
        gdir = os.path.join(sdir, "global")
        if components.global_skills and os.path.isdir(self.layout.skills_dir):
            copied_files += _copy_tree_incremental(self.layout.skills_dir, os.path.join(gdir, "skills"))
        elif os.path.isdir(os.path.join(gdir, "skills")):
            shutil.rmtree(os.path.join(gdir, "skills"), ignore_errors=True)
        if components.global_agents_md and os.path.isdir(self.layout.agents_dir):
            dst = os.path.join(gdir, "agents_md")
            os.makedirs(dst, exist_ok=True)
            for f in os.listdir(self.layout.agents_dir):
                if f.endswith(".md"):
                    _copy_stable(os.path.join(self.layout.agents_dir, f), os.path.join(dst, f))
        if components.global_constraints:
            dst = os.path.join(gdir, "constraints")
            os.makedirs(dst, exist_ok=True)
            for f in self.layout.global_constraint_files():
                _copy_stable(f, os.path.join(dst, os.path.basename(f)))
        if components.global_plugins and os.path.isfile(self.layout.plugins_config):
            _copy_stable(self.layout.plugins_config, os.path.join(gdir, "config.json"))

        # 打包为单文件 .ztar(清单先入包, 体积字段在侧车清单中补全)
        prog("pack", 88, "压缩打包")
        old = self.store.manifest(archive_id)
        zt = self.store.ztar_path(archive_id)
        files = [{"path": p, "size": os.path.getsize(os.path.join(sdir, *p.split("/")))}
                 for p in _walk_files(sdir)]
        manifest = {
            "format": BUNDLE_FORMAT,
            "archive_id": archive_id,
            "created_at": (old or {}).get("created_at", int(time.time() * 1000)),
            "updated_at": int(time.time() * 1000),
            "build_seconds": round(time.time() - t0, 1),
            "source": {
                "hostname": os.environ.get("COMPUTERNAME", ""),
                "zcode_cli_version": zclayout.zcode_cli_version(),
                "project_id": project_id,
                "project_path": project_path,
                "memory_slug": zclayout.memory_slug_for(project_path) if project_path else None,
                "session_titles": titles,
            },
            "components": components.to_dict(),
            "source_filter": source_filter or {},
            "stats": stats | {"counts": counts, "copied_files": copied_files,
                              # 打包前的 staging 数据体积: 备份前估算用其与
                              # ztar_bytes 的比值外推压缩后大小
                              "staged_bytes": sum(f["size"] for f in files)},
        }
        if old:
            manifest["history"] = (old.get("history") or [])[-19:] + [
                {"updated_at": manifest["updated_at"], "build_seconds": "pending"}
            ]
        with open(os.path.join(sdir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        packed = _tar_staging(sdir, zt, progress=progress)
        manifest["build_seconds"] = round(time.time() - t0, 1)
        manifest["ztar_bytes"] = os.path.getsize(zt)
        manifest["stats"]["packed_files"] = packed
        manifest["files"] = files
        if manifest.get("history"):
            manifest["history"][-1] = {"updated_at": manifest["updated_at"],
                                       "build_seconds": manifest["build_seconds"]}
        tmpm = self.store.manifest_path(archive_id) + ".tmp"
        with open(tmpm, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        os.replace(tmpm, self.store.manifest_path(archive_id))
        if not keep_staging:
            shutil.rmtree(sdir, ignore_errors=True)
        prog("done", 100, f"完成 {fmt_bytes(manifest['ztar_bytes'])}, {manifest['build_seconds']}s")
        return manifest


@dataclass
class RestoreOptions:
    target_path: str
    components: Components = field(default_factory=Components)
    dry_run: bool = False


@dataclass
class RestoreReport:
    db_counts: dict = field(default_factory=dict)
    tasks_index_rows: int = 0
    warnings: list = field(default_factory=list)
    files_copied: int = 0
    source_files: int = 0
    verify: dict = field(default_factory=dict)
    tasks_verify: int = 0


def assert_db_writable(db_path: str) -> None:
    if not os.path.isfile(db_path):
        raise RuntimeError(f"目标数据库不存在: {db_path} (目标机器需先运行一次 zcode 以初始化)")
    con = sqlite3.connect(db_path, timeout=3)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
    except sqlite3.Error as e:
        raise RuntimeError("目标数据库被占用 —— 请先完全退出 zcode 再执行恢复") from e
    finally:
        con.close()


def restore_bundle(
    bundle_dir: str,
    layout: zclayout.ZcodeLayout,
    opts: RestoreOptions,
    progress=None,
) -> RestoreReport:
    report = RestoreReport()

    def prog(phase, pct, detail=""):
        if progress:
            progress(phase, pct, detail)

    with open(os.path.join(bundle_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    src = manifest["source"]
    old_path = src.get("project_path")
    target = opts.target_path
    remap = bool(old_path and target and os.path.normcase(old_path) != os.path.normcase(target.replace("/", "\\")))
    new_pid = zclayout.project_id_for(target)
    c = opts.components

    if c.source:
        srcdir = os.path.join(bundle_dir, "source")
        if os.path.isdir(srcdir) and os.listdir(srcdir):
            os.makedirs(target, exist_ok=True)
            prog("source", 5, "解压项目源码")
            n = _copy_tree_incremental(srcdir, target)
            report.source_files = n
            prog("source", 15, f"源码 {n} 个文件就位")
        else:
            report.warnings.append("存档不含源码组件")

    if c.sessions:
        prog("sessions", 25, "导入会话数据库")
        sdb = os.path.join(bundle_dir, "project", "sessions.sqlite")
        if os.path.isfile(sdb):
            if not opts.dry_run:
                assert_db_writable(layout.db_path)
                rep = dbio.import_project(
                    sdb, layout.db_path,
                    remap_from=old_path if remap else None,
                    remap_to=target if remap else None,
                )
                report.db_counts = rep.counts
                report.warnings.extend(rep.warnings or [])
            # 会话列表索引
            tdb = os.path.join(bundle_dir, "project", "tasks-index.sqlite")
            if os.path.isfile(tdb) and not opts.dry_run:
                try:
                    report.tasks_index_rows = tasksindex.import_tasks(
                        tdb,
                        tasksindex.tasks_index_path(layout.home),
                        remap_from=old_path if remap else None,
                        remap_to=target if remap else None,
                    )
                except sqlite3.Error as e:
                    report.warnings.append(f"tasks-index 写入失败: {e}")
        else:
            report.warnings.append("存档不含会话数据库组件")
        prog("sessions", 45, f"DB行 {sum(report.db_counts.values())}, 列表索引 {report.tasks_index_rows} 行")

    def tree_copy(sub: str, dest_base: str, enabled: bool):
        if not enabled:
            return
        src_dir = os.path.join(bundle_dir, sub)
        if not os.path.isdir(src_dir):
            return
        report.files_copied += _copy_tree_incremental(src_dir, dest_base)

    tree_copy("project/rollout", layout.rollout_dir, c.rollout)
    tree_copy("project/artifacts", layout.artifacts_dir, c.artifacts)
    tree_copy("project/agents", layout.agents_dir, c.agents)
    tree_copy("project/exec", layout.exec_dir, c.exec_logs)
    if c.memory:
        src_dir = os.path.join(bundle_dir, "project", "memory")
        if os.path.isdir(src_dir):
            dst = layout.memory_dir_for(target)
            os.makedirs(dst, exist_ok=True)
            report.files_copied += _copy_tree_incremental(src_dir, dst)
            prog("memory", 70, f"记忆 -> {zclayout.memory_slug_for(target)}")

    gdir = os.path.join(bundle_dir, "global")
    if os.path.isdir(gdir):
        if c.global_skills and os.path.isdir(os.path.join(gdir, "skills")):
            prog("global", 80, "合并全局技能")
            report.files_copied += _copy_tree_incremental(
                os.path.join(gdir, "skills"), layout.skills_dir)
        if c.global_agents_md and os.path.isdir(os.path.join(gdir, "agents_md")):
            for f in os.listdir(os.path.join(gdir, "agents_md")):
                _copy_stable(os.path.join(gdir, "agents_md", f), os.path.join(layout.agents_dir, f))
        if c.global_constraints and os.path.isdir(os.path.join(gdir, "constraints")):
            for f in os.listdir(os.path.join(gdir, "constraints")):
                _copy_stable(os.path.join(gdir, "constraints", f), os.path.join(layout.home, f))
        if c.global_plugins and os.path.isfile(os.path.join(gdir, "config.json")):
            _merge_plugins_config(os.path.join(gdir, "config.json"), layout.plugins_config)

    if not opts.dry_run:
        prog("verify", 92, "校验恢复结果")
        report.verify = dbio.verify_import(layout.db_path, new_pid)
        report.tasks_verify = tasksindex.verify_tasks(
            tasksindex.tasks_index_path(layout.home), target)
    prog("done", 100, "恢复完成")
    return report


def _merge_plugins_config(src_json: str, dst_json: str) -> None:
    try:
        with open(src_json, encoding="utf-8") as f:
            src = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    dst: dict = {}
    if os.path.isfile(dst_json):
        try:
            with open(dst_json, encoding="utf-8") as f:
                dst = json.load(f)
        except (OSError, json.JSONDecodeError):
            dst = {}
    ep = dst.setdefault("plugins", {}).setdefault("enabledPlugins", {})
    for k, v in src.get("plugins", {}).get("enabledPlugins", {}).items():
        ep[k] = v
    with open(dst_json, "w", encoding="utf-8") as f:
        json.dump(dst, f, ensure_ascii=False, indent=2)
