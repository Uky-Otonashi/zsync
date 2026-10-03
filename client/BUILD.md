# zsync-client 桌面端打包说明(Windows 单文件 exe)

产物 `zsync-client.exe`：内嵌 Python 运行时 + 共享核心(`zsync/`) + 客户端入口 + Web GUI
三件套(`web/`)，目标机器**无需安装 Python**，仅需 Edge WebView2 运行时(Win10/11 一般自带)。

## 一次性准备(构建机)

```
python -m pip install pyinstaller pywebview
```

仅打包需要这两个依赖；核心代码运行时仍是纯标准库，pywebview 只在桌面窗口形态用到
(缺失时 exe 仍可运行 CLI 子命令)。

## 构建

在仓库根目录执行：

```
python client/build_exe.py
```

产物：`dist/zsync-client.exe`（约 50MB，含 Python + .NET 绑定链路）。
中间产物在 `build/pyi-zsync-client/` 与 `client/zsync-client.spec`，可安全删除。

## 图标

zsync 自绘 logo 随仓库分发：`assets/icon.ico`(exe 图标) + `assets/zsync-icon-*.png`
(原始尺寸组，`assets/icon.png` 即 1024 版)，`web/icon.png`(512 版) 作为页面 favicon。
`build_exe.py` 在 Windows 构建时自动嵌入 exe 图标（Linux 产物是 ELF，无图标资源，
自动跳过），无需任何手工放置。

⚠️ 版权红线不变：**严禁用 zcode 官方图标替换本 logo**——官方图标仅限本机自用，
不得入仓或随 Release 发布。

## 行为要点

- 双击 exe 直接打开桌面窗口(无子命令默认进入 `gui`)；也可命令行使用
  `agent / build / pull / restore ...` 等子命令。
- agent 内嵌于窗口进程：启动即拉起(127.0.0.1:8643，被占自动顺延)，关窗即停止。
- 数据目录默认 `%LOCALAPPDATA%\zsync\data`，不污染 exe 所在目录；
  `--store` 可覆盖。
- 冒烟建议：`ZSYNC_GUI_AUTOCLOSE=10 ./dist/zsync-client.exe` 自动开窗 10 秒后自关，
  期间 `curl http://127.0.0.1:8643/api/state` 应答 `mode=agent`。

## 产物去向

构建出的 `zsync-client-<platform>-<arch>` 除上传 GitHub Release 外，还可以直接
放进服务端目录旁的 `bin/`（源码部署=仓库根 `bin/`，单文件 server exe=其所在
目录的 `bin/`）——Web 首访引导页即会直链下发、`tool.zip?bin=` 可打入引导包，
详见 README「让服务器自己下发客户端产物」。`bin/` 里的文件不会被 git 跟踪。
