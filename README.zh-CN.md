# zsync

**把 ZCode 开发环境 —— 会话、记忆、约束、技能与项目源码 —— 打包成单个可移植归档，实现备份 / 同步 / 迁移。**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]() [![Dependencies](https://img.shields.io/badge/dependencies-zero-stdlib_only-green)]() [![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE) [![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)]()

简体中文 | [English](README.md)

---

## 为什么需要 zsync?

ZCode 把 AI 辅助开发的完整历史都留在本机：会话（含完整上下文、思考过程、
工具调用轨迹）、项目记忆、约束、技能，以及项目源码。这些数据不会跟着你走 ——
换机器、把项目交给一台虚拟机、重装系统后恢复，往往意味着从零开始。

zsync 把这套环境打成**单个压缩 `.ztar` 归档**，推送到中央服务器，可在任意
其他机器拉取恢复 —— 并带**路径重映射**：在 `D:\work\myproject` 构建的归档能
干净地恢复到 `C:\Projects\myproject`，侧边栏会话列表索引一并迁移。

```
中央服务器(任意机器/VM)                        每台开发机
┌──────────────────────────────┐    push .ztar ┌──────────────────────┐
│  zsync-server :8642          │ ◀──────────── │ 客户端(agent :8643)  │
│  · 共用 Web GUI              │               │  读本机 ~/.zcode     │
│  · 归档仓库                  │ ────────────▶ │  构建 / 恢复          │
└──────────────────────────────┘  pull+恢复    └──────────────────────┘
        ▲ 服务器: 浏览器界面或纯命令行运维       客户端: 桌面程序
          http://<服务器>:8642                 (单文件 exe)或浏览器
```

v0.4 起仓库按 `server/` 与 `client/` 拆分，共享纯标准库核心（`zsync/`）；
Web GUI（`web/`）单源维护，运行时按角色切换服务器/客户端变体。

## 特性

- **中央服务器 + 每机客户端** —— 所有机器共用一个 Web 界面；客户端是桌面程序
  (Windows 单文件 exe)，内嵌仅监听 loopback 的 agent。
- **单压缩包存储** —— 每次备份是一个 `.ztar`(tar.gz, 内嵌 `manifest.json`),
  侧车清单支持不解包直接列表/下载。
- **完整迁移单元** —— 会话(上下文/思考过程/工具轨迹)、**侧边栏会话列表索引**、
  项目记忆、约束、技能、插件状态、项目源码(可含 `.git`)、全局组件。
- **路径重映射** —— project_id、会话 directory、记忆 slug、会话列表索引全部
  自动改写到目标路径。
- **幽灵项目** —— 已从侧边栏移除、但会话/记忆仍存在的项目照常发现、列出、
  可备份(界面带徽标)。
- **源码筛选** —— 预设忽略(node_modules/venv/build/logs…) + 自定义排除/强制
  包含，带文件树选择器，按项目持久化。
- **实时备份** —— 监视项目，变更自动重建并推送。
- **桌面端内联日志** —— 任务与客户端日志收进底部默认收起的抽屉；服务器日志
  留在服务器 Web 界面。
- **目标机没有 Python?** —— 可生成"免 Python 迁移包"，Win10+ 内置的
  curl/tar/PowerShell 即可执行。
- **零运行时依赖** —— 服务器、agent、Web GUI、CLI 全部纯 Python 标准库
  (Windows 桌面 exe 额外捆绑 WebView2 胶水层，见 `client/BUILD.md`)。

## 快速开始

### 1. 启动中央服务器(任意机器, 一次性)

```bash
python server/zsync-server.py serve --port 8642   # 不可信局域网建议加 --token <密钥>
```

服务器是纯归档仓库 + 共用 Web GUI，无需安装 ZCode、不读写本机 ZCode 目录，
只提供命令行运维:

```bash
python server/zsync-server.py start|stop|status|restart   # 后台守护(pidfile + 日志)
python server/zsync-server.py service install             # systemd 单元(Linux) / 开机任务(Windows)
```

### 2. 接入客户端机器

首选**桌面客户端**: 构建或获取 `zsync-client.exe`，双击即用 —— agent 随窗口
启动、关窗即停，机器上无需安装 Python。自行构建: `python client/build_exe.py`
(见 [client/BUILD.md](client/BUILD.md))。

轻量替代 —— 无头 agent，直接从服务器页面引导: 在客户端浏览器打开
`http://<服务器IP>:8642`，首次访问页面显示接入引导: 下载
`http://<服务器IP>:8642/tool.zip` 解压到任意目录(如 `C:\zsync`)，
双击 `start-agent.cmd`(Windows)或运行 `python client/zsync-client.py agent`
(Linux/macOS)，回到页面点「重新检测」。

- agent 只监听 `127.0.0.1:8643`，不会暴露到局域网。
- Windows 下请通过 `start-agent.cmd`(或带 `python` 前缀)启动, **不要**直接运行
  `zsync-client.py agent`: cmd 会按 `.py` 文件关联解析, 若关联的是编辑器
  (如 VS Code), 会打开文件而不是启动 agent。
- 首次访问引导确认本机 ZCode 目录(按当前用户自动探测 `~/.zcode`),
  确认后自动加载本机项目清单。
- 直接访问 `http://127.0.0.1:8643` 会看到同一界面的**客户端变体**
  (桌面程序展示的即此)。

### 3. 备份 / 恢复

- **项目备份** —— 按项目勾选组件、调源码筛选，「立即备份并推送」，归档进入
  服务器仓库。
- **服务器仓库** —— 浏览归档 → 选中 → 填本机目标路径与组件 → 「拉取恢复」，
  路径自动重映射。

## .ztar 里装了什么

```
project/sessions.sqlite      会话库行(session/entry/message/part/usage/权限…)
project/tasks-index.sqlite   侧边栏会话列表索引行   ← 会话可见的关键
project/rollout/*.jsonl      模型原始 I/O 轨迹(可能很大)
project/agents|artifacts|exec/**
project/memory/**            项目记忆
source/**                    项目源码(经筛选, 可含 .git)
global/**                    可选全局技能/约束/插件开关
```

## 目录结构

```
zsync/            共享核心(纯标准库): 打包/恢复/zcode 布局/HTTP 服务层
server/           服务端入口: serve / 后台守护 / 服务注册
client/           客户端入口: 桌面壳 / 无头 agent / 备份 CLI / exe 打包
web/              共用 Web GUI(服务器与客户端变体运行时切换)
```

## CLI

```bash
# 客户端(备份操作针对本机 ZCode 目录)
python client/zsync-client.py                    # 桌面 GUI(默认子命令)
python client/zsync-client.py agent              # 无头 agent(127.0.0.1:8643)
python client/zsync-client.py config --zcode-home <目录> --remote-url http://host:8642
python client/zsync-client.py projects           # 列本机项目(含幽灵项目)
python client/zsync-client.py build --project-id PID [--no-push] [--set source=0 ...]
python client/zsync-client.py push  --archive ID [--server URL]
python client/zsync-client.py pull  --server URL --archive ID --to PATH [--only sessions,memory,...]
python client/zsync-client.py restore --archive ID --to PATH
python client/zsync-client.py archives [--server URL]
python client/zsync-client.py watch  --project-id PID [--interval 20]
python client/zsync-client.py vmpkg  --archive ID --to C:\path   # 免 Python 迁移包
python client/zsync-client.py selftest [--project-id PID]        # 沙箱端到端自测

# 服务端
python server/zsync-server.py serve [--port 8642] [--token T]
python server/zsync-server.py start|stop|status|restart
python server/zsync-server.py service install|uninstall|start|stop|status
```

根目录旧入口 `zsync.py` 仍作为转发垫片可用(打印迁移提示)，后续版本将移除。

## REST API(节选)

```
GET  /api/state | /api/archives | /api/jobs/{id} | /api/logs          (服务器与 agent)
GET  /api/projects | /api/filetree | /api/project-detail | /api/session…   (仅 agent)
POST /api/settings        {zcode_home?, remote_url?, remote_token?}   (agent)
POST /api/build           {project_id, components?, push_url?}  -> job (agent)
POST /api/restore         {archive_id | remote{url,archive_id}, target_path, components} (agent)
POST /api/upload/{id}/manifest | /ztar            # 归档推送(agent -> 服务器)
GET  /api/archives/{id}/manifest | /download
GET  /tool.zip                                     # 工具自打包(客户端引导, 仅服务器)
```

## 注意事项

- 恢复前请**完全退出 ZCode**(工具含 WAL 占用检测)。
- 归档是完整快照；轨迹达数 GB 且不需要时可关闭 `rollout` 组件。
- 实时备份默认间隔 20s，变更自动重建，配置了服务器则自动推送。
- 服务器页面访问本机 loopback agent 时浏览器可能提示"允许访问本地网络"
  (私有网络访问)——请允许。
- **长期部署**: `zsync-server service install` 生成并启用 systemd 服务
  (`Restart=always`、开机自启)；无 systemd 的环境用 `zsync-server start`
  起后台守护(pidfile + 日志落盘)。

## 自测验证

`python client/zsync-client.py selftest` 构建真实归档 → 恢复到路径不同的沙箱
home → 校验会话/消息/分片数量、侧边栏索引、记忆、轨迹与服务器端导入回环。

## Roadmap

- [ ] 归档保留/清理策略
- [ ] 大轨迹的增量(分块)归档
- [ ] 服务器定时调度各 agent 备份
- [ ] 多服务器联邦

## 参与贡献

欢迎 Issue 与 PR。请保持核心零依赖 —— 纯标准库是本项目的特性
(桌面 exe 的打包期依赖是唯一例外)。

## 许可证

[MIT](LICENSE)
