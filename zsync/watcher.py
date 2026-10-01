"""实时备份: 轮询项目相关数据的变更签名, 变化后自动重建归档。

签名涵盖: 数据库 mtime/wal 尺寸、项目会话 max(time_updated)、
记忆目录树 mtime、该项目 rollout 文件尺寸集合、技能目录签名。
源码目录默认不参与实时监控(体积大), 由手动构建或显式开启。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time

from . import zclayout
from .bundle import BundleStore, Components


def _dir_signature(path: str, max_entries: int = 5000) -> str:
    if not os.path.isdir(path):
        return "-"
    parts: list[str] = []
    n = 0
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for f in sorted(files):
            fp = os.path.join(root, f)
            try:
                parts.append(f"{os.path.relpath(fp, path)}:{os.path.getmtime(fp)}:{os.path.getsize(fp)}")
            except OSError:
                continue
            n += 1
            if n > max_entries:
                parts.append("TRUNC")
                break
    return "|".join(parts) or "empty"


class ProjectWatcher:
    """单项目监视器; 由 WatchManager 驱动。"""

    def __init__(self, project_id: str, project_path: str | None, components: Components,
                 interval: float = 20.0, min_rebuild_gap: float = 15.0, label: str = ""):
        self.project_id = project_id
        self.project_path = project_path
        self.components = components
        self.interval = interval
        self.min_rebuild_gap = min_rebuild_gap
        self.label = label
        self.enabled = True
        self.last_sig: str | None = None
        self.last_rebuild = 0.0
        self.last_check = 0.0
        self.last_change: float | None = None
        self.rebuilds = 0
        self.status = "idle"
        self.error: str | None = None

    def signature(self, layout: zclayout.ZcodeLayout) -> str:
        sig: list[str] = []
        for f in (layout.db_path, layout.db_path + "-wal"):
            try:
                sig.append(f"{os.path.getmtime(f)}:{os.path.getsize(f)}")
            except OSError:
                sig.append("-")
        try:
            con, tmp = zclayout.open_ro(layout.db_path)
            try:
                row = con.execute(
                    "SELECT count(*), max(time_updated) FROM session WHERE project_id=?",
                    (self.project_id,),
                ).fetchone()
                sig.append(f"sessions={row[0]},maxupd={row[1]}")
                sids = [r[0] for r in con.execute(
                    "SELECT id FROM session WHERE project_id=?", (self.project_id,)
                )]
            finally:
                con.close()
                if tmp:
                    shutil.rmtree(tmp, ignore_errors=True)
        except sqlite3.Error as e:
            sig.append(f"dberr:{e}")
            sids = []
        roll = []
        for sid in sids:
            f = os.path.join(layout.rollout_dir, f"model-io-{sid}.jsonl")
            try:
                roll.append(f"{sid[-6:]}:{os.path.getsize(f)}")
            except OSError:
                pass
        sig.append("roll:" + ",".join(roll))
        if self.components.memory and self.project_path:
            sig.append("mem:" + _dir_signature(layout.memory_dir_for(self.project_path)))
        if self.components.global_skills:
            sig.append("skills:" + _dir_signature(layout.skills_dir))
        return ";".join(sig)

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "project_path": self.project_path,
            "label": self.label,
            "enabled": self.enabled,
            "interval": self.interval,
            "rebuilds": self.rebuilds,
            "status": self.status,
            "error": self.error,
            "last_change": self.last_change,
            "components": self.components.to_dict(),
        }


class WatchManager:
    """管理所有项目监视器, 单线程轮询, 变化即触发归档重建(经由回调)。"""

    def __init__(self, layout: zclayout.ZcodeLayout, store: BundleStore,
                 on_rebuild, state_path: str | None = None):
        self.layout = layout
        self.store = store
        self.on_rebuild = on_rebuild  # fn(watcher) -> 通常启动一个构建 job
        self.state_path = state_path
        self.watchers: dict[str, ProjectWatcher] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if state_path and os.path.isfile(state_path):
            try:
                with open(state_path, encoding="utf-8") as f:
                    saved = json.load(f)
                for pid, w in saved.items():
                    if w.get("project_path") and os.path.isdir(w["project_path"]) is not None:
                        self.watchers[pid] = ProjectWatcher(
                            pid, w.get("project_path"), Components.from_dict(w.get("components")),
                            interval=w.get("interval", 20), label=w.get("label", ""),
                        )
            except (OSError, json.JSONDecodeError, KeyError):
                pass

    def set_watch(self, project_id: str, project_path: str | None, enabled: bool,
                  components: dict | None = None, interval: float = 20.0, label: str = "") -> dict:
        with self._lock:
            if not enabled:
                w = self.watchers.pop(project_id, None)
                self._save()
                return {"watching": False, "project_id": project_id}
            c = Components.from_dict(components) if components else Components()
            self.watchers[project_id] = ProjectWatcher(
                project_id, project_path, c, interval=interval, label=label
            )
            self._save()
            return {"watching": True, "project_id": project_id, "interval": interval}

    def _save(self) -> None:
        if not self.state_path:
            return
        data = {
            pid: {"project_path": w.project_path, "interval": w.interval,
                  "label": w.label, "components": w.components.to_dict()}
            for pid, w in self.watchers.items()
        }
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def list(self) -> list[dict]:
        with self._lock:
            return [w.to_dict() for w in self.watchers.values()]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="zsync-watch")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            with self._lock:
                watchers = list(self.watchers.values())
            now = time.time()
            for w in watchers:
                if not w.enabled:
                    continue
                if now < w.last_check + w.interval and w.last_sig is not None:
                    continue
                w.last_check = now
                try:
                    sig = w.signature(self.layout)
                    w.status = "checking"
                except Exception as e:  # noqa: BLE001
                    w.status = "error"
                    w.error = str(e)
                    continue
                if w.last_sig is None:
                    w.last_sig = sig  # 首次只记录基线, 不触发
                    w.status = "baseline"
                    continue
                if sig != w.last_sig:
                    w.last_change = now
                    if now - w.last_rebuild >= w.min_rebuild_gap:
                        w.status = "rebuilding"
                        w.last_sig = sig
                        w.last_rebuild = now
                        w.rebuilds += 1
                        try:
                            self.on_rebuild(w)
                        except Exception as e:  # noqa: BLE001
                            w.error = str(e)
                else:
                    w.status = "idle"
                    w.error = None
