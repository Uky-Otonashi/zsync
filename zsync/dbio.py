"""按项目导出 / 导入 zcode 会话数据库数据。

导出: 从源库(只读, 兼容 WAL)筛选出属于某项目的全部行, 连同建表语句写入一个
独立的 sessions.sqlite; 表结构直接复制源库, 保证列完整。

导入: 将 sessions.sqlite 的行写入目标库(INSERT OR REPLACE 实现镜像覆盖),
支持路径重映射 —— 项目迁移到不同目录时改写 project_id / directory / path /
scope_id / cwd 等路径字段。
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field

from . import zclayout

# 直接以 session_id 关联的表: 列名 -> 过滤方式
SESSION_KEY_COLS = {
    "session_entry": ("session_id",),
    "message": ("session_id",),
    "part": ("session_id",),
    "todo": ("session_id",),
    "session_target": ("session_id",),
    "session_task_link": ("session_id",),
    "session_input": ("session_id",),
    "input_history": ("session_id",),
    "model_usage": ("session_id",),
    "tool_usage": ("session_id",),
    "turn_usage": ("session_id",),
    "workflow_run": ("parent_session_id",),
    "dwf_run": ("session_id",),
    "dwf_actor": ("session_id",),
}

# 链式关联: 表 -> (外键列, 依赖表, 依赖表主键列)
CHAINED_TABLES = [
    ("workflow_activity", "run_id", "workflow_run", "id"),
    ("dwf_event", "run_id", "dwf_run", "id"),
    ("dwf_node", "run_id", "dwf_run", "id"),
]

# 按 project_id 直接关联的表
PROJECT_TABLES = {"permission": "project_id"}


@dataclass
class ExportResult:
    db_path: str
    counts: dict = field(default_factory=dict)
    schema_migrations: list = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(self.counts.values())


def export_project(
    source_db: str,
    project_id: str,
    dest_db: str,
    progress=None,
) -> ExportResult:
    """把 source_db 中属于 project_id 的所有行导出到 dest_db。"""
    if os.path.exists(dest_db):
        os.remove(dest_db)
    src_con, tmp = zclayout.open_ro(source_db)
    out = sqlite3.connect("file:" + dest_db.replace("\\", "/"), uri=True)
    try:
        src_name = "srcdb"
        out.execute(
            f"ATTACH DATABASE ? AS {src_name}",
            ("file:" + source_db.replace("\\", "/") + "?mode=ro",),
        )
        cur = src_con.cursor()
        tables = {
            r[0]: r[1]
            for r in cur.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
            ).fetchall()
        }

        def report(t, n):
            if progress:
                progress(t, n)

        counts: dict[str, int] = {}

        def copy_table(name: str, where: str, params: tuple = ()):
            if name not in tables:
                return 0
            out.execute(tables[name])
            out.execute(
                f"INSERT INTO main.[{name}] SELECT * FROM {src_name}.[{name}] WHERE {where}",
                params,
            )
            n = out.execute(f"SELECT count(*) FROM main.[{name}]").fetchone()[0]
            counts[name] = n
            report(name, n)
            return n

        copy_table("session", "project_id=?", (project_id,))
        # 并入派生到项目内子目录的 subagent 会话(project_id 不同, parent 指向
        # 已收录会话); 迭代以覆盖 subagent 再派 subagent 的嵌套。
        if col_exists(src_con, "session", "task_type") and col_exists(
            src_con, "session", "parent_id"
        ):
            while True:
                n0 = out.execute("SELECT count(*) FROM main.session").fetchone()[0]
                out.execute(
                    f"INSERT OR IGNORE INTO main.session SELECT * FROM {src_name}.session "
                    "WHERE task_type='subagent_child' "
                    "AND parent_id IN (SELECT id FROM main.session)"
                )
                if out.execute("SELECT count(*) FROM main.session").fetchone()[0] == n0:
                    break
            counts["session"] = out.execute(
                "SELECT count(*) FROM main.session"
            ).fetchone()[0]
            report("session", counts["session"])
        copy_table("permission", "project_id=?", (project_id,))
        copy_table(
            "local_setting",
            "scope='project' AND scope_id=?",
            (project_id,),
        )
        for table, key_cols in SESSION_KEY_COLS.items():
            for col in key_cols:
                if col_exists(src_con, table, col):
                    copy_table(
                        table,
                        f"{col} IN (SELECT id FROM main.session)",
                        (),
                    )
                    break
        for table, fk, dep, dep_pk in CHAINED_TABLES:
            if table in counts or table not in tables:
                continue
            if table == "workflow_definition" or not col_exists(src_con, table, fk):
                continue
            if dep in counts and counts.get(dep):
                copy_table(
                    table,
                    f"{fk} IN (SELECT {dep_pk} FROM main.[{dep}])",
                    (),
                )
        # workflow_definition: 导出被本次 run 引用的定义
        if "workflow_definition" in tables and counts.get("workflow_run"):
            copy_table(
                "workflow_definition",
                "id IN (SELECT definition_id FROM main.workflow_run WHERE definition_id IS NOT NULL)",
                (),
            )
        # schema_migration 供兼容性检查
        mig = []
        if "schema_migration" in tables:
            out.execute(tables["schema_migration"])
            try:
                rows = src_con.execute("SELECT * FROM schema_migration").fetchall()
                cols = [d[0] for d in src_con.execute("SELECT * FROM schema_migration").description]
                out.executemany(
                    f"INSERT INTO main.schema_migration ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    rows,
                )
                mig = rows
            except sqlite3.Error:
                pass
        out.commit()
        out.execute(f"DETACH DATABASE {src_name}")
        return ExportResult(dest_db, counts, mig)
    finally:
        out.close()
        src_con.close()
        if tmp:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


def col_exists(con: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        rows = con.execute(f"PRAGMA table_info([{table}])").fetchall()
    except sqlite3.Error:
        return False
    return any(r[1] == col for r in rows)


@dataclass
class ImportReport:
    counts: dict = field(default_factory=dict)
    skipped: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def import_project(
    export_db: str,
    target_db: str,
    remap_from: str | None = None,
    remap_to: str | None = None,
    project_id_override: str | None = None,
    progress=None,
) -> ImportReport:
    """将导出库中的行导入目标库。若给出 remap_from/remap_to 则重映射路径字段。

    要求目标 zcode 未运行(库未被占用)。
    """
    report = ImportReport()
    new_pid = project_id_override
    if remap_from and remap_to:
        new_pid = new_pid or zclayout.project_id_for(remap_to)
    src = sqlite3.connect(f"file:{export_db.replace(chr(92), '/')}?mode=ro", uri=True)
    try:
        tgt = sqlite3.connect(target_db, timeout=10)
    except sqlite3.Error as e:
        src.close()
        raise RuntimeError(f"无法打开目标数据库(请先关闭 zcode 再恢复): {e}")
    try:
        tgt.execute("PRAGMA foreign_keys=OFF")
        tgt_tables = {
            r[0]
            for r in tgt.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        src_tables = [
            r[0]
            for r in src.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        # 先 session 再其余, 保证依赖顺序
        order = ["session"] + [t for t in src_tables if t != "session"]
        if remap_from and remap_to:
            remaps = _build_value_remaps(remap_from, remap_to, new_pid)
        else:
            remaps = {"pid": lambda v: v, "path": lambda v: v}
        for table in order:
            if table not in tgt_tables or table == "schema_migration":
                if table not in tgt_tables and table != "sqlite_sequence":
                    report.skipped[table] = "目标库缺少该表"
                continue
            src_cols = [r[1] for r in src.execute(f"PRAGMA table_info([{table}])").fetchall()]
            tgt_cols = [r[1] for r in tgt.execute(f"PRAGMA table_info([{table}])").fetchall()]
            cols = [c for c in src_cols if c in tgt_cols]
            if not cols:
                report.skipped[table] = "无交集列"
                continue
            colidx = {c: i for i, c in enumerate(src_cols)}
            # 需要改写的列 -> 该列的重映射函数
            rewrite = {
                c: remaps[_col_rewrite_kind(table, c)]
                for c in cols
                if _col_rewrite_kind(table, c)
            }
            rows = src.execute(
                f"SELECT {','.join(f'[{c}]' for c in cols)} FROM [{table}]"
            ).fetchall()
            out_rows = []
            for row in rows:
                new_row = list(row)
                for c, fn in rewrite.items():
                    i = colidx[c]
                    if row[i] is not None:
                        new_row[i] = fn(str(row[i]))
                out_rows.append(new_row)
            placeholders = ",".join("?" * len(cols))
            collist = ",".join(f"[{c}]" for c in cols)
            tgt.executemany(
                f"INSERT OR REPLACE INTO [{table}] ({collist}) VALUES ({placeholders})",
                out_rows,
            )
            report.counts[table] = len(out_rows)
            if progress:
                progress(table, len(out_rows))
        tgt.commit()
        try:
            tgt.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        return report
    finally:
        tgt.close()
        src.close()


def _build_value_remaps(remap_from: str, remap_to: str, new_pid: str | None) -> dict:
    """构造 {重写类别: 函数(旧值)->新值}。

    pid   : project_id 精确替换
    path  : 完整路径或其子路径前缀替换(同时兼容正/反斜杠写法)
    """
    from_n = remap_from.replace("/", "\\").rstrip("\\")
    to_n = remap_to.replace("/", "\\").rstrip("\\")
    old_pid = zclayout.project_id_for(remap_from)
    target_pid = new_pid or zclayout.project_id_for(remap_to)

    def remap_pid(v: str) -> str:
        return target_pid if v == old_pid else v

    def remap_path(v: str) -> str:
        vv = v.replace("/", "\\")
        if vv == from_n:
            return to_n
        if vv.startswith(from_n + "\\"):
            return to_n + vv[len(from_n):]
        return v

    return {"pid": remap_pid, "path": remap_path}


def _col_rewrite_kind(table: str, col: str) -> str | None:
    """返回该列的重写类别('pid'/'path')或 None。"""
    if table == "session":
        if col == "project_id":
            return "pid"
        if col in ("directory", "path"):
            return "path"
        return None
    if table == "permission":
        return "pid" if col == "project_id" else None
    if table == "local_setting":
        return "pid" if col == "scope_id" else None
    if table == "workflow_run":
        return "path" if col == "cwd" else None
    return None


def verify_import(target_db: str, project_id: str) -> dict:
    """恢复后校验: 统计该项目的行数(含按 parent 链归并的 subagent 会话)。"""
    con = sqlite3.connect(f"file:{target_db.replace(chr(92), '/')}?mode=ro", uri=True)
    try:
        out = {}
        owner = zclayout.session_owner_map(con)
        sids = [sid for sid, pid in owner.items() if pid == project_id]
        out["session"] = len(sids)
        if sids:
            ph = ",".join("?" * len(sids))
            for t, c in (("message", "session_id"), ("part", "session_id"), ("session_entry", "session_id")):
                try:
                    out[t] = con.execute(
                        f"SELECT count(*) FROM [{t}] WHERE {c} IN ({ph})", sids
                    ).fetchone()[0]
                except sqlite3.Error:
                    pass
        return out
    finally:
        con.close()
