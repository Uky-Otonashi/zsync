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

const SERVER = window.location.origin;   // 中央服务器(即提供本页面的服务器)
const AGENT_PORTS = [8643, 8642];        // 本机 agent 探测候选(后者兼容本机跑完整节点)

let STATE = null;      // 服务器 /api/state
let AGENT = null;      // {base, state} —— base 为 "" 表示即本源(旧单机模式)
let PROJECTS = [];
let REPO_ARCHIVES = [];     // 当前仓库来源(服务器或本机存档库)的存档
let SELECTED = null;        // 选中的存档 {archive_id, info, src}
let projComps = {};         // project_id -> components(编辑态)
let ftState = { projectId: null, filter: null, open: {} };
let REMOTE_TOKEN = localStorage.getItem("zsync_remote_token") || "";

const COMP_DEFS = [
  { key: "sessions", label: "会话数据", desc: "完整上下文/思考/轨迹 + 会话列表索引" },
  { key: "rollout", label: "模型原始轨迹", desc: "model-io jsonl, 可能很大" },
  { key: "artifacts", label: "工具产物", desc: "截图/生成文件" },
  { key: "agents", label: "子代理数据", desc: "agent 会话目录" },
  { key: "exec_logs", label: "执行日志", desc: "工具调用日志" },
  { key: "memory", label: "项目记忆", desc: "MEMORY.md 等" },
  { key: "source", label: "项目源码 + git", desc: "按文件筛选规则" },
  { key: "include_git", label: "包含 .git", desc: "git 历史" },
  { key: "global_skills", label: "全局技能", desc: "skills/" },
  { key: "global_constraints", label: "全局约束", desc: "AGENTS.md 等" },
  { key: "global_plugins", label: "插件开关", desc: "cli/config.json" },
  { key: "global_agents_md", label: "全局代理定义", desc: "agents/*.md" },
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
function apiAgent(path, opts = {}) {
  if (!AGENT) return Promise.resolve({ ok: false, error: "本机未运行客户端 agent" });
  return fetchJSON(AGENT.base + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
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
      if (j && j.ok && (j.mode === "agent" || j.mode === "node")) {
        return { base, state: j, kind: j.mode };
      }
    } catch (e) { /* 端口无响应, 继续探测 */ }
  }
  // 旧单机模式: 经 loopback 直接访问完整节点, 节点即本机
  if (loopback && STATE && STATE.mode === "node") {
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
  AGENT = await detectAgent();
  renderStateLine();

  const guide = $("#agent-guide");
  if (!AGENT) {
    guide.style.display = "";
    $("#guide-tool-url").textContent = SERVER + "/tool.zip";
    $("#projects-box").innerHTML = "";
    $("#local-banner").innerHTML =
      `<span style="color:var(--danger)">本机尚未接入:</span> 下方步骤启动本机客户端 agent 后, 此页将自动加载本机 zcode 项目。`;
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
  const parts = [`服务器: ${STATE?.server?.hostname || "?"} · 存档 ${STATE?.archives_count ?? "?"}`];
  if (AGENT) {
    const l = AGENT.state.local || {};
    parts.unshift(`客户端: ${l.hostname || "?"} · ${l.zcode_home || "?"} · DB ${l.db_exists ? "OK" : "缺失"}`);
  } else {
    parts.unshift("客户端: 未接入");
  }
  $("#state-line").textContent = parts.join("  |  ");
}

function switchTab(name) {
  $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".panel").forEach(p => p.classList.toggle("active", p.id === "tab-" + name));
  if (name === "backup") loadProjects();
  if (name === "remote") loadRepo();
  if (name === "settings") loadLocalArchives();
}
$$(".tab").forEach(btn => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));

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
    card.className = "card";
    card.innerHTML = `
      <div class="pcard-head">
        <div class="pcard-name" title="${esc(p.project_id)}">${esc(p.name)}</div>
        ${w ? '<span class="badge live">实时备份中</span>' : ""}
        ${ghost ? '<span class="badge ghost">已移出侧边栏 · 数据完整</span>' : ""}
      </div>
      <div class="pcard-path" title="${esc(p.path)}">${esc(p.path || p.project_id)}</div>
      <div class="pcard-meta">
        <span>会话 <b>${p.sessions}</b>${partial ? ` <small>(列表 ${p.in_sidebar})</small>` : ""}</span>
        <span>轨迹 <b>${fmtBytes(p.rollout_bytes)}</b></span>
        <span>记忆 <b>${p.memory_files}</b></span>
        <span>CLI <b>${(p.versions || []).slice(-1)[0] || "?"}</b></span>
      </div>
      <details><summary class="hint" style="cursor:pointer">备份内容</summary>
        <div class="comp-grid" data-pid="${esc(p.project_id)}">
          <div class="grp">项目级</div>
          ${COMP_DEFS.filter(c => !GLOBAL_KEYS.includes(c.key)).map(c => compCb(p.project_id, c, comps)).join("")}
          <div class="grp">全局级(可选, 随包分发)</div>
          ${COMP_DEFS.filter(c => GLOBAL_KEYS.includes(c.key)).map(c => compCb(p.project_id, c, comps)).join("")}
        </div>
      </details>
      <div class="switch-row">
        <button class="primary" data-act="build">立即备份并推送</button>
        <button class="ghost" data-act="filter">源码筛选…</button>
        <div class="switch ${w ? "on" : ""}" data-act="watch"></div>
        <span class="switch-label">实时备份 <small>${w ? `已重建 ${w.rebuilds} 次` : ""}</small></span>
      </div>`;
    card.querySelectorAll("[data-comp]").forEach(cb => cb.addEventListener("change", () => {
      projComps[p.project_id][cb.dataset.comp] = cb.checked;
      apiAgent("/api/project-config", { method: "POST", body: { project_id: p.project_id, components: projComps[p.project_id] } });
    }));
    card.querySelector('[data-act="build"]').addEventListener("click", () => doBuild(p));
    card.querySelector('[data-act="filter"]').addEventListener("click", () => openFileTree(p));
    card.querySelector('[data-act="watch"]').addEventListener("click", () => doWatchToggle(p));
    box.appendChild(card);
  }
  if (!list.length) box.innerHTML = `<div class="hint">本机没有匹配的 zcode 项目(检查客户端设置中的 zcode 目录)</div>`;
}

function compCb(pid, c, comps) {
  return `<label><input type="checkbox" data-comp="${c.key}" ${comps[c.key] ? "checked" : ""}> ${c.label} <small>${c.desc}</small></label>`;
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
  else alert("备份失败: " + (r.error || "?"));
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
    (isRoot ? "" : `<div class="ft-row ft-dir" data-rel="${esc(rel.split("/").slice(0, -1).join("/"))}">📁 .. 返回上级</div>`) +
    (entries.length ? entries.map(e => {
      const mark = e.ignored ? '<span class="ft-mark ignored">忽略</span>' : "";
      return `<div class="ft-row ${e.ignored ? "dim" : ""}" data-rel="${esc(e.rel)}" data-type="${e.type}">
        ${e.type === "dir" ? "📁" : "📄"}
        <span class="ft-name">${esc(e.name)}</span>
        ${e.type === "dir" && e.ignored ? "" : `<span class="ft-size">${fmtBytes(e.size)}</span>`}
        ${mark}
        <span class="ft-actions">
          <button class="ghost mini" data-ignore="${esc(e.rel)}">排除</button>
          <button class="ghost mini" data-include="${esc(e.rel)}">强制包含</button>
        </span>
      </div>`;
    }).join("") : '<div class="hint" style="padding:6px">空目录</div>');
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
  const extra = (f.extra_ignores || []).map(x => `<span class="badge">✕ ${esc(x)} <a href="#" data-del="extra_ignores:${esc(x)}" style="color:#e08585">删</a></span>`).join("");
  const forced = (f.forced_includes || []).map(x => `<span class="badge on">✓ ${esc(x)} <a href="#" data-del="forced_includes:${esc(x)}" style="color:#e08585">删</a></span>`).join("");
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
$("#modal-close").addEventListener("click", () => $("#modal").classList.add("hidden"));

/* ---------------- 远端仓库 ---------------- */
async function loadRepo() {
  const src = document.querySelector('input[name="rsrc"]:checked')?.value || "server";
  const box = $("#repo-box");
  let archives = [];
  if (src === "server") {
    const r = await api("/api/archives");
    if (!r.ok) { box.innerHTML = `<div class="hint" style="color:var(--danger)">服务器读取失败: ${esc(r.error || "")}</div>`; return; }
    archives = r.archives || [];
  } else {
    if (!AGENT) { box.innerHTML = `<div class="hint">本机未运行 agent, 无本机存档库</div>`; return; }
    const r = await apiAgent("/api/archives");
    if (!r.ok) { box.innerHTML = `<div class="hint" style="color:var(--danger)">本机存档库读取失败: ${esc(r.error || "")}</div>`; return; }
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
    box.innerHTML = `<div class="hint">仓库中暂无存档 —— 在「项目备份」页备份本机项目即可上传</div>`;
    return;
  }
  box.innerHTML = REPO_ARCHIVES.map(a => {
    const src = a.source || {};
    const comps = a.components || {};
    const badges = COMP_DEFS.filter(c => comps[c.key]).map(c => `<span class="badge on">${c.label}</span>`).join("");
    return `<div class="repo-item" data-aid="${esc(a.archive_id)}">
      <span class="ri-name">${esc(a.archive_id)}</span>
      <span class="ri-meta">${esc(src.project_path || "")} · 会话${a.stats?.sessions ?? "?"} · ${fmtBytes(a.ztar_bytes ?? a.total_bytes)} · ${fmtTime(a.updated_at)} · ${esc(src.hostname || "")}</span>
      <span>${badges}</span>
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
  $("#restore-components").innerHTML = COMP_DEFS.map(c => {
    const has = !!comps[c.key];
    return `<label style="${has ? "" : "opacity:.4"}">
      <input type="checkbox" data-rcomp="${c.key}" ${has ? "checked" : ""} ${has ? "" : "disabled"}>
      ${c.label} <small>${has ? c.desc : "存档未包含"}</small></label>`;
  }).join("");
}

$$('input[name="rsrc"]').forEach(r => r.addEventListener("change", loadRepo));
$("#btn-load-repo").addEventListener("click", loadRepo);

$("#btn-restore").addEventListener("click", async () => {
  if (!SELECTED) return;
  if (!AGENT) return alert("本机未运行客户端 agent, 无法恢复到本机");
  const target = $("#target-path").value.trim();
  if (!(/^[a-zA-Z]:[\\/]/.test(target) || target.startsWith("/")))
    return alert("目标路径需为绝对路径, 如 D:\\Project\\xxx");
  if (!confirm(`把 ${SELECTED.id} 恢复到 ${target}?\n(将写入本机 zcode: ${AGENT.state.local.zcode_home}, 请先退出 zcode)`)) return;
  const components = {};
  $$("[data-rcomp]").forEach(cb => components[cb.dataset.rcomp] = cb.checked);
  const body = { archive_id: SELECTED.id, target_path: target, components };
  if (SELECTED.src === "server") body.remote = { url: SERVER, archive_id: SELECTED.id };
  const r = await apiAgent("/api/restore", { method: "POST", body });
  if (r.ok) trackJob(r.job_id, `恢复 ${SELECTED.id}`, AGENT.base);
  else alert("恢复失败: " + (r.error || "?"));
});

$("#btn-vmpkg").addEventListener("click", async () => {
  if (!SELECTED) return;
  if (SELECTED.src !== "server") return alert("免Python迁移包基于服务器存档构建, 请在「服务器仓库」来源下选择");
  const target = $("#target-path").value.trim() || prompt("目标机器上的项目路径:", (SELECTED.info?.source || {}).project_path || "");
  if (!target) return;
  const r = await api("/api/vmpkg", { method: "POST", body: { archive_id: SELECTED.id, target_path: target } });
  if (r.ok) trackJob(r.job_id, `迁移包 ${SELECTED.id}`, SERVER);
  else alert("构建失败: " + (r.error || "?"));
});

/* ---------------- 设置(作用于本机 agent) ---------------- */
$("#btn-detect-zhome").addEventListener("click", () => {
  $("#set-zhome").value = $("#set-zhome-default").value || "";
});

$("#btn-save-settings").addEventListener("click", async () => {
  if (!AGENT) return alert("本机未运行客户端 agent");
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
    await init();
  } else alert("保存失败: " + (r.error || "?"));
});

$("#btn-test-remote").addEventListener("click", async () => {
  if (!AGENT) return;
  $("#remote-status").textContent = "连接中…";
  const r = await apiAgent("/api/remote/list", {
    method: "POST",
    body: { url: $("#set-remote-url").value.trim() || undefined,
            token: $("#set-remote-token").value.trim() || null },
  });
  $("#remote-status").textContent = r.ok
    ? `✓ 连接成功, 远端有 ${r.archives.length} 个存档`
    : "✗ " + (r.error || "连接失败");
});

async function loadLocalArchives() {
  const box = $("#local-archives-box");
  if (!AGENT) { box.innerHTML = `<div class="hint">本机未运行 agent</div>`; return; }
  const r = await apiAgent("/api/archives");
  const arcs = r.archives || [];
  if (!arcs.length) { box.innerHTML = `<div class="hint">本机存档库为空</div>`; return; }
  box.innerHTML = arcs.map(a => `<div class="repo-item" data-aid="${esc(a.archive_id)}">
      <span class="ri-name">${esc(a.archive_id)}</span>
      <span class="ri-meta">${esc((a.source || {}).project_path || "")} · ${fmtBytes(a.ztar_bytes)} · ${fmtTime(a.updated_at)}</span>
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
    else alert(r2.error || "推送失败");
  }));
  box.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
    if (!confirm(`删除本机存档 ${b.dataset.del}?`)) return;
    await apiAgent(`/api/archives/${encodeURIComponent(b.dataset.del)}/delete`, { method: "POST", body: {} });
    loadLocalArchives();
  }));
}

/* ---------------- 任务/日志(agent + 服务器 双端) ---------------- */
async function loadJobs() {
  // 客户端任务
  if (AGENT) {
    const r = await apiAgent("/api/jobs").catch(() => null);
    const jobs = (r?.jobs || []).slice(0, 12);
    $("#jobs-agent-box").innerHTML = renderJobs(jobs) || `<div class="hint">暂无任务</div>`;
    const lr = await apiAgent("/api/logs").catch(() => null);
    $("#logs-agent-box").textContent = (lr?.logs || []).join("\n");
  } else {
    $("#jobs-agent-box").innerHTML = `<div class="hint">本机未运行 agent</div>`;
    $("#logs-agent-box").textContent = "";
  }
  // 服务器任务
  const sr = await api("/api/jobs").catch(() => null);
  $("#jobs-server-box").innerHTML = renderJobs((sr?.jobs || []).slice(0, 12)) || `<div class="hint">暂无任务</div>`;
  const slr = await api("/api/logs").catch(() => null);
  $("#logs-server-box").textContent = (slr?.logs || []).join("\n");
}

function renderJobs(jobs) {
  return jobs.map(j => `
    <div class="job-item">
      <div>${esc(j.label)} <span class="st-${j.status}">${j.status === "done" ? "✓ 完成" : j.status === "error" ? "✗ 失败" : "…"}</span></div>
      <div class="bar"><div class="${j.status}" style="width:${j.percent}%"></div></div>
      <div class="meta">${esc(j.phase)} ${j.percent.toFixed(0)}% ${esc(j.detail || "")}</div>
      ${j.error ? `<div class="meta st-error">${esc(j.error.split("\n")[0])}</div>` : ""}
    </div>`).join("");
}

/* ---------------- 任务浮层 ---------------- */
let trackTimer = null;
function trackJob(jobId, title, base = "") {
  $("#job-float").classList.remove("hidden");
  $("#jf-title").textContent = title;
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
      $("#jf-detail").textContent = "失败: " + (j.error || "").split("\n")[0];
      clearInterval(trackTimer); trackTimer = null;
    }
  };
  trackTimer = setInterval(tick, 900);
  tick();
}

init();
