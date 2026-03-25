# X-Digest 配置指南

本文档详细说明 `.env` 文件中每个配置项的含义、推荐值和调优方法。

---

## 1. 网络代理

```bash
PROXY=http://127.0.0.1:7897
```

国内用户必填，用于访问 `x.com` 和海外 AI API。端口号需与你本地代理软件一致（常见：7890、7897、1080）。

---

## 2. AI 供应商降级链

```bash
AI_PROVIDER_CHAIN=GROQ,OPENROUTER,ZHIPUAI
```

**工作原理：** 逗号分隔的供应商前缀列表。第一个为主模型，后续为备选。主模型失败时自动降级到下一个。

### 添加供应商的三步法

1. 在 `AI_PROVIDER_CHAIN` 中追加前缀名
2. 配置该前缀的三要素：`{前缀}_API_KEY`、`{前缀}_BASE_URL`、`{前缀}_MODEL`
3. （可选）配置备选模型：`{前缀}_FALLBACK_MODEL`

### 预置供应商示例

```bash
# ── Groq（推荐首选，极速推理） ──
GROQ_API_KEY=gsk_xxxx
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=moonshotai/kimi-k2-instruct-0905

# ── OpenRouter（多模型聚合平台） ──
OPENROUTER_API_KEY=sk-or-v1-xxxx
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=qwen/qwen3-next-80b-a3b-instruct:free

# ── ZhipuAI / 智谱（国产，中文能力强） ──
ZHIPUAI_API_KEY=xxxx.xxxx
ZHIPUAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
ZHIPUAI_MODEL=glm-4.7-flash

# ── DeepSeek ──
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

### 为翻译和洞察指定不同模型

如果你希望翻译用快模型、洞察用强模型：

```bash
AI_MODEL_TRANSLATE=moonshotai/kimi-k2-instruct-0905   # 翻译：用快的
AI_MODEL_INSIGHTS=moonshotai/kimi-k2-instruct-0905    # 洞察：用强的
```

默认两者都使用主模型，只在需要差异化时配置。

---

## 3. 批次大小与安全上限

这是影响 AI 处理效率和稳定性的核心配置。

### 3.1 AI_BATCH_SIZE — 每批处理条数

```bash
AI_BATCH_SIZE=30
```

每次发送给 AI 的推文条数。**值越大，API 调用次数越少，但单次输出 token 越多。**

### 3.2 AI_MAX_BATCH_SIZE — 安全上限

```bash
# 单批次最大条目数上限，防止 AI 输出 token 截断
# 默认 30 适配 Groq Kimi K2 (max_output=16K)
# 仅在使用输出上限更高的模型（如 32K+）时才建议调大
AI_MAX_BATCH_SIZE=30
```

实际批次大小 = `min(AI_BATCH_SIZE, AI_MAX_BATCH_SIZE)`。

如果 `AI_BATCH_SIZE` 超过 `AI_MAX_BATCH_SIZE`，程序会自动限制并打印警告。

### 3.3 如何确定合适的批次大小

关键公式：**每条推文的洞察输出约 200~300 tokens**

```
所需输出 tokens ≈ 批次大小 × 300
```

| 你的模型 max_output | 推荐 AI_MAX_BATCH_SIZE | 推荐 AI_BATCH_SIZE |
|---------------------|------------------------|---------------------|
| 4K tokens | 10 | 10 |
| 8K tokens | 20 | 20 |
| **16K tokens**（Groq Kimi K2） | **30** | **30** |
| 32K tokens | 50 | 50 |
| 64K+ tokens | 80 | 80 |

### 3.4 怎么知道你的模型 max_output 是多少？

| 服务商 | 查看方式 |
|--------|---------|
| Groq | [console.groq.com/docs/models](https://console.groq.com/docs/models) |
| OpenRouter | 模型页面标注 "Max Output" |
| OpenAI | 文档中的 "max_completion_tokens" |
| 智谱 | 模型详情页 |

**简单判断法：** 如果你运行时频繁看到 `⚠️ JSON 结构受损，正则抢救出 N 条记录`，说明批次太大了，需要调小 `AI_MAX_BATCH_SIZE`。

### 3.5 AI_BATCH_COOLDOWN — 批次间冷却

```bash
AI_BATCH_COOLDOWN=15
```

两个批次之间的等待秒数，防止触发 API 速率限制。免费 API 建议 15~30 秒，付费 API 可以调低到 5~10 秒。

---

## 4. 抓取参数

```bash
TWEETS_PER_ACCOUNT=30      # 每账号最多抓取条数
HOURS_LOOKBACK=72           # 回溯时长（小时）
ACCOUNT_SCAN_INTERVAL=12   # 扫描冷却时间（小时），避免短时间内重复扫描
CACHE_RETENTION_HOURS=720  # 推文池保留时长（720h = 30天）
```

### 回溯窗口说明

`HOURS_LOOKBACK=72` 表示只收集最近 72 小时内的推文。生成报告时会从推文池中合拢该窗口内的全量数据。

- 日报：建议 24~48
- 周报：建议 168（7天）
- 实时监控：建议 12~24

---

## 5. 飞书推送

```bash
FEISHU_APP_ID=cli_xxxx
FEISHU_APP_SECRET=xxxx
FEISHU_USER_ID=ou_xxxx
```

配置后，每次生成报告会自动：
1. 创建飞书文档（完整 Markdown 内容）
2. 推送消息通知到指定用户

不需要飞书功能？留空即可，程序会自动跳过。

---

## 6. 常见配置组合

### 场景 A：Groq 免费用户（推荐起手配置）

```bash
AI_PROVIDER_CHAIN=GROQ
GROQ_API_KEY=gsk_xxxx
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=moonshotai/kimi-k2-instruct-0905
AI_BATCH_SIZE=30
AI_MAX_BATCH_SIZE=30
AI_BATCH_COOLDOWN=15
```

### 场景 B：OpenRouter 免费模型

```bash
AI_PROVIDER_CHAIN=OPENROUTER
OPENROUTER_API_KEY=sk-or-v1-xxxx
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=qwen/qwen3-next-80b-a3b-instruct:free
AI_BATCH_SIZE=15
AI_MAX_BATCH_SIZE=20
AI_BATCH_COOLDOWN=30
```

### 场景 C：多供应商降级链（高可用）

```bash
AI_PROVIDER_CHAIN=GROQ,OPENROUTER,ZHIPUAI
# 主模型挂了 → 自动切 OpenRouter → 再挂切智谱
# 三要素分别配置...
AI_BATCH_SIZE=30
AI_MAX_BATCH_SIZE=30
```

### 场景 D：付费高性能模型

```bash
AI_PROVIDER_CHAIN=OPENAI
OPENAI_API_KEY=sk-xxxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
AI_BATCH_SIZE=50
AI_MAX_BATCH_SIZE=50    # GPT-4o 支持 16K output
AI_BATCH_COOLDOWN=5     # 付费用户速率限制更宽松
```

---

## 7. 故障排查

| 现象 | 原因 | 解决方案 |
|------|------|---------|
| `⚠️ JSON 结构受损，正则抢救出 N 条` | 批次太大，AI 输出被截断 | 调小 `AI_MAX_BATCH_SIZE` |
| `⚠️ [主模型] 失败，降级到 [xxx]` | 主模型 API 故障或限流 | 检查 API Key / 等待限流恢复 |
| `⚠️ AI_BATCH_SIZE=50 超过安全上限 30` | 配置超限 | 同步调大 `AI_MAX_BATCH_SIZE` 或调小 `AI_BATCH_SIZE` |
| 翻译/洞察结果缺失 | 补抓失败或缓存过期 | 删除 `output/intermediate/` 重新运行 |
| 飞书推送失败 | Token 过期或网络问题 | 检查飞书配置三要素 |
