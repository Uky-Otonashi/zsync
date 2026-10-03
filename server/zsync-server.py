#!/usr/bin/env python3
"""zsync 服务端命令行入口 —— 中央存档库 + Web GUI 提供方, 仅命令行运维。

  serve                   前台运行(默认 0.0.0.0:8642)
  start / stop / restart / status   后台守护(pidfile + 日志落 <store>/logs/)
  service install         注册系统服务(Linux: systemd unit + enable;
                          Windows: 开机计划任务), service uninstall 反向清理
  service start|stop|status         交给系统服务管理器代管

服务器只接收客户端推送的存档、响应拉取请求并提供 web 管理界面,
不读写本机 zcode 目录(那是客户端 agent 的职责)。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zsync import httpapi  # noqa: E402

SERVICE_NAME = "zsync"


def _run_text(cmd: list[str]):
    """运行命令并按本机代码页安全取回文本(中文 Windows 的 tasklist/schtasks
    输出 GBK, 直接 text=True 按 utf-8 解码会在读线程崩)。"""
    enc = "gbk" if os.name == "nt" else "utf-8"
    return subprocess.run(cmd, capture_output=True, encoding=enc, errors="replace")


def _default_store() -> str:
    return os.path.join(ROOT, "data")


def _pidfile(store: str) -> str:
    return os.path.join(store, "zsync-server.pid")


def _serve_argv(args) -> list[str]:
    """守护/服务注册时重启本入口所需的 serve 参数(--store 为顶层参数, 须在子命令前)。"""
    argv = [sys.executable, os.path.abspath(__file__), "--store", args.store, "serve"]
    if args.port is not None:
        argv += ["--port", str(args.port)]
    if args.bind is not None:
        argv += ["--bind", args.bind]
    if args.token:
        argv += ["--token", args.token]
    return argv


def _read_pidinfo(store: str) -> dict | None:
    try:
        with open(_pidfile(store), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True).stdout
        return str(pid).encode() in out  # 输出为 GBK, 按 ASCII pid 匹配即可
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def cmd_serve(args):
    httpapi.serve(port=args.port, bind=args.bind, store_dir=args.store,
                  token=args.token, mode="server")


def cmd_start(args):
    store = args.store or _default_store()
    os.makedirs(os.path.join(store, "logs"), exist_ok=True)
    old = _read_pidinfo(store)
    if old and _pid_alive(old["pid"]):
        raise SystemExit(f"已在运行 (pid {old['pid']}), 用 stop 先停或 status 查看")
    argv = _serve_argv(args)
    log = open(os.path.join(store, "logs", "server.log"), "ab")
    kw = {"stdout": log, "stderr": log, "cwd": ROOT, "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen(argv, **kw)
    with open(_pidfile(store), "w", encoding="utf-8") as f:
        json.dump({"pid": p.pid, "argv": argv, "started": time.time()}, f)
    time.sleep(1.0)
    if p.poll() is not None:
        raise SystemExit(f"进程立即退出(code {p.returncode}), 查看 {store}/logs/server.log")
    print(f"已启动 pid={p.pid}  日志: {os.path.join(store, 'logs', 'server.log')}")


def cmd_stop(args):
    store = args.store or _default_store()
    info = _read_pidinfo(store)
    if not info:
        raise SystemExit("未发现运行实例(无 pidfile)")
    pid = info["pid"]
    if not _pid_alive(pid):
        os.remove(_pidfile(store))
        raise SystemExit(f"进程 {pid} 已不在, 清理 pidfile")
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(50):
                if not _pid_alive(pid):
                    break
                time.sleep(0.2)
            else:
                os.kill(pid, signal.SIGKILL)
        except PermissionError:
            raise SystemExit(f"无权限停止 pid {pid}(需要对应权限)")
    os.remove(_pidfile(store))
    print(f"已停止 pid={pid}")


def cmd_status(args):
    store = args.store or _default_store()
    info = _read_pidinfo(store)
    port = args.port if args.port is not None else httpapi.DEFAULT_PORT
    if info and _pid_alive(info["pid"]):
        print(f"运行中 pid={info['pid']}  端口 {'监听中' if _port_listening(port) else '未监听'}"
              f"  启动于 {time.strftime('%Y-%m-%d %H:%M', time.localtime(info['started']))}")
        return 0
    print("未运行")
    return 1


def cmd_restart(args):
    store = args.store or _default_store()
    if _read_pidinfo(store):
        ns = argparse.Namespace(**vars(args))
        cmd_stop(ns)
        time.sleep(0.5)
    cmd_start(args)


# ---------------- systemd / 计划任务 ----------------

def _systemd_unit(args) -> str:
    exec_argv = _serve_argv(args)
    return f"""[Unit]
Description=zsync central server (archive store + web GUI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={os.environ.get("USER") or "root"}
WorkingDirectory={ROOT}
ExecStart={' '.join(exec_argv)}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def _need_root_or_die():
    if os.name == "posix" and os.geteuid() != 0:
        raise SystemExit("需要 root 权限(加 sudo 重试)")


def _service_install(args):
    if shutil.which("systemctl"):
        _need_root_or_die()
        unit = "/etc/systemd/system/zsync.service"
        if os.path.exists(unit):
            print(f"unit 已存在, 覆盖: {unit}")
        with open(unit, "w", encoding="utf-8") as f:
            f.write(_systemd_unit(args))
        for c in (["systemctl", "daemon-reload"], ["systemctl", "enable", "--now", SERVICE_NAME]):
            r = _run_text(c)
            if r.returncode != 0:
                raise SystemExit(f"命令失败: {' '.join(c)}\n{r.stderr.strip()}")
        print(f"已安装 systemd 服务 {SERVICE_NAME} 并设为开机自启/立即启动\n  unit: {unit}")
    elif os.name == "nt":
        tr = " ".join(f'"{a}"' if " " in a else a for a in _serve_argv(args))
        r = _run_text(["schtasks", "/Create", "/F", "/TN", SERVICE_NAME,
                      "/SC", "ONSTART", "/RU", "SYSTEM", "/TR", tr])
        if r.returncode != 0:
            raise SystemExit(f"schtasks 失败: {(r.stderr or r.stdout).strip()}")
        print(f"已注册开机计划任务 {SERVICE_NAME} (SYSTEM 账户)\n"
              f"  注意: exe 路径不能变动, 变动后需重新 install")
    else:
        raise SystemExit("未找到 systemctl, 且非 Windows —— 请手工配置服务管理器")


def _service_uninstall(args):
    if shutil.which("systemctl"):
        _need_root_or_die()
        for c in (["systemctl", "disable", "--now", SERVICE_NAME],
                  ["systemctl", "stop", SERVICE_NAME]):
            subprocess.run(c, capture_output=True)
        unit = "/etc/systemd/system/zsync.service"
        if os.path.exists(unit):
            os.remove(unit)
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
        print(f"已卸载 systemd 服务 {SERVICE_NAME}")
    elif os.name == "nt":
        r = _run_text(["schtasks", "/Delete", "/F", "/TN", SERVICE_NAME])
        print("已删除计划任务" if r.returncode == 0 else f"删除失败: {(r.stderr or r.stdout).strip()}")
    else:
        raise SystemExit("不支持的平台")


def _service_ctl(args, action: str):
    if shutil.which("systemctl"):
        _need_root_or_die()
        r = _run_text(["systemctl", action, SERVICE_NAME])
        if r.returncode != 0:
            raise SystemExit(f"systemctl {action} 失败: {r.stderr.strip()}")
    elif os.name == "nt":
        sch = {"start": ["/Run"], "stop": ["/End"], "status": ["/Query"]}[action]
        r = _run_text(["schtasks", *sch, "/TN", SERVICE_NAME])
        if action == "status":
            print((r.stdout or r.stderr).strip())
            return
        if r.returncode != 0:
            raise SystemExit(f"schtasks {action} 失败: {(r.stderr or r.stdout).strip()}")
    else:
        raise SystemExit("不支持的平台")
    print(f"服务 {SERVICE_NAME}: {action} 完成")


def main():
    ap = argparse.ArgumentParser(prog="zsync-server",
                                 description="zsync 中央服务器(存档库 + Web GUI), 仅命令行运维")
    ap.add_argument("--store", help=f"数据目录(默认 {_default_store()})")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="前台运行")
    s.add_argument("--port", type=int, default=None, help="端口(默认 8642)")
    s.add_argument("--bind", default=None, help="绑定地址(默认 0.0.0.0)")
    s.add_argument("--token", help="访问令牌(校验 API 与 GUI 请求)")
    s.set_defaults(func=cmd_serve)

    for name, help_ in (("start", "后台守护启动(pidfile+日志)"), ("stop", "停止后台守护"),
                        ("restart", "重启后台守护"), ("status", "查看运行状态")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("--port", type=int, default=None)
        s.add_argument("--bind", default=None)
        s.add_argument("--token", default=None)
        s.set_defaults(func=globals()[f"cmd_{name}"])

    s = sub.add_parser("service", help="系统服务注册与管理(systemd / 计划任务)")
    ssub = s.add_subparsers(dest="service_cmd", required=True)
    for name, help_ in (("install", "注册并设开机自启"), ("uninstall", "停止并卸载注册"),
                        ("start", "经服务管理器启动"), ("stop", "经服务管理器停止"),
                        ("status", "查看服务状态")):
        ss = ssub.add_parser(name, help=help_)
        ss.add_argument("--port", type=int, default=None)
        ss.add_argument("--bind", default=None)
        ss.add_argument("--token", default=None)
        ss.set_defaults(action=name)
    s.set_defaults(func=lambda a: _service_ctl(a, a.action) if a.action in ("start", "stop", "status")
                   else (_service_install(a) if a.action == "install" else _service_uninstall(a)))

    args = ap.parse_args()
    if args.cmd is None:
        ap.print_help()
        return
    if not args.store:
        args.store = _default_store()
    rc = args.func(args)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
