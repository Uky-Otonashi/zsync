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
│  zsync serve :8642           │ ◀──────────── │ agent 127.0.0.1:8643 │
│  · shared Web GUI            │               │  reads local ~/.zcode│
│  · archive repository        │ ────────────▶ │  build / restore     │
└──────────────────────────────┘  pull+restore └──────────────────────┘
        ▲ open http://<server>:8642 in a browser — the page auto-detects
          the local agent and shows THIS machine's projects
```

## Features

- **Central server + per-machine agent** — one Web UI for every machine; a lightweight
  agent (pure Python stdlib, loopback-only) provides local access.
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
- **No Python on the target?** — generate a *Python-free migration package* that runs
  with the curl/tar/PowerShell built into Windows 10+.
- **Zero dependencies** — server, agent, Web GUI and CLI are pure Python stdlib.

## Quick start

### 1. Start the central server (any machine, once)

```bash
python zsync.py serve --port 8642          # add --token <secret> on untrusted LANs
```

Runs a pure repository + the shared Web GUI. The server does not need ZCode installed.
For a permanent deployment a systemd unit is all it takes (see [notes](#notes--caveats)).

### 2. Connect a client machine

Open `http://<server-ip>:8642` in the client's browser. On first visit the page shows
a short onboarding: download `http://<server-ip>:8642/tool.zip`, unpack it anywhere
(e.g. `C:\zsync`), double-click `start-agent.cmd` (Windows) or run
`python zsync.py serve --agent` (Linux/macOS), then hit **re-detect**.

- The agent listens on `127.0.0.1:8643` only — never exposed to the LAN.
- On Windows always launch via `start-agent.cmd` (or `python zsync.py serve --agent`).
  Do **not** run bare `zsync.py serve --agent`: cmd resolves it through the `.py`
  file association, which may be an editor (e.g. VS Code) — that opens the file
  instead of starting the agent.
- First-time clients confirm their ZCode directory (auto-detected as `~/.zcode` for
  the current user); after that the local project list loads automatically.
- Put a shortcut to `start-agent.cmd` into `shell:startup` for auto-start.

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

## CLI

```bash
python zsync.py serve [--port 8642] [--token T]    # central server / full node
python zsync.py serve --agent                      # client agent (127.0.0.1:8643)
python zsync.py config --zcode-home <dir> --remote-url http://host:8642
python zsync.py projects                           # list local projects (incl. ghost projects)
python zsync.py build --project-id PID [--no-push] [--set source=0 ...]
python zsync.py push  --archive ID [--server URL]
python zsync.py pull  --server URL --archive ID --to PATH [--only sessions,memory,...]
python zsync.py restore --archive ID --to PATH
python zsync.py archives [--server URL]
python zsync.py watch  --project-id PID [--interval 20]
python zsync.py vmpkg  --archive ID --to C:\path   # Python-free migration package
python zsync.py selftest [--project-id PID]        # sandboxed end-to-end self test
```

## REST API (excerpt)

```
GET  /api/state | /api/projects | /api/archives | /api/jobs/{id} | /api/logs
GET  /api/filetree?project_id=..&rel=..           # source-filter file tree
POST /api/settings        {zcode_home?, remote_url?, remote_token?}
POST /api/build           {project_id, components?, push_url?}  -> job
POST /api/restore         {archive_id | remote{url,archive_id}, target_path, components}
POST /api/upload/{id}/manifest | /ztar            # archive push (agent -> server)
GET  /api/archives/{id}/manifest | /download
GET  /tool.zip                                     # self-package for client onboarding
```

## Notes & caveats

- Close ZCode completely before restoring into a live ZCode home (WAL checks included).
- Archives are full snapshots; disable the `rollout` component when transcripts are
  multi-GB and you don't need them.
- Live backup rebuilds on change (default interval 20 s) and pushes if a server is
  configured.
- The browser may ask for permission when the server page contacts the loopback agent
  (private-network access) — allow it.
- **Headless deployment**: a minimal systemd unit (`User=<user>`,
  `WorkingDirectory=/opt/zsync`,
  `ExecStart=/usr/bin/python3 zsync.py serve --port 8642`, `Restart=always`) is enough
  for a permanent server.

## Verified by self tests

`python zsync.py selftest` builds a real archive, restores it into a sandbox home with
a different path and verifies session/message/part counts, the sidebar index, memory,
transcripts and the server-side import round-trip.

## Roadmap

- [ ] Archive pruning / retention policies
- [ ] Incremental (chunked) archives for large rollouts
- [ ] Scheduled server-side backups of registered agents
- [ ] Multi-server federation

## Contributing

Issues and PRs are welcome. Keep it stdlib-only — that constraint is a feature.

## License

[MIT](LICENSE)
