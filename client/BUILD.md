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

## 可选: 本地自用图标(⚠️ 版权红线)

zcode 官方图标**只能本地自用**:把 `icon.ico` 放到 `assets/`、`icon.png` 放到 `web/`
(两个路径都在 .gitignore 排除,**严禁提交或随 Release 发布**,否则构成侵权),
再运行 `python client/build_exe.py` 即得到带图标的自用 exe。仓库默认不含这些文件,
`git status` 若看到它们出现,说明 ignore 失效,必须先处理再提交。

## 行为要点

- 双击 exe 直接打开桌面窗口(无子命令默认进入 `gui`)；也可命令行使用
  `agent / build / pull / restore ...` 等子命令。
- agent 内嵌于窗口进程：启动即拉起(127.0.0.1:8643，被占自动顺延)，关窗即停止。
- 数据目录默认 `%LOCALAPPDATA%\zsync\data`，不污染 exe 所在目录；
  `--store` 可覆盖。
- 冒烟建议：`ZSYNC_GUI_AUTOCLOSE=10 ./dist/zsync-client.exe` 自动开窗 10 秒后自关，
  期间 `curl http://127.0.0.1:8643/api/state` 应答 `mode=agent`。
