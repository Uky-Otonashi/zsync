"""zcode 侧边栏会话列表索引(tasks-index.sqlite)的导出/导入。

zcode 桌面端的项目会话列表读取 ~/.zcode/v2/tasks-index.sqlite 的 tasks 表:
  workspace_key / workspace_path = 项目绝对路径(原大小写)
  task_id = 会话 id, title/status/model/meta_json 等为展示元数据
只迁移主会话库而不写此索引时, 恢复后的会话不会出现在列表中 —— 本模块补齐。

导出: 单独小库只含 tasks 表行(按 workspace_path 精确匹配项目路径)。
导入: INSERT OR REPLACE, 并把 workspace_key/workspace_path/meta_json.workspacePath
重映射到目标路径。
"""
from __future__ import annotations

import json
import os
import sqlite3


def tasks_index_path(zcode_home: str) -> str:
    return os.path.join(zcode_home, "v2", "tasks-index.sqlite")


def export_tasks(source_index: str, project_path: str, dest_db: str) -> int:
    """导出某项目路径对应的 tasks 行到独立小库, 返回行数。"""
    if not os.path.isfile(source_index):
        return 0
    if os.path.exists(dest_db):
        os.remove(dest_db)
    src = sqlite3.connect(f"file:{source_index.replace(chr(92), '/')}?mode=ro", uri=True)
    out = sqlite3.connect(dest_db)
    try:
        sql = src.execute(
            "SELECT sql FROM sqlite_master WHERE name='tasks'"
        ).fetchone()
        if not sql:
            return 0
        out.execute(sql[0])
        rows = src.execute(
            "SELECT * FROM tasks WHERE workspace_path = ? COLLATE NOCASE",
            (project_path,),
        ).fetchall()
        cols = [d[0] for d in src.execute("SELECT * FROM tasks LIMIT 0").description]
        ph = ",".join("?" * len(cols))
        out.executemany(
            f"INSERT INTO tasks ({','.join(cols)}) VALUES ({ph})", rows
        )
        out.commit()
        return len(rows)
    finally:
        out.close()
        src.close()


def remap_task_row(row: dict, old_path: str, new_path: str) -> dict:
    """重映射一行 task: workspace 列 + meta_json.workspacePath + searchable 无路径。"""
    old_n = old_path.replace("/", "\\")
    new_n = new_path.replace("/", "\\")

    def rp(v: str) -> str:
        vv = v.replace("/", "\\")
        if vv == old_n:
            return new_n
        if vv.startswith(old_n + "\\"):
            return new_n + vv[len(old_n):]
        return v

    out = dict(row)
    for col in ("workspace_key", "workspace_path"):
        if out.get(col):
            out[col] = rp(out[col])
    if out.get("meta_json"):
        try:
            m = json.loads(out["meta_json"])
            if isinstance(m.get("workspacePath"), str):
                m["workspacePath"] = rp(m["workspacePath"])
            out["meta_json"] = json.dumps(m, ensure_ascii=False, separators=(",", ":"))
        except json.JSONDecodeError:
            pass
    return out


def import_tasks(
    export_db: str,
    target_index: str,
    remap_from: str | None = None,
    remap_to: str | None = None,
) -> int:
    """把导出的 tasks 行写入目标索引库(不存在则创建含表结构), 返回写入行数。"""
    if not os.path.isfile(export_db):
        return 0
    src = sqlite3.connect(f"file:{export_db.replace(chr(92), '/')}?mode=ro", uri=True)
    os.makedirs(os.path.dirname(target_index), exist_ok=True)
    tgt = sqlite3.connect(target_index, timeout=10)
    try:
        src_cols = [r[1] for r in src.execute("PRAGMA table_info(tasks)").fetchall()]
        if not src_cols:
            return 0
        # 目标库若无 tasks 表则建(拷贝源结构)
        has = tgt.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='tasks'"
        ).fetchone()[0]
        if not has:
            create = src.execute(
                "SELECT sql FROM sqlite_master WHERE name='tasks'"
            ).fetchone()[0]
            tgt.execute(create)
            tgt.commit()
        tgt_cols = [r[1] for r in tgt.execute("PRAGMA table_info(tasks)").fetchall()]
        cols = [c for c in src_cols if c in tgt_cols]
        idx = {c: i for i, c in enumerate(src_cols)}
        rows = src.execute(
            f"SELECT {','.join(cols)} FROM tasks"
        ).fetchall()
        out_rows = []
        for row in rows:
            d = {c: row[idx[c]] for c in cols}
            if remap_from and remap_to:
                d = remap_task_row(d, remap_from, remap_to)
            out_rows.append([d[c] for c in cols])
        collist = ",".join(f"[{c}]" for c in cols)
        ph = ",".join("?" * len(cols))
        tgt.executemany(
            f"INSERT OR REPLACE INTO tasks ({collist}) VALUES ({ph})", out_rows
        )
        tgt.commit()
        try:
            tgt.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        return len(out_rows)
    finally:
        tgt.close()
        src.close()


def verify_tasks(target_index: str, project_path: str) -> int:
    if not os.path.isfile(target_index):
        return 0
    try:
        con = sqlite3.connect(f"file:{target_index.replace(chr(92), '/')}?mode=ro", uri=True)
        try:
            return con.execute(
                "SELECT count(*) FROM tasks WHERE workspace_path = ? COLLATE NOCASE",
                (project_path,),
            ).fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return 0
