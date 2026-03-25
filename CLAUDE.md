# CLAUDE.md - X Digest

This file provides guidance to Claude Code when working with this repository.

## 项目概述

X Digest 是一个自动化 X（Twitter）摘要生成工具，使用 AI 对关注账户的推文进行智能聚合、分类和总结，生成日报/周报。

## 快速开始

```bash
# 安装依赖
uv pip install -r requirements.txt

# 配置 X API 和 AI 模型
cp .env.example .env
# 编辑 .env，填入：
# - X API Key / Bearer Token
# - AI 模型 API Key（OpenAI / Gemini / DeepSeek 等）

# 获取浏览器 Cookie（用于绕过登录验证）
# 使用浏览器插件（EditThisCookie 或 Cookie-Editor）导出 X 的 Cookie
# 保存为 x_cookies_1.json（多账号：x_cookies_2.json, x_cookies_3.json ...）

# 运行摘要生成
python fetcher.py
```

## 项目结构

```
x_digest/
├── fetcher.py              # 主程序（爬取推文 → AI 分析 → 生成摘要）
├── config.py               # 配置管理（账户列表、主题分类）
├── custom_accounts.json    # 自定义关注账户列表
├── custom_accounts.json.example  # 模板
├── x_cookies_*.json        # X 浏览器 Cookie（.gitignore 忽略，支持多账号）
├── .env                    # API Key（.gitignore 忽略）
├── .env.example            # 环境变量模板
├── requirements.txt        # Python 依赖
├── defaults/               # 默认配置
├── docs/                   # 文档
└── outputs/                # 生成的摘要输出
```

## 核心功能

### 1. 推文收集（Tweet Collection）
- 通过 X API 或浏览器自动化获取推文
- 支持自定义账户列表（`custom_accounts.json`）
- 支持多种数据源：时间线、搜索、热门话题

### 2. 内容分类（Content Classification）
- AI 自动识别推文主题（技术、金融、娱乐等）
- 基于 `config.py` 的主题配置进行分类
- 过滤垃圾和重复内容

### 3. 智能总结（AI Summarization）
- 调用 LLM（GPT-4 / Gemini 优先，支持降级）
- 生成高质量摘要，保留关键信息
- 支持多语言总结

### 4. 报告生成（Report Generation）
- 日报：当日推文摘要
- 周报：周内推文聚合分析
- 输出格式：Markdown / HTML / PDF

## 配置说明

### custom_accounts.json
```json
{
  "tech": [
    {"id": "username1", "name": "Tech Expert 1"},
    {"id": "username2", "name": "Tech Expert 2"}
  ],
  "finance": [
    {"id": "finance_account", "name": "Finance News"}
  ]
}
```

### config.py
```python
# 支持的主题分类
CATEGORIES = {
    'tech': ['AI', 'blockchain', 'startups'],
    'finance': ['stocks', 'crypto', 'economics'],
    'general': ['news', 'entertainment']
}

# AI 模型选择
AI_MODELS = {
    'primary': 'gpt-4',
    'fallback': ['gemini-pro', 'deepseek']
}

# 摘要长度配置
SUMMARY_LENGTH = {
    'daily': 500,      # 日报字数
    'weekly': 2000     # 周报字数
}
```

### .env 配置
```bash
# X API
X_API_KEY="..."
X_BEARER_TOKEN="..."

# AI 模型
OPENAI_API_KEY="..."
GEMINI_API_KEY="..."
DEEPSEEK_API_KEY="..."

# 应用配置
OUTPUT_DIR="./outputs"
BATCH_SIZE=50
MAX_RETRIES=3
```

## 工作流

```
获取推文 → 去重 → 分类 → AI 总结 → 生成报告 → 保存输出
```

### 详细步骤
1. **连接 X API**：使用 Bearer Token 或浏览器 Cookie
2. **下载推文**：按时间范围、账户、关键词等条件获取
3. **预处理**：清理 HTML/标签、去除重复、过滤垃圾
4. **分类处理**：按 `custom_accounts.json` 分配到不同话题
5. **AI 分析**：调用 LLM 进行内容理解和摘要
6. **报告生成**：Markdown 格式输出到 `outputs/`

## 重要实现细节

### Cookie 管理
- X 可能要求登录验证 → 需要浏览器 Cookie
- Cookie 过期时间：通常数周
- 失效后：重新导出 `x_cookies_*.json`

### 速率限制
- X API 有请求限制（通常 450 请求/15分钟）
- 实现指数退避重试和请求排队

### 误差处理
- API 故障时降级使用本地缓存数据
- LLM 调用失败时尝试其他模型
- 网络超时自动重试

## 开发注意事项

### 推文解析
- Twitter API v2 返回 JSON 格式
- 需要处理引用、转发、线程等特殊格式
- 图片/视频URL 需要保留或下载

### 本地化
- 推文可能来自多种语言 → AI 需要支持多语言
- 报告生成时考虑用户语言偏好

### 性能优化
- 批量下载推文时使用并发控制
- 缓存 AI 分析结果避免重复调用
- 定期清理过期缓存

### 隐私和合规
- 尊重 X 的服务条款（不可用于商业用途的大规模爬取）
- 存储推文时需要注意版权
- `.gitignore` 必须忽略：`x_cookies_*.json`, `.env`, 缓存文件

## 中文支持

- 所有用户可见文本使用中文
- 支持中文推文和中文账户
- 摘要优先生成中文版本
