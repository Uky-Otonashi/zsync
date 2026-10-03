#!/usr/bin/env python3
"""zsync-server 可执行文件打包脚本(仅构建机使用, 不是运行时依赖)。

前置: python -m pip install pyinstaller
用法: python server/build_exe.py
产物: dist/zsync-server 可执行文件(控制台程序, 内嵌共享核心 + web 资产;
      数据目录默认 <exe所在目录>/data, 便于便携部署; systemd 部署建议仍用源码方式)

可选自用图标: 把图标文件放到 assets/icon.ico(不入仓)再构建, 脚本检测到才带
--icon。zcode 官方图标有版权, 仅限本地自用, 开源发布严禁携带。
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
ICON = os.path.join(ROOT, "assets", "icon.ico")  # 可选, 仓库默认不存在


def main() -> int:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--console",
        "--name", "zsync-server",
        "--paths", ROOT,
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build", "pyi-zsync-server"),
        "--specpath", SERVER,
        "--add-data", os.path.join(ROOT, "web") + os.pathsep + "web",
        os.path.join(SERVER, "zsync-server.py"),
    ]
    if os.path.isfile(ICON):
        cmd += ["--icon", ICON]
        print(f"[build] 使用本地图标 {ICON} (自用构建, 勿发布)")
    else:
        print("[build] 无本地图标文件, 使用默认图标(开源发布形态)")
    print("[build]", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=SERVER)
    if rc == 0:
        out = os.path.join(ROOT, "dist", "zsync-server.exe" if os.name == "nt" else "zsync-server")
        print(f"[build] OK -> {out} ({os.path.getsize(out)/1e6:.1f} MB)" if os.path.isfile(out)
              else "[build] 未找到产物")
    return rc


if __name__ == "__main__":
    sys.exit(main())
