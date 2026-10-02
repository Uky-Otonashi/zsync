"""项目详情只读探测: git 状态 / 会话内容 / 模型调用轨迹。

全部操作只读:
  - db 经 zclayout.open_ro(mode=ro, 锁定时回退快照副本), 绝不写入;
  - git 仅执行探测类命令(rev-parse/branch/status/log/remote), 不联网;
    联网 fetch 由 UI 显式触发且只更新 remote-tracking 引用, 不碰工作区;
  - 文件浏览走已有 /api/filetree, 此处不重复实现。
"""
from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

from . import zclayout

# 模型调用轨迹摘要的进程内缓存: sid -> (mtime, size, [call, ...])
_TRACE_CACHE: dict[str, tuple[float, int, list]] = {}
_TRACE_CACHE_MAX = 8
_SYSTEM_CACHE: dict[str, tuple[float, int, dict]] = {}

_GIT_TIMEOUT = 10  # 单命令秒数; 大仓 status/log 可能较慢

# part 文本截断上限(防止读文件类 tool 输出把响应撑爆)
TEXT_LIMIT = 8000
TOOL_INPUT_LIMIT = 1500
TOOL_OUTPUT_LIMIT = 4000


def _git(path: str, *args: str) -> tuple[int, str]:
    """运行 git 探测命令, 返回 (returncode, stdout)。任何失败返回 (非0, '')。"""
    try:
        p = subprocess.run(
            ["git", "-C", path, *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_GIT_TIMEOUT,
        )
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def _truncate(s: str, limit: int) -> tuple[str, bool]:
    if s is None:
        return "", False
    s = str(s)
    if len(s) <= limit:
        return s, False
    return s[:limit] + f"…[+{len(s) - limit} 字符]", True


def probe_git(path: str) -> dict:
    """探测项目目录的 git 状态(并行, 不联网)。"""
    out: dict = {"is_repo": False}
    if not path or not os.path.isdir(path):
        return out
    with ThreadPoolExecutor(max_workers=6) as ex:
        fns = {
            "top": ex.submit(_git, path, "rev-parse", "--show-toplevel"),
            "branch": ex.submit(_git, path, "branch", "--show-current"),
            "upstream": ex.submit(_git, path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"),
            "ab": ex.submit(_git, path, "rev-list", "--left-right", "--count", "@{u}...HEAD"),
            "status": ex.submit(_git, path, "status", "--porcelain"),
            "log": ex.submit(_git, path, "log", "-10", "--pretty=%H%x1f%an%x1f%at%x1f%s"),
            "remote": ex.submit(_git, path, "remote", "-v"),
        }
    if fns["top"].result()[0] != 0:
        return out
    out["is_repo"] = True
    out["toplevel"] = fns["top"].result()[1]
    out["branch"] = fns["branch"].result()[1] or "(detached)"

    rc, ups = fns["upstream"].result()
    if rc == 0 and ups:
        out["upstream"] = ups
        rc2, ab = fns["ab"].result()
        if rc2 == 0 and ab:
            left, _, right = ab.partition("\t")
            try:
                out["behind"], out["ahead"] = int(left), int(right)
            except ValueError:
                pass
    else:
        out["upstream"] = None

    staged = dirty = untracked = 0
    for line in fns["status"].result()[1].splitlines():
        if not line.strip():
            continue
        x, y = line[0], line[1] if len(line) > 1 else " "
        if x == "?":
            untracked += 1
        elif x not in (" ", "?"):
            staged += 1
        if y not in (" ", "?") :
            dirty += 1
    out["changes"] = {"staged": staged, "unstaged": dirty, "untracked": untracked,
                      "total": staged + dirty + untracked}

    commits = []
    for line in fns["log"].result()[1].splitlines():
        h, an, at, subj = (line.split("\x1f", 3) + ["", "", "", ""])[:4]
        if h:
            commits.append({"hash": h[:9], "author": an, "time": int(at) * 1000 if at else None,
                            "subject": subj})
    out["recent_commits"] = commits

    remotes: dict[str, str] = {}
    for line in fns["remote"].result()[1].splitlines():
        parts = line.split()
        if len(parts) >= 2 and "(fetch)" == parts[-1]:
            remotes[parts[0]] = parts[1]
    out["remotes"] = remotes
    out["note"] = "ahead/behind 基于本地缓存的远端引用, 未联网 fetch"
    return out


def fetch_remote(path: str, timeout: int = 60) -> dict:
    """显式联网 git fetch: 只更新 remote-tracking 引用, 不碰工作区/本地分支。"""
    try:
        p = subprocess.run(
            ["git", "-C", path, "fetch", "--all", "--quiet"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        if p.returncode != 0:
            return {"ok": False, "error": (p.stderr or p.stdout or "fetch 失败").strip()[:500]}
        return {"ok": True}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"git fetch 执行失败: {e}"}


def project_sessions(layout: zclayout.ZcodeLayout, project_id: str) -> list[dict] | None:
    """归属项目的全部会话(含派生 subagent), 附每会话消息数。"""
    if not layout.exists():
        return None
    con, tmp = zclayout.open_ro(layout.db_path)
    try:
        cur = con.cursor()
        sids = zclayout.project_session_ids(con, project_id)
        if not sids:
            return []
        owner = zclayout.session_owner_map(con)
        ph = ",".join("?" * len(sids))
        counts = {r[0]: r[1] for r in cur.execute(
            f"SELECT session_id, count(*) FROM message WHERE session_id IN ({ph}) "
            f"GROUP BY session_id", sids)}
        out = []
        for sid, parent, ttype, directory, title, tc, tu, version in cur.execute(
            f"SELECT id, parent_id, task_type, directory, title, time_created, "
            f"time_updated, version FROM session WHERE id IN ({ph})", sids):
            out.append({
                "id": sid, "title": title, "task_type": ttype,
                "is_subagent": ttype == "subagent_child",
                "parent_id": parent, "directory": directory,
                "time_created": tc, "time_updated": tu, "version": version,
                "messages": counts.get(sid, 0),
                "owner_pid": owner.get(sid),
            })
        out.sort(key=lambda s: s["time_updated"] or 0, reverse=True)
        return out
    finally:
        con.close()
        if tmp:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


def _part_view(d: dict) -> dict | None:
    t = d.get("type")
    if t == "text":
        txt, trunc = _truncate(d.get("text") or "", TEXT_LIMIT)
        return {"type": "text", "text": txt, "truncated": trunc}
    if t == "reasoning":
        txt, trunc = _truncate(d.get("text") or "", TEXT_LIMIT)
        return {"type": "reasoning", "text": txt, "truncated": trunc}
    if t == "tool":
        st = d.get("state") or {}
        if d.get("tool") == "Agent":
            # 子代理派发调用: 结构化展示(调用时机卡片 + 分屏入口)
            inp = st.get("input") or {}
            outp, otrunc = _truncate(st.get("output") or "", 2000)
            return {"type": "agent", "callID": d.get("callID"),
                    "status": st.get("status"),
                    "description": inp.get("description"),
                    "subagent_type": inp.get("subagent_type"),
                    "prompt": _truncate(inp.get("prompt") or "", 1500)[0],
                    "output": outp, "truncated": otrunc}
        try:
            inp = json.dumps(st.get("input"), ensure_ascii=False)
        except (TypeError, ValueError):
            inp = str(st.get("input"))
        inp, _ = _truncate(inp, TOOL_INPUT_LIMIT)
        outp, otrunc = _truncate(st.get("output") or "", TOOL_OUTPUT_LIMIT)
        return {"type": "tool", "tool": d.get("tool"), "status": st.get("status"),
                "callID": d.get("callID"),
                "input": inp, "output": outp, "truncated": otrunc}
    if t == "file":
        return {"type": "file", "mime": d.get("mime")}
    if t == "timeline":
        to_model = (d.get("toModel") or {}).get("modelID")
        info = str(d.get("timelineType") or "")
        if to_model:
            info = (info + " → " + to_model).strip(" →")
        return {"type": "timeline", "info": info}
    if t in ("step-start", "step-finish", "compaction"):
        return {"type": t}
    return None


def read_session(layout: zclayout.ZcodeLayout, sid: str,
                 offset_from_end: int = 0, limit: int = 150) -> dict | None:
    """读取会话内容(只读)。

    按 sequence 升序取「尾部第 offset_from_end 批」的 limit 条消息,
    供前端「加载更早」向上翻页; 返回 total 供前端判断是否还有更早消息。
    """
    if not layout.exists():
        return None
    con, tmp = zclayout.open_ro(layout.db_path)
    try:
        cur = con.cursor()
        row = cur.execute(
            "SELECT id, title, directory, task_type, parent_id, time_created, "
            "time_updated, version FROM session WHERE id=?", (sid,)).fetchone()
        if not row:
            return None
        session = {"id": row[0], "title": row[1], "directory": row[2],
                   "task_type": row[3], "parent_id": row[4],
                   "time_created": row[5], "time_updated": row[6], "version": row[7]}
        children = [
            {"id": r[0], "title": r[1], "directory": r[2], "time_updated": r[3],
             "time_created": r[4]}
            for r in cur.execute(
                "SELECT id, title, directory, time_updated, time_created FROM session "
                "WHERE parent_id=? ORDER BY time_updated", (sid,))
        ]
        if children:
            # 把子会话与派发它的 Agent 工具调用按时间就近配对(15 分钟窗口),
            # 供前端在主会话时间线上定位"调用点"并提供分屏入口
            calls: list[tuple[int, str]] = []
            for t_create, pdata in cur.execute(
                "SELECT time_created, data FROM part WHERE session_id=?", (sid,)):
                try:
                    pj = json.loads(pdata)
                except (ValueError, TypeError):
                    continue
                if pj.get("type") == "tool" and pj.get("tool") == "Agent":
                    calls.append((t_create or 0, pj.get("callID") or ""))
            calls.sort()
            used: set[str] = set()
            for ch in children:
                best = None
                best_diff = 15 * 60 * 1000
                for ct, cid in calls:
                    if not cid or cid in used:
                        continue
                    diff = abs((ch["time_created"] or 0) - ct)
                    if diff < best_diff:
                        best, best_diff = (ct, cid), diff
                if best:
                    used.add(best[1])
                    ch["agent_call"] = {"callID": best[1], "time": best[0]}
        total = cur.execute(
            "SELECT count(*) FROM message WHERE session_id=?", (sid,)).fetchone()[0]
        start = max(0, total - offset_from_end - limit)
        end = max(0, total - offset_from_end)
        rows = cur.execute(
            "SELECT id, data FROM message WHERE session_id=? ORDER BY sequence, "
            "time_created LIMIT ? OFFSET ?", (sid, end - start, start)).fetchall()
        mids = [r[0] for r in rows]
        parts_by_msg: dict[str, list] = {m: [] for m in mids}
        if mids:
            ph = ",".join("?" * len(mids))
            for pid, mid, data in cur.execute(
                f"SELECT id, message_id, data FROM part WHERE message_id IN ({ph}) "
                f"ORDER BY sequence, time_created", mids):
                try:
                    pv = _part_view(json.loads(data))
                except (ValueError, TypeError):
                    pv = None
                if pv:
                    parts_by_msg[mid].append(pv)
        messages = []
        for mid, data in rows:
            try:
                d = json.loads(data)
            except (ValueError, TypeError):
                d = {}
            err = (d.get("error") or {})
            model = d.get("modelId") or (d.get("model") or {}).get("modelID")
            sem = d.get("semantics") or {}
            messages.append({
                "id": mid, "role": d.get("role") or "?",
                "origin": sem.get("origin"), "kind": sem.get("kind"),
                "model": model, "tokens": d.get("tokens"),
                "error": err.get("data", {}).get("message") or err.get("name"),
                "parts": parts_by_msg.get(mid, []),
            })
        return {"session": session, "children": children, "messages": messages,
                "total_messages": total,
                "offset_from_end": offset_from_end, "limit": limit,
                "has_more": start > 0}
    finally:
        con.close()
        if tmp:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------- 模型调用轨迹(rollout/model-io jsonl, 只读) ----------------

def session_system(layout: zclayout.ZcodeLayout, sid: str) -> dict | None:
    """会话的系统提示词(rollout 每次调用都完整记录 request.body.system,
    含 skills/AGENTS.md 注入)。返回首末两个 main_turn 版本供对比。

    rollout 单行可达数十 MB(messages/response 巨大), 因此不做整行 json.loads:
    用子串筛出 main_turn 行, 在行首前缀中定位 "system": 并 raw_decode 其值,
    startedAt 从行尾切片提取。
    """
    path = os.path.join(layout.rollout_dir, f"model-io-{sid}.jsonl")
    if not os.path.isfile(path):
        return {"exists": False}
    st = os.stat(path)
    cached = _SYSTEM_CACHE.get(sid)
    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
        return cached[2]
    dec = json.JSONDecoder()

    def sys_from_line(line: str) -> list | None:
        # request.body.system 位于行首附近(request 在 response/messages 之前)
        for size in (262144, 4194304):
            prefix = line[:size]
            i = prefix.find('"system"')
            if i < 0:
                if len(line) <= size:
                    return None
                continue
            j = prefix.index(":", i) + 1
            while j < len(prefix) and prefix[j] in " \t":
                j += 1
            try:
                val, _ = dec.raw_decode(prefix, j)
                return val
            except ValueError:
                if len(line) <= size:
                    return None
        return None

    def at_from_line(line: str) -> str | None:
        tail = line[-400:]
        for tag in ('"startedAt": "', '"startedAt":"'):
            i = tail.find(tag)
            if i >= 0:
                return tail[i + len(tag):i + len(tag) + 40].split('"')[0]
        return None

    def blocks_of(sysv) -> list[str]:
        out = []
        if isinstance(sysv, list):
            for b in sysv:
                if isinstance(b, dict) and b.get("type") == "text":
                    out.append(b.get("text") or "")
                elif isinstance(b, str):
                    out.append(b)
        return out

    first = last = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if ('"querySource": "main_turn"' not in line
                    and '"querySource":"main_turn"' not in line):
                continue
            blocks = blocks_of(sys_from_line(line))
            if not blocks:
                continue
            snap = {"at": at_from_line(line), "chars": sum(len(b) for b in blocks),
                    "blocks": blocks}
            first = first or snap
            last = snap
    result = ({"exists": True, "first": first, "last": last,
               "changed": bool(first and last and first["chars"] != last["chars"])}
              if first else {"exists": False})
    if len(_SYSTEM_CACHE) >= _TRACE_CACHE_MAX:
        _SYSTEM_CACHE.pop(next(iter(_SYSTEM_CACHE)))
    _SYSTEM_CACHE[sid] = (st.st_mtime, st.st_size, result)
    return result


def _trace_summary_line(idx: int, j: dict) -> dict:
    resp = j.get("response") or {}
    usage = resp.get("usage") or {}
    tcs = resp.get("toolCalls") or []
    text = resp.get("text") or ""
    preview = text.strip()[:140] or (f"[{len(tcs)} 个工具调用] " +
        ", ".join(str(t.get("name") or "?") for t in tcs[:4]))
    return {
        "idx": idx,
        "startedAt": j.get("startedAt"),
        "durationMs": j.get("durationMs"),
        "attempt": j.get("attempt"),
        "model": (j.get("model") or {}).get("modelId"),
        "querySource": j.get("querySource"),
        "turnId": j.get("turnId"),
        "finishReason": resp.get("finishReason"),
        "tokens": {"in": usage.get("inputTokens"), "out": usage.get("outputTokens"),
                   "cacheRead": usage.get("cacheReadTokens")},
        "reqMessages": len(((j.get("request") or {}).get("body") or {}).get("messages") or []),
        "preview": preview,
    }


def session_trace_summary(layout: zclayout.ZcodeLayout, sid: str) -> dict | None:
    """模型调用轨迹摘要列表(带进程内缓存, 文件变化自动失效)。"""
    path = os.path.join(layout.rollout_dir, f"model-io-{sid}.jsonl")
    if not os.path.isfile(path):
        return {"calls": [], "exists": False}
    st = os.stat(path)
    cached = _TRACE_CACHE.get(sid)
    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
        return {"calls": cached[2], "exists": True}
    calls: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                calls.append(_trace_summary_line(idx, json.loads(line)))
            except (ValueError, TypeError):
                calls.append({"idx": idx, "error": "解析失败"})
    if len(_TRACE_CACHE) >= _TRACE_CACHE_MAX:
        _TRACE_CACHE.pop(next(iter(_TRACE_CACHE)))
    _TRACE_CACHE[sid] = (st.st_mtime, st.st_size, calls)
    return {"calls": calls, "exists": True}


def _msg_view(m: dict) -> dict:
    """请求消息的瘦身视图(role + 内容摘要, 尾部消息用)。"""
    content = m.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            if t == "text":
                parts.append(c.get("text") or "")
            elif t == "tool_result":
                s = str(c.get("content") or "")
                parts.append(f"[tool_result {s[:300]}]")
            elif t == "tool_use":
                parts.append(f"[tool_use {c.get('name')}: "
                             f"{json.dumps(c.get('input'), ensure_ascii=False)[:300]}]")
    body, trunc = _truncate("\n".join(p for p in parts if p), 1200)
    return {"role": m.get("role"), "content": body, "truncated": trunc}


def session_trace_detail(layout: zclayout.ZcodeLayout, sid: str, line_no: int) -> dict | None:
    """单次模型调用的详情(请求尾部消息 + 响应文本/工具调用, 大字段截断)。"""
    path = os.path.join(layout.rollout_dir, f"model-io-{sid}.jsonl")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f):
            if idx != line_no:
                continue
            j = json.loads(line)
            req = (j.get("request") or {}).get("body") or {}
            resp = j.get("response") or {}
            msgs = req.get("messages") or []
            tail = [_msg_view(m) for m in msgs[-6:]]
            system = req.get("system") or []
            sys_size = len(json.dumps(system, ensure_ascii=False)) if system else 0
            text, _ = _truncate(resp.get("text") or "", 6000)
            reasoning, _ = _truncate(resp.get("reasoningText") or "", 4000)
            tools = []
            for t in (resp.get("toolCalls") or []):
                tools.append({
                    "name": t.get("name"),
                    "input": _truncate(json.dumps(t.get("input") or t.get("arguments") or {},
                                                   ensure_ascii=False), 1500)[0],
                })
            return {
                "summary": _trace_summary_line(idx, j),
                "system_chars": sys_size,
                "req_total_messages": len(msgs),
                "req_tail_messages": tail,
                "response": {"text": text, "reasoning": reasoning, "toolCalls": tools,
                             "finishReason": resp.get("finishReason")},
            }
    return None
