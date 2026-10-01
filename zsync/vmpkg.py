"""免 Python 迁移包: 为无法安装 Python 的目标机器准备自包含迁移包。

输入: 本地 store 中的 .ztar 归档 + 目标机当前数据库(可选底座, 保留其自有数据)。
在服务端完成全部合并、路径重映射与 tasks-index(会话列表索引)写入, 产出:

  package.tgz 解压后:
    apply.ps1        一键应用(停止zcode -> 备份 -> 覆盖 .zcode overlay -> 解压源码)
    package.json     包清单
    payload/
      cli/db/db.sqlite            已合并的主会话库
      v2/tasks-index.sqlite       已合并的会话列表索引
      cli/rollout|agents|artifacts|exec|memories/...
      skills/                     (可选)全局技能
      cli/config.json             (可选)插件开关
    source/          项目源码(可直接 robocopy)
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tarfile
import time

from . import zclayout, tasksindex
from .bundle import (BundleStore, Components, RestoreOptions, restore_bundle,
                     _copy_tree_incremental)

APPLY_PS1 = r'''# zsync migration package apply script (no Python required)
# Usage:  powershell -ExecutionPolicy Bypass -File apply.ps1 [-ProjectPath "C:\path"] [-ZHome "$env:USERPROFILE\.zcode"]
param(
  [string]$ProjectPath = "__DEFAULT_PROJECT__",
  [string]$ZHome = "$env:USERPROFILE\.zcode"
)
$ErrorActionPreference = 'Stop'
$pkg = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "== zsync migration apply =="

# 1) stop zcode
$procs = Get-Process ZCode -ErrorAction SilentlyContinue
if ($procs) { Write-Host "停止 zcode (pid: $($procs.Id -join ','))"; $procs | Stop-Process -Force; Start-Sleep 2 }

# 2) backup current db + tasks index
foreach ($rel in @('cli\db\db.sqlite', 'v2\tasks-index.sqlite')) {
  $f = Join-Path $ZHome $rel
  if (Test-Path $f) {
    $bak = "$f.pre-zsync-$(Get-Date -Format yyyyMMdd_HHmmss).bak"
    Copy-Item $f $bak -Force
    Write-Host "已备份 $rel"
  }
}

# 3) overlay .zcode content (cli/ + v2/tasks-index)
$overlay = Join-Path $pkg 'payload'
robocopy (Join-Path $overlay 'cli') (Join-Path $ZHome 'cli') /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy cli 失败: $LASTEXITCODE" }
if (Test-Path (Join-Path $overlay 'v2')) {
  robocopy (Join-Path $overlay 'v2') (Join-Path $ZHome 'v2') /E /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy v2 失败: $LASTEXITCODE" }
}
Write-Host "已覆盖 .zcode 数据(主库 + 会话列表索引)"

# 4) merge plugins config
$cfgSrc = Join-Path $overlay 'cli\config.json'
$cfgDst = Join-Path $ZHome 'cli\config.json'
if (Test-Path $cfgSrc) {
  $src = Get-Content $cfgSrc -Raw | ConvertFrom-Json
  $dst = $null
  if (Test-Path $cfgDst) { $dst = Get-Content $cfgDst -Raw | ConvertFrom-Json }
  if (-not $dst) { $dst = New-Object PSObject }
  if (-not $dst.plugins) { $dst | Add-Member -NotePropertyName plugins -NotePropertyValue (New-Object PSObject) }
  if (-not $dst.plugins.enabledPlugins) { $dst.plugins | Add-Member -NotePropertyName enabledPlugins -NotePropertyValue (New-Object PSObject) }
  foreach ($p in $src.plugins.enabledPlugins.PSObject.Properties) { $dst.plugins.enabledPlugins | Add-Member -NotePropertyName $p.Name -NotePropertyValue $p.Value -Force }
  $dst | ConvertTo-Json -Depth 10 | Set-Content $cfgDst -Encoding UTF8
  Write-Host "已合并插件配置"
}

# 5) copy source
$srcDir = Join-Path $pkg 'source'
if (Test-Path $srcDir) {
  New-Item -ItemType Directory -Force -Path $ProjectPath | Out-Null
  robocopy $srcDir $ProjectPath /E /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "源码复制失败: $LASTEXITCODE" }
  Write-Host "源码已就位 -> $ProjectPath"
}

Write-Host "== 完成 =="
Write-Host "项目目录: $ProjectPath"
Write-Host "现在启动 zcode 并打开该目录即可看到迁移的会话(左侧会话列表)。"
'''


def build_migration_package(
    store: BundleStore,
    archive_id: str,
    target_path: str,
    out_dir: str,
    base_db: str | None = None,
    base_tasks_index: str | None = None,
    components: dict | None = None,
    progress=None,
) -> dict:
    def prog(phase, pct, detail=""):
        if progress:
            progress(phase, pct, detail)

    manifest = store.manifest(archive_id)
    if not manifest or not os.path.isfile(store.ztar_path(archive_id)):
        raise RuntimeError(f"归档不存在: {archive_id}")
    src_path = manifest["source"].get("project_path") or ""
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, ".work")
    shutil.rmtree(work, ignore_errors=True)
    bundle_dir = os.path.join(work, "bundle")
    staging_home = os.path.join(work, "home", ".zcode")
    staging = zclayout.ZcodeLayout(staging_home)
    os.makedirs(os.path.dirname(staging.db_path), exist_ok=True)

    prog("extract", 5, "解包归档")
    store.extract_to(store.ztar_path(archive_id), bundle_dir)

    # 底座: 目标机当前 db + tasks-index(保留其自有数据); 无则克隆主机 schema
    if base_db and os.path.isfile(base_db):
        prog("base", 10, "使用目标机数据库作为底座")
        shutil.copy2(base_db, staging.db_path)
        for suffix in ("-wal", "-shm"):
            if os.path.isfile(base_db + suffix):
                shutil.copy2(base_db + suffix, staging.db_path + suffix)
    else:
        prog("base", 10, "克隆本机 zcode schema 作为底座")
        host = zclayout.default_layout()
        con, tmp = zclayout.open_ro(host.db_path)
        try:
            sqls = [r[0] for r in con.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
        finally:
            con.close()
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
        out = sqlite3.connect(staging.db_path)
        out.executescript(";\n".join(sqls))
        out.commit()
        out.close()
    if base_tasks_index and os.path.isfile(base_tasks_index):
        ti_dst = tasksindex.tasks_index_path(staging_home)
        os.makedirs(os.path.dirname(ti_dst), exist_ok=True)
        shutil.copy2(base_tasks_index, ti_dst)
        for suffix in ("-wal", "-shm"):
            if os.path.isfile(base_tasks_index + suffix):
                shutil.copy2(base_tasks_index + suffix, ti_dst + suffix)

    comps = Components.from_dict(components)
    opts = RestoreOptions(target_path=target_path, components=comps)
    prog("restore", 15, "合并归档(含路径重映射与会话列表索引)")
    rep = restore_bundle(bundle_dir, staging, opts, lambda ph, pc, d="": prog(
        ph, 15 + pc * 0.5, d))

    # 组装 payload
    prog("pack", 70, "组装 payload")
    payload = os.path.join(out_dir, "payload")
    os.makedirs(payload, exist_ok=True)
    for sub in ("rollout", "agents", "artifacts", "exec", "memories"):
        s = os.path.join(staging.cli_dir, sub)
        if os.path.isdir(s) and os.listdir(s):
            os.makedirs(os.path.join(payload, "cli"), exist_ok=True)
            shutil.copytree(s, os.path.join(payload, "cli", sub), dirs_exist_ok=True)
    os.makedirs(os.path.join(payload, "cli", "db"), exist_ok=True)
    shutil.copy2(staging.db_path, os.path.join(payload, "cli", "db", "db.sqlite"))
    ti = tasksindex.tasks_index_path(staging_home)
    if os.path.isfile(ti):
        os.makedirs(os.path.join(payload, "v2"), exist_ok=True)
        shutil.copy2(ti, os.path.join(payload, "v2", "tasks-index.sqlite"))
    if comps.global_skills and os.path.isdir(os.path.join(staging.home, "skills")):
        shutil.copytree(os.path.join(staging.home, "skills"),
                        os.path.join(payload, "skills"), dirs_exist_ok=True)
    if comps.global_plugins and os.path.isfile(staging.plugins_config):
        shutil.copy2(staging.plugins_config, os.path.join(payload, "cli", "config.json"))
    # 源码(不二次压缩, robocopy 直接可用)
    src_bundle = os.path.join(bundle_dir, "source")
    if comps.source and os.path.isdir(src_bundle) and os.listdir(src_bundle):
        shutil.copytree(src_bundle, os.path.join(out_dir, "source"), dirs_exist_ok=True)

    apply_ps1 = APPLY_PS1.replace("__DEFAULT_PROJECT__", target_path)
    with open(os.path.join(out_dir, "apply.ps1"), "w", encoding="utf-8-sig") as f:
        f.write(apply_ps1)

    new_pid = zclayout.project_id_for(target_path)
    pkg_manifest = {
        "format": "zsync-vmpkg/2",
        "created_at": int(time.time() * 1000),
        "archive_id": archive_id,
        "source_project_path": src_path,
        "target_path": target_path,
        "target_project_id": new_pid,
        "target_memory_slug": zclayout.memory_slug_for(target_path),
        "restore": {"db_counts": rep.db_counts, "tasks_index_rows": rep.tasks_index_rows,
                    "files_copied": rep.files_copied, "verify": rep.verify,
                    "tasks_verify": rep.tasks_verify, "warnings": rep.warnings},
        "components": comps.to_dict(),
    }
    with open(os.path.join(out_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(pkg_manifest, f, ensure_ascii=False, indent=1)

    # 单一 tgz
    prog("tar", 80, "打包 package.tgz")
    tgz = os.path.join(out_dir, "package.tgz")
    if os.path.exists(tgz):
        os.remove(tgz)
    count = 0
    with tarfile.open(tgz + ".tmp", "w:gz", compresslevel=1) as tf:
        for name in ("apply.ps1", "package.json"):
            p = os.path.join(out_dir, name)
            if os.path.isfile(p):
                tf.add(p, arcname=name)
                count += 1
        for top in ("payload", "source"):
            root = os.path.join(out_dir, top)
            if not os.path.isdir(root):
                continue
            for root_, _dirs, files in os.walk(root):
                for fn in files:
                    full = os.path.join(root_, fn)
                    tf.add(full, arcname=os.path.relpath(full, out_dir).replace("\\", "/"))
                    count += 1
                    if progress and count % 200 == 0:
                        prog("tar", 80, f"已打包 {count} 个文件")
    os.replace(tgz + ".tmp", tgz)
    pkg_manifest["package_tgz_bytes"] = os.path.getsize(tgz)
    pkg_manifest["build_seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(out_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(pkg_manifest, f, ensure_ascii=False, indent=1)
    shutil.rmtree(work, ignore_errors=True)
    prog("done", 100, f"完成 {pkg_manifest['package_tgz_bytes']/1e6:.0f}MB, {pkg_manifest['build_seconds']}s")
    return pkg_manifest
