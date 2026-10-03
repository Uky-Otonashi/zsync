/* zsync Web GUI —— 中央服务器 + 客户端 agent 模型
 *
 * 页面由中央服务器提供(本源)。加载后自动探测本机 agent(127.0.0.1:8643):
 *   - 探测到 → 「项目备份/恢复/设置/客户端任务」等本机操作全部走 agent,
 *     备份自动推送到本服务器; 项目清单含已移出侧边栏但会话/记忆仍在的"幽灵"项目。
 *   - 未探测到 → 显示首次接入引导(下载 tool.zip → 运行 start-agent)。
 *   - 兼容旧单机模式: 经 127.0.0.1 直接访问节点自身时, 以节点为 agent。 */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));


/* ---------------- i18n / 主题 ---------------- */
const I18N = {
  zh: {
    "nav.backup": "项目备份", "nav.backupSub": "本机客户端", "nav.remote": "服务器仓库",
    "nav.remoteSub": "拉取恢复", "nav.settings": "客户端设置", "nav.jobs": "任务与日志",
    "common.refresh": "刷新", "common.refreshList": "刷新列表", "common.close": "关闭",
    "build.now": "立即备份", "build.filter": "源码筛选…", "build.live": "实时备份",
    "build.liveOn": "实时备份中", "build.rebuilt": (n) => `已重建 ${n} 次`, "build.failed": "备份失败: ",
    "card.sessions": "会话", "card.trace": "轨迹", "card.memory": "记忆", "card.list": "列表",
    "card.comps": "备份内容", "card.grpProject": "项目级", "card.grpGlobal": "全局级 · 可选, 随包分发",
    "card.ghost": "已移出侧边栏", "card.empty": "no-match-placeholder<br>检查「客户端设置」中的 zcode 目录是否正确",
    "d.overview": "概览", "d.git": "Git 仓库", "d.files": "项目文件", "d.filesSub": "点击目录展开 · 只读",
    "d.sessions": (n) => `zcode 会话 ${n} 个 · 点击浏览内容`,
    "d.path": "项目路径", "d.notGit": "该目录不是 git 仓库", "d.noUpstream": "无上游分支",
    "d.changes": (n) => `${n} 处改动`, "d.fetch": "联网刷新差异", "d.fetching": "fetch 中…",
    "d.noCommits": "无提交", "d.collapsed": "已收起", "d.loading": "加载中…", "d.empty": "空目录",
    "d.searchPh": "搜索会话标题…", "d.sortUpdated": "按最近更新", "d.sortCreated": "按建立时间",
    "d.sortDesc": "↓ 新→旧", "d.sortAsc": "↑ 旧→新",
    "d.noMatch": (q) => `没有匹配「${q}」的会话`, "d.probing": "探测中… git 状态与目录统计可能需要数秒(大仓库较慢)",
    "d.readFail": (e) => `读取失败: ${e}`, "d.noSessions": "该项目名下没有 zcode 会话",
    "d.subagent": "子代理", "d.subagentTip": "子代理会话(由主会话派生)",
    "d.msgs": "消息", "d.back": "← 返回项目", "d.rootName": "项目根目录", "d.root": "根",
    "sv.chat": "对话", "sv.trace": "模型轨迹", "sv.system": "系统提示词",
    "role.user": "用户", "role.assistant": "助手", "role.agent": "主代理指令",
    "kind.todo_reminder": "任务清单提醒", "kind.background_notification": "后台任务通知",
    "kind.system_reminder": "系统提醒", "kind.compact_summary": "压缩摘要", "kind.subagent_notification": "子代理通知",
    "ac.launch": "派发子代理", "ac.ret": "子代理已返回", "ac.prompt": "下达的指令", "ac.output": "返回结果",
    "ac.split": "↗ 分屏查看", "ac.done": "已完成", "ac.error": "出错", "ac.unfilled": "运行中·未回填",
    "ac.noOutput": "(无输出)",
    "fold.reasoning": "◈ 思考过程", "fold.in": "输入", "fold.out": "输出", "fold.attach": "🖼 附件",
    "fold.noText": "(无文本内容)", "fold.step": (n) => `⟡ 步骤标记${n > 1 ? ` ×${n}` : ""}`,
    // zcode 风格 工具/思考行
    "tc.thought": "思考", "tc.thoughtDur": (s) => `持续了 ${s} 秒`, "tc.turn": (d) => `用时 ${d}`,
    "tc.read": "读取", "tc.write": "写入", "tc.edit": "编辑", "tc.bash": "终端", "tc.grep": "搜索",
    "tc.glob": "匹配", "tc.todo": "待办", "tc.web": "网页", "tc.skill": "技能", "tc.tool": "工具",
    "tc.msg": "消息", "tc.st.failed": "执行失败", "tc.st.unfilled": "未回填",
    "tc.params": "参数", "tc.result": "结果", "tc.output": "输出", "tc.noOutput": "没有输出。",
    "tc.truncOut": "…(内容过长已截断)",
    "d.colName": "名称", "d.colCnt": "项数", "d.colSize": "大小",
    "msg.total": (n, all) => `共 ${n} 条消息${all ? "(已全部加载)" : ""}`,
    "msg.earlier": (n) => `↑ 加载更早的消息(还有 ${n} 条未显示)`,
    "msg.children": (n) => `子会话 ${n} 个(点击分屏对照):`,
    "ld.msgs": "读取消息…", "ld.session": "读取会话内容…", "ld.trace": "读取模型调用轨迹…(大文件可能需要数秒)",
    "ld.system": "读取系统提示词…", "ld.sub": "读取子代理会话…", "ld.dir": "读取目录失败: ",
    "sp.exit": "✕ 退出分屏",
    "sys.head": (c, b) => `系统提示词 ${c} 字符 · ${b} 段`,
    "sys.first": (t) => `首次注入 ${t}`, "sys.last": (t) => `末次调用 ${t}`,
    "sys.changed": (a, b) => `会话期间系统提示词发生变化(首 ${a} → 末 ${b} 字符)`,
    "sys.switchLast": "切换到末次版本", "sys.switchFirst": "切换到首次版本",
    "sys.note": " · 含 zcode 基础指令/技能列表/AGENTS.md/记忆等注入内容",
    "sys.noTrace": "该会话没有模型调用轨迹(rollout), 无法提取系统提示词",
    "sys.blk": (i, c) => `第 ${i} 段 · ${c} 字符 · `,
    "tr.total": (n) => `共 ${n} 次模型调用`, "tr.clickDetail": " · 点击查看单次详情",
    "tr.noTrace": "该会话没有模型调用轨迹文件(rollout)",
    "tr.sysChars": (c) => `系统提示词 ${c}`,
    "tr.reqTail": (t, n) => ` · 请求共 ${t} 条消息(展示尾部 ${n} 条)`,
    "tr.tailTitle": "请求尾部消息", "tr.respText": "响应文本", "tr.respReasoning": "◈ 响应思考", "tr.toolCalls": "工具调用",
    "tr.parseFail": "解析失败", "tr.toolCnt": (n) => `[${n} 个工具调用] `,
    "ui.theme": "主题", "ui.themeDark": "深色", "ui.themeLight": "浅色", "ui.lang": "界面语言",
    // ---- 静态页 key(index.html) ----
    "brand.sub": "zcode 环境同步",
    "backup.title": "项目备份", "backup.sub": "本机 zcode 项目的会话、记忆与源码打包备份, 备份完成后自动推送至中央服务器",
    "backup.filterPh": "筛选本机项目 — 名称或路径…", "backup.refreshTip": "重新加载本机项目清单",
    "guide.title": "首次接入 —— 在本机启动客户端 agent",
    "guide.intro": "本页面由中央服务器提供, 读取本机 zcode 项目需要在本机运行一个轻量 agent(纯 Python 标准库, 无需安装任何依赖):",
    "guide.s1": "下载工具包", "guide.s2": "解压到任意目录(如 C:\\zsync)",
    "guide.s3": "双击 start-agent.cmd(Windows), 或运行 python client/zsync-client.py agent(Linux/macOS)",
    "guide.s4": "回到本页点击「重新检测」—— 首次将引导确认本机 zcode 目录(默认 ~/.zcode 自动探测), 之后自动加载本机项目清单",
    "guide.tip": "Windows 下请始终通过 start-agent.cmd 或带 python 前缀运行, 不要直接敲 zsync-client.py agent —— 若 .py 关联的是编辑器(如 VS Code), 会弹出编辑器而不是运行 agent。agent 只监听 127.0.0.1:8643, 不对局域网开放; 浏览器若弹出「允许访问本地网络」请选择允许。也可改用桌面客户端(zsync-client.exe): 启动即自动拉起 agent, 关闭即停止。",
    "guide.redetect": "重新检测本机 agent", "tip.label": "提示",
    "remote.title": "服务器仓库", "remote.sub": "浏览中央服务器或本机存档库中的备份, 拉取恢复到任意机器",
    "remote.source": "仓库来源", "remote.srcServer": "服务器仓库", "remote.srcAgent": "本机存档库 (agent)",
    "remote.filterPh": "筛选存档 — 名称或路径…",
    "remote.noMatch": (q) => `没有匹配「${q}」的存档`,
    "restore.title": "拉取恢复 ·", "restore.target": "恢复到本机路径",
    "restore.remapHint": "路径与原机器不同时自动重映射 project_id / 目录 / 记忆 slug / 会话列表索引",
    "restore.warn": "恢复会写入本机 zcode 数据库(", "restore.warn2": "), 执行前请完全退出 zcode",
    "restore.go": "开始拉取恢复", "restore.vmpkg": "生成免 Python 迁移包",
    "settings.title": "客户端设置", "settings.sub": "配置本机 zcode 目录与备份推送目标(经 agent 生效)",
    "settings.agent": "客户端本机 (经 agent)", "settings.firstVisit": "首次接入: 请确认下方本机 zcode 目录后点「保存设置」, 保存后将自动加载本机项目清单。",
    "settings.zhome": "本机 zcode 目录", "settings.detect": "自动探测 (~/.zcode)",
    "settings.zhomeHint": "备份/恢复读写该目录下的 cli/db、rollout、memories、v2/tasks-index 等。家目录按当前用户自动探测, zcode 目录迁移过则手动指定。",
    "settings.status": "状态", "settings.push": "备份推送目标", "settings.server": "服务器地址",
    "settings.token": "访问令牌", "settings.tokenPh": "token(服务器启用时填写)",
    "settings.save": "保存设置", "settings.test": "测试连接", "settings.localArchives": "本机存档库 (agent)",
    "ui.appearance": "界面外观", "ui.hint": "主题即时生效; 语言切换后页面将刷新。选择保存在本浏览器中。",
    "jobs.title": "任务与日志", "jobs.sub": "客户端与中央服务器的任务执行状态和运行日志(每 3 秒自动刷新)",
    "jobs.agent": "客户端任务", "jobs.agentSub": "本机 agent", "jobs.agentLogs": "客户端日志",
    "jobs.server": "服务器任务", "jobs.serverSub": "中央服务器", "jobs.serverLogs": "服务器日志",
    "ld.none": "暂无任务", "ld.jobs": "客户端任务", "ld.logs": "客户端日志",
    "ld.serverUnset": "服务器未配置",
    "filter.addPh": "添加排除规则, 如 site/mirror 或 *.log", "filter.exclude": "排除",
    "sv.created": (t) => `创建 ${t}`, "sv.updated": (t) => `最后更新 ${t}`,
    "st.server": "服务器", "st.client": "客户端", "st.noClient": "客户端未接入",
    "st.archives": (n) => `存档 ${n} · zcode 环境同步`,
    "rcomp.absent": "存档未包含",
    "comp.sessions.l": "会话数据", "comp.sessions.d": "完整上下文/思考/轨迹 + 会话列表索引",
    "comp.rollout.l": "模型原始轨迹", "comp.rollout.d": "model-io jsonl, 可能很大",
    "comp.artifacts.l": "工具产物", "comp.artifacts.d": "截图/生成文件",
    "comp.agents.l": "子代理数据", "comp.agents.d": "agent 会话目录",
    "comp.exec_logs.l": "执行日志", "comp.exec_logs.d": "工具调用日志",
    "comp.memory.l": "项目记忆", "comp.memory.d": "MEMORY.md 等",
    "comp.source.l": "项目源码 + git", "comp.source.d": "按文件筛选规则",
    "comp.include_git.l": "包含 .git", "comp.include_git.d": "git 历史",
    "comp.global_skills.l": "全局技能", "comp.global_skills.d": "skills/",
    "comp.global_constraints.l": "全局约束", "comp.global_constraints.d": "AGENTS.md 等",
    "comp.global_plugins.l": "插件开关", "comp.global_plugins.d": "cli/config.json",
    "comp.global_agents_md.l": "全局代理定义", "comp.global_agents_md.d": "agents/*.md",
  },
  en: {
    "nav.backup": "Backup", "nav.backupSub": "Local client", "nav.remote": "Server Repo",
    "nav.remoteSub": "Pull & restore", "nav.settings": "Client Settings", "nav.jobs": "Jobs & Logs",
    "common.refresh": "Refresh", "common.refreshList": "Refresh list", "common.close": "Close",
    "build.now": "Back Up Now", "build.filter": "Source Filter…", "build.live": "Live backup",
    "build.liveOn": "Live", "build.rebuilt": (n) => `rebuilt ${n}×`, "build.failed": "Backup failed: ",
    "card.sessions": "Sessions", "card.trace": "Trace", "card.memory": "Memory", "card.list": "listed",
    "card.comps": "Backup contents", "card.grpProject": "Project-level", "card.grpGlobal": "Global · optional, shipped with bundle",
    "card.ghost": "Removed from sidebar", "card.empty": "No matching zcode projects on this machine<br>Check the zcode directory in Client Settings",
    "d.overview": "Overview", "d.git": "Git Repository", "d.files": "Project Files", "d.filesSub": "Click a folder to expand · read-only",
    "d.sessions": (n) => `zcode sessions: ${n} · click to browse`,
    "d.path": "Path", "d.notGit": "Not a git repository", "d.noUpstream": "No upstream branch",
    "d.changes": (n) => `${n} change(s)`, "d.fetch": "Fetch remote", "d.fetching": "fetching…",
    "d.noCommits": "No commits", "d.collapsed": "collapsed", "d.loading": "Loading…", "d.empty": "Empty folder",
    "d.searchPh": "Search session titles…", "d.sortUpdated": "By last update", "d.sortCreated": "By created time",
    "d.sortDesc": "↓ new→old", "d.sortAsc": "↑ old→new",
    "d.noMatch": (q) => `No sessions matching "${q}"`, "d.probing": "Probing… git status & directory stats may take seconds (large repos)",
    "d.readFail": (e) => `Failed to read: ${e}`, "d.noSessions": "No zcode sessions under this project",
    "d.subagent": "subagent", "d.subagentTip": "Subagent session (spawned by main session)",
    "d.msgs": "msgs", "d.back": "← Back to project", "d.rootName": "Project root", "d.root": "root",
    "sv.chat": "Chat", "sv.trace": "Model Trace", "sv.system": "System Prompt",
    "role.user": "User", "role.assistant": "Assistant", "role.agent": "Main-agent instruction",
    "kind.todo_reminder": "todo reminder", "kind.background_notification": "background notification",
    "kind.system_reminder": "system reminder", "kind.compact_summary": "compaction summary", "kind.subagent_notification": "subagent notification",
    "ac.launch": "Subagent dispatched", "ac.ret": "Subagent returned", "ac.prompt": "Instruction given", "ac.output": "Returned result",
    "ac.split": "↗ Split view", "ac.done": "done", "ac.error": "error", "ac.unfilled": "running·unfilled",
    "ac.noOutput": "(no output)",
    "fold.reasoning": "◈ Reasoning", "fold.in": "Input", "fold.out": "Output", "fold.attach": "🖼 Attachment",
    "fold.noText": "(no text content)", "fold.step": (n) => `⟡ step mark${n > 1 ? ` ×${n}` : ""}`,
    // zcode-style tool / reasoning rows
    "tc.thought": "Thought", "tc.thoughtDur": (s) => `took ${s}s`, "tc.turn": (d) => `${d}`,
    "tc.read": "Read", "tc.write": "Write", "tc.edit": "Edit", "tc.bash": "Terminal", "tc.grep": "Search",
    "tc.glob": "Match", "tc.todo": "Todo", "tc.web": "Web", "tc.skill": "Skill", "tc.tool": "Tool",
    "tc.msg": "Message", "tc.st.failed": "Failed", "tc.st.unfilled": "unfilled",
    "tc.params": "Parameters", "tc.result": "Result", "tc.output": "Output", "tc.noOutput": "No output.",
    "tc.truncOut": "…(truncated)",
    "d.colName": "Name", "d.colCnt": "Items", "d.colSize": "Size",
    "msg.total": (n, all) => `${n} messages${all ? " (all loaded)" : ""}`,
    "msg.earlier": (n) => `↑ Load earlier messages (${n} more)`,
    "msg.children": (n) => `Sub-sessions: ${n} (click for split view):`,
    "ld.msgs": "Loading messages…", "ld.session": "Loading session…", "ld.trace": "Loading model trace… (large files may take seconds)",
    "ld.system": "Loading system prompt…", "ld.sub": "Loading subagent session…", "ld.dir": "Failed to read directory: ",
    "sp.exit": "✕ Exit split",
    "sys.head": (c, b) => `System prompt: ${c} chars · ${b} block(s)`,
    "sys.first": (t) => `first injected ${t}`, "sys.last": (t) => `last call ${t}`,
    "sys.changed": (a, b) => `System prompt changed during session (${a} → ${b} chars)`,
    "sys.switchLast": "Switch to last version", "sys.switchFirst": "Switch to first version",
    "sys.note": " · includes zcode base instructions / skills / AGENTS.md / memory injections",
    "sys.noTrace": "No model trace (rollout) for this session; system prompt unavailable",
    "sys.blk": (i, c) => `Block ${i} · ${c} chars · `,
    "tr.total": (n) => `${n} model call(s)`, "tr.clickDetail": " · click a row for details",
    "tr.noTrace": "No model trace file (rollout) for this session",
    "tr.sysChars": (c) => `System prompt ${c}`,
    "tr.reqTail": (t, n) => ` · ${t} request messages (showing last ${n})`,
    "tr.tailTitle": "Request tail messages", "tr.respText": "Response text", "tr.respReasoning": "◈ Response reasoning", "tr.toolCalls": "Tool calls",
    "tr.parseFail": "parse error", "tr.toolCnt": (n) => `[${n} tool call(s)] `,
    "ui.theme": "Theme", "ui.themeDark": "Dark", "ui.themeLight": "Light", "ui.lang": "Language",
    // ---- static page keys (index.html) ----
    "brand.sub": "zcode env sync",
    "backup.title": "Backup", "backup.sub": "Back up local zcode projects (sessions, memory, source) and auto-push to the central server",
    "backup.filterPh": "Filter local projects — name or path…", "backup.refreshTip": "Reload local project list",
    "guide.title": "First-time setup — start the local agent",
    "guide.intro": "This page is served by the central server. Reading local zcode projects requires a lightweight agent on this machine (pure Python stdlib, no dependencies):",
    "guide.s1": "Download the tool package", "guide.s2": "Extract to any directory (e.g. C:\\zsync)",
    "guide.s3": "Double-click start-agent.cmd (Windows), or run python client/zsync-client.py agent (Linux/macOS)",
    "guide.s4": "Back on this page click “Redetect” — first run guides you to confirm the local zcode directory, then loads the project list",
    "guide.tip": "On Windows always launch via start-agent.cmd or with a python prefix; a bare zsync-client.py may open an editor if .py is associated with one. The agent only listens on 127.0.0.1:8643. Allow “local network access” if the browser asks. Or use the desktop client (zsync-client.exe): it starts the agent on launch and stops it on exit.",
    "guide.redetect": "Redetect local agent", "tip.label": "Tip",
    "remote.title": "Server Repository", "remote.sub": "Browse backups on the central server or local archive store, pull & restore to any machine",
    "remote.source": "Source", "remote.srcServer": "Server repository", "remote.srcAgent": "Local store (agent)",
    "remote.filterPh": "Filter archives — name or path…",
    "remote.noMatch": (q) => `No archives matching "${q}"`,
    "restore.title": "Pull & restore ·", "restore.target": "Restore to local path",
    "restore.remapHint": "Paths differing from the origin machine are auto-remapped (project_id / directories / memory slug / tasks index)",
    "restore.warn": "Restoring writes into the local zcode database (", "restore.warn2": "). Fully exit zcode before running.",
    "restore.go": "Start pull & restore", "restore.vmpkg": "Build Python-free migration package",
    "settings.title": "Client Settings", "settings.sub": "Configure the local zcode directory and backup push target (applied via agent)",
    "settings.agent": "Local client (via agent)", "settings.firstVisit": "First time: confirm the zcode directory below and click “Save”, the project list will load afterwards.",
    "settings.zhome": "Local zcode directory", "settings.detect": "Auto-detect (~/.zcode)",
    "settings.zhomeHint": "Backup/restore reads & writes cli/db, rollout, memories, v2/tasks-index under this directory. Auto-detected per user; set manually if relocated.",
    "settings.status": "Status", "settings.push": "Backup push target", "settings.server": "Server address",
    "settings.token": "Access token", "settings.tokenPh": "token (if enabled on server)",
    "settings.save": "Save settings", "settings.test": "Test connection", "settings.localArchives": "Local store (agent)",
    "ui.appearance": "Appearance", "ui.hint": "Theme applies instantly; switching language reloads the page. Choices are saved in this browser.",
    "jobs.title": "Jobs & Logs", "jobs.sub": "Task status and runtime logs of client & central server (auto-refresh every 3s)",
    "jobs.agent": "Client jobs", "jobs.agentSub": "local agent", "jobs.agentLogs": "Client logs",
    "jobs.server": "Server jobs", "jobs.serverSub": "central server", "jobs.serverLogs": "Server logs",
    "ld.none": "No jobs yet", "ld.jobs": "Client jobs", "ld.logs": "Client logs",
    "ld.serverUnset": "Server not set",
    "filter.addPh": "Add exclude rule, e.g. site/mirror or *.log", "filter.exclude": "Exclude",
    "sv.created": (t) => `created ${t}`, "sv.updated": (t) => `updated ${t}`,
    "st.server": "Server", "st.client": "Client", "st.noClient": "Client not connected",
    "st.archives": (n) => `${n} archive(s) · zcode env sync`,
    "rcomp.absent": "not in archive",
    "comp.sessions.l": "Sessions", "comp.sessions.d": "full context/reasoning/trace + tasks index",
    "comp.rollout.l": "Raw model trace", "comp.rollout.d": "model-io jsonl, can be large",
    "comp.artifacts.l": "Tool artifacts", "comp.artifacts.d": "screenshots / generated files",
    "comp.agents.l": "Subagent data", "comp.agents.d": "agent session dirs",
    "comp.exec_logs.l": "Exec logs", "comp.exec_logs.d": "tool invocation logs",
    "comp.memory.l": "Project memory", "comp.memory.d": "MEMORY.md etc.",
    "comp.source.l": "Source + git", "comp.source.d": "per file-filter rules",
    "comp.include_git.l": "Include .git", "comp.include_git.d": "git history",
    "comp.global_skills.l": "Global skills", "comp.global_skills.d": "skills/",
    "comp.global_constraints.l": "Global constraints", "comp.global_constraints.d": "AGENTS.md etc.",
    "comp.global_plugins.l": "Plugin switches", "comp.global_plugins.d": "cli/config.json",
    "comp.global_agents_md.l": "Global agent defs", "comp.global_agents_md.d": "agents/*.md",
  },
};
let LANG = localStorage.getItem("zsync_lang") || "zh";
function t(key, ...args) {
  const v = (I18N[LANG] && I18N[LANG][key]) ?? I18N.zh[key] ?? key;
  return typeof v === "function" ? v(...args) : v;
}
function applyI18n() {
  document.documentElement.lang = LANG === "en" ? "en" : "zh-CN";
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const v = t(el.dataset.i18n);
    if (typeof v === "string") el.textContent = v;
  });
  document.querySelectorAll("[data-i18n-ph]").forEach(el => el.placeholder = t(el.dataset.i18nPh));
  document.querySelectorAll("[data-i18n-title]").forEach(el => el.title = t(el.dataset.i18nTitle));
}
function applyTheme() {
  document.documentElement.dataset.theme = localStorage.getItem("zsync_theme") || "dark";
}
applyTheme();
document.querySelectorAll('input[name="theme"]').forEach(r => r.addEventListener("change", () => {
  localStorage.setItem("zsync_theme", r.value);
  applyTheme();
}));
document.querySelectorAll('input[name="lang"]').forEach(r => r.addEventListener("change", () => {
  if (r.value === LANG) return;
  localStorage.setItem("zsync_lang", r.value);
  location.reload();
}));
document.querySelectorAll(`input[name="theme"][value="${localStorage.getItem("zsync_theme") || "dark"}"]`)
  .forEach(r => r.checked = true);
document.querySelectorAll(`input[name="lang"][value="${LANG}"]`).forEach(r => r.checked = true);
applyI18n();

const SERVER = window.location.origin;   // 中央服务器(即提供本页面的服务器)
const AGENT_PORTS = [8643];              // 本机客户端 agent 探测端口

let STATE = null;      // 服务器 /api/state
let AGENT = null;      // {base, state} —— base 为 "" 表示即本源(旧单机模式)
let IS_CLIENT = false; // 客户端变体: 页面由 agent 自身伺服(桌面端/本机直开)
let PROJECTS = [];
let REPO_ARCHIVES = [];     // 当前仓库来源(服务器或本机存档库)的存档
let SELECTED = null;        // 选中的存档 {archive_id, info, src}
let projComps = {};         // project_id -> components(编辑态)
let ftState = { projectId: null, filter: null, open: {} };
let REMOTE_TOKEN = localStorage.getItem("zsync_remote_token") || "";

/* ---------------- 图标与 UI 小件 ---------------- */
const ICO_DIR = '<svg class="ft-ico" viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M1.8 4.3c0-.6.5-1.1 1.1-1.1h2.9l1.5 1.8h5.8c.6 0 1.1.5 1.1 1.1v6.5c0 .6-.5 1.1-1.1 1.1H2.9c-.6 0-1.1-.5-1.1-1.1V4.3z"/></svg>';
const ICO_FILE = '<svg class="ft-ico file" viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M4 1.8h5.2L13 5.5v8.7H4V1.8z"/><path d="M9.2 1.8v3.7H13"/></svg>';
const ICO_EMPTY = '<svg viewBox="0 0 48 48" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="6" width="26" height="36" rx="2.5"/><path d="M14 15h13M14 21h13M14 27h9" opacity=".55"/><path d="M33 33l8.5-8.5 3.5 3.5-8.5 8.5H33V33z"/></svg>';

/* zcode 同款 lucide 图标(会话流 工具/思考 行) */
const lucide = (w, paths) =>
  `<svg viewBox="0 0 24 24" width="${w}" height="${w}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
const ICO_L_SEARCH = lucide(14, '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>');
const ICO_L_TERM = lucide(14, '<path d="m7 11 2-2-2-2"/><path d="M11 13h4"/><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>');
const ICO_L_PEN = lucide(14, '<path d="M13 21h8"/><path d="m15 5 4 4"/><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>');
const ICO_L_FILEPEN = lucide(14, '<path d="M14.364 13.634a2 2 0 0 0-.506.854l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837a2 2 0 0 0 .854-.506l4.013-4.009a1 1 0 0 0-3.004-3.004z"/><path d="M14.487 7.858A1 1 0 0 1 14 7V2"/><path d="M20 19.645V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l2.516 2.516"/><path d="M8 18h1"/>');
const ICO_L_BRAIN = lucide(14, '<path d="M12 18V5"/><path d="M15 13a4.17 4.17 0 0 1-3-4 4.17 4.17 0 0 1-3 4"/><path d="M17.598 6.5A3 3 0 1 0 12 5a3 3 0 1 0-5.598 1.5"/><path d="M17.997 5.125a4 4 0 0 1 2.526 5.77"/><path d="M18 18a4 4 0 0 0 2-7.464"/><path d="M19.967 17.483A4 4 0 1 1 12 18a4 4 0 1 1-7.967-.517"/><path d="M6 18a4 4 0 0 1-2-7.464"/><path d="M6.003 5.125a4 4 0 0 0-2.526 5.77"/>');
const ICO_L_TODO = lucide(14, '<path d="M13 5h8"/><path d="M13 12h8"/><path d="M13 19h8"/><path d="m3 17 2 2 4-4"/><rect x="3" y="4" width="6" height="6" rx="1"/>');
const ICO_L_GLOBE = lucide(14, '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>');
const ICO_L_WRENCH = lucide(14, '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.984z"/>');
const ICO_L_TXTSEARCH = lucide(14, '<path d="M21 5H3"/><path d="M10 12H3"/><path d="M10 19H3"/><circle cx="17" cy="15" r="3"/><path d="m21 19-1.9-1.9"/>');
const ICO_L_ZAP = lucide(14, '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>');
const ICO_L_MSG = lucide(14, '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>');
const ICO_L_BOT = lucide(15, '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>');
const ICO_L_CHECK = lucide(15, '<path d="M21.801 10A10 10 0 1 1 17 3.335"/><path d="m9 11 3 3L22 4"/>');
const ICO_L_CHEV = lucide(14, '<path d="m9 18 6-6-6-6"/>');

function emptyBox(text) {
  return `<div class="empty">${ICO_EMPTY}<p>${text}</p></div>`;
}

function notify(msg, type = "") {
  const t = document.createElement("div");
  t.className = "toast " + type;
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 300); }, 4200);
}

const COMP_DEFS = [
  { key: "sessions" }, { key: "rollout" }, { key: "artifacts" }, { key: "agents" },
  { key: "exec_logs" }, { key: "memory" }, { key: "source" }, { key: "include_git" },
  { key: "global_skills" }, { key: "global_constraints" }, { key: "global_plugins" },
  { key: "global_agents_md" },
];
const GLOBAL_KEYS = ["global_skills", "global_constraints", "global_plugins", "global_agents_md"];

function fmtBytes(n) {
  if (n == null) return "-";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0; while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(i ? 1 : 0) + u[i];
}
function fmtTime(ms) {
  if (!ms) return "-";
  const d = new Date(ms);
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
/* 毫秒 → 紧凑时长(工具行/本轮用时): 3.2s / 42s / 1m03s / 2h05m */
function fmtDur(ms) {
  if (ms == null || ms < 0) return "";
  const s = ms / 1000;
  if (s < 10) return s.toFixed(1) + "s";
  if (s < 60) return Math.round(s) + "s";
  const m = Math.floor(s / 60), rs = Math.round(s % 60);
  if (m < 60) return `${m}m${String(rs).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m`;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function fetchJSON(url, opts = {}, timeoutMs = 30000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...opts, signal: ctl.signal });
    return await r.json().catch(() => ({ ok: false, error: `HTTP ${r.status}` }));
  } finally { clearTimeout(t); }
}

/* 同源(中央服务器) API */
function api(path, opts = {}) {
  return fetchJSON(SERVER + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
}
/* 本机 agent API —— 无 agent 时抛错(调用方应确保仅在 AGENT 存在时使用) */
function apiAgent(path, opts = {}, timeoutMs = 30000) {
  if (!AGENT) return Promise.resolve({ ok: false, error: "本机未运行客户端 agent" });
  return fetchJSON(AGENT.base + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  }, timeoutMs);
}

/* ---------------- agent 探测与初始化 ---------------- */
async function detectAgent() {
  const self = window.location.origin;
  const loopback = ["127.0.0.1", "localhost", "[::1]", "::1"].includes(window.location.hostname);
  for (const port of AGENT_PORTS) {
    const base = `http://127.0.0.1:${port}`;
    if (base === self) continue;
    try {
      const j = await fetchJSON(base + "/api/state", {}, 4000);
      if (j && j.ok && j.mode === "agent") {
        return { base, state: j, kind: j.mode };
      }
    } catch (e) { /* 端口无响应, 继续探测 */ }
  }
  // 页面由 agent 自身伺服(桌面客户端/本机直开) → 本源即客户端;
  // 旧单机节点(mode=node)经 loopback 访问时亦以自身为客户端
  if (loopback && STATE && (STATE.mode === "agent" || STATE.mode === "node")) {
    return { base: "", state: STATE, kind: "self" };
  }
  return null;
}

async function init() {
  try {
    STATE = await api("/api/state");
  } catch (e) {
    $("#state-line").textContent = "无法连接服务器: " + e.message;
    return;
  }
  IS_CLIENT = STATE.mode === "agent";
  if (IS_CLIENT) {
    document.body.classList.add("client-mode");
    $("#log-drawer").hidden = false;
  }
  AGENT = await detectAgent();
  renderStateLine();

  const guide = $("#agent-guide");
  if (!AGENT) {
    guide.style.display = "";
    $("#guide-tool-url").textContent = SERVER + "/tool.zip";
    $("#projects-box").innerHTML = "";
    $("#local-banner").innerHTML =
      `<span style="color:var(--red)">本机尚未接入:</span> 下方步骤启动本机客户端 agent 后, 此页将自动加载本机 zcode 项目。`;
    await loadRepo();
    await loadJobs();
    setInterval(loadJobs, 3000);
    return;
  }
  guide.style.display = "none";

  // agent 默认把备份推送到提供本页面的服务器(用户可在设置页改)
  if (AGENT.kind !== "self" && AGENT.state.remote?.url !== SERVER) {
    const r = await apiAgent("/api/settings", { method: "POST", body: { remote_url: SERVER } });
    if (r.ok) AGENT.state = await apiAgent("/api/state");
  }

  const local = AGENT.state.local || {};
  $("#set-zhome").value = local.zcode_home || "";
  $("#set-zhome-default").value = local.default_zcode_home || "";
  $("#set-remote-url").value = AGENT.state.remote?.url || SERVER;
  $("#set-remote-token").value = REMOTE_TOKEN;
  $("#zhome-status").textContent = local.db_exists
    ? "✓ 检测到会话数据库"
    : `✗ 未找到会话数据库 (已自动填入本机默认路径, 确认无误后点「保存设置」)`;
  $("#zhome-status").className = "hint " + (local.db_exists ? "st-done" : "st-error");

  // 首次接入: 数据库缺失/目录无效 → 直接进入设置页让用户确认 zcode 路径
  if (!local.db_exists) {
    switchTab("settings");
    $("#first-visit-hint").style.display = "";
  } else {
    $("#first-visit-hint").style.display = "none";
    await Promise.all([loadProjects(), loadRepo(), loadJobs(), loadLocalArchives()]);
    setInterval(loadJobs, 3000);
  }
}

function renderStateLine() {
  const el = $("#state-line");
  const arcs = STATE?.archives_count ?? "?";
  let serverChip;
  if (IS_CLIENT) {
    // 客户端变体: 页面由本机 agent 伺服, "服务器"指配置的推送/拉取目标
    const ru = AGENT?.state?.remote?.url || $("#set-remote-url")?.value.trim() || "";
    let host = "";
    try { host = ru ? new URL(ru).host : ""; } catch (e) { host = ru; }
    serverChip = host
      ? `<div class="st-chip"><span class="dot ok"></span><span>${t("st.server")} ${esc(host)}</span></div>`
      : `<div class="st-chip bad"><span class="dot err"></span><span>${t("ld.serverUnset")}</span></div>`;
  } else {
    serverChip = `<div class="st-chip"><span class="dot ok"></span><span>${t("st.server")} ${esc(STATE?.server?.hostname || "?")}</span></div>`;
  }
  el.innerHTML = serverChip +
    (AGENT
      ? `<div class="st-chip"><span class="dot ok"></span><span>${t("st.client")} ${esc(AGENT.state.local?.hostname || "?")}</span></div>`
      : `<div class="st-chip bad"><span class="dot err"></span><span>${t("st.noClient")}</span></div>`) +
    `<div class="st-sub">${t("st.archives", arcs)}</div>`;
}

function switchTab(name) {
  $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".panel").forEach(p => p.classList.toggle("active", p.id === "tab-" + name));
  if (name === "backup") loadProjects();
  if (name === "remote") loadRepo();
  if (name === "settings") loadLocalArchives();
}
$$(".tab").forEach(btn => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));

/* ---------------- 备份页吸顶: 吸附态哨兵 ----------------
   哨兵滚出滚动容器 = 头部已吸附, 加 .is-stuck 显示底部渐隐 veil; 回到顶部即移除 */
(() => {
  const sticky = document.querySelector(".page-sticky");
  const root = document.querySelector(".content");
  if (!sticky || !root || !("IntersectionObserver" in window)) return;
  const sentinel = document.createElement("div");
  sentinel.style.cssText = "height:1px;margin-bottom:-1px";
  sticky.before(sentinel);
  new IntersectionObserver((es) => {
    for (const e of es) sticky.classList.toggle("is-stuck", !e.isIntersecting);
  }, { root }).observe(sentinel);
})();

/* ---------------- 首次接入引导 ---------------- */
$("#btn-redetect").addEventListener("click", () => { $("#state-line").textContent = "重新探测中…"; init(); });

/* ---------------- 项目备份(本机, 经 agent) ---------------- */
async function loadProjects() {
  if (!AGENT) return;
  const r = await apiAgent("/api/projects");
  PROJECTS = r.projects || [];
  renderProjects();
}
$("#btn-refresh-projects").addEventListener("click", loadProjects);
$("#proj-filter").addEventListener("input", renderProjects);

function renderProjects() {
  const q = $("#proj-filter").value.trim().toLowerCase();
  const box = $("#projects-box");
  box.innerHTML = "";
  const list = PROJECTS.filter(p => !q || (p.path || "").toLowerCase().includes(q) || p.name.toLowerCase().includes(q));
  for (const p of list) {
    const cfg = p.config || {};
    if (!projComps[p.project_id]) projComps[p.project_id] = cfg.components || {};
    const w = ((AGENT.state.watchers) || []).find(x => x.project_id === p.project_id);
    const comps = projComps[p.project_id];
    const ghost = p.sessions > 0 && (p.in_sidebar || 0) === 0;
    const partial = (p.in_sidebar || 0) > 0 && p.in_sidebar < p.sessions;
    const card = document.createElement("div");
    card.className = "card pcard";
    card.innerHTML = `
      <div class="pcard-head">
        <div class="pcard-title">
          <div class="pcard-name" title="${esc(p.project_id)}">${esc(p.name)}</div>
          <div class="pcard-path" title="${esc(p.path)}">${esc(p.path || p.project_id)}</div>
        </div>
        ${(w || ghost) ? `<div class="pcard-badges">
          ${w ? '' + '<span class="badge live">' + t("build.liveOn") + '</span>' : ""}
          ${ghost ? '<span class="badge ghost" title="' + t("card.ghost") + '">' + t("card.ghost") + '</span>' : ""}
        </div>` : ""}
      </div>
      <div class="pcard-meta">
        <span class="mstat">${t("card.sessions")} <b>${p.sessions}</b>${partial ? ` <small>${t("card.list")} ${p.in_sidebar}</small>` : ""}</span>
        <span class="mstat">${t("card.trace")} <b>${fmtBytes(p.rollout_bytes)}</b></span>
        <span class="mstat">${t("card.memory")} <b>${p.memory_files}</b></span>
        <span class="mstat">CLI <b>${esc((p.versions || []).slice(-1)[0] || "?")}</b></span>
      </div>
      <details class="pcard-comps"><summary>${t("card.comps")}</summary>
        <div class="comp-grid" data-pid="${esc(p.project_id)}">
          <div class="grp">${t("card.grpProject")}</div>
          ${COMP_DEFS.filter(c => !GLOBAL_KEYS.includes(c.key)).map(c => compCb(p.project_id, c, comps)).join("")}
          <div class="grp">${t("card.grpGlobal")}</div>
          ${COMP_DEFS.filter(c => GLOBAL_KEYS.includes(c.key)).map(c => compCb(p.project_id, c, comps)).join("")}
        </div>
      </details>
      <div class="pcard-actions">
        <button class="primary" data-act="build">${t("build.now")}</button>
        <button class="ghost" data-act="filter">${t("build.filter")}</button>
        <span class="spacer"></span>
        <span class="switch-label">${t("build.live")}${w ? `<small>${t("build.rebuilt", w.rebuilds)}</small>` : ""}</span>
        <div class="switch ${w ? "on" : ""}" data-act="watch" role="switch" aria-checked="${!!w}" tabindex="0"></div>
      </div>`;
    card.querySelectorAll("[data-comp]").forEach(cb => cb.addEventListener("change", () => {
      projComps[p.project_id][cb.dataset.comp] = cb.checked;
      apiAgent("/api/project-config", { method: "POST", body: { project_id: p.project_id, components: projComps[p.project_id] } });
    }));
    card.querySelector('[data-act="build"]').addEventListener("click", () => doBuild(p));
    card.querySelector('[data-act="filter"]').addEventListener("click", () => openFileTree(p));
    const sw = card.querySelector('[data-act="watch"]');
    sw.addEventListener("click", () => doWatchToggle(p));
    sw.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); doWatchToggle(p); } });
    card.querySelector(".pcard-head").addEventListener("click", () => openDetail(p));
    card.querySelector(".pcard-head").title = "点击查看项目详情(git / 文件 / 会话)";
    box.appendChild(card);
  }
  if (!list.length) box.innerHTML = emptyBox(t("card.empty"));
}

function compCb(pid, c, comps) {
  return `<label class="comp"><input type="checkbox" data-comp="${c.key}" ${comps[c.key] ? "checked" : ""}><span>${t("comp." + c.key + ".l")}</span><small class="comp-desc">${t("comp." + c.key + ".d")}</small></label>`;
}

async function doBuild(p, live = false) {
  const body = { project_id: p.project_id, components: projComps[p.project_id], label: p.name, live };
  // 备份产物推送到提供本页面的中央服务器
  if (AGENT.kind !== "self") {
    body.push_url = SERVER;
    if (REMOTE_TOKEN) body.push_token = REMOTE_TOKEN;
  }
  const r = await apiAgent("/api/build", { method: "POST", body });
  if (r.ok) trackJob(r.job_id, `备份 ${p.name}`, AGENT.base);
  else notify(t("build.failed") + (r.error || "?"), "err");
}

async function doWatchToggle(p) {
  const enable = !((AGENT.state.watchers) || []).some(w => w.project_id === p.project_id);
  const body = { project_id: p.project_id, project_path: p.path, enabled: enable,
                 components: projComps[p.project_id], label: p.name, interval: 20 };
  const r = await apiAgent("/api/watch", { method: "POST", body });
  if (r.ok) {
    AGENT.state.watchers = r.watchers;
    renderProjects();
    if (enable) doBuild(p, true);
  }
}

/* ---------------- 文件筛选器 ---------------- */
async function openFileTree(p) {
  ftState = { projectId: p.project_id, filter: (p.config || {}).source_filter || {}, open: {} };
  $("#modal-title").textContent = `源码筛选 —— ${p.name}`;
  $("#modal").classList.remove("hidden");
  await renderFileTree("");
}

async function renderFileTree(rel) {
  ftState._rel = rel;
  const r = await apiAgent(`/api/filetree?project_id=${encodeURIComponent(ftState.projectId)}&rel=${encodeURIComponent(rel)}`);
  if (!r.ok) { $("#filetree").textContent = r.error || "读取失败"; return; }
  ftState.filter = r.filter || ftState.filter;
  const box = $("#filetree");
  const isRoot = !rel;
  const entries = r.entries || [];
  box.innerHTML =
    (isRoot ? "" : `<div class="ft-row ft-dir" data-rel="${esc(rel.split("/").slice(0, -1).join("/"))}">${ICO_DIR}<span class="ft-name">..</span><span class="ft-size"></span><span class="ft-actions"></span></div>`) +
    (entries.length ? entries.map(e => {
      const mark = e.ignored ? '<span class="ft-mark ignored">忽略</span>' : "";
      return `<div class="ft-row ${e.ignored ? "dim" : ""}" data-rel="${esc(e.rel)}" data-type="${e.type}">
        ${e.type === "dir" ? ICO_DIR : ICO_FILE}
        <span class="ft-name">${esc(e.name)}</span>
        ${e.type === "dir" && e.ignored ? "" : `<span class="ft-size">${fmtBytes(e.size)}</span>`}
        ${mark}
        <span class="ft-actions">
          <button class="ghost mini" data-ignore="${esc(e.rel)}">排除</button>
          <button class="ghost mini" data-include="${esc(e.rel)}">包含</button>
        </span>
      </div>`;
    }).join("") : '<div class="hint" style="padding:8px 10px">空目录</div>');
  box.querySelectorAll(".ft-dir[data-rel]").forEach(row => row.addEventListener("click", ev => {
    if (ev.target.tagName === "BUTTON") return;
    renderFileTree(row.dataset.rel);
  }));
  box.querySelectorAll("[data-ignore]").forEach(b => b.addEventListener("click", ev => {
    ev.stopPropagation();
    addRule("extra_ignores", b.dataset.ignore);
  }));
  box.querySelectorAll("[data-include]").forEach(b => b.addEventListener("click", ev => {
    ev.stopPropagation();
    addRule("forced_includes", b.dataset.include);
  }));
  renderRules();
}

async function addRule(kind, pattern) {
  const f = ftState.filter;
  f[kind] = f[kind] || [];
  if (!f[kind].includes(pattern)) f[kind].push(pattern);
  await apiAgent("/api/project-config", { method: "POST", body: { project_id: ftState.projectId, source_filter: f } });
  renderFileTree(ftState._rel || "");
  renderRules();
}

function renderRules() {
  const f = ftState.filter || {};
  const parts = [];
  if (f.preset_ignores !== false) parts.push(`预设忽略规则已启用(node_modules/__pycache__/venv/dist/logs…)`);
  else parts.push(`预设忽略规则已停用`);
  const extra = (f.extra_ignores || []).map(x => `<span class="badge">✕ ${esc(x)}<a href="#" class="del-link" data-del="extra_ignores:${esc(x)}">删</a></span>`).join("");
  const forced = (f.forced_includes || []).map(x => `<span class="badge on">✓ ${esc(x)}<a href="#" class="del-link" data-del="forced_includes:${esc(x)}">删</a></span>`).join("");
  $("#ft-rules").innerHTML =
    `${parts[0]}<br>自定义排除: ${extra || "无"}<br>强制包含: ${forced || "无"}`;
  $("#ft-rules").querySelectorAll("[data-del]").forEach(a => a.addEventListener("click", async e => {
    e.preventDefault();
    const [kind, pat] = a.dataset.del.split(":");
    const f2 = ftState.filter;
    f2[kind] = (f2[kind] || []).filter(x => x !== pat);
    await apiAgent("/api/project-config", { method: "POST", body: { project_id: ftState.projectId, source_filter: f2 } });
    renderFileTree(ftState._rel || "");
    renderRules();
  }));
}

$("#ft-add-btn").addEventListener("click", () => {
  const v = $("#ft-add-ignore").value.trim();
  if (v) { addRule("extra_ignores", v); $("#ft-add-ignore").value = ""; }
});
const hideModal = () => $("#modal").classList.add("hidden");
$("#modal-close").addEventListener("click", hideModal);
$("#modal").addEventListener("click", e => { if (e.target === e.currentTarget) hideModal(); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !$("#modal").classList.contains("hidden")) hideModal();
});

/* ---------------- 项目详情 / 会话浏览(只读) ---------------- */
const dtState = {
  pid: null, project: null, view: "project", sid: null, offset: 0,
  tree: {},                                // rel -> {loaded, open, loading, entries}
  fsFocus: null,                           // 文件树下钻的当前目录(null=根视图)
  sess: { sortKey: "updated", sortDir: "desc", query: "", openSet: new Set() },
  sview: "chat",                           // 会话视图: chat | trace
};

function hideDetail() { closeSplit(); $("#detail").classList.add("hidden"); }
$("#dt-close").addEventListener("click", hideDetail);
$("#detail").addEventListener("click", e => { if (e.target === e.currentTarget) hideDetail(); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !$("#detail").classList.contains("hidden")) hideDetail();
});
$("#dt-back").addEventListener("click", () => {
  if (dtState.view === "session" && dtState.project) renderDetailProject();
});

async function openDetail(p) {
  dtState.pid = p.project_id;
  dtState.project = null;
  dtState.view = "project";
  dtState.tree = {};
  dtState.sess.openSet = new Set();
  $("#dt-back").style.display = "none";
  $("#dt-body").classList.remove("sess");
  $("#dt-name").textContent = p.name;
  $("#dt-sub").textContent = p.path || p.project_id;
  $("#detail").classList.remove("hidden");
  $("#dt-body").innerHTML = '<div class="hint" style="padding:24px">探测中… git 状态与目录统计可能需要数秒(大仓库较慢)</div>';
  const r = await apiAgent(`/api/project-detail?project_id=${encodeURIComponent(p.project_id)}`, {}, 90000);
  if (!r.ok) {
    $("#dt-body").innerHTML = `<div class="hint st-error" style="padding:24px">读取失败: ${esc(r.error || "?")}</div>`;
    return;
  }
  dtState.project = r;
  renderDetailProject();
}

function renderDetailProject() {
  const r = dtState.project;
  if (!r) return;
  closeSplit();
  dtState.view = "project";
  $("#dt-back").style.display = "none";
  $("#dt-body").classList.remove("sess");
  const p = r.project;
  $("#dt-name").textContent = p.name;
  $("#dt-name").title = p.project_id;
  $("#dt-sub").textContent = p.path || p.project_id;
  $("#dt-body").innerHTML = `
    <div class="dt-sec">
      <h4>${t("d.overview")}</h4>
      <div class="dt-kv">
        <span>${t("d.path")}</span><b class="mono">${esc(p.path || "(未知)")}</b>
        <span>project_id</span><b class="mono">${esc(p.project_id)}</b>
        <span>记忆 slug</span><b class="mono">${esc(p.memory_slug || "-")}</b>
        <span>会话</span><b>${p.sessions} 个(含子代理) · 侧边栏 ${p.in_sidebar}</b>
        <span>模型轨迹</span><b>${fmtBytes(p.rollout_bytes)}</b>
        <span>记忆文件</span><b>${p.memory_files}</b>
        <span>zcode CLI</span><b>${esc((p.versions || []).join(" / ") || "?")}</b>
      </div>
    </div>
    <div class="dt-sec">
      <h4>${t("d.git")}</h4>
      <div id="dt-git"></div>
    </div>
    <div class="dt-sec">
      <h4>${t("d.files")} <span class="h3-sub">${t("d.filesSub")}</span></h4>
      <div class="filetree dt-fs" id="dt-fs"></div>
    </div>
    <div class="dt-sec">
      <h4>${t("d.sessions", (r.sessions || []).length)}</h4>
      <div id="dt-sessions" class="dt-sessions"></div>
    </div>`;
  renderGitSec(r.git);
  renderDetailSessions(r.sessions || []);
  renderDetailFs();
}

function renderGitSec(git) {
  const el = $("#dt-git");
  if (!el) return;
  if (!git || !git.is_repo) {
    el.innerHTML = `<div class="hint">${t("d.notGit")}</div>`;
    return;
  }
  const ch = git.changes || {};
  const abHtml = git.upstream == null
    ? `<span class="badge">${t("d.noUpstream")}</span>`
    : `<span class="badge ${git.ahead > 0 ? "on" : ""}">↑${git.ahead ?? "?"} 待推送</span>` +
      `<span class="badge ${git.behind > 0 ? "live" : ""}">↓${git.behind ?? "?"} 待拉取</span>`;
  el.innerHTML = `
    <div class="git-line">
      <span class="badge on mono">${esc(git.branch)}</span>
      ${git.upstream ? `<span class="hint mono">${esc(git.upstream)}</span>` : ""}
      ${abHtml}
      <span class="badge ${ch.total > 0 ? "live" : ""}" title="staged ${ch.staged} · 未暂存 ${ch.unstaged} · 未跟踪 ${ch.untracked}">
        ${t("d.changes", ch.total ?? 0)}</span>
      <span class="spacer"></span>
      <button class="ghost mini" id="dt-git-fetch" title="联网 git fetch, 仅更新远端跟踪引用, 不碰工作区">${t("d.fetch")}</button>
    </div>
    ${git.note ? `<div class="hint">${esc(git.note)}</div>` : ""}
    ${Object.entries(git.remotes || {}).map(([k, v]) => `<div class="hint mono">${esc(k)}: ${esc(v)}</div>`).join("")}
    <div class="git-log">${(git.recent_commits || []).map(c => `
      <div class="git-commit">
        <span class="mono hash">${esc(c.hash)}</span>
        <span class="subj">${esc(c.subject)}</span>
        <span class="hint">${esc(c.author)} · ${fmtTime(c.time)}</span>
      </div>`).join("") || `<div class="hint">${t("d.noCommits")}</div>`}
    </div>`;
  const fb = el.querySelector("#dt-git-fetch");
  if (fb) fb.addEventListener("click", async () => {
    fb.disabled = true;
    fb.textContent = t("d.fetching");
    const res = await apiAgent("/api/git-fetch", { method: "POST", body: { project_id: dtState.pid } }, 120000);
    if (res.ok) {
      notify("fetch 完成, 重新探测差异", "ok");
      openDetail({ project_id: dtState.pid, name: $("#dt-name").textContent, path: dtState.project?.project?.path });
    } else {
      notify("fetch 失败: " + (res.error || "?"), "err");
      fb.disabled = false;
      fb.textContent = t("d.fetch");
    }
  });
}

/* 文件树: 箭头=原地树形展开, 目录名=下钻为该目录的内部列表(面包屑返回) */
async function ensureLoaded(rel) {
  dtState.tree[rel] ||= { loaded: false, open: false, loading: false, entries: [] };
  const n = dtState.tree[rel];
  if (n.loaded || n.loading) return n;
  n.loading = true;
  renderTree();
  const r = await apiAgent(`/api/filetree?project_id=${encodeURIComponent(dtState.pid)}&rel=${encodeURIComponent(rel)}`);
  n.loading = false;
  if (r.ok) {
    n.entries = r.entries || [];
    n.loaded = true;
  } else {
    notify("读取目录失败: " + (r.error || "?"), "err");
  }
  return n;
}

async function toggleTreeNode(rel) {
  const wasLoaded = !!dtState.tree[rel]?.loaded;
  const n = await ensureLoaded(rel);
  if (n.loaded) n.open = wasLoaded ? !n.open : true;
  renderTree();
}

async function drillInto(rel) {
  dtState.fsFocus = rel;
  await ensureLoaded(rel);
  renderTree();
}

function fsRowHtml(e, depth, isOpen) {
  if (e.type === "dir") {
    return `
    <div class="ft-row dt-dir" data-rel="${esc(e.rel)}" style="--depth:${depth}">
      <span class="tw">${isOpen ? "▾" : "▸"}</span>${ICO_DIR}
      <span class="ft-name">${esc(e.name)}</span>
      <span class="ft-meta"><span class="ft-cnt">${e.children} 项</span><span class="ft-sz">${fmtBytes(e.size)}</span></span>
    </div>`;
  }
  return `
  <div class="ft-row" style="--depth:${depth}">
    <span class="tw"></span>${ICO_FILE}
    <span class="ft-name">${esc(e.name)}</span>
    <span class="ft-meta"><span class="ft-cnt"></span><span class="ft-sz">${fmtBytes(e.size)}</span></span>
  </div>`;
}

function fsLevelHtml(rel, baseDepth) {
  let html = "";
  const emit = (r, d) => {
    const nn = dtState.tree[r] || {};
    for (const e of (nn.entries || [])) {
      const child = dtState.tree[e.rel] || {};
      html += fsRowHtml(e, d, !!child.open);
      if (e.type === "dir" && child.open && child.loaded) emit(e.rel, d + 1);
    }
    if (nn.loading) html += `<div class="hint ft-load" style="--depth:${d}">${t("d.loading")}</div>`;
    else if (nn.loaded && !(nn.entries || []).length) html += `<div class="hint ft-load" style="--depth:${d}">${t("d.empty")}</div>`;
  };
  emit(rel, baseDepth);
  return html;
}

function renderTree() {
  const box = $("#dt-fs");
  if (!box) return;
  if (!box.dataset.bound) {
    box.dataset.bound = "1";
    box.addEventListener("click", e => {
      if (e.target.classList.contains("tw")) {
        const row = e.target.closest(".ft-row.dt-dir[data-rel]");
        if (row) toggleTreeNode(row.dataset.rel);
        return;
      }
      const crumb = e.target.closest("[data-drill]");
      if (crumb) {
        if (crumb.dataset.drill === "") dtState.fsFocus = null;
        else drillInto(crumb.dataset.drill);
        renderTree();
        return;
      }
      const row = e.target.closest(".ft-row.dt-dir[data-rel]");
      if (row) drillInto(row.dataset.rel);
    });
  }
  // 列头(名称/项数/大小)
  const headHtml = `
    <div class="ft-head">
      <span class="fh-tw"></span><span class="fh-ico"></span>
      <span class="fh-name">${t("d.colName")}</span>
      <span class="fh-cnt">${t("d.colCnt")}</span>
      <span class="fh-sz">${t("d.colSize")}</span>
    </div>`;
  const focus = dtState.fsFocus;
  if (focus) {
    // 下钻视图: 面包屑 + 该目录直接内容(其内箭头仍可原地树形展开)
    const parts = focus.split("/");
    box.innerHTML = `
      <div class="dt-crumb">
        <span class="crumb" data-drill="">${esc(dtState.project?.project?.name || t("d.root"))}</span>
        ${parts.map((s, i) => `<span class="crumb-sep">/</span><span class="crumb${i === parts.length - 1 ? " cur" : ""}" data-drill="${esc(parts.slice(0, i + 1).join("/"))}">${esc(s)}</span>`).join("")}
      </div>
      ${headHtml}
      ${fsLevelHtml(focus, 0)}`;
  } else {
    const root = dtState.tree[""] || {};
    const rootName = dtState.project?.project?.path || t("d.rootName");
    box.innerHTML = `
      ${headHtml}
      <div class="ft-row dt-dir root" data-rel="" style="--depth:0">
        <span class="tw">${root.open ? "▾" : "▸"}</span>${ICO_DIR}
        <span class="ft-name">${esc(rootName)}</span>
        <span class="ft-meta"><span class="ft-cnt"></span><span class="ft-sz">${root.loaded ? (root.open ? "" : t("d.collapsed")) : ""}</span></span>
      </div>
      ${root.open ? fsLevelHtml("", 1) : ""}`;
  }
}

async function renderDetailFs() {
  // 默认收起(用户一般不需要在此浏览文件清单, 给下方会话列表腾位置), 点开时再加载
  dtState.tree = { "": { loaded: false, open: false, loading: false, entries: [] } };
  dtState.fsFocus = null;
  renderTree();
}

function renderDetailSessions(sessions) {
  const box = $("#dt-sessions");
  if (!box) return;
  if (!sessions.length) {
    box.innerHTML = `<div class="hint">${t("d.noSessions")}</div>`;
    return;
  }
  box.innerHTML = `
    <div class="dt-sess-tools">
      <input id="dt-sess-search" class="grow" placeholder="${esc(t('d.searchPh'))}" value="${esc(dtState.sess.query)}">
      <select id="dt-sess-sortkey" class="mini">
        <option value="updated"${dtState.sess.sortKey === "updated" ? " selected" : ""}>${t("d.sortUpdated")}</option>
        <option value="created"${dtState.sess.sortKey === "created" ? " selected" : ""}>${t("d.sortCreated")}</option>
      </select>
      <button id="dt-sess-sortdir" class="ghost mini" title="切换升序/降序">${t(dtState.sess.sortDir === "desc" ? "d.sortDesc" : "d.sortAsc")}</button>
    </div>
    <div id="dt-sess-list" class="dt-sessions"></div>`;
  $("#dt-sess-search").addEventListener("input", e => {
    dtState.sess.query = e.target.value;
    renderSessList();
  });
  $("#dt-sess-sortkey").addEventListener("change", e => {
    dtState.sess.sortKey = e.target.value;
    renderSessList();
  });
  $("#dt-sess-sortdir").addEventListener("click", () => {
    dtState.sess.sortDir = dtState.sess.sortDir === "desc" ? "asc" : "desc";
    $("#dt-sess-sortdir").textContent = t(dtState.sess.sortDir === "desc" ? "d.sortDesc" : "d.sortAsc");
    renderSessList();
  });
  renderSessList();
}

function sessRow(s, opts = {}) {
  const rootPath = (dtState.project?.project?.path || "").toLowerCase();
  const dirDiff = s.directory && rootPath && s.directory.toLowerCase() !== rootPath;
  const open = dtState.sess.openSet.has(s.id);
  const kids = opts.kids || [];
  const hasKids = !opts.child && kids.length > 0;
  return `
  <div class="dt-session${opts.child ? " child" : ""}${opts.dimmed ? " dim" : ""}" data-sid="${esc(s.id)}" data-toggle-target="1" title="${esc(s.id)} · 创建 ${new Date(s.time_created || 0).toLocaleString()}">
    ${opts.child
      ? `<span class="tw"></span><span class="badge sub" title="subagent">${t("d.subagent")}</span>`
      : hasKids
        ? `<span class="tw sess-tw" data-toggle="${esc(s.id)}">${open ? "▾" : "▸"}</span>`
        : `<span class="tw tw-sp"></span>`}
    <span class="ds-name">${esc(s.title || "(无标题)")}</span>
    <span class="ds-meta-inline">${fmtTime(s.time_updated)} · ${s.messages} ${t("d.msgs")}${dirDiff ? ` · <span class="mono" title="子代理运行目录">${esc(s.directory)}</span>` : ""}</span>
  </div>`;
}

function renderSessList() {
  const list = $("#dt-sess-list");
  if (!list) return;
  const sessions = (dtState.project?.sessions) || [];
  const q = dtState.sess.query.trim().toLowerCase();
  const key = dtState.sess.sortKey === "created" ? "time_created" : "time_updated";
  const dir = dtState.sess.sortDir === "asc" ? 1 : -1;
  const match = s => (s.title || "").toLowerCase().includes(q);
  const tops = sessions.filter(s => !s.is_subagent);
  const subs = sessions.filter(s => s.is_subagent);
  const subOf = pid => subs.filter(x => x.parent_id === pid)
    .sort((a, b) => (a.time_created || 0) - (b.time_created || 0));
  dtState.sess.openSet ||= new Set();
  let shown = q ? tops.filter(t => match(t) || subOf(t.id).some(match)) : tops;
  shown.sort((a, b) => ((a[key] || 0) - (b[key] || 0)) * dir);
  // 搜索时自动展开命中子代理的主会话
  const openSet = dtState.sess.openSet;
  if (q) {
    for (const t of shown) {
      if (!match(t) && subOf(t.id).some(match) && !openSet.has(t.id)) openSet.add(t.id);
    }
  }
  list.innerHTML = shown.map(t => {
    const allKids = subOf(t.id);
    const kids = q
      ? (match(t) ? allKids : allKids.filter(match))
      : allKids;
    const open = openSet.has(t.id) || (q && kids.length > 0);
    return sessRow(t, { kids: allKids }) +
      (open || q ? kids.map(k => sessRow(k, { child: true, dimmed: q && !match(k) })).join("") : "");
  }).join("") || `<div class="hint" style="padding:8px 10px">${t("d.noMatch", dtState.sess.query)}</div>`;
  // 事件委托: 箭头=展开/收起子代理, 行其余区域=打开会话
  if (!list.dataset.bound) {
    list.dataset.bound = "1";
    list.addEventListener("click", e => {
      const tw = e.target.closest("[data-toggle]");
      if (tw) {
        const pid = tw.dataset.toggle;
        if (openSet.has(pid)) openSet.delete(pid); else openSet.add(pid);
        renderSessList();
        return;
      }
      const row = e.target.closest(".dt-session[data-sid]");
      if (!row) return;
      const sid = row.dataset.sid;
      const meta = sessions.find(s => s.id === sid);
      if (meta?.is_subagent && meta.parent_id) openChildSession(sid);
      else openSession(sid);
    });
  }
}

/* 从列表打开子代理会话: 左侧加载其父会话并定位调用点, 右侧分屏展示子代理 */
async function openChildSession(childSid) {
  const child = (dtState.project?.sessions || []).find(s => s.id === childSid);
  if (!child?.parent_id) { openSession(childSid); return; }
  await openSession(child.parent_id);
  const callId = (dtState.sessionChildren || [])
    .find(c => c.id === childSid)?.agent_call?.callID || "";
  openSplit(childSid, callId);
}

async function openSession(sid, sview = "chat") {
  dtState.view = "session";
  dtState.sid = sid;
  dtState.offset = 0;
  dtState.sview = sview;
  $("#dt-back").style.display = "";
  $('#dt-body').innerHTML = `<div class="hint" style="padding:24px">${t("ld.session")}</div>`;
  const r = await apiAgent(`/api/session?sid=${encodeURIComponent(sid)}`);
  if (!r.ok) {
    $("#dt-body").innerHTML = `<div class="hint st-error" style="padding:24px">读取失败: ${esc(r.error || "?")}</div>`;
    return;
  }
  renderSession(r);
}

function renderSession(r) {
  const s = r.session;
  dtState.sessionChildren = r.children || [];
  dtState.sessionIsSub = s.task_type === "subagent_child";
  dtState.childByCall = new Map(
    (r.children || []).filter(c => c.agent_call).map(c => [c.agent_call.callID, c]));
  $("#dt-name").textContent = s.title || s.id;
  $("#dt-name").title = s.title || s.id;
  $("#dt-sub").textContent = `${s.directory || ""}`;
  $("#dt-body").classList.add("sess");
  $("#dt-body").innerHTML = `
    <div id="dt-main-col" class="dt-col">
      <div class="dt-sess-head">
        <div class="dt-ssinfo">
          ${s.task_type === "subagent_child"
            ? '<span class="badge sub">子代理会话</span>'
            : `<span class="badge on">${esc(s.task_type || "interactive")}</span>`}
          <span class="hint">${t("sv.created", fmtTime(s.time_created))} · ${t("sv.updated", fmtTime(s.time_updated))}</span>
          <span class="hint">CLI ${esc(s.version || "?")} · <b>${t("msg.total", r.total_messages, !r.has_more)}</b></span>
          <span class="spacer"></span>
          <div id="dt-sview">
            <button class="${dtState.sview === "chat" ? "active" : ""}" data-sv="chat">${t("sv.chat")}</button>
            <button class="${dtState.sview === "trace" ? "active" : ""}" data-sv="trace">${t("sv.trace")}</button>
            <button class="${dtState.sview === "system" ? "active" : ""}" data-sv="system">${t("sv.system")}</button>
          </div>
        </div>
        ${(r.children || []).length ? `
        <div class="dt-children">
          <span class="hint">${t("msg.children", r.children.length)}</span>
          ${r.children.map(c => `<span class="badge sub dt-child" data-sid="${esc(c.id)}" data-call="${esc(c.agent_call?.callID || "")}" title="${esc(c.directory || "")} · ${fmtTime(c.time_updated)}">${esc((c.title || c.id).slice(0, 34))}</span>`).join("")}
        </div>` : ""}
      </div>
      <div id="dt-sview-body"></div>
    </div>`;
  document.querySelectorAll("#dt-sview button").forEach(b =>
    b.addEventListener("click", () => {
      if (dtState.sview === b.dataset.sv) return;
      dtState.sview = b.dataset.sv;
      document.querySelectorAll("#dt-sview button").forEach(x =>
        x.classList.toggle("active", x.dataset.sv === dtState.sview));
      renderSviewBody();
    }));
  document.querySelectorAll(".dt-child").forEach(el =>
    el.addEventListener("click", () => openSplit(el.dataset.sid, el.dataset.call)));
  renderSviewBody();
}

/* ---------------- 主/子会话分屏对照 ---------------- */
async function openSplit(childSid, anchorCallId) {
  const child = (dtState.sessionChildren || []).find(c => c.id === childSid) || { id: childSid, title: "" };
  $("#detail").classList.add("split");
  $("#dt-body").classList.add("split");
  let sub = $("#dt-sub-col");
  if (!sub) {
    sub = document.createElement("div");
    sub.id = "dt-sub-col";
    sub.className = "dt-col";
    $("#dt-body").appendChild(sub);
  }
  sub.innerHTML = `<div class="hint" style="padding:16px">${t("ld.sub")}</div>`;
  // 主栏滚动到调用点并高亮(消息已渲染则立即, 否则待 renderChat 完成后定位)
  if (anchorCallId) {
    const el = document.getElementById("ac-" + anchorCallId);
    if (el) {
      el.scrollIntoView({ block: "center" });
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
    } else {
      dtState.pendingAnchor = anchorCallId;
    }
  }
  const r = await apiAgent(`/api/session?sid=${encodeURIComponent(childSid)}&limit=150`);
  if (!r.ok) { sub.innerHTML = `<div class="hint st-error">${esc(r.error || "?")}</div>`; return; }
  const wasSub = dtState.sessionIsSub;
  const wasChildren = dtState.sessionChildren;
  dtState.sessionIsSub = r.session.task_type === "subagent_child";
  dtState.sessionChildren = [];
  sub.innerHTML = `
    <div class="dt-sub-head">
      <div>
        <div class="dt-sub-title">${esc(r.session.title || childSid)}</div>
        <div class="hint mono">${esc(r.session.directory || "")}</div>
      </div>
      <button class="ghost mini" id="dt-sub-close">${t("sp.exit")}</button>
    </div>
    <div class="dt-msgs">${renderChatFlow(r.messages)}</div>`;
  dtState.sessionIsSub = wasSub;
  dtState.sessionChildren = wasChildren;
  $("#dt-sub-close").addEventListener("click", closeSplit);
}

function closeSplit() {
  $("#detail").classList.remove("split");
  const body = $("#dt-body");
  if (body) body.classList.remove("split");
  const sub = $("#dt-sub-col");
  if (sub) sub.remove();
}

function renderSviewBody() {
  if (dtState.sview === "trace") {
    renderTrace();
  } else if (dtState.sview === "system") {
    renderSystemPrompt();
  } else {
    renderChat();
  }
}

async function renderSystemPrompt() {
  const body = $("#dt-sview-body");
  body.innerHTML = `<div class="hint" style="padding:16px">${t("ld.system")}</div>`;
  const r = await apiAgent(`/api/session-system?sid=${encodeURIComponent(dtState.sid)}`, {}, 60000);
  if (!r.ok) { body.innerHTML = `<div class="hint st-error">${esc(r.error || "?")}</div>`; return; }
  if (!r.exists) {
    body.innerHTML = `<div class="hint">${t("sys.noTrace")}</div>`;
    return;
  }
  const which = dtState.sysWhich || "first";
  const snap = r[which] || r.first;
  const fmtAt = t => t ? new Date(t).toLocaleString("zh-CN", { hour12: false }) : "?";
  body.innerHTML = `
    <div class="hint" style="margin-bottom:10px">
      ${t("sys.head", snap.chars.toLocaleString(), snap.blocks.length)}
      · ${which === "first" ? t("sys.first", fmtAt(snap.at)) : t("sys.last", fmtAt(snap.at))}
      ${r.changed ? `<br><span class="st-error">${t("sys.changed", r.first.chars.toLocaleString(), r.last.chars.toLocaleString())}</span>
        <button class="ghost mini" id="dt-sys-which" data-w="${which === "first" ? "last" : "first"}">${which === "first" ? t("sys.switchLast") : t("sys.switchFirst")}</button>` : ""}
       · 含 zcode 基础指令/技能列表/AGENTS.md/记忆等注入内容
    </div>
    <div class="dt-sys">
      ${snap.blocks.map((b, i) => `
      <details class="mp-fold sysblk"${i === 0 ? " open" : ""}>
        <summary>${t("sys.blk", i + 1, b.length.toLocaleString())}${esc(b.slice(0, 80).split("\n").join(" "))}…</summary>
        <pre>${esc(b)}</pre>
      </details>`).join("")}
    </div>`;
  const btn = body.querySelector("#dt-sys-which");
  if (btn) btn.addEventListener("click", () => {
    dtState.sysWhich = btn.dataset.w;
    renderSystemPrompt();
  });
}

async function renderChat() {
  dtState.offset = 0;
  const body = $("#dt-sview-body");
  body.innerHTML = `<div class="hint" style="padding:16px">${t("ld.msgs")}</div>`;
  const r = await apiAgent(`/api/session?sid=${encodeURIComponent(dtState.sid)}&limit=150`);
  if (!r.ok) { body.innerHTML = `<div class="hint st-error">${esc(r.error || "?")}</div>`; return; }
  body.innerHTML = `
    <div id="dt-more"></div>
    <div class="dt-msgs" id="dt-msgs"></div>`;
  $("#dt-msgs").innerHTML = renderChatFlow(r.messages);
  renderMoreBtn(r);
  // 分屏打开时主栏渲染完成后才定位调用点(从会话列表直接进入的时序)
  if (dtState.pendingAnchor) {
    const el = document.getElementById("ac-" + dtState.pendingAnchor);
    if (el) { el.scrollIntoView({ block: "center" }); el.classList.add("flash"); }
    dtState.pendingAnchor = null;
  }
  if (!body.dataset.bound) {
    body.dataset.bound = "1";
    body.addEventListener("click", e => {
      const btn = e.target.closest("[data-split]");
      if (btn) openSplit(btn.dataset.split, btn.dataset.call);
    });
  }
}

async function renderTrace() {
  const body = $("#dt-sview-body");
  body.innerHTML = `<div class="hint" style="padding:16px">${t("ld.trace")}</div>`;
  const r = await apiAgent(`/api/session-trace?sid=${encodeURIComponent(dtState.sid)}`, {}, 120000);
  if (!r.ok) { body.innerHTML = `<div class="hint st-error">${esc(r.error || "?")}</div>`; return; }
  const calls = r.calls || [];
  if (!r.exists || !calls.length) {
    body.innerHTML = `<div class="hint">${t("tr.noTrace")}</div>`;
    return;
  }
  const totalIn = calls.reduce((a, c) => a + ((c.tokens?.in) || 0), 0);
  const totalOut = calls.reduce((a, c) => a + ((c.tokens?.out) || 0), 0);
  body.innerHTML = `
    <div class="hint" style="margin-bottom:10px"><b>${t("tr.total", calls.length)}</b> · ↑${fmtTokens(totalIn)} tok / ↓${fmtTokens(totalOut)} tok${t("tr.clickDetail")}</div>
    <div class="dt-trace">${calls.map(renderTraceRow).join("")}</div>`;
  body.querySelectorAll(".trace-row").forEach(el =>
    el.addEventListener("click", () => toggleTraceDetail(el.dataset.idx)));
}

function fmtTokens(n) {
  if (n == null) return "-";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}

function renderTraceRow(c, i) {
  if (c.error) return `<div class="trace-row err">#${c.idx} ${esc(c.error)}</div>`;
  const t = c.startedAt ? new Date(c.startedAt).toLocaleString("zh-CN", { hour12: false }) : "?";
  const qs = c.querySource && c.querySource !== "main_turn" ? ` <span class="badge sub">${esc(c.querySource)}</span>` : "";
  const fin = c.finishReason ? `<span class="badge ${c.finishReason === "stop" || c.finishReason === "tool-calls" ? "" : "live"}">${esc(c.finishReason)}</span>` : "";
  return `
  <div class="trace-row" data-idx="${c.idx}">
    <div class="tr-main">
      <span class="tr-idx mono">#${c.idx}</span>
      <span class="tr-time">${esc(t)}</span>
      <span class="mono tr-model">${esc(c.model || "?")}</span>
      ${qs}${fin}
      <span class="hint">${((c.durationMs || 0) / 1000).toFixed(1)}s</span>
      <span class="hint mono">↑${fmtTokens(c.tokens?.in)} ↓${fmtTokens(c.tokens?.out)}${c.tokens?.cacheRead ? ` ⚡${fmtTokens(c.tokens.cacheRead)}` : ""}</span>
      <span class="hint">消息 ${c.reqMessages}</span>
    </div>
    <div class="tr-preview">${esc(c.preview || "")}</div>
    <div class="tr-detail" hidden></div>
  </div>`;
}

async function toggleTraceDetail(idx) {
  const row = document.querySelector(`.trace-row[data-idx="${idx}"] .tr-detail`);
  if (!row) return;
  if (!row.hidden) { row.hidden = true; return; }
  if (!row.innerHTML) {
    row.innerHTML = '<div class="hint">加载详情…</div>';
    row.hidden = false;
    const r = await apiAgent(`/api/session-trace?sid=${encodeURIComponent(dtState.sid)}&line=${encodeURIComponent(idx)}`, {}, 30000);
    if (!r.ok) { row.innerHTML = `<div class="hint st-error">${esc(r.error || "?")}</div>`; return; }
    const d = r.detail || {};
    const req = (d.req_tail_messages || []).map(m => `
      <div class="mp-io"><div class="mp-lbl">${esc(m.role || "?")}${m.truncated ? " · 已截断" : ""}</div><pre>${esc(m.content)}</pre></div>`).join("");
    const resp = d.response || {};
    row.innerHTML = `
      <div class="hint">${t("tr.sysChars", fmtBytes(d.system_chars || 0))}${t("tr.reqTail", d.req_total_messages, req ? (d.req_tail_messages || []).length : 0)}</div>
      ${req ? `<div class="mp-lbl">${t("tr.tailTitle")}</div>${req}` : ""}
      ${resp.reasoning ? `<details class="mp-fold reasoning" open><summary>${t("tr.respReasoning")}</summary><pre>${esc(resp.reasoning)}</pre></details>` : ""}
      ${resp.text ? `<div class="mp-lbl">${t("tr.respText")}</div><div class="mp-io"><pre>${esc(resp.text)}</pre></div>` : ""}
      ${(resp.toolCalls || []).length ? `<div class="mp-lbl">${t("tr.toolCalls")}</div>${resp.toolCalls.map(t => `
        <div class="mp-io"><div class="mp-lbl">⚙ ${esc(t.name || "?")}</div><pre>${esc(t.input)}</pre></div>`).join("")}` : ""}`;
  } else {
    row.hidden = false;
  }
}

function renderMoreBtn(r) {
  const more = $("#dt-more");
  if (!more) return;
  more.innerHTML = r.has_more
    ? `<button class="ghost" id="dt-more-btn">↑ 加载更早的消息(还有 ${r.total_messages - r.offset_from_end - r.limit} 条未显示)</button>`
    : "";
  const btn = more.querySelector("#dt-more-btn");
  if (btn) btn.addEventListener("click", loadEarlier);
}

async function loadEarlier() {
  if (!dtState.sid) return;
  dtState.offset += 150;
  const r = await apiAgent(`/api/session?sid=${encodeURIComponent(dtState.sid)}&offset=${dtState.offset}`);
  if (!r.ok) { notify("加载失败: " + (r.error || "?"), "err"); return; }
  renderMoreBtn(r);
  $("#dt-msgs").insertAdjacentHTML("afterbegin", renderChatFlow(r.messages));
}

const KIND_LABELS = {
  todo_reminder: "任务清单提醒",
  background_notification: "后台任务通知",
  system_reminder: "系统提醒",
  compact_summary: "压缩摘要",
  subagent_notification: "子代理通知",
};

function roleOf(m) {
  if (m.role === "assistant") return { key: "assistant", label: t("role.assistant") };
  if (m.role !== "user") return { key: m.role, label: m.role };
  // origin 判定优先: TodoWrite 提醒/后台通知等无论主/子会话都是 zcode 运行时注入
  if (m.origin === "real_user") return { key: "user", label: t("role.user") };
  if (m.origin) return { key: "system", label: (LANG === "en" ? "System · " : "系统 · ") + t("kind." + (m.kind || m.origin)) };
  if (dtState.sessionIsSub) return { key: "agent", label: t("role.agent") };
  // 旧版消息无 semantics: 按内容特征识别已知注入
  const text0 = (m.parts?.[0]?.text) || "";
  if (text0.startsWith("The TodoWrite tool hasn't been used") || text0.startsWith("Here are the existing contents"))
    return { key: "system", label: (LANG === "en" ? "System · " : "系统 · ") + t("kind.todo_reminder") };
  return { key: "user", label: t("role.user") };
}

const CONTENT_PART_TYPES = new Set(["text", "reasoning", "tool", "agent", "file"]);

/* ---------------- zcode 风格 工具/思考行 ----------------
   收起 = 单行摘要[图标|类别|对象|目录|· 耗时|状态|▸], 展开 = 圆角面板(参数/结果)。
   图标与文案对齐 zcode(packages/ui ToolCallBlocks + i18n chat.toolCall.*)。 */
const TOOL_META = {
  Read: { icon: ICO_L_SEARCH, label: "tc.read" },
  Bash: { icon: ICO_L_TERM, label: "tc.bash" },
  Edit: { icon: ICO_L_PEN, label: "tc.edit" },
  MultiEdit: { icon: ICO_L_PEN, label: "tc.edit" },
  NotebookEdit: { icon: ICO_L_PEN, label: "tc.edit" },
  Write: { icon: ICO_L_FILEPEN, label: "tc.write" },
  Grep: { icon: ICO_L_TXTSEARCH, label: "tc.grep" },
  Glob: { icon: ICO_L_SEARCH, label: "tc.glob" },
  TodoWrite: { icon: ICO_L_TODO, label: "tc.todo" },
  WebSearch: { icon: ICO_L_GLOBE, label: "tc.web" },
  WebFetch: { icon: ICO_L_GLOBE, label: "tc.web" },
  Skill: { icon: ICO_L_ZAP, label: "tc.skill" },
  SendMessage: { icon: ICO_L_MSG, label: "tc.msg" },
};

function toolInputObj(p) {
  try { return JSON.parse(p.input || "null") || {}; } catch (e) { return {}; }
}

/* 从工具入参提取 摘要主文本(文件名/命令/查询词) 与 次文本(所在目录) */
function toolSummary(p) {
  const tool = p.tool || "";
  const meta = TOOL_META[tool] || { icon: ICO_L_WRENCH, label: "tc.tool" };
  const inp = toolInputObj(p);
  let primary = "", isCmd = false, dir = "";
  if (tool === "Bash") {
    let cmd = inp.command ?? inp.cmd ?? inp.script ?? inp.exec ?? "";
    if (Array.isArray(cmd)) cmd = cmd.join(" ");
    primary = String(cmd).replace(/\s+/g, " ").trim();
    isCmd = true;
  } else if (["Read", "Edit", "MultiEdit", "Write", "NotebookEdit"].includes(tool)) {
    const fp = String(inp.file_path || inp.filePath || inp.path || "");
    primary = fp ? fp.split(/[\\/]/).pop() : "";
    dir = fp.slice(0, fp.length - primary.length).replace(/[\\/]$/, "");
  } else if (tool === "Grep" || tool === "Glob") {
    primary = inp.pattern || inp.query || "";
  } else if (tool === "WebSearch") {
    primary = inp.query || "";
  } else if (tool === "WebFetch") {
    primary = inp.url || "";
  } else if (tool === "Skill") {
    primary = inp.skill || "";
  } else if (tool === "TodoWrite") {
    primary = "";
  } else {
    primary = tool; // 未知/MCP 工具: 至少亮出名字
  }
  return { meta, primary, isCmd, dir };
}

function reasoningRow(p) {
  const durMs = Number.isFinite(p.t0) && Number.isFinite(p.t1) ? p.t1 - p.t0 : null;
  return `
  <details class="tc reasoning">
    <summary>
      <span class="tc-ico">${ICO_L_BRAIN}</span>
      <span class="tc-label">${t("tc.thought")}</span>
      ${durMs != null ? `<span class="tc-dur">· ${t("tc.thoughtDur", Math.max(1, Math.round(durMs / 1000)))}</span>` : ""}
      <span class="tc-chv">${ICO_L_CHEV}</span>
    </summary>
    <div class="tc-body"><div class="tc-panel"><pre>${esc(p.text)}${p.truncated ? t("tc.truncOut") : ""}</pre></div></div>
  </details>`;
}

function toolRow(p) {
  const { meta, primary, isCmd, dir } = toolSummary(p);
  const durMs = Number.isFinite(p.t0) && Number.isFinite(p.t1) ? p.t1 - p.t0 : null;
  const failed = p.status === "error" || p.status === "failed";
  const unfilled = !failed && p.status !== "completed";
  const stHtml = failed
    ? `<span class="tc-st fail" title="${esc((p.output || "").split("\n")[0].slice(0, 200))}">${t("tc.st.failed")}</span>`
    : unfilled ? `<span class="tc-st unfilled">${t("tc.st.unfilled")}</span>` : "";
  const mainHtml = primary
    ? `<span class="tc-main"${!isCmd && dir ? ` title="${esc(dir + "/" + primary)}"` : ""}>` +
      (isCmd ? `<span class="tc-cmdline">${esc(primary)}</span>` : esc(primary)) + `</span>`
    : "";
  // 展开面板: Bash = $命令 + 输出; 其余 = 参数 + 结果
  const inp = toolInputObj(p);
  let prettyIn = p.input || "";
  try { prettyIn = JSON.stringify(inp, null, 2); } catch (e) { /* 保留原文 */ }
  const isBash = p.tool === "Bash";
  let cmdRaw = isBash ? (inp.command ?? inp.cmd ?? inp.script ?? inp.exec ?? "") : "";
  if (Array.isArray(cmdRaw)) cmdRaw = cmdRaw.join(" ");
  const cmdFull = String(cmdRaw);
  const outPre = esc(p.output || (failed ? "" : t("tc.noOutput")));
  const bodyHtml = isBash
    ? `<div class="tc-cmd"><span class="tc-dollar">$</span><div>${esc(cmdFull)}</div></div>
       <div class="tc-lbl">${t("tc.output")}</div><pre>${outPre}</pre>`
    : `<div class="tc-lbl">${t("tc.params")}</div><pre>${esc(prettyIn)}</pre>
       <div class="tc-lbl">${t("tc.result")}</div><pre>${outPre}</pre>`;
  return `
  <details class="tc tool">
    <summary>
      <span class="tc-ico">${meta.icon}</span>
      <span class="tc-label">${t(meta.label)}</span>
      ${mainHtml}
      ${!isCmd && dir ? `<span class="tc-sub">${esc(dir)}</span>` : ""}
      ${durMs != null ? `<span class="tc-dur">· ${fmtDur(durMs)}</span>` : ""}
      ${stHtml}
      <span class="tc-chv">${ICO_L_CHEV}</span>
    </summary>
    <div class="tc-body"><div class="tc-panel">${bodyHtml}${p.truncated ? `<div class="tc-trunc">${t("tc.truncOut")}</div>` : ""}</div></div>
  </details>`;
}

function agentLaunchCard(p) {
  const child = dtState.childByCall?.get(p.callID);
  const st = p.status === "completed" ? `<span class="badge on">${t("ac.done")}</span>`
    : p.status === "error" ? `<span class="badge live">${t("ac.error")}</span>`
    : `<span class="badge" title="unfilled">${t("ac.unfilled")}</span>`;
  return `
  <div class="agent-card launch" id="ac-${esc(p.callID || "")}">
    <div class="ac-head">
      <span class="ac-ico">${ICO_L_BOT}</span>
      <span class="ac-title">${t("ac.launch")}${p.subagent_type ? ` · ${esc(p.subagent_type)}` : ""}</span>
      ${st}
      ${p.description ? `<span class="hint ac-desc">${esc(p.description)}</span>` : ""}
      ${child ? `<button class="ghost mini" data-split="${esc(child.id)}" data-call="${esc(p.callID)}">${t("ac.split")}</button>` : ""}
    </div>
    ${p.prompt ? `<details class="mp-fold prompt"><summary>${t("ac.prompt")}</summary><pre>${esc(p.prompt)}</pre></details>` : ""}
  </div>`;
}

function agentReturnCard(p) {
  const child = dtState.childByCall?.get(p.callID);
  return `
  <div class="agent-card ret">
    <div class="ac-head">
      <span class="ac-ico">${ICO_L_CHECK}</span>
      <span class="ac-title">${t("ac.ret")}${p.description ? ` · ${esc(p.description)}` : ""}</span>
      ${child ? `<button class="ghost mini" data-split="${esc(child.id)}" data-call="${esc(p.callID)}">↗ 分屏查看</button>` : ""}
    </div>
    ${p.output ? `<details class="mp-fold out" open><summary>${t("ac.output")}</summary><pre>${esc(p.output)}${p.truncated ? "\n…(已截断)" : ""}</pre></details>` : `<div class="hint" style="padding:2px 12px 8px">${t("ac.noOutput")}</div>`}
  </div>`;
}

function renderMsg(m) {
  const role = roleOf(m);
  const parts = m.parts || [];
  if (role.key === "assistant" && !parts.some(p => CONTENT_PART_TYPES.has(p.type))) {
    // 无正文内容的助手消息 = agent loop 的步骤边界/时间线事件, 渲染为紧凑分隔行
    const tl = parts.find(p => p.type === "timeline" && p.info);
    const n = parts.filter(p => p.type === "step-start" || p.type === "step-finish").length;
    return `<div class="msg-step"><span>${tl ? "⟳ " + esc(tl.info) : t("fold.step", n)}</span></div>`;
  }
  const partsHtml = parts.map(p => {
    if (p.type === "text") {
      return `<div class="mp-text">${esc(p.text)}${p.truncated ? '<div class="hint">…(内容过长已截断)</div>' : ""}</div>`;
    }
    if (p.type === "reasoning") {
      return reasoningRow(p);
    }
    if (p.type === "agent") {
      return agentLaunchCard(p);
    }
    if (p.type === "tool") {
      return toolRow(p);
    }
    if (p.type === "file") {
      return `<div class="mp-file">${t("fold.attach")} ${esc(p.mime || "")}</div>`;
    }
    return "";
  }).join("");
  // 本轮用时 = 助手消息全部 part 的起止时间跨度
  let turnDur = null;
  if (role.key === "assistant") {
    const t0s = parts.map(p => p.t0).filter(v => Number.isFinite(v));
    const t1s = parts.map(p => (p.t1 != null ? p.t1 : p.t0)).filter(v => Number.isFinite(v));
    if (t0s.length && t1s.length) turnDur = Math.max(...t1s) - Math.min(...t0s);
  }
  return `
  <div class="msg ${role.key}" data-mid="${esc(m.id)}">
    <div class="msg-head">
      <span class="msg-role">${esc(role.label)}</span>
      ${role.key === "assistant" && m.model ? `<span class="hint mono">${esc(m.model)}</span>` : ""}
      ${turnDur != null && turnDur >= 2000 ? `<span class="msg-dur">${t("tc.turn", fmtDur(turnDur))}</span>` : ""}
      ${m.error ? `<span class="badge live" title="${esc(m.error)}">出错</span>` : ""}
    </div>
    ${partsHtml || `<div class="hint">${t("fold.noText")}</div>`}
  </div>`;
}

/* 消息流渲染: 子代理"派发"卡片在调用位置, "已返回"卡片在其后第一条非助手消息处
   (即返回结果真正进入上下文的位置); 跨分页边界的调用可能缺返回卡, 属已知限制 */
function renderChatFlow(messages) {
  let html = "";
  let pending = [];
  for (const m of messages) {
    if (m.role !== "assistant") {
      for (const p of pending) html += agentReturnCard(p);
      pending = [];
      html += renderMsg(m);
      continue;
    }
    html += renderMsg(m);
    pending = pending.concat((m.parts || []).filter(p => p.type === "agent" && p.status === "completed"));
  }
  for (const p of pending) html += agentReturnCard(p);
  return html;
}

/* ---------------- 远端仓库 ---------------- */
async function loadRepo() {
  const src = document.querySelector('input[name="rsrc"]:checked')?.value || "server";
  const box = $("#repo-box");
  let archives = [];
  if (src === "server" && !IS_CLIENT) {
    const r = await api("/api/archives");
    if (!r.ok) { box.innerHTML = `<div class="hint st-error" style="padding:6px 2px">服务器读取失败: ${esc(r.error || "")}</div>`; return; }
    archives = r.archives || [];
  } else if (src === "server") {
    // 客户端变体: 本源即 agent, "服务器仓库"经 agent 的 remote-list 读取配置的远端
    if (!AGENT) { box.innerHTML = emptyBox("本机未运行 agent"); return; }
    const r = await apiAgent("/api/remote/list", {
      method: "POST",
      body: { url: $("#set-remote-url").value.trim() || undefined,
              token: $("#set-remote-token").value.trim() || null },
    });
    if (!r.ok) { box.innerHTML = `<div class="hint st-error" style="padding:6px 2px">服务器读取失败: ${esc(r.error || "")} (检查「客户端设置」中的服务器地址)</div>`; return; }
    archives = r.archives || [];
  } else {
    if (!AGENT) { box.innerHTML = emptyBox("本机未运行 agent, 无本机存档库"); return; }
    const r = await apiAgent("/api/archives");
    if (!r.ok) { box.innerHTML = `<div class="hint st-error" style="padding:6px 2px">本机存档库读取失败: ${esc(r.error || "")}</div>`; return; }
    archives = r.archives || [];
  }
  REPO_ARCHIVES = archives;
  REPO_SRC = src;
  renderRepo();
  loadLocalArchives();
}
let REPO_SRC = "server";

function renderRepo() {
  const box = $("#repo-box");
  if (!REPO_ARCHIVES.length) {
    box.innerHTML = emptyBox("仓库中暂无存档<br>在「项目备份」页备份本机项目即可上传");
    return;
  }
  const q = ($("#repo-filter")?.value || "").trim().toLowerCase();
  const list = q ? REPO_ARCHIVES.filter(a => {
    const src = a.source || {};
    return [a.archive_id, src.project_path, src.hostname, a.label]
      .some(v => String(v || "").toLowerCase().includes(q));
  }) : REPO_ARCHIVES;
  if (!list.length) {
    box.innerHTML = `<div class="hint" style="padding:14px 4px">${t("remote.noMatch", $("#repo-filter").value.trim())}</div>`;
    return;
  }
  box.innerHTML = list.map(a => {
    const src = a.source || {};
    const comps = a.components || {};
    const badges = COMP_DEFS.filter(c => comps[c.key]).map(c => `<span class="badge on">${t("comp." + c.key + ".l")}</span>`).join("");
    return `<div class="repo-item${SELECTED?.id === a.archive_id ? " selected" : ""}" data-aid="${esc(a.archive_id)}">
      <div class="ri-main">
        <div class="ri-name" title="${esc(a.archive_id)}">${esc(a.archive_id)}</div>
        <div class="ri-meta">${esc(src.project_path || "")} · ${esc(src.hostname || "")} · ${fmtTime(a.updated_at)}</div>
      </div>
      <div class="ri-stats">
        <span class="mstat">会话 <b>${a.stats?.sessions ?? "?"}</b></span>
        <span class="mstat">大小 <b>${fmtBytes(a.ztar_bytes ?? a.total_bytes)}</b></span>
      </div>
      <div class="ri-badges">${badges}</div>
      <button class="ok mini" data-restore="${esc(a.archive_id)}">拉取恢复…</button>
    </div>`;
  }).join("");
  box.querySelectorAll("[data-restore]").forEach(b => b.addEventListener("click", () => selectArchive(b.dataset.restore)));
}

function selectArchive(aid) {
  SELECTED = { id: aid, info: REPO_ARCHIVES.find(a => a.archive_id === aid), src: REPO_SRC };
  $$(".repo-item").forEach(el => el.classList.toggle("selected", el.dataset.aid === aid));
  const info = SELECTED.info || {};
  $("#restore-card").style.display = "";
  $("#rv-name").textContent = aid;
  $("#rv-meta").innerHTML =
    `源: ${esc((info.source || {}).project_path || "?")} · 会话 ${info.stats?.sessions ?? "?"} · ${fmtBytes(info.ztar_bytes)} · CLI ${(info.source || {}).zcode_cli_version || "?"}`;
  $("#target-path").value = (info.source || {}).project_path || "";
  $("#rv-zhome").textContent = AGENT?.state?.local?.zcode_home || "(本机未接入 agent)";
  const comps = info.components || {};
  $("#restore-components").innerHTML =
    `<div class="grp">项目级</div>` +
    COMP_DEFS.filter(c => !GLOBAL_KEYS.includes(c.key)).map(c => rcompCb(c, comps)).join("") +
    `<div class="grp">全局级</div>` +
    COMP_DEFS.filter(c => GLOBAL_KEYS.includes(c.key)).map(c => rcompCb(c, comps)).join("");
}

function rcompCb(c, comps) {
  const has = !!comps[c.key];
  return `<label class="comp${has ? "" : " off"}">
    <input type="checkbox" data-rcomp="${c.key}" ${has ? "checked" : ""} ${has ? "" : "disabled"}>
    <span>${t("comp." + c.key + ".l")}</span><small class="comp-desc">${has ? t("comp." + c.key + ".d") : t("rcomp.absent")}</small></label>`;
}

$$('input[name="rsrc"]').forEach(r => r.addEventListener("change", loadRepo));
$("#btn-load-repo").addEventListener("click", loadRepo);
$("#repo-filter").addEventListener("input", renderRepo);

$("#btn-restore").addEventListener("click", async () => {
  if (!SELECTED) return;
  if (!AGENT) return notify("本机未运行客户端 agent, 无法恢复到本机", "err");
  const target = $("#target-path").value.trim();
  if (!(/^[a-zA-Z]:[\\/]/.test(target) || target.startsWith("/")))
    return notify("目标路径需为绝对路径, 如 D:\\Project\\xxx", "err");
  if (!confirm(`把 ${SELECTED.id} 恢复到 ${target}?\n(将写入本机 zcode: ${AGENT.state.local.zcode_home}, 请先退出 zcode)`)) return;
  const components = {};
  $$("[data-rcomp]").forEach(cb => components[cb.dataset.rcomp] = cb.checked);
  const body = { archive_id: SELECTED.id, target_path: target, components };
  if (SELECTED.src === "server") {
    // 服务器变体: 远端=本页服务器; 客户端变体: 远端=设置页配置的服务器
    const rurl = IS_CLIENT ? ($("#set-remote-url").value.trim() || AGENT.state.remote?.url) : SERVER;
    body.remote = { url: rurl, archive_id: SELECTED.id };
    if (REMOTE_TOKEN) body.remote.token = REMOTE_TOKEN;
  }
  const r = await apiAgent("/api/restore", { method: "POST", body });
  if (r.ok) trackJob(r.job_id, `恢复 ${SELECTED.id}`, AGENT.base);
  else notify("恢复失败: " + (r.error || "?"), "err");
});

$("#btn-vmpkg").addEventListener("click", async () => {
  if (!SELECTED) return;
  if (IS_CLIENT) return notify("免 Python 迁移包请在服务器 Web 界面构建(客户端不直接读服务器存档)", "err");
  if (SELECTED.src !== "server") return notify("免Python迁移包基于服务器存档构建, 请在「服务器仓库」来源下选择", "err");
  const target = $("#target-path").value.trim() || prompt("目标机器上的项目路径:", (SELECTED.info?.source || {}).project_path || "");
  if (!target) return;
  const r = await api("/api/vmpkg", { method: "POST", body: { archive_id: SELECTED.id, target_path: target } });
  if (r.ok) trackJob(r.job_id, `迁移包 ${SELECTED.id}`, SERVER);
  else notify("构建失败: " + (r.error || "?"), "err");
});

/* ---------------- 设置(作用于本机 agent) ---------------- */
$("#btn-detect-zhome").addEventListener("click", () => {
  $("#set-zhome").value = $("#set-zhome-default").value || "";
});

$("#btn-save-settings").addEventListener("click", async () => {
  if (!AGENT) return notify("本机未运行客户端 agent", "err");
  REMOTE_TOKEN = $("#set-remote-token").value.trim();
  localStorage.setItem("zsync_remote_token", REMOTE_TOKEN);
  const body = {
    zcode_home: $("#set-zhome").value.trim() || undefined,
    remote_url: $("#set-remote-url").value.trim(),
    remote_token: REMOTE_TOKEN,
  };
  const r = await apiAgent("/api/settings", { method: "POST", body });
  if (r.ok) {
    AGENT.state = await apiAgent("/api/state");
    $("#first-visit-hint").style.display = "none";
    renderStateLine();
    notify("设置已保存", "ok");
    await init();
  } else notify("保存失败: " + (r.error || "?"), "err");
});

$("#btn-test-remote").addEventListener("click", async () => {
  if (!AGENT) return;
  $("#remote-status").className = "hint";
  $("#remote-status").textContent = "连接中…";
  const r = await apiAgent("/api/remote/list", {
    method: "POST",
    body: { url: $("#set-remote-url").value.trim() || undefined,
            token: $("#set-remote-token").value.trim() || null },
  });
  $("#remote-status").className = "hint " + (r.ok ? "st-done" : "st-error");
  $("#remote-status").textContent = r.ok
    ? `✓ 连接成功, 远端有 ${r.archives.length} 个存档`
    : "✗ " + (r.error || "连接失败");
});

async function loadLocalArchives() {
  const box = $("#local-archives-box");
  if (!AGENT) { box.innerHTML = emptyBox("本机未运行 agent"); return; }
  const r = await apiAgent("/api/archives");
  const arcs = r.archives || [];
  if (!arcs.length) { box.innerHTML = emptyBox("本机存档库为空"); return; }
  box.innerHTML = arcs.map(a => `<div class="repo-item" data-aid="${esc(a.archive_id)}">
      <div class="ri-main">
        <div class="ri-name" title="${esc(a.archive_id)}">${esc(a.archive_id)}</div>
        <div class="ri-meta">${esc((a.source || {}).project_path || "")} · ${fmtTime(a.updated_at)}</div>
      </div>
      <div class="ri-stats"><span class="mstat">大小 <b>${fmtBytes(a.ztar_bytes)}</b></span></div>
      <button class="ghost mini" data-dl="${esc(a.archive_id)}">下载</button>
      <button class="ghost mini" data-push="${esc(a.archive_id)}">推送远端</button>
      <button class="danger mini" data-del="${esc(a.archive_id)}">删除</button>
    </div>`).join("");
  box.querySelectorAll("[data-dl]").forEach(b => b.addEventListener("click", () =>
    window.open(AGENT.base + `/api/archives/${encodeURIComponent(b.dataset.dl)}/download`, "_blank")));
  box.querySelectorAll("[data-push]").forEach(b => b.addEventListener("click", async () => {
    const body = { archive_id: b.dataset.push };
    if (AGENT.kind !== "self") { body.url = $("#set-remote-url").value.trim() || SERVER; if (REMOTE_TOKEN) body.token = REMOTE_TOKEN; }
    const r2 = await apiAgent("/api/push", { method: "POST", body });
    if (r2.ok) trackJob(r2.job_id, `推送 ${b.dataset.push}`, AGENT.base);
    else notify(r2.error || "推送失败", "err");
  }));
  box.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
    if (!confirm(`删除本机存档 ${b.dataset.del}?`)) return;
    await apiAgent(`/api/archives/${encodeURIComponent(b.dataset.del)}/delete`, { method: "POST", body: {} });
    loadLocalArchives();
  }));
}

/* ---------------- 任务/日志 ---------------- */
/* 服务器变体: 双列(agent + 服务器); 客户端变体: 驱动底部抽屉(仅客户端) */
async function loadJobs() {
  if (IS_CLIENT) {
    const r = await apiAgent("/api/jobs").catch(() => null);
    const jobs = (r?.jobs || []).slice(0, 12);
    const lr = await apiAgent("/api/logs").catch(() => null);
    const logs = (lr?.logs || []).join("\n");
    $("#ld-jobs").innerHTML = renderJobs(jobs) || `<div class="hint" style="padding:8px 2px">${t("ld.none")}</div>`;
    $("#ld-logs").textContent = logs || "-";
    const j = jobs[0];
    $("#ld-summary").textContent = j
      ? `${j.label} · ${j.phase || ""} ${j.percent.toFixed(0)}%${j.status === "done" ? " ✓" : j.status === "error" ? " ✗" : ""}`
      : t("ld.none");
    return;
  }
  // 客户端任务
  if (AGENT) {
    const r = await apiAgent("/api/jobs").catch(() => null);
    const jobs = (r?.jobs || []).slice(0, 12);
    $("#jobs-agent-box").innerHTML = renderJobs(jobs) || emptyBox("暂无任务");
    const lr = await apiAgent("/api/logs").catch(() => null);
    $("#logs-agent-box").textContent = (lr?.logs || []).join("\n");
  } else {
    $("#jobs-agent-box").innerHTML = emptyBox("本机未运行 agent");
    $("#logs-agent-box").textContent = "";
  }
  // 服务器任务
  const sr = await api("/api/jobs").catch(() => null);
  $("#jobs-server-box").innerHTML = renderJobs((sr?.jobs || []).slice(0, 12)) || emptyBox("暂无任务");
  const slr = await api("/api/logs").catch(() => null);
  $("#logs-server-box").textContent = (slr?.logs || []).join("\n");
}

/* 底部抽屉: 默认收起, 点击切换; 展开时沿用既有 3s 轮询刷新 */
$("#ld-toggle").addEventListener("click", () => {
  const d = $("#log-drawer");
  d.classList.toggle("open");
  const open = d.classList.contains("open");
  $("#ld-body").classList.toggle("hidden", !open);
  $("#ld-toggle").setAttribute("aria-expanded", open);
  if (open) loadJobs();
});

function renderJobs(jobs) {
  return jobs.map(j => `
    <div class="job-item">
      <div class="job-top">
        <span class="job-label" title="${esc(j.label)}">${esc(j.label)}</span>
        <span class="st-pill st-${j.status}">${j.status === "done" ? "完成" : j.status === "error" ? "失败" : j.percent.toFixed(0) + "%"}</span>
      </div>
      <div class="bar"><div class="${j.status}" style="width:${j.percent}%"></div></div>
      <div class="meta">${esc(j.phase)} · ${j.percent.toFixed(0)}% ${esc(j.detail || "")}</div>
      ${j.error ? `<div class="meta st-error">${esc(j.error.split("\n")[0])}</div>` : ""}
    </div>`).join("");
}

/* ---------------- 任务浮层 ---------------- */
let trackTimer = null;
$("#jf-close").addEventListener("click", () => {
  $("#job-float").classList.add("hidden");
  if (trackTimer) { clearInterval(trackTimer); trackTimer = null; }
});
function trackJob(jobId, title, base = "") {
  $("#job-float").classList.remove("hidden");
  $("#jf-title").textContent = title;
  $("#jf-fill").style.background = "";
  if (trackTimer) clearInterval(trackTimer);
  const tick = async () => {
    const j = await fetchJSON(base + `/api/jobs/${jobId}`).catch(() => null);
    if (!j) return;
    $("#jf-fill").style.width = (j.percent || 0) + "%";
    $("#jf-detail").textContent = `${j.phase || ""} ${(j.percent || 0).toFixed(0)}% ${j.detail || ""}`;
    if (j.status === "done") {
      $("#jf-fill").style.width = "100%";
      $("#jf-detail").textContent = "完成 ✓ " + JSON.stringify(j.result?.restore?.verify || j.result?.stats || "").slice(0, 120);
      clearInterval(trackTimer); trackTimer = null;
      setTimeout(() => $("#job-float").classList.add("hidden"), 8000);
    } else if (j.status === "error") {
      $("#jf-fill").style.background = "var(--red)";
      $("#jf-detail").textContent = "失败: " + (j.error || "").split("\n")[0];
      clearInterval(trackTimer); trackTimer = null;
    }
  };
  trackTimer = setInterval(tick, 900);
  tick();
}

init();
