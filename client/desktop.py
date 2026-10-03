"""zsync 桌面壳 —— agent 线程内嵌 + pywebview(WebView2) 窗口。

生命周期: 启动 -> 线程内起 agent(127.0.0.1, 首选 8643, 被占自动顺延)
       -> 打开桌面窗口指向该端口(客户端变体 GUI) -> 关窗 -> 停 HTTP+watcher -> 进程退出。
pywebview/WebView2 不可用时降级: 打开系统浏览器 + 前台驻留(Ctrl+C 退出)。
agent 随窗口启停, 不再以系统后台服务形式常驻。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zsync import httpapi  # noqa: E402

PREFERRED_PORT = 8643
PORT_TRIES = 20
# 测试钩子: ZSYNC_GUI_AUTOCLOSE=<秒> 后自动关窗(验证生命周期用)
AUTOCLOSE = float(os.environ.get("ZSYNC_GUI_AUTOCLOSE") or 0)


def _log(msg: str) -> None:
    print(f"[zsync-gui] {msg}", flush=True)


def _default_store() -> str:
    """与 zsync-client.py 保持一致: 冻结 exe 落系统用户目录, 源码运行用仓库 data/。"""
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "zsync", "data")
    return os.path.join(ROOT, "data")


def _port_busy(port: int) -> bool:
    """TCP connect 探测。Windows 的 SO_REUSEADDR 允许对 LISTEN 端口二次 bind,
    仅靠 bind 试错探测不出占用, 必须先 connect。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _start_agent(store_dir: str | None, port: int | None):
    """线程内起 agent; 端口被占则顺延。返回 (httpd, ctx, 实际端口)。"""
    preferred = port or PREFERRED_PORT
    last_err = None
    for p in range(preferred, preferred + PORT_TRIES):
        if _port_busy(p):
            continue
        try:
            httpd, ctx = httpapi.build_server(port=p, bind="127.0.0.1",
                                              store_dir=store_dir, mode="agent")
        except OSError as e:
            last_err = e
            continue
        t = threading.Thread(target=httpd.serve_forever, daemon=True,
                             name=f"zsync-agent-{p}")
        t.start()
        if p != preferred:
            _log(f"端口 {preferred} 被占用, agent 已顺延到 {p}")
        return httpd, ctx, p
    raise SystemExit(f"无法绑定 {preferred}~{preferred + PORT_TRIES - 1}: {last_err or '端口均被占用'}")


def _stop_agent(httpd, ctx) -> None:
    ctx.log("桌面窗口已关闭, 停止 agent")
    try:
        httpd.shutdown()      # 停 serve_forever 线程
        ctx.watchman.stop()
        httpd.server_close()
    except Exception as e:  # noqa: BLE001
        _log(f"agent 收尾异常(忽略): {e}")


def run_gui(store_dir: str | None = None, port: int | None = None) -> int:
    """打开桌面窗口; 返回退出码。pywebview 缺失时降级为浏览器 + 前台驻留。"""
    store = store_dir or _default_store()
    httpd, ctx, port = _start_agent(store, port)
    url = f"http://127.0.0.1:{port}/"
    _log(f"agent 就绪: {url} (store={store})")

    try:
        import webview  # pywebview
    except ImportError:
        _log("未安装 pywebview, 降级: 打开系统浏览器, Ctrl+C 退出")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        _stop_agent(httpd, ctx)
        return 0

    def on_closed():
        _log("窗口关闭事件")

    window = webview.create_window(
        "zsync 客户端 · zcode 环境同步", url,
        width=1280, height=840, min_size=(960, 600))
    window.events.closed += on_closed  # pywebview 5+: 关窗回调走事件
    if AUTOCLOSE > 0:
        def _autoclose():
            try:
                window.destroy()
            except Exception:  # noqa: BLE001  窗口可能已关
                pass
        threading.Timer(AUTOCLOSE, _autoclose).start()
    try:
        webview.start(gui="edgechromium")
    except Exception as e:  # noqa: BLE001  (WebView2 运行时缺失等)
        _log(f"桌面窗口启动失败({e}), 降级: 打开系统浏览器, Ctrl+C 退出")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    _stop_agent(httpd, ctx)
    _log("已退出")
    return 0


if __name__ == "__main__":
    sys.exit(run_gui())
