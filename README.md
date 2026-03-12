# 🛰️ X-Digest 科技情报自动汇总系统

X-Digest 是一个专为科技从业者、投资人和极客设计的 Twitter 情报聚合工具。它利用 Playwright 自动化技术突破数据获取壁垒，结合 **Kimi K2 (moonshotai/kimi-k2-instruct-0905)** 的长上下文理解能力，将 Twitter 上的海量行业动态转化为精炼、具备深度洞察的中英对照情报日报。

---

## 💎 情报处理哲学：极致精简三要素
本项目拒绝信息过载，生成的每一条情报均经过 AI 深度脱水，严格遵循以下结构：
1.  **原文直达**：保留 100% 完整推文，正文后紧跟 `[[🔗]](URL)`，一键直达原帖。
2.  **精炼译文**：智能识别语言，仅在非中文推文下提供专业编译，消除阅读冗余。
3.  **深度启示**：`💡 深度启示` 模块直接点出消息背后的行业价值、潜在机会或技术演进。

---

## 🚀 核心技术特性
- **72h 推文池大合拢**：引入持久化推文池机制，即使每日轮转抓取不同博主，报告也会自动合拢过去 72 小时内的全量存留资讯。
- **Kimi K2 长上下文优化**：利用 90+ 条目的大批次并发处理能力，实现资讯间的关联分析与全局趋势总结。
- **PDF 自动化同步渲染**： MD 生成的同时自动导出符合 **Google Material / 极简主义** 审美的高清 A4 PDF 报告。
- **智能爬虫策略**：具备 9 小时扫描冷却保护，自动识别“博主未发推”状态并闪电跳过，保护账号安全。

---

## 🛠 快速开始

### 1. 环境准备
项目基于 Python 3.12+，强制使用 `uv` 进行依赖管理。
```bash
# 安装 uv (如果尚未安装)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装依赖
uv pip install -r pyproject.toml
uv pip install markdown

# 安装浏览器引擎
uv run playwright install chromium
```

### 2. 配置敏感数据 (关键)
复制项目根目录下的 `.env.example` 为 `.env`，并填写相关参数。

**本项目支持任何兼容 OpenAI 协议的 API 服务商：**
- **AI_BASE_URL**: 接口地址（如 `https://api.moonshot.cn/v1`）。
- **AI_API_KEY**: 您的 API 密钥。
- **AI_MODEL**: 模型名称（如 `kimi-k2-thinking`）。

常见的服务商预设（Kimi, Groq, DeepInfra, SiliconFlow）已在 `.env.example` 中列出，只需填入对应的三要素即可无缝切换。

### 3. 导出 Twitter Cookie (核心避坑)
本项目不使用账号密码登录，而是挂载本地 Cookie 以降低被 X 平台风控的概率。
1. 在 Chrome 浏览器安装 **EditThisCookie** 插件。
2. 登录您的 Twitter (X) 账号。
3. 点击插件，选择“导出” (格式为 JSON)。
4. 将导出的内容保存为项目根目录下的 **`browser_cookies.json`**。
*注：此文件已加入 .gitignore，请放心使用。*

### 4. 自定义关注列表 (可选)
项目默认仅关注 3 位核心大V（Musk, Karpathy, Altman）。如果您想抓取更多账号：
1. 参考 **`defaults/suggested_accounts.json`**，其中收录了 100+ 位科技/AI 领域的推荐账号。
2. 在根目录创建 **`custom_accounts.json`**。
3. 按照以下格式填写（用户名: 简介）：
   ```json
   {
     "ID_1": "博主简介 1",
     "ID_2": "博主简介 2"
   }
   ```
4. 重新启动程序，系统将自动优先加载您的私有列表。

---

## 🎮 运行与交互控制台

直接运行主程序即可进入智能交互模式：
```bash
uv run python main.py
```

### 快捷键指南：
| 按键 | 模式 | 实战场景 |
| :--- | :--- | :--- |
| **`Enter` (A)** | **自动轮询** | 日常使用。自动抓取今日批次博主，汇总 72h 全量内容。 |
| **`F`** | **全量扫描** | 突发大新闻时。强制一次性扫描全部 100+ 博主。 |
| **`1 / 2 / 3`** | **指定批次** | 手动查漏补缺特定的博主分组。 |
| **`C`** | **高级自定义** | 灵活调整回溯时长（如生成周报）或开启强制重扫。 |

---

## ⚙️ 进阶配置 (`config.py`)
- **`ACCOUNTS`**: 字典格式，存储博主 ID 及其一句话背景简介（将显示在日报中）。
- **`ACCOUNT_SCAN_INTERVAL`**: 冷却时间（默认 9h），保障账号频率安全。
- **`AI_BATCH_SIZE`**: 建议设为 90-150，充分发挥长上下文模型的理解力。

---

## 📂 产出展示
- **本地存档**: `output/YYYY-MM-DD-HHMM.md` & `.pdf`
- **飞书推送**: 自动创建精美飞书文档，并通过机器人实时推送至您的飞书 App。

---

## ⚠️ 免责声明 (Disclaimer)
1.  **非官方工具**：本项目仅利用 Playwright 模拟浏览器行为，并非 X (Twitter) 官方 API 工具。
2.  **合规性**：请确保使用行为符合 X 平台服务条款及当地法律。由此产生的账号风禁，本项目不承担任何责任。
3.  **仅供学习**：代码仅供技术研究与 AI 编译实验，严禁用于恶意爬虫或商业营利。

---

## 📄 开源协议
本项目采用 [MIT License](LICENSE) 许可协议。

*Powered by Gemini AI & Moonshot Kimi K2. Optimized for Modern Tech Insight.*
