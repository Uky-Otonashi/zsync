# zsync

**Backup, sync and migrate your ZCode development environment — sessions, memory, constraints, skills and source code — as a single portable archive.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]() [![Dependencies](https://img.shields.io/badge/dependencies-zero-stdlib_only-green)]() [![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE) [![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)]()

[简体中文](README.zh-CN.md) | English

---

## Why zsync?

ZCode keeps the full history of your AI-assisted work locally: conversation sessions
(with complete context, reasoning traces and tool-call transcripts), project memory,
constraints, skills, and your project source. None of that travels with you — moving
between machines, handing a project to a VM, or recovering after a reinstall usually
means starting from zero.

zsync turns that environment into a **single compressed `.ztar` archive** you can push
to a central server and pull on any other machine — with **path remapping** so an
archive built at `D:\work\myproject` restores cleanly at `C:\Projects\myproject`,
including the sidebar session index.

```
Central server (any machine / VM)              Every dev machine
┌──────────────────────────────┐    push .ztar ┌──────────────────────┐
│  zsync-server :8642          │ ◀──────────── │ client (agent :8643) │
│  · shared Web GUI            │               │  reads local ~/.zcode│
│  · archive repository        │ ────────────▶ │  build / restore     │
└──────────────────────────────┘  pull+restore └──────────────────────┘
        ▲ server: browser UI or CLI-only ops     client: desktop app
          http://<server>:8642                   (single exe) or browser
```

Since v0.4 the repo is split into `server/` and `client/` around a shared stdlib
core (`zsync/`); the Web GUI (`web/`) is shared and switches variant at runtime.

## Features

- **Central server + per-machine client** — one Web UI for every machine; the client
  is a desktop app (single exe on Windows) with an embedded loopback-only agent.
- **Single-archive storage** — each backup is one `.ztar` (tar.gz with an embedded
  `manifest.json`); a sidecar manifest allows listing/downloading without unpacking.
- **Complete migration unit** — sessions (context, reasoning, tool transcripts),
  **sidebar session-list index**, project memory, constraints, skills, plugin state,
  project source (with optional `.git`), global-level components.
- **Path remapping** — project_id, session directory, memory slug and the tasks index
  are all rewritten to the target path automatically.
- **Ghost projects** — projects removed from the sidebar but whose sessions/memory
  still exist are discovered, listed and can be backed up (badged in the UI).
- **Source filtering** — gitignore-style preset ignores (node_modules, venv, build
  output, logs, …) plus custom excludes/force-includes with a file-tree picker,
  persisted per project.
- **Live backup** — watch a project and rebuild+push automatically on change.
- **Inline logs in the desktop client** — jobs and client logs live in a collapsible
  bottom drawer; server logs stay on the server's Web UI.
- **No Python on the target?** — generate a *Python-free migration package* that runs
  with the curl/tar/PowerShell built into Windows 10+.
- **Zero runtime dependencies** — server, agent, Web GUI and CLI are pure Python
  stdlib (the Windows desktop exe additionally bundles WebView2 glue; see
  `client/BUILD.md`).

## Quick start

### 1. Start the central server (any machine, once)

```bash
python server/zsync-server.py serve --port 8642   # add --token <secret> on untrusted LANs
```

Runs a pure repository + the shared Web GUI. The server does not need ZCode installed,
never touches a local ZCode home, and is CLI-only:

```bash
python server/zsync-server.py start|stop|status|restart   # background daemon (pidfile + logs)
python server/zsync-server.py service install             # systemd unit (Linux) / boot task (Windows)
```

### 2. Connect a client machine

Preferred: **the desktop client**. Build (or download) `zsync-client.exe`, double-click,
done — the agent starts with the window and stops when you close it. No Python needed
on the machine. Build your own with `python client/build_exe.py` (see
[client/BUILD.md](client/BUILD.md)).

Lightweight alternative — the headless agent, straight from the server's Web UI:
open `http://<server-ip>:8642` in the client's browser; on first visit the page shows
a short onboarding: download `http://<server-ip>:8642/tool.zip`, unpack it anywhere
(e.g. `C:\zsync`), double-click `start-agent.cmd` (Windows) or run
`python client/zsync-client.py agent` (Linux/macOS), then hit **re-detect**.

- The agent listens on `127.0.0.1:8643` only — never exposed to the LAN.
- On Windows always launch via `start-agent.cmd` (or with a `python` prefix).
  Do **not** run bare `zsync-client.py agent`: cmd resolves it through the `.py`
  file association, which may be an editor (e.g. VS Code) — that opens the file
  instead of starting the agent.
- First-time clients confirm their ZCode directory (auto-detected as `~/.zcode` for
  the current user); after that the local project list loads automatically.
- Opening `http://127.0.0.1:8643` directly shows the same UI in *client variant*
  (this is what the desktop app displays).

### 3. Backup / restore

- **Project backup** — pick components per project, optionally tune the source filter,
  then *Backup & push*. Archives land in the server repository.
- **Server repository** — browse archives, select one, choose a local target path and
  components, *Pull & restore*. Paths are remapped automatically.

## What travels inside a `.ztar`

```
project/sessions.sqlite      session DB rows (session/entry/message/part/usage/permissions…)
project/tasks-index.sqlite   sidebar session-list index rows   ← what makes sessions visible
project/rollout/*.jsonl      raw model I/O transcripts (can be large)
project/agents|artifacts|exec/**
project/memory/**            project memory
source/**                    project source (filtered; may include .git)
global/**                    optional global skills / constraints / plugin switches
```

## Layout

```
zsync/            shared core (pure stdlib): bundle / restore / zcode layout / http layer
server/           server entry: serve / daemon / service registration
client/           client entry: desktop GUI shell, headless agent, backup CLI, exe packaging
web/              shared Web GUI (server & client variants switch at runtime)
```

## CLI

```bash
# client (backup operations run against the local ZCode home)
python client/zsync-client.py                    # desktop GUI (default subcommand)
python client/zsync-client.py agent              # headless agent (127.0.0.1:8643)
python client/zsync-client.py config --zcode-home <dir> --remote-url http://host:8642
python client/zsync-client.py projects           # list local projects (incl. ghost projects)
python client/zsync-client.py build --project-id PID [--no-push] [--set source=0 ...]
python client/zsync-client.py push  --archive ID [--server URL]
python client/zsync-client.py pull  --server URL --archive ID --to PATH [--only sessions,memory,...]
python client/zsync-client.py restore --archive ID --to PATH
python client/zsync-client.py archives [--server URL]
python client/zsync-client.py watch  --project-id PID [--interval 20]
python client/zsync-client.py vmpkg  --archive ID --to C:\path   # Python-free migration package
python client/zsync-client.py selftest [--project-id PID]        # sandboxed end-to-end self test

# server
python server/zsync-server.py serve [--port 8642] [--token T]
python server/zsync-server.py start|stop|status|restart
python server/zsync-server.py service install|uninstall|start|stop|status
```

The legacy root entry `zsync.py` still works as a forwarding shim (prints a
deprecation note) and will be removed in a future release.

## REST API (excerpt)

```
GET  /api/state | /api/archives | /api/jobs/{id} | /api/logs          (server & agent)
GET  /api/projects | /api/filetree | /api/project-detail | /api/session…   (agent only)
POST /api/settings        {zcode_home?, remote_url?, remote_token?}   (agent)
POST /api/build           {project_id, components?, push_url?}  -> job (agent)
POST /api/restore         {archive_id | remote{url,archive_id}, target_path, components} (agent)
POST /api/upload/{id}/manifest | /ztar            # archive push (agent -> server)
GET  /api/archives/{id}/manifest | /download
GET  /tool.zip                                     # self-package for client onboarding (server)
```

## Notes & caveats

- Close ZCode completely before restoring into a live ZCode home (WAL checks included).
- Archives are full snapshots; disable the `rollout` component when transcripts are
  multi-GB and you don't need them.
- Live backup rebuilds on change (default interval 20 s) and pushes if a server is
  configured.
- The browser may ask for permission when the server page contacts the loopback agent
  (private-network access) — allow it.
- **Headless deployment**: `zsync-server service install` generates and enables a
  systemd unit (`Restart=always`, boot start); `zsync-server start` covers hosts
  without systemd via a detached daemon + pidfile.

## Verified by self tests

`python client/zsync-client.py selftest` builds a real archive, restores it into a
sandbox home with a different path and verifies session/message/part counts, the
sidebar index, memory, transcripts and the server-side import round-trip.

## Roadmap

- [ ] Archive pruning / retention policies
- [ ] Incremental (chunked) archives for large rollouts
- [ ] Scheduled server-side backups of registered agents
- [ ] Multi-server federation

## Contributing

Issues and PRs are welcome. Keep the core stdlib-only — that constraint is a feature
(packaging-time deps for the desktop exe are the one exception).

## License

[MIT](LICENSE)
