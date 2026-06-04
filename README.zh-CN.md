# X-Digest

> **5 分钟 · 200+ 科技大 V · 零 API 费用**
> 每天一份可决策的科技日报，不是另一份推文 RSS。

[English](#english) · [快速开始](#快速开始) · [配置文档](docs/configuration-guide.md) · [更新日志](docs/changelog.md)

---

## 一个真实场景

你关注了 233 个科技账号，昨晚有 800 条新推文。

- 早上 9 点，你有 30 分钟准备开周会。
- 你打开 X 客户端，瀑布流把 *Sam Altman 关于 GPT-6 的传闻*、*某 KOL 的早餐照片*、*Sora 2 视频泄露* 混在一起。
- 半小时过去，你只看到 50 条，其中 5 条有价值。
- 你错过了 *NVIDIA Blackwell B200 评测*，错过了一份价值 $50K 的 B2B 询盘。

**X-Digest 在你睡觉时已经做完这件事：**

- ✅ 把 800 条压成 30 条，**每条都过了两个独立 AI 评委**
- ✅ 自动翻译非中文推文，**保留原文对照**
- ✅ 自动写好"💡 小贴士"和"🧠 启示"，**你直接看洞察，不必先搞懂术语**
- ✅ 推送到飞书群，开会前 3 分钟看完

---

## 实测效果

下面这段是 `test_pipeline.py` 跑出的真实产出（[B200 GPU 推文](https://x.com/NVIDIAGeForce)）：

> **@NVIDIAGeForce**
>
> 🔗 [原推](https://x.com/NVIDIAGeForce)
> *Our Blackwell B200 GPU features 208 billion transistors and is connected by the 1.8TB/s Fifth-Generation NVLink. This is a massive leap for LLM training.*
>
> 📝 **译文**：我们的 Blackwell B200 GPU 搭载了 2080 亿个晶体管，并通过 1.8TB/s 的第五代 NVLink 连接。这是 LLM 训练领域的一大飞跃。
>
> 💡 **小贴士**：B200 是英伟达最新 GPU，2080 亿晶体管相当于把整个城市的人口塞进指甲盖大小的芯片；NVLink 是芯片间超高速数据线，第五代速度比光纤还快 10 倍，专门给 AI 大模型训练用的超级高速公路。
>
> 🧠 **启示**：在 AI 算力军备竞赛白热化阶段，B200 的晶体管密度和互联带宽直接决定大模型训练效率。这种硬件突破将加速万亿参数模型普及，可能引发新一轮 AI 应用爆发。

**每条推文都被转译成"决策素材"——不是再读一遍英文，而是拿到背景、意义、行动建议。**

---

## 三步工作流

```
┌──────────────┐     ┌────────────────┐     ┌────────────────┐
│  ① 抓取      │     │  ② 分析        │     │  ③ 推送        │
│  Playwright  │ ──> │  跨端点双打分   │ ──> │  飞书 / 文档   │
│  多账号并发  │     │  + 翻译 + 洞察  │     │  PDF / 飞书    │
└──────────────┘     └────────────────┘     └────────────────┘
   72h 滚动合拢        双 AI 评委 80 分海选       Markdown / 飞书
```

| 阶段 | 耗时 | 关键能力 |
|------|------|---------|
| 抓取 | 3 min (3 账号) | 72h 滚动合拢、Per-Context 隔离、智能降温 |
| 分析 | 5-8 min | 跨端点双打分、自动科普、启示生成 |
| 推送 | 10s | 飞书群 / 飞书文档 / PDF / 本地存档 |

> 单条 pipeline 端到端 **< 12 分钟**。每天定时跑一次，醒来就有日报。

---

## 为什么不是 X 官方 API？

| 方案 | 月费 | 读取额度 | 现实 |
|------|------|----------|------|
| X Free | $0 | **不能读取** | 拿不到任何推文 |
| X Basic | **$200/月** | 10,000 条/月 | 抓 200 个账号 × 50 条就用完 |
| X Pro | **$5,000/月** | 1M 条/月 | 个人用户不可能承受 |
| **X-Digest** | **$0** | **无限制** | 用 Cookie 挂载 + 浏览器自动化 |

每年省 **$2,400+**（约 ¥17,000），数据量、搜索窗口、AI 集成全部更好。

---

## 核心特性

### 1. 跨端点双打分引擎

两个不同端点、不同模型的 AI 评委**同时打分**，取交集——既不漏好内容，也不让单一模型的偏见通过：

```
sensenova-6.7-flash-lite  @token.sensenova.cn/v1     ─┐
                                                      ├─> 取 ≥80 分交集
DeepSeek-R1-Distill-Qwen-14B @api.sensenova.cn/v2    ─┘
```

**为什么这么做：** 单一 AI 评分会过拟合自己的偏好（喜欢简短的、喜欢 technical 的、忽略中文推文）。双引擎 + 不同端点 = 互相纠错 + 限流隔离。详见 `pipeline/score.py:42`。

### 2. 永久免费的 AI 翻译

**DeepSeek-R1-Distill-Qwen-14B** 翻译，术语保留率 67%（V3-1/R1 都只有 48%）。**永久免费**——不受 2026-08-09 限免到期影响。

### 3. 多账号并发抓取

放 `x_cookies_1.json` 就开 1 路，放 3 个就开 3 路，**线性扩展**。单账号抓 200 个账号 8 分钟，3 账号 3 分钟。

### 4. 72h 推文池滚动合拢

即使每天只抓一部分账号，3 天内的所有推文都自动合并去重——**不遗漏、不重复**。

### 5. 自动科普与启示

每条推文都附"💡 小贴士"（解释术语）和"🧠 启示"（行业意义）。让没背景的人也能读懂，让有背景的人立刻看到重点。

### 6. 飞书原生集成

日报直接推送到飞书群 / 飞书文档 / PDF附件。开会前打开飞书，3 分钟看完一天精华。

---

## 快速开始

### 5 分钟跑起来

```bash
# 1. 装依赖（Python 3.12+）
uv pip install -r requirements.txt
uv run playwright install chromium

# 2. 配 API Key
cp .env.example .env
# 编辑 .env，填入 SENSENOVA_API_KEY（默认走商汤，零费用）

# 3. 导 Cookie（Chrome 装 Cookie-Editor 插件 → 导出 JSON）
# 保存为 x_cookies_1.json（多账号：x_cookies_2.json ...）

# 4. 跑
uv run python main.py
```

交互式 UI 引导选领域、回溯时长、回溯窗口。一键生成日报。

非交互模式（CI 用）：
```bash
uv run python main.py --manual --hours 24
```

### 项目结构

```
x-digest/
├── main.py                  # 主程序 + 交互 UI + 飞书推送
├── fetcher.py               # 多账号并发抓取引擎
├── config.py                # 供应商降级链 + 运行参数
├── pipeline/                # AI 处理管线
│   ├── score.py             #   跨端点双打分引擎
│   ├── translate.py         #   翻译（Distill-14B）
│   ├── insights.py          #   洞察（sensenova-6.7-flash-lite）
│   ├── curate.py            #   策展去重
│   ├── assemble.py          #   报告装配
│   └── orchestrator.py      #   管线编排
├── custom_accounts.json     # 关注账号（6 领域 233 账号）
├── defaults/                # 推荐账号
├── docs/                    # 配置指南 / 更新日志
└── output/                  # 日报 + PDF + 审计报告
```

---

## 路线图

- [x] 跨端点双打分引擎（v2.0, 2026-06）
- [x] 永久免费 AI 翻译（v2.0）
- [x] 飞书原生集成（v1.5）
- [ ] 微信公众号 / 邮件订阅（v3.0）
- [ ] 自定义分类与多租户（v3.0）
- [ ] 桌面端 / iOS Widget 推送（v3.5）

---

## 高级配置

详见 [`docs/configuration-guide.md`](docs/configuration-guide.md)。要点：

| 关注点 | 在哪配 |
|--------|--------|
| AI 供应商降级链 | `.env` 中 `AI_PROVIDER_CHAIN=SENSENOVA,GROQ,OPENROUTER` |
| 打分模型（双引擎） | `pipeline/score.py` 中 hardcode |
| 翻译模型 | `AI_MODEL_TRANSLATE=DeepSeek-R1-Distill-Qwen-14B` |
| 洞察模型 | `AI_MODEL_INSIGHTS=sensenova-6.7-flash-lite` |
| 关注账号 | `custom_accounts.json` |
| 飞书凭据 | GitHub Secrets |

---

## 致谢

- 抓取层：[Playwright](https://playwright.dev/python/) + [playwright-stealth](https://github.com/nicedouble/playwright-stealth-python)
- AI 层：[商汤日日新 SenseNova](https://platform.sensenova.cn/) + [Token Plan](https://token.sensenova.cn/)（限免期间零费用）
- 推送层：[飞书开放平台](https://open.feishu.cn/)

---

## License

[MIT](LICENSE) · 仅供学习研究，请遵守 X 平台服务条款。

---

<a id="english"></a>
## English Summary

**X-Digest** is an AI-driven Twitter intelligence engine. It uses Playwright browser automation (with mounted cookies, bypassing X's expensive official API) to scrape tweets from 200+ tech accounts, then runs a cross-endpoint dual-AI scoring engine (sensenova-6.7-flash-lite + DeepSeek-R1-Distill-Qwen-14B), translates non-Chinese tweets, and generates insight-rich daily reports with auto-generated analogies and industry implications. Reports are pushed to Feishu (飞书) groups as Markdown + PDF.

**Why it exists:** X's official API costs $200-$42,000/month. X-Digest costs $0 and integrates translation + insights + delivery out of the box.

**Stack:** Python 3.12 + asyncio + Playwright + SenseNova (DeepSeek models, free tier) + Feishu OpenAPI.

---

<p align="center">
  <i>Built with Playwright, powered by AI. Engineered for insight.</i>
</p>
