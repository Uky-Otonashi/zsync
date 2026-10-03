#!/usr/bin/env python3
"""zsync-server 可执行文件打包脚本(仅构建机使用, 不是运行时依赖)。

前置: python -m pip install pyinstaller
用法: python server/build_exe.py
产物: dist/zsync-server 可执行文件(控制台程序, 内嵌共享核心 + web 资产;
      数据目录默认 <exe所在目录>/data, 便于便携部署; systemd 部署建议仍用源码方式)

图标: 仓库自带 zsync logo(assets/icon.ico), Windows 构建自动嵌入 exe;
Linux 产物是 ELF 无图标资源, 自动跳过。zcode 官方图标有版权, 严禁拿来替换。
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
ICON = os.path.join(ROOT, "assets", "icon.ico")  # 仓库自带 zsync logo


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
    if sys.platform == "win32":
        if os.path.isfile(ICON):
            cmd += ["--icon", ICON]
        else:
            print(f"[build] 缺少 {ICON}, exe 将没有自定义图标")
    print("[build]", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=SERVER)
    if rc == 0:
        out = os.path.join(ROOT, "dist", "zsync-server.exe" if os.name == "nt" else "zsync-server")
        print(f"[build] OK -> {out} ({os.path.getsize(out)/1e6:.1f} MB)" if os.path.isfile(out)
              else "[build] 未找到产物")
    return rc


if __name__ == "__main__":
    sys.exit(main())
