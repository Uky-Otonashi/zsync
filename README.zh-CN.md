# zsync

把 ZCode 的工作环境 —— 会话记录、项目记忆、约束、技能和项目源码 —— 打成一个可移植的归档，
在任何机器上恢复。

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]() [![Dependencies](https://img.shields.io/badge/dependencies-stdlib_only-green)]() [![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE) [![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)]()

简体中文 | [English](README.md)

## 为什么写这个工具

ZCode 把 AI 辅助开发的完整历史都留在产生它的那台机器上：会话库里是每一条消息、
思考过程和工具调用，还有逐个项目积累下来的记忆、约束和技能，以及项目本身。这些
数据不会自己走。换一台机器、把项目交给一台虚拟机、或者重装系统，就意味着从零开始。

zsync 做的事情很简单：把这套环境打成单个 `.ztar` 归档（内嵌清单的 tar.gz），推到
中央服务器，需要时在任何机器上恢复。恢复时路径会自动重映射 —— 在
`D:\work\myproject` 打的归档，恢复到 `C:\Projects\myproject` 一样干净，侧边栏会话
索引也一并迁移，打开 ZCode 就像项目一直在这台机器上一样。

## 工作方式

两个角色：

```
        中央服务器                            你的机器
┌───────────────────────────┐     push      ┌────────────────────────┐
│  zsync-server   :8642     │ ◀──────────── │  zsync 客户端          │
│  归档仓库                  │               │  桌面程序(exe)或       │
│  Web 界面                  │ ───────────▶ │  无头 agent            │
└───────────────────────────┘  pull+恢复    └────────────────────────┘
```

**服务器**是个老实巴交的归档库：接收推送、提供下载、挂一个 Web 界面，不碰任何
ZCode 目录，全部用命令行管理。**客户端**跑在每台开发机上，Windows 上就是一个
exe —— 双击出窗口，关窗全停。客户端内嵌一个只监听本机回环地址的小 agent 负责
读取 `~/.zcode`，桌面端和 Web 端共用同一套界面。

## 上手

### 客户端 (Windows)

从[最新 Release](https://github.com/Uky-Otonashi/zsync/releases) 下载
`zsync-client-windows-x86_64.exe` 直接运行，不需要装 Python，也没有安装程序。
第一次启动会让你确认本机 ZCode 目录和服务器地址，之后自动加载项目清单。关掉
窗口一切随之停止，没有任何后台常驻。

喜欢用浏览器、或者你在 Linux/macOS 上：直接打开服务器的 Web 界面，它会引导你
完成一次性接入 —— 从服务器下载 `tool.zip` 解压，Windows 双击 `start-agent.cmd`，
Linux/macOS 运行 `python client/zsync-client.py agent`。任何 Python 3.10+ 都行，
零依赖。服务器也可以自己附带客户端产物（见下文），新机器连 GitHub 和 Python
都不需要。

### 服务器

用发布版二进制：

```
zsync-server-windows-x86_64.exe serve --port 8642 --token <密钥>
```

或者从源码跑：

```
python server/zsync-server.py serve --port 8642 --token <密钥>
```

长期部署有内置的守护和服务注册：

```
python server/zsync-server.py start            # 后台守护(pidfile + 日志)
python server/zsync-server.py service install  # 生成并启用 systemd 服务
```

服务器不在完全可信的网络里就务必设置 `--token`。

### 让服务器自己下发客户端产物（可选）

默认情况下新机器从 GitHub 下载客户端 exe；私有部署可以让服务器自己发。把想
下发的发布产物（至少是各平台的 `zsync-client-*`）放进服务端目录旁的 `bin/`：

```
/opt/zsync/bin/zsync-client-windows-x86_64.exe
/opt/zsync/bin/zsync-client-linux-x86_64
```

之后 Web 界面的首次接入引导会直接给出各平台下载链接；`/tool.zip?bin=win`
（或 `linux` / `all`）会把对应产物打进引导包；包里的 `start-agent` 脚本会自动
优先用随包的单文件客户端，没有才回退 Python。`bin/` 留空则一切照旧 —— 引导包
永远带着无头启动脚本和 Python 源码。

## 归档里有什么

```
project/sessions.sqlite      会话库行(消息/分片/用量/权限…)
project/tasks-index.sqlite   侧边栏索引 —— 会话在 ZCode 里可见的凭据
project/rollout/*.jsonl      模型原始 I/O 轨迹(可能很大)
project/agents|artifacts|exec/**
project/memory/**            项目记忆
source/**                    项目源码(经筛选, 可含 .git)
global/**                    可选: 技能/约束/插件开关
```

每一项都是开关，备份时按项目选，恢复时再选一次：会话、轨迹、子代理数据、记忆、
源码，以及一组可选的全局内容。源码筛选开箱即用（node_modules、venv、构建产物、
日志默认忽略），也可以在界面里按项目对着文件树细调。

## 日常使用

备份在界面里点一下就行：选项目、勾内容，构建并推送到服务器。恢复是对称的 ——
浏览服务器上的归档列表，选一个目标路径，拉下来。目标路径和原机器不同的话，
project id、会话目录、记忆 slug、侧边栏索引都会重写匹配。还有实时备份模式，
项目一有变更就自动重建并推送。

任务和客户端日志收在窗口底部一个默认收起的抽屉里；服务器自己的日志在它的
Web 界面看。

一条铁律：**恢复前完全退出 ZCode**。恢复要写会话库，而 ZCode 正开着它。

## 命令行

客户端本身就是命令行工具，适合脚本化和无头机器：

```
python client/zsync-client.py projects           # 列本机项目
python client/zsync-client.py build --project-id PID [--no-push] [--set source=0 ...]
python client/zsync-client.py push  --archive ID [--server URL]
python client/zsync-client.py pull  --server URL --archive ID --to PATH
python client/zsync-client.py restore --archive ID --to PATH
python client/zsync-client.py archives [--server URL]
python client/zsync-client.py watch  --project-id PID      # 实时备份
python client/zsync-client.py vmpkg  --archive ID --to C:\path
python client/zsync-client.py selftest                    # 沙箱端到端自测
python client/zsync-client.py agent                       # 无头 agent
```

`vmpkg` 生成免 Python 迁移包，目标机器上用 Windows 自带的能力就能恢复。

## 从源码构建

运行时是纯标准库 Python —— clone 下来直接跑，什么都不用装。唯一的构建期依赖是
打桌面/服务器可执行文件：

```
python -m pip install pyinstaller pywebview
python client/build_exe.py
python server/build_exe.py
```

产物在 `dist/`。细节见 [client/BUILD.md](client/BUILD.md)，包括如何给客户端换本地图标。

## 说明与限制

- 轨迹（rollout）在长项目上可能有好几 GB。它和别的一样只是个开关，不需要就关掉。
- Windows 客户端需要 WebView2 运行时，Win10/11 自带。
- Linux 客户端二进制的 agent/CLI 开箱即用，GUI 窗口另需系统 webview 库。
- macOS 从源码构建，代码里没有平台特定的东西。

## 许可证

[MIT](LICENSE)
