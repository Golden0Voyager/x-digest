# X-Digest 配置指南

本文档详细说明 `.env` 文件中每个配置项的含义、推荐值和调优方法。

---

## 1. 网络代理

```bash
PROXY=http://127.0.0.1:7897
```

国内用户必填，用于访问 `x.com` 和海外 AI API。端口号需与你本地代理软件一致（常见：7890、7897、1080）。

---

## 2. AI 供应商与模型降级链

```bash
AI_PROVIDER_CHAIN=OPENROUTER,SENSENOVA
AI_MODEL_TRANSLATE=baidu/ernie-5.5-flash-preview:free
AI_MODEL_INSIGHTS=baidu/ernie-5.5-flash-preview:free

AI_FALLBACK_CHAIN=SENSENOVA:deepseek-flash,OPENROUTER:nvidia/nemotron-3.5-super-vl:free,SENSENOVA:sensenova-6.8-flash-lite,OPENROUTER:nvidia/nemotron-3.5-lightning:free,SENSENOVA:sensenova-6.8-flash

AI_MODEL_MAX_TOKENS='{"baidu/ernie-5.5-flash-preview:free":60000,"deepseek-flash":240000,"nvidia/nemotron-3.5-super-vl:free":60000,"sensenova-6.8-flash-lite":60000,"nvidia/nemotron-3.5-lightning:free":60000,"sensenova-6.8-flash":60000}'
```

**当前调用顺序：**

```text
OpenRouter Ernie（首选，最多 2 次）
  → SenseNova Token Plan deepseek-flash
  → OpenRouter Nemotron Super
  → SenseNova Token Plan sensenova-6.8-flash-lite
  → OpenRouter Nemotron Lightning
  → SenseNova Token Plan sensenova-6.8-flash
```

- `AI_PROVIDER_CHAIN`：逗号分隔的供应商前缀；第一个配置了 Key 的供应商作为任务首选。
- `AI_FALLBACK_CHAIN`：可选的显式模型顺序，格式为 `PREFIX:model`。每个模型只尝试一次，可跨供应商交错，避免请求集中在同一个免费端点。
- `AI_MODEL_MAX_TOKENS`：JSON 对象，按模型 ID 覆盖输出上限；未配置的模型使用调用方传入的 `max_tokens`。
- 不设置 `AI_FALLBACK_CHAIN` 时，仍按供应商分组，并使用 `{PREFIX}_FALLBACK_MODEL`、`{PREFIX}_FALLBACK_MODEL_2` 等变量。

> 翻译和洞察的当前首选模型由 `AI_MODEL_TRANSLATE` / `AI_MODEL_INSIGHTS` 指定。打分已交给 Jev，不再由 LLM 评分模型承担。

### 添加供应商的三步法

1. 在 `AI_PROVIDER_CHAIN` 中追加前缀名。
2. 配置该前缀的三要素：`{前缀}_API_KEY`、`{前缀}_BASE_URL`、`{前缀}_MODEL`。
3. 在 `AI_FALLBACK_CHAIN` 中按需要插入 `前缀:模型`；也可继续使用编号式 `{前缀}_FALLBACK_MODEL*` 做供应商内降级。

### 预置供应商示例

```bash
# ── OpenRouter（当前任务首选）──
OPENROUTER_API_KEY=sk-or-v1-xxxx
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=baidu/ernie-5.5-flash-preview:free

# ── SenseNova / Token Plan（交错降级）──
SENSENOVA_API_KEY=sk-xxxxxxxxxxxxxxxx
SENSENOVA_BASE_URL=https://api.sensenova.cn/compatible-mode/v2
SENSENOVA_MODEL=deepseek-flash
# 显式链中的 SenseNova 模型统一走 Token Plan
SENSENOVA_FALLBACK_BASE_URL=https://token.sensenova.cn/v1
# 留空则复用 SENSENOVA_API_KEY；CI 中注入 SENSENOVA_TP_API_KEY
SENSENOVA_FALLBACK_API_KEY=

# ── Groq（可选降级供应商）──
GROQ_API_KEY=gsk_xxxx
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=moonshotai/kimi-k2-instruct-0905
```

### 模型级输出上限

`AI_MODEL_MAX_TOKENS` 的键必须与请求中的模型 ID 完全一致。当前配置：

| 模型 | `max_tokens` | 说明 |
|------|-------------:|------|
| OpenRouter Ernie | 60,000 | 免费模型，保留充足输出空间 |
| SenseNova `deepseek-flash` | 240,000 | Token Plan 长输出配置 |
| OpenRouter Nemotron Super | 60,000 | 低于 131,072 输出上限 |
| SenseNova `sensenova-6.8-flash-lite` | 60,000 | 适配 Token Plan 约 64K 输出快照 |
| OpenRouter Nemotron Lightning | 60,000 | 低于 65,536 输出上限，避免推理 token 吃满小额预算 |
| SenseNova `sensenova-6.8-flash` | 60,000 | 适配 Token Plan 约 64K 输出快照 |

> ⚠️ **限流提醒**：交错链把连续失败分散到不同供应商，降低单端点 RPM 压力；Token Plan 调用仍受 `TP_MIN_INTERVAL_SECONDS=15` 的全局间隔保护。

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

### 场景 A：OpenRouter + SenseNova 交错降级（当前生产配置）

使用第 2 节的完整 `AI_PROVIDER_CHAIN`、`AI_FALLBACK_CHAIN` 和 `AI_MODEL_MAX_TOKENS` 配置。关键参数：

```bash
AI_PROVIDER_CHAIN=OPENROUTER,SENSENOVA
AI_MODEL_TRANSLATE=baidu/ernie-5.5-flash-preview:free
AI_MODEL_INSIGHTS=baidu/ernie-5.5-flash-preview:free
SENSENOVA_FALLBACK_BASE_URL=https://token.sensenova.cn/v1
AI_BATCH_SIZE=15
AI_BATCH_SIZE_TP=30
AI_MAX_BATCH_SIZE=30
AI_BATCH_COOLDOWN=15
```

> OpenRouter 作为首选；失败后依次交替到 SenseNova Token Plan 和 OpenRouter 的其他模型。每个模型的输出上限由 `AI_MODEL_MAX_TOKENS` 单独控制。

### 场景 B：Groq 免费用户（极速推理备选）

```bash
AI_PROVIDER_CHAIN=GROQ
GROQ_API_KEY=gsk_xxxx
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=moonshotai/kimi-k2-instruct-0905
AI_BATCH_SIZE=30
AI_MAX_BATCH_SIZE=30
AI_BATCH_COOLDOWN=15
```

### 场景 C：多供应商降级链（高可用）

```bash
AI_PROVIDER_CHAIN=SENSENOVA,GROQ,OPENROUTER
# SenseNova 限流 → 自动切 Groq → 再挂切 OpenRouter
# 三要素分别配置...
AI_BATCH_SIZE=15
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

### 场景 E：长期稳定运行（SenseNova 限免到期后）

```bash
SENSENOVA_MODEL=DeepSeek-R1-Distill-Qwen-14B     # 永久免费，32K 上下文
SENSENOVA_FALLBACK_MODEL=DeepSeek-R1-Distill-Qwen-32B
AI_MODEL_TRANSLATE=DeepSeek-R1-Distill-Qwen-14B
AI_MODEL_INSIGHTS=DeepSeek-R1-Distill-Qwen-14B
```

> 适用：担心 2026-08-09 限免到期、需要长期稳定运行的场景。Distill 系列推理能力弱于原生 R1，但永久免费 + 32K 上下文已能覆盖 99% 翻译/洞察任务。

---

## 7. 故障排查

| 现象 | 原因 | 解决方案 |
|------|------|---------|
| `⚠️ JSON 结构受损，正则抢救出 N 条` | 批次太大，AI 输出被截断 | 调小 `AI_MAX_BATCH_SIZE` |
| `⚠️ [主模型] 失败，降级到 [xxx]` | 兜底模型 API 故障或限流 | 检查 API Key / 等待限流恢复 |
| `⚠️ AI_BATCH_SIZE=50 超过安全上限 30` | 配置超限 | 同步调大 `AI_MAX_BATCH_SIZE` 或调小 `AI_BATCH_SIZE` |
| SenseNova `429 Rate Limit Exceeded` | 触发 1 QPS / 6 RPM 限流 | 调大 `AI_BATCH_COOLDOWN`、减小 `AI_BATCH_SIZE` |
| SenseNova `400 reasoning_content is required` | R1 多轮对话特有（本项目单轮不触发） | 确认使用场景为单轮（打分/翻译/洞察）；如做多轮，参考 docs/api/sensenova-best-practices.md §3.1 |
| 翻译/洞察结果缺失 | 补抓失败或缓存过期 | 删除 `output/intermediate/` 重新运行 |
| 飞书推送失败 | Token 过期或网络问题 | 检查飞书配置三要素 |
