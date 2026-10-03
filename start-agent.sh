#!/bin/sh
# zsync 客户端 agent 启动器(供中央服务器 Web 页面读取本机 zcode 项目)
cd "$(dirname "$0")"
# 优先用随包的单文件客户端(tool.zip?bin=linux 会带一个, 免 Python); 解压丢失执行位时先补 chmod
for exe in zsync-client zsync-client-linux-*; do
  if [ -f "$exe" ]; then
    [ -x "$exe" ] || chmod +x "$exe" 2>/dev/null
    if [ -x "$exe" ]; then
      exec "./$exe" agent "$@"
    fi
  fi
done
exec python3 client/zsync-client.py agent "$@"
