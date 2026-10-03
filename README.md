# zsync

Back up and migrate your ZCode working environment — chat sessions, project memory,
constraints, skills, and project source — as one portable archive you can restore on
any machine.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]() [![Dependencies](https://img.shields.io/badge/dependencies-stdlib_only-green)]() [![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE) [![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)]()

[简体中文](README.zh-CN.md) | English

## Why this exists

ZCode keeps the whole history of your AI-assisted work on the machine where it
happened: the session database with every message, reasoning trace, and tool call,
the per-project memory it has accumulated, your constraints and skills, and of
course the project itself. All of that stays put. Move to another machine, hand a
project to a VM, or reinstall your OS, and you're starting over.

zsync packages that environment into a single `.ztar` archive (a tar.gz with a
manifest inside), pushes it to a central server, and restores it anywhere. Paths
are remapped on the way in — an archive built at `D:\work\myproject` restores
cleanly at `C:\Projects\myproject`, including the sidebar session index, so
everything shows up in ZCode as if it had always lived there.

## How it works

There are two pieces:

```
        central server                       your machines
┌───────────────────────────┐     push      ┌────────────────────────┐
│  zsync-server   :8642     │ ◀──────────── │  zsync client          │
│  archive store            │               │  desktop app (exe) or  │
│  web UI                    │ ───────────▶ │  headless agent        │
└───────────────────────────┘  pull+restore └────────────────────────┘
```

The **server** is a dumb, reliable archive: it receives pushes, serves downloads,
and hosts the web UI. It never touches a ZCode home and is managed entirely from
the command line. The **client** runs on each dev machine. On Windows it's a
single exe — double-click, get a window, close it and everything shuts down. The
client embeds a small loopback agent that reads your local `~/.zcode`, and the
same web UI is used on both sides.

## Getting started

### Client (Windows)

Grab `zsync-client-windows-x86_64.exe` from the
[latest release](https://github.com/Uky-Otonashi/zsync/releases) and run it. No
Python, no installer. On first launch it asks you to confirm your ZCode directory
and the server address, then loads your project list. Closing the window stops
everything — there is no background service.

If you prefer a browser (or you're on Linux/macOS), open the server's web UI
instead; it walks you through a one-time setup: download `tool.zip` from the
server, unpack it, and start the headless agent with `start-agent.cmd` (Windows)
or `python client/zsync-client.py agent`. Any Python 3.10+ works, no dependencies.

### Server

Either run the release binary:

```
zsync-server-windows-x86_64.exe serve --port 8642 --token <secret>
```

or from source:

```
python server/zsync-server.py serve --port 8642 --token <secret>
```

For a permanent deployment there's a built-in daemon and service registration:

```
python server/zsync-server.py start          # detached daemon (pidfile + logs)
python server/zsync-server.py service install  # generates+enables a systemd unit
```

Set a `--token` unless the server sits on a fully trusted network.

## What's inside an archive

```
project/sessions.sqlite      session rows (messages, parts, usage, permissions…)
project/tasks-index.sqlite   sidebar index — what makes sessions visible in ZCode
project/rollout/*.jsonl      raw model I/O transcripts (can get large)
project/agents|artifacts|exec/**
project/memory/**            project memory
source/**                    project source, filtered, optionally with .git
global/**                    optional: skills, constraints, plugin switches
```

Every component is a toggle, per project and per restore: sessions, transcripts,
sub-agent data, memory, source, and a set of global items you can carry along.
The source filter ships with sensible defaults (node_modules, venvs, build
output, logs are ignored out of the box) and you can refine it per project from
a file tree in the UI.

## Daily use

Backups are one click in the web UI: pick a project, pick what goes in, and it
builds and pushes to the server. Restoring is symmetric — browse the server's
archive list, choose a target path, and pull. If the path differs from the
original machine, project ids, session directories, memory slugs, and the
sidebar index are all rewritten to match. There's also a live-backup mode that
rebuilds and pushes an archive whenever a project changes.

Jobs and client logs live in a drawer at the bottom of the client window,
collapsed by default; the server keeps its own log page in its web UI.

One rule to remember: **quit ZCode completely before restoring** into the home
you're using. The restore writes to the session database, and ZCode holds it
open.

## CLI

The client doubles as a CLI for scripting or headless machines:

```
python client/zsync-client.py projects           # list local projects
python client/zsync-client.py build --project-id PID [--no-push] [--set source=0 ...]
python client/zsync-client.py push  --archive ID [--server URL]
python client/zsync-client.py pull  --server URL --archive ID --to PATH
python client/zsync-client.py restore --archive ID --to PATH
python client/zsync-client.py archives [--server URL]
python client/zsync-client.py watch  --project-id PID      # live backup
python client/zsync-client.py vmpkg  --archive ID --to C:\path
python client/zsync-client.py selftest                    # sandboxed end-to-end test
python client/zsync-client.py agent                       # headless agent
```

`vmpkg` builds a migration package that restores on a machine with no Python at
all, using nothing but what ships with Windows.

## Building from source

The runtime is pure standard-library Python — clone and run, nothing to install.
The only build-time dependency is packaging the desktop/server executables:

```
python -m pip install pyinstaller pywebview
python client/build_exe.py
python server/build_exe.py
```

Artifacts land in `dist/`. See [client/BUILD.md](client/BUILD.md) for details,
including how to give the client a custom icon locally.

## Notes and limitations

- Transcripts (`rollout`) can reach multiple GB on long projects. They're a
  component like everything else — turn them off when you don't need them.
- The Windows client needs the WebView2 runtime, which Windows 10/11 ships with.
- On Linux the client binary covers agent and CLI use out of the box; the GUI
  window additionally needs system webview libraries.
- macOS builds from source; nothing is platform-specific.

## License

[MIT](LICENSE)
