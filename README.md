# X (Twitter) 摘要生成器

监控 AI、科技、航天、机器人、经济领域的意见领袖，自动翻译并总结。

## 功能

- ✅ 抓取指定 Twitter 账号的最新推文
- ✅ AI 翻译（英文 → 中文）
- ✅ AI 提炼要点
- ✅ 输出为 Markdown / 飞书文档

## 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的 API 密钥
```

### 2. 获取 Twitter API Token

访问 https://developer.twitter.com 申请免费 API 密钥

### 3. 运行

```bash
uv run main.py
```

## 监控账号

见 `config.py` 中的 `ACCOUNTS` 列表

## 输出

- `output/YYYY-MM-DD.md` — 每日摘要
