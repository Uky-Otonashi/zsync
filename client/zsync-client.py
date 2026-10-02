#!/usr/bin/env python3
"""zsync 客户端命令行入口 —— 本机 zcode 环境的备份/恢复操作 + 无头 agent。

  agent   启动本机代理(127.0.0.1:8643, 供中央服务器页面跨源调用;
          桌面 GUI 模式会以内嵌线程自动拉起, 一般无需手动运行)
  config  查看/修改客户端设置(zcode 目录、推送目标)
  projects        列出本机项目
  build   --project-id PID [--set k=v] [--archive-id ID] [--no-push]
  push    --archive ID --server URL [--token T]
  pull    --server URL --archive ID --to PATH [--only k,...]
  restore --archive ID --to PATH
  archives [--server URL]
  watch   --project-id PID [--interval 20]
  vmpkg   --archive ID --to C:\\path [--vm-db db] [--vm-tasks-index idx]
  selftest [--project-id PID]

组件开关 k=v: sessions rollout artifacts agents exec_logs memory source
  include_git global_skills global_constraints global_plugins global_agents_md
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time

if getattr(sys, "frozen", False):  # PyInstaller 单文件 exe: 核心包已内嵌, 无需源码树
    ROOT = os.path.dirname(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zsync import zclayout, dbio, bundle, client, tasksindex  # noqa: E402
from zsync.bundle import BundleStore, BundleBuilder, Components, RestoreOptions, restore_bundle  # noqa: E402
from zsync.nodeconfig import NodeConfig  # noqa: E402


def _default_store() -> str:
    """数据目录: 冻结 exe 落系统用户目录; 源码运行沿用仓库 data/。"""
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "zsync", "data")
    return os.path.join(ROOT, "data")


def parse_sets(pairs: list[str]) -> dict:
    d = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        d[k] = {"1": True, "0": False, "true": True, "false": False}.get(v.lower(), v)
    return d


def _store(args) -> BundleStore:
    return BundleStore(args.store or _default_store())


def _layout(args=None):
    """优先客户端配置的 zcode 目录, 其次 --zcode-home / ZCODE_HOME / 默认。"""
    home = None
    if args and getattr(args, "zcode_home", None):
        home = args.zcode_home
    else:
        try:
            st = _store(args)
            cfg = NodeConfig(st.dir)
            if os.path.isfile(cfg.path):
                home = cfg.zcode_home
        except Exception:  # noqa: BLE001
            pass
    if not home:
        home = os.environ.get("ZCODE_HOME") or NodeConfig(_store(args).dir).zcode_home
    return zclayout.ZcodeLayout(home)


def _prog(phase, pct, detail=""):
    print(f"\r[{phase}] {pct:5.1f}%  {detail[:70]:<70}", end="", flush=True)


def find_project(layout, project_id: str):
    for p in zclayout.list_projects(layout):
        if p.project_id == project_id or (
            p.path and p.path.lower() == project_id.lower().replace("/", "\\")
        ):
            return p
    raise SystemExit(f"项目不存在: {project_id} (用 projects 命令查看)")


def cmd_agent(args):
    from zsync import httpapi
    httpapi.serve(port=args.port, bind=args.bind, store_dir=args.store,
                  token=args.token, mode="agent")


def cmd_config(args):
    st = _store(args)
    cfg = NodeConfig(st.dir)
    if args.zcode_home or args.remote_url is not None or args.remote_token is not None:
        cfg.update(zcode_home=args.zcode_home, remote_url=args.remote_url,
                   remote_token=args.remote_token)
    pub = cfg.public()
    print(json.dumps(pub, ensure_ascii=False, indent=2))
    print("store:", st.dir)


def cmd_projects(args):
    layout = _layout(args)
    for p in zclayout.list_projects(layout):
        last = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.last_active / 1000)) if p.last_active else "-"
        print(f"{p.project_id}\n    路径: {p.path}  会话: {p.sessions}  最近: {last}  "
              f"轨迹: {bundle.fmt_bytes(p.rollout_bytes)}  记忆文件: {p.memory_files}")


def cmd_build(args):
    layout = _layout(args)
    st = _store(args)
    cfg = NodeConfig(st.dir)
    p = find_project(layout, args.project_id)
    sets = parse_sets(args.sets)
    comps = Components.from_dict(sets or cfg.project_config(p.project_id).get("components"))
    sf = cfg.project_config(p.project_id).get("source_filter")
    archive_id = args.archive_id or f"{p.name}_{time.strftime('%Y%m%d_%H%M%S')}"
    print(f"构建 {archive_id} (项目 {p.name}, {p.sessions} 会话)")
    m = BundleBuilder(layout, st).build(
        archive_id, {"project_id": p.project_id, "path": p.path}, comps,
        source_filter=sf, keep_staging=bool(args.keep_staging), progress=_prog)
    print(f"\n完成: {bundle.fmt_bytes(m['ztar_bytes'])} -> {st.ztar_path(archive_id)}")
    server = args.server or cfg.remote_url
    if server and not args.no_push:
        print(f"推送到 {server} ...")
        client.upload_ztar(server, archive_id, st.ztar_path(archive_id), m,
                           token=args.token or cfg.remote_token, progress=_prog)
        print("\n推送完成")


def cmd_push(args):
    st = _store(args)
    cfg = NodeConfig(st.dir)
    server = args.server or cfg.remote_url
    token = args.token or cfg.remote_token
    if not server:
        raise SystemExit("未指定远端(--server 或 config --remote-url)")
    m = st.manifest(args.archive)
    if not m:
        raise SystemExit(f"本地归档不存在: {args.archive}")
    client.upload_ztar(server, args.archive, st.ztar_path(args.archive), m,
                       token=token, progress=_prog)
    print(f"\n已推送 {args.archive} -> {server}")


def _comps_from(args) -> Components:
    comps = Components.from_dict(parse_sets(args.sets))
    if getattr(args, "only", None):
        comps = Components()
        for k in args.only.split(","):
            if hasattr(comps, k):
                setattr(comps, k, True)
            else:
                raise SystemExit(f"未知组件: {k}")
    return comps


def cmd_pull(args):
    st = _store(args)
    layout = _layout(args)
    comps = _comps_from(args)
    pull_dir = os.path.join(st.dir, "pulls", args.archive)
    zt = os.path.join(pull_dir, "package.ztar")
    print(f"拉取 {args.archive} 自 {args.server}")
    if os.path.exists(zt):
        os.remove(zt)
    client.download_ztar(args.server, args.archive, zt, args.token, _prog)
    print(f"\n下载完成 {bundle.fmt_bytes(os.path.getsize(zt))}")
    xdir = pull_dir + "_x"
    shutil.rmtree(xdir, ignore_errors=True)
    st.extract_to(zt, xdir)
    _do_restore(st, layout, xdir, args.to, comps)


def _do_restore(st, layout, bundle_dir, target, comps):
    print(f"恢复到 {target} (请确保 zcode 已退出)")
    opts = RestoreOptions(target_path=os.path.abspath(target), components=comps)
    rep = restore_bundle(bundle_dir, layout, opts, _prog)
    print(f"\nDB行: {rep.db_counts}")
    print(f"会话列表索引写入: {rep.tasks_index_rows} 行 (校验 {rep.tasks_verify})")
    print(f"文件: {rep.files_copied}  源码: {rep.source_files}")
    if rep.warnings:
        print("警告:", *rep.warnings, sep="\n  ")
    print("校验:", rep.verify)


def cmd_restore(args):
    st = _store(args)
    layout = _layout(args)
    if not st.manifest(args.archive):
        raise SystemExit(f"本地归档不存在: {args.archive}")
    xdir = os.path.join(st.dir, "pulls", args.archive + "_local")
    shutil.rmtree(xdir, ignore_errors=True)
    st.extract_to(st.ztar_path(args.archive), xdir)
    _do_restore(st, layout, xdir, args.to, _comps_from(args))


def cmd_archives(args):
    if args.server:
        for a in client.list_remote_archives(args.server, args.token):
            print(f"{a['archive_id']}  {bundle.fmt_bytes(a.get('ztar_bytes', 0))}  "
                  f"{time.strftime('%m-%d %H:%M', time.localtime(a.get('updated_at', 0) / 1000))}")
    else:
        for a in _store(args).list_archives():
            print(f"{a['archive_id']}  {bundle.fmt_bytes(a.get('ztar_bytes', 0))}  "
                  f"{time.strftime('%m-%d %H:%M', time.localtime(a.get('updated_at', 0) / 1000))}")


def cmd_watch(args):
    from zsync.watcher import WatchManager, ProjectWatcher
    layout = _layout(args)
    st = _store(args)
    cfg = NodeConfig(st.dir)
    p = find_project(layout, args.project_id)
    comps = Components.from_dict(parse_sets(args.sets) or cfg.project_config(p.project_id).get("components"))
    sf = cfg.project_config(p.project_id).get("source_filter")
    archive_id = f"{p.name}_live"
    builder = BundleBuilder(layout, st)
    w = ProjectWatcher(p.project_id, p.path, comps, interval=args.interval, label=p.name)

    def on_rebuild(watcher):
        def run():
            print(f"\n[{time.strftime('%H:%M:%S')}] 变更, 重建 {archive_id} ...")
            m = builder.build(archive_id, {"project_id": p.project_id, "path": p.path},
                              comps, source_filter=sf, keep_staging=True, progress=_prog)
            print(f"[{time.strftime('%H:%M:%S')}] 完成 ({m['build_seconds']}s)")

        threading.Thread(target=run, daemon=True).start()

    wm = WatchManager(layout, st, on_rebuild)
    wm.watchers[p.project_id] = w
    print(f"实时监控 {p.name} (间隔 {args.interval}s, Ctrl+C 退出)")
    wm.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        wm.stop()


def cmd_vmpkg(args):
    st = _store(args)
    from zsync import vmpkg as vmpkg_mod
    comps = Components.from_dict(parse_sets(args.sets)) if args.sets else None
    out_dir = args.out or os.path.join(
        st.dir, "vmprep", f"{args.archive}_{time.strftime('%Y%m%d_%H%M%S')}")
    m = vmpkg_mod.build_migration_package(
        st, args.archive, args.to, out_dir,
        base_db=args.vm_db, base_tasks_index=args.vm_tasks_index,
        components=comps.to_dict() if comps else None, progress=_prog)
    print(f"\n迁移包: {os.path.join(out_dir, 'package.tgz')} ({bundle.fmt_bytes(m['package_tgz_bytes'])})")
    print(f"目标: {m['target_path']}  project_id: {m['target_project_id']}")
    print(f"tasks-index: 写入 {m['restore'].get('tasks_index_rows')} 行 / 校验 {m['restore'].get('tasks_verify')}")


def _clone_schema(src_db: str, dst_db: str) -> None:
    con, tmp = zclayout.open_ro(src_db)
    try:
        sqls = [r[0] for r in con.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
    finally:
        con.close()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    out = sqlite3.connect(dst_db)
    out.executescript(";\n".join(sqls))
    out.commit()
    out.close()


def cmd_selftest(args):
    """沙箱端到端: 构建 .ztar -> 克隆 schema + tasks-index 的临时 home -> 恢复(重映射) -> 校验。"""
    layout = _layout(args)
    if not layout.exists():
        raise SystemExit("本机无 zcode 数据库")
    pid = args.project_id
    if not pid:
        cands = [p for p in zclayout.list_projects(layout) if p.path]
        if not cands:
            raise SystemExit("没有可用项目")
        pid = sorted(cands, key=lambda p: (p.rollout_bytes, -p.sessions))[0].project_id
    proj = find_project(layout, pid)
    print(f"自测项目: {proj.name} ({proj.path}, {proj.sessions} 会话)")

    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        mark = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{mark}] {name} {detail}")

    with tempfile.TemporaryDirectory(prefix="zsync_selftest_") as td:
        st = BundleStore(os.path.join(td, "store"))
        aid = f"selftest_{proj.name}"
        comps = Components(sessions=True, rollout=True, artifacts=True, agents=True,
                           exec_logs=True, memory=True, source=True)
        if proj.rollout_bytes > 3_000_000_000:
            print(f"  轨迹过大({bundle.fmt_bytes(proj.rollout_bytes)}), 自测关闭 rollout")
            comps.rollout = False

        def prog(phase, pct, detail=""):
            if pct in (0, 100) or detail:
                print(f"  [{phase}] {pct:.0f}% {detail}")

        m = BundleBuilder(layout, st).build(
            aid, {"project_id": pid, "path": proj.path}, comps, progress=prog)
        print(f"  构建 {bundle.fmt_bytes(m['ztar_bytes'])} ({m['build_seconds']}s)")
        check("单压缩包存在", os.path.isfile(st.ztar_path(aid)))

        # 清单可独立读取
        man = st.manifest(aid)
        check("清单可读", man is not None and man.get("stats", {}).get("sessions") == proj.sessions)

        # 沙箱 home
        sandbox = zclayout.ZcodeLayout(os.path.join(td, "home", ".zcode"))
        os.makedirs(os.path.dirname(sandbox.db_path), exist_ok=True)
        _clone_schema(layout.db_path, sandbox.db_path)
        # 沙箱 tasks-index(空库带表)
        src_idx = tasksindex.tasks_index_path(layout.home)
        if os.path.isfile(src_idx):
            con = sqlite3.connect(src_idx)
            create = con.execute("SELECT sql FROM sqlite_master WHERE name='tasks'").fetchone()
            con.close()
            os.makedirs(os.path.dirname(tasksindex.tasks_index_path(sandbox.home)), exist_ok=True)
            tcon = sqlite3.connect(tasksindex.tasks_index_path(sandbox.home))
            tcon.execute(create[0])
            tcon.commit()
            tcon.close()

        xdir = os.path.join(td, "x")
        st.extract_to(st.ztar_path(aid), xdir)
        new_path = os.path.join(td, "dest", proj.name)
        rep = restore_bundle(xdir, sandbox, RestoreOptions(
            target_path=new_path, components=comps), prog)

        exp = m["stats"]["sessions"]
        check("会话数一致", rep.verify.get("session") == exp, f"{rep.verify.get('session')}/{exp}")
        src_counts = dbio.verify_import(layout.db_path, pid)
        for t in ("message", "part"):
            check(f"{t} 行一致", rep.verify.get(t) == src_counts.get(t),
                  f"{rep.verify.get(t)}/{src_counts.get(t)}")
        # tasks-index
        src_tasks = tasksindex.verify_tasks(src_idx, proj.path)
        check("会话列表索引迁移", rep.tasks_verify == src_tasks,
              f"恢复 {rep.tasks_verify} / 源 {src_tasks}")
        if rep.tasks_verify:
            con = sqlite3.connect(tasksindex.tasks_index_path(sandbox.home))
            row = con.execute(
                "SELECT count(*) FROM tasks WHERE workspace_path = ? COLLATE NOCASE",
                (new_path,)).fetchone()
            meta_ok = con.execute(
                "SELECT count(*) FROM tasks WHERE meta_json LIKE ?",
                ('%' + new_path.replace('\\', '\\\\')[:20] + '%',)).fetchone()[0]
            con.close()
            check("索引 workspace 重映射", row[0] == src_tasks, f"{row[0]}/{src_tasks}")
        # 重映射
        con = sqlite3.connect(sandbox.db_path)
        row = con.execute(
            "SELECT count(*), max(directory=?) FROM session WHERE project_id=?",
            (new_path, zclayout.project_id_for(new_path))).fetchone()
        check("project_id/directory 重映射", row[0] == exp and bool(row[1]), new_path)
        con.close()
        if comps.memory and proj.path:
            md = layout.memory_dir_for(proj.path)
            if os.path.isdir(md):
                n_src = sum(len(f) for _, _, f in os.walk(md))
                n_dst = sum(len(f) for _, _, f in os.walk(sandbox.memory_dir_for(new_path)))
                check("记忆迁移", n_dst == n_src, f"{n_dst}/{n_src}")
        if comps.rollout:
            con, tmp = zclayout.open_ro(layout.db_path)
            sids = zclayout.project_session_ids(con, pid)
            con.close()
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            missing = [s for s in sids
                       if os.path.isfile(os.path.join(layout.rollout_dir, f"model-io-{s}.jsonl"))
                       and not os.path.isfile(os.path.join(sandbox.rollout_dir, f"model-io-{s}.jsonl"))]
            check("模型轨迹迁移", not missing, f"缺失 {len(missing)}")
        if comps.source and os.path.isdir(proj.path):
            n_items = len(os.listdir(new_path)) if os.path.isdir(new_path) else 0
            check("源码解压", n_items > 0, f"{n_items} 项")
        else:
            print("  [SKIP] 源码解压 (项目目录不在本机)")

        # 远端接收回环: 验证 import_ztar
        st2 = BundleStore(os.path.join(td, "store2"))
        aid2 = st2.import_ztar(st.ztar_path(aid), man)
        check("远端接收(import_ztar)", st2.manifest(aid2) is not None and os.path.isfile(st2.ztar_path(aid2)))

    print("\n自测结果:", "PASS ✓" if ok else "FAIL ✗")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(prog="zsync-client", description="zsync 客户端(本机 zcode 备份/恢复 + agent)")
    ap.add_argument("--store", help=f"数据目录(默认 {_default_store()})")
    ap.add_argument("--zcode-home", help="覆盖本机 zcode 目录(默认读客户端配置/环境变量)")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("agent", help="启动本机 agent(127.0.0.1:8643, 供服务器页面/桌面 GUI 使用)")
    s.add_argument("--port", type=int, default=None, help="端口(默认 8643)")
    s.add_argument("--bind", default=None, help="绑定地址(默认 127.0.0.1)")
    s.add_argument("--token")
    s.set_defaults(func=cmd_agent)

    s = sub.add_parser("config", help="查看/修改客户端设置")
    s.add_argument("--zcode-home")
    s.add_argument("--remote-url")
    s.add_argument("--remote-token")
    s.set_defaults(func=cmd_config)

    s = sub.add_parser("projects", help="列出本机项目")
    s.set_defaults(func=cmd_projects)

    s = sub.add_parser("build", help="构建归档(默认推送到已配置远端)")
    s.add_argument("--project-id", required=True)
    s.add_argument("--sets", nargs="*", default=[])
    s.add_argument("--archive-id")
    s.add_argument("--no-push", action="store_true")
    s.add_argument("--keep-staging", action="store_true")
    s.add_argument("--server")
    s.add_argument("--token")
    s.set_defaults(func=cmd_build)

    s = sub.add_parser("push", help="推送本地归档到远端")
    s.add_argument("--archive", required=True)
    s.add_argument("--server")
    s.add_argument("--token")
    s.set_defaults(func=cmd_push)

    s = sub.add_parser("pull", help="从远端拉取并恢复到本机")
    s.add_argument("--server", required=True)
    s.add_argument("--archive", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--token")
    s.add_argument("--only")
    s.add_argument("--sets", nargs="*", default=[])
    s.set_defaults(func=cmd_pull)

    s = sub.add_parser("restore", help="从本机存档恢复")
    s.add_argument("--archive", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--only")
    s.add_argument("--sets", nargs="*", default=[])
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("archives", help="列出存档")
    s.add_argument("--server")
    s.add_argument("--token")
    s.set_defaults(func=cmd_archives)

    s = sub.add_parser("watch", help="前台实时备份")
    s.add_argument("--project-id", required=True)
    s.add_argument("--interval", type=float, default=20)
    s.add_argument("--sets", nargs="*", default=[])
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("vmpkg", help="构建免 Python 迁移包")
    s.add_argument("--archive", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--vm-db", help="目标机当前 db.sqlite(合并底座)")
    s.add_argument("--vm-tasks-index", help="目标机当前 tasks-index.sqlite")
    s.add_argument("--out")
    s.add_argument("--sets", nargs="*", default=[])
    s.set_defaults(func=cmd_vmpkg)

    s = sub.add_parser("selftest", help="沙箱端到端自测")
    s.add_argument("--project-id")
    s.set_defaults(func=cmd_selftest)

    args = ap.parse_args()
    rc = args.func(args)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
