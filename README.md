# X-Digest

**AI 驱动的 Twitter 情报聚合引擎** — 自动抓取、翻译、分析，生成专业级科技日报。

```
 ██╗  ██╗       ██████╗ ██╗ ██████╗ ███████╗███████╗████████╗
 ╚██╗██╔╝       ██╔══██╗██║██╔════╝ ██╔════╝██╔════╝╚══██╔══╝
  ╚███╔╝███████╗██║  ██║██║██║  ███╗█████╗  ███████╗   ██║
  ██╔██╗╚══════╝██║  ██║██║██║   ██║██╔══╝  ╚════██║   ██║
 ██╔╝ ██╗       ██████╔╝██║╚██████╔╝███████╗███████║   ██║
 ╚═╝  ╚═╝       ╚═════╝ ╚═╝ ╚═════╝ ╚══════╝╚══════╝   ╚═╝
```

> 每天 5 分钟，掌握 200+ 科技大 V 的核心动态。

---

## 为什么需要 X-Digest?

| 痛点 | X-Digest 方案 |
|------|--------------|
| 刷 Twitter 一小时只看到 10% 有价值内容 | AI 自动过滤噪音，只保留**有洞察价值**的推文 |
| 英文推文阅读慢 | 自动中英对照翻译，不丢原文语境 |
| 跨领域信息分散 | 6 大领域分类聚合，一份报告纵览全局 |
| 怕错过关键信息 | 72h 推文池滚动合拢，**不遗漏、不重复** |

---

## 核心架构

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│  Playwright  │───>│   AI 管线    │───>│  报告生成   │───>│   多端推送    │
│  双账号并发   │    │  翻译+洞察   │    │  MD / PDF   │    │  飞书 / 本地  │
└─────────────┘    └──────────────┘    └─────────────┘    └──────────────┘
     抓取层              分析层              输出层              分发层
```

### 数据流

```
200+ 账号 ──> 双 Cookie 并发抓取 ──> 72h 推文池去重合拢
                                          │
                            ┌──────────────┴──────────────┐
                            ▼                              ▼
                     智能翻译 (中英对照)            深度洞察分析
                            │                              │
                            └──────────────┬──────────────┘
                                           ▼
                                  Markdown / PDF 日报
                                           │
                              ┌─────────────┼─────────────┐
                              ▼             ▼             ▼
                          本地存档      飞书文档       飞书消息
```

---

## 技术亮点

### 1. 双账号并发抓取引擎

X-Digest 独创的 **Per-Context 队列架构**，在保障账号安全的前提下实现真正的并行抓取：

```
Cookie #1 队列：@karpathy → @ylecun → @drfeifei → @nvidia → ...
                  ↕ 并行执行
Cookie #2 队列：@elonmusk → @AndrewYNg → @DrJimFan → @gdb → ...
```

| 特性 | 说明 |
|------|------|
| 会话预热 | 每个 Cookie 先访问首页激活会话，避免冷启动失败 |
| Per-Context 隔离 | 同一 Cookie 内严格串行，不同 Cookie 间真并发 |
| 跨号重试 | 失败账号自动切换到另一个 Cookie 重试 |
| 智能降温 | 连续失败 5 次自动冷却 30s，保护 IP |
| 错误页检测 | 自动识别 "Something went wrong" 并原地刷新恢复 |

**实测数据（8 账号 / 24h 窗口）：**

```
成功率 ········ 100% (8/8)
总耗时 ········ 158.7s
平均每账号 ···· 19.8s
首轮零重试 ···· 双 Cookie 负载均衡，全部一次成功
```

### 2. AI 管线 — 翻译 + 洞察

采用 **供应商降级链** 架构，支持任意 OpenAI 协议兼容服务商热切换：

```
主模型 (Kimi K2) ──失败──> 备选 1 (Groq) ──失败──> 备选 2 (ZhipuAI) ──...
```

每条推文经过三层处理：

| 层级 | 功能 | 输出 |
|------|------|------|
| 原文层 | 完整保留推文 + `[🔗]` 链接 | 一键直达原帖 |
| 翻译层 | 智能识别语言，非中文自动编译 | 中英对照 |
| 洞察层 | `💡 深度启示` — 行业价值与趋势解读 | 投资/技术决策参考 |

### 3. 72h 推文池滚动合拢

```
Day 1 抓取 ──┐
Day 2 抓取 ──┼──> 推文池 (去重 + 时间窗口) ──> 生成报告时合拢 72h 全量
Day 3 抓取 ──┘
```

即使每次只扫描部分账号，报告也会自动包含过去 72 小时内所有已收集的推文，确保信息完整性。

### 4. 账号健康度监控

自动追踪每个账号的抓取表现，定期生成审计报告：

- **僵尸号检测** — 连续失败 5 次以上自动标记
- **沉寂号识别** — 14 天无新推文的账号
- **活跃度排行** — TOP 10 高产出账号一目了然

---

## 快速开始

### 1. 环境准备

```bash
# 安装依赖（需要 Python 3.12+，使用 uv 管理）
uv pip install -r pyproject.toml
uv pip install markdown

# 安装浏览器引擎
uv run playwright install chromium
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入 AI API Key 和代理地址
# 详细配置说明见 docs/configuration-guide.md
```

**AI 供应商支持**：Kimi K2 / Groq / OpenRouter / ZhipuAI / DeepSeek 等任意 OpenAI 协议兼容服务商。在 `.env` 中配置 `AI_PROVIDER_CHAIN` 即可设置降级链。

### 3. 导出 Twitter Cookie

本项目通过挂载浏览器 Cookie 获取数据，不使用账号密码登录：

1. Chrome 安装 **Cookie-Editor** 插件
2. 登录 X (Twitter) 账号
3. 插件导出 JSON → 保存为 `x_cookies_1.json`
4. （可选）第二个账号 → 保存为 `x_cookies_2.json`，自动启用双账号并发
5. 更多账号？`x_cookies_3.json`、`x_cookies_4.json` ... **自动扩展，放几个就开几路并发**

### 4. 自定义关注列表

编辑 `custom_accounts.json`，按领域分类添加账号：

```json
{
  "AI_Scientists_&_Academia": {
    "karpathy": "OpenAI 联合创始人",
    "ylecun": "Meta 首席 AI 科学家"
  },
  "Tech_Industry_&_CEOs": {
    "elonmusk": "Tesla / SpaceX / xAI CEO",
    "sama": "OpenAI CEO"
  }
}
```

项目已内置 6 大领域、233 个精选账号。

### 5. 运行

```bash
uv run python main.py
```

交互式 UI 引导选择领域、回溯时长，一键生成日报。

也支持非交互模式（自动选前 4 领域）：

```bash
uv run python main.py --manual --hours 24
```

---

## 项目结构

```
x_digest/
├── main.py                  # 主程序 — 交互 UI + 调度 + 飞书推送
├── fetcher.py               # 抓取引擎 — 双账号并发 + 会话预热 + 跨号重试
├── config.py                # 配置管理 — 供应商降级链 + 运行参数
├── pipeline/                # AI 处理管线
│   ├── orchestrator.py      #   管线编排器
│   ├── translate.py         #   智能翻译（中英对照）
│   ├── insights.py          #   深度洞察分析
│   ├── curate.py            #   内容策展与去重
│   ├── assemble.py          #   报告组装
│   └── shortlinks.py        #   短链接处理
├── custom_accounts.json     # 关注账号列表（6 领域 233 账号）
├── x_cookies_1.json         # Cookie #1（.gitignore）
├── x_cookies_2.json         # Cookie #2（.gitignore，可选）
├── .env                     # API Key 与配置（.gitignore）
├── defaults/                # 默认配置与推荐账号
├── output/                  # 生成的日报（MD / PDF / 审计报告）
└── docs/                    # 项目文档
```

---

## 配置参考

### 关键环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PROXY` | `http://127.0.0.1:7897` | 代理地址（国内必填） |
| `AI_PROVIDER_CHAIN` | `GROQ,OPENROUTER,ZHIPUAI` | AI 供应商降级链 |
| `HOURS_LOOKBACK` | `72` | 推文回溯时长（小时） |
| `TWEETS_PER_ACCOUNT` | `30` | 每账号最大抓取条数 |
| `AI_BATCH_SIZE` | `30` | AI 处理批次大小 |
| `ACCOUNT_SCAN_INTERVAL` | `12` | 扫描冷却时间（小时） |
| `CACHE_RETENTION_HOURS` | `720` | 推文池保留时长（30 天） |

### 产出示例

- 本地存档：`output/2026-03-25-1212.md` + `.pdf`
- 飞书文档：自动创建并推送至指定用户
- 健康审计：`output/health_report.md`（每 7 天自动生成）

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 浏览器自动化 | Playwright + playwright-stealth |
| AI 推理 | OpenAI 协议（Kimi K2 / Groq / ZhipuAI 等） |
| 数据处理 | Python asyncio + httpx |
| 报告渲染 | Markdown + Playwright PDF |
| 消息推送 | 飞书开放平台 API |
| 包管理 | uv |

---

## 免责声明

1. **非官方工具** — 本项目通过 Playwright 模拟浏览器行为获取公开数据，非 X (Twitter) 官方 API 工具。
2. **合规使用** — 请确保使用行为符合 X 平台服务条款及当地法律法规。
3. **仅供学习** — 代码仅供技术研究与 AI 编译实验，严禁用于恶意爬虫或商业营利。
4. **风险自担** — 由此产生的账号风控，本项目不承担任何责任。

---

## License

[MIT](LICENSE)

---

*Built with Playwright, powered by AI. Engineered for insight.*
