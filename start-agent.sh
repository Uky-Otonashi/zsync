#!/bin/sh
# zsync 客户端 agent 启动器(供中央服务器 Web 页面读取本机 zcode 项目)
cd "$(dirname "$0")"
exec python3 client/zsync-client.py agent "$@"
