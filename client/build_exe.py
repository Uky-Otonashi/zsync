#!/usr/bin/env python3
"""zsync-client 单文件 exe 打包脚本(仅构建机使用, 不是运行时依赖)。

前置: python -m pip install pyinstaller pywebview
用法: python client/build_exe.py
产物: dist/zsync-client.exe (内嵌 Python + 共享核心 + client 入口 + web 资产;
      数据目录默认 %LOCALAPPDATA%/zsync, 不污染 exe 所在目录)
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT = os.path.join(ROOT, "client")


def main() -> int:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "zsync-client",
        "--paths", ROOT,                        # 供 import zsync(共享核心)
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build", "pyi-zsync-client"),
        "--specpath", CLIENT,
        # web GUI 三件套按 zsync 包同级布局打入(httpapi 按 <核心包父目录>/web 解析)
        "--add-data", os.path.join(ROOT, "web") + os.pathsep + "web",
        # pywebview / .NET 绑定链路整体收集, 避免动态加载缺模块
        "--collect-all", "webview",
        "--collect-all", "clr_loader",
        "--collect-all", "pythonnet",
        os.path.join(CLIENT, "zsync-client.py"),
    ]
    print("[build]", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=CLIENT)
    if rc == 0:
        out = os.path.join(ROOT, "dist", "zsync-client.exe")
        print(f"[build] OK -> {out} ({os.path.getsize(out)/1e6:.1f} MB)" if os.path.isfile(out)
              else "[build] 未找到产物 exe")
    return rc


if __name__ == "__main__":
    sys.exit(main())
