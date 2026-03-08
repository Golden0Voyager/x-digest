#!/bin/bash
# X-Digest 定时运行脚本

# 设置代理
export https_proxy=http://127.0.0.1:8118
export http_proxy=http://127.0.0.1:8118

# Playwright 需要的环境
export HOME=/Users/hainingyu
export DISPLAY=:0
export PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright"

# 项目目录
cd /Users/hainingyu/Code/x-digest

# 日志文件
LOG="output/cron.log"
echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "[$(date)] X-Digest 开始运行" >> "$LOG"

# 运行
/Users/hainingyu/.local/bin/uv run main.py >> "$LOG" 2>&1

echo "[$(date)] X-Digest 运行完成 (exit: $?)" >> "$LOG"
