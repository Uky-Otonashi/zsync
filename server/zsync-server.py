#!/usr/bin/env python3
"""zsync 服务端命令行入口 —— 中央存档库 + Web GUI 提供方。

  serve            前台运行(默认 0.0.0.0:8642)
  start/stop/status/restart   后台守护(pidfile + 日志落盘)
  service install/uninstall   注册系统服务(Linux systemd / Windows 计划任务)

服务器只接收客户端推送的存档、响应拉取请求并提供 web 管理界面,
不读写本机 zcode 目录(那是客户端 agent 的职责)。
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zsync import httpapi  # noqa: E402


def main():
    ap = argparse.ArgumentParser(prog="zsync-server",
                                 description="zsync 中央服务器(存档库 + Web GUI), 仅命令行运维")
    ap.add_argument("--store", help="数据目录(默认 <仓库>/data)")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="前台运行")
    s.add_argument("--port", type=int, default=None, help="端口(默认 8642)")
    s.add_argument("--bind", default=None, help="绑定地址(默认 0.0.0.0)")
    s.add_argument("--token", help="访问令牌(校验 API 与 GUI 请求)")

    args = ap.parse_args()
    if args.cmd in (None, "serve"):
        httpapi.serve(port=args.port, bind=args.bind, store_dir=args.store,
                      token=args.token, mode="server")
    else:
        ap.error(f"未知命令: {args.cmd}")


if __name__ == "__main__":
    main()
