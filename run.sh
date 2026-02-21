#!/bin/bash
# X-Digest 定时运行脚本

# 设置代理
export https_proxy=http://127.0.0.1:8118
export http_proxy=http://127.0.0.1:8118

# 项目目录
cd /Users/hainingyu/Code/x-digest

# 运行
/Users/hainingyu/.local/bin/uv run main.py >> /Users/hainingyu/Code/x-digest/output/cron.log 2>&1

echo "[$(date)] X-Digest 运行完成" >> /Users/hainingyu/Code/x-digest/output/cron.log
