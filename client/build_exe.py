#!/usr/bin/env python3
"""zsync-client 单文件 exe 打包脚本(仅构建机使用, 不是运行时依赖)。

前置: python -m pip install pyinstaller pywebview
用法: python client/build_exe.py
产物: dist/zsync-client.exe (内嵌 Python + 共享核心 + client 入口 + web 资产;
      数据目录默认 %LOCALAPPDATA%/zsync, 不污染 exe 所在目录)

图标: 仓库自带 zsync logo(assets/icon.ico, 完整 PNG 尺寸组同在 assets/),
Windows 构建自动嵌入 exe; Linux 产物是 ELF 无图标资源, 自动跳过。
zcode 官方图标有版权, 严禁拿来替换本 logo(仅限本机自用)。
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT = os.path.join(ROOT, "client")
ICON = os.path.join(ROOT, "assets", "icon.ico")  # 仓库自带 zsync logo


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
        os.path.join(CLIENT, "zsync-client.py"),
    ]
    # pywebview 动态加载平台后端, 整包收集; clr_loader/pythonnet 是 Windows 上
    # EdgeChromium 后端的 .NET 绑定链路, Linux 构建环境没有这两个包, 跳过
    cmd += ["--collect-all", "webview"]
    if sys.platform == "win32":
        cmd += ["--collect-all", "clr_loader", "--collect-all", "pythonnet"]
    if sys.platform == "win32":
        if os.path.isfile(ICON):
            cmd += ["--icon", ICON]
        else:
            print(f"[build] 缺少 {ICON}, exe 将没有自定义图标")
    print("[build]", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=CLIENT)
    if rc == 0:
        out = os.path.join(ROOT, "dist", "zsync-client.exe" if os.name == "nt" else "zsync-client")
        print(f"[build] OK -> {out} ({os.path.getsize(out)/1e6:.1f} MB)" if os.path.isfile(out)
              else "[build] 未找到产物 exe")
    return rc


if __name__ == "__main__":
    sys.exit(main())
