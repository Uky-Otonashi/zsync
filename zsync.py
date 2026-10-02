#!/usr/bin/env python3
"""zsync 兼容垫片(v0.4 拆分) —— 旧命令自动转发到新入口:

  服务端:  python server/zsync-server.py serve ...
  客户端:  python client/zsync-client.py agent|build|pull|...

映射规则: `zsync.py serve --agent ...` → 客户端 `agent`;
          `zsync.py serve ...`        → 服务端 `serve`;
          其余子命令                  → 客户端(备份/恢复 CLI 均属客户端)。
垫片将在后续版本移除, 请尽快改用新入口。
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.join(HERE, "client", "zsync-client.py")
SERVER = os.path.join(HERE, "server", "zsync-server.py")


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "serve":
        if "--agent" in argv:
            rest = [a for a in argv if a not in ("serve", "--agent")]
            target, args = CLIENT, ["agent"] + rest
        else:
            target, args = SERVER, argv
    else:
        target, args = CLIENT, argv
    print(f"[zsync] v0.4 起入口已拆分, 转发到 {os.path.relpath(target, HERE)} (兼容垫片, 后续版本移除)",
          file=sys.stderr)
    sys.exit(subprocess.call([sys.executable, target] + args))


if __name__ == "__main__":
    main()
