# X-Digest 科技摘要自动生成器

这是一个使用 Playwright 抓取 Twitter (X) 大V动态，并通过大语言模型进行自动化摘要和翻译，最后推送到飞书文档与飞书群的工具。

## 🤖 当前使用的 AI 模型
本项目调用了 **Groq** 的极速推理 API 进行文本总结。
当前配置的默认大模型为：
**`llama-3.3-70b-versatile`**

*该模型是 Llama 3.3 的 70B 版本，作为全能型模型，在长上下文和复杂翻译总结任务上表现出色，同时得益于 Groq 的 LPU 硬件加速，能够实现极低延迟的瞬间响应。*

---

## 🚀 功能特性
1. **自动化爬虫**：基于 Playwright 挂载本地登录态 (Cookie)，无需官方昂贵的 API Key 即可批量拉取 100+ 行业领袖和机构的主页推文。
2. **富内容支持**：不仅抓取纯文本推文，还会自动识别**转发内容**以及**图片链接**，即使是无文字的纯图片推文也不会遗漏。
3. **极速 AI 总结**：使用 Groq + Llama 3.3 70B 模型，以极高的吞吐量提炼要点、翻译原文、并输出 5 条核心亮点。
4. **多端发布**：自动生成结构化的飞书在线文档，并通过飞书机器人直接在工作群推送早报。

---

## 🛠 依赖配置与运行

### 环境准备
项目使用 `uv` 进行环境与依赖管理。
```bash
# 1. 确保安装了 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 安装浏览器依赖 (首次运行 Playwright 需要)
uv run playwright install chromium
```

### 必需文件
运行前，请确保项目根目录下存在以下文件及配置：

1. **`browser_cookies.json`**
   - 包含你的 Twitter 登录 Cookie (使用浏览器插件如 EditThisCookie 导出为 JSON 格式)。

2. **`.env`** 配置文件，格式如下：
   ```env
   # 代理地址 (由于国内网络需要，保障 Playwright 访问 x.com)
   PROXY=http://127.0.0.1:8118
   
   # Groq 极速 API
   GROQ_API_KEY=gsk_your_api_key_here
   GROQ_MODEL=llama-3.3-70b-versatile
   
   # 飞书应用配置
   FEISHU_APP_ID=cli_a...
   FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx
   FEISHU_USER_ID=ou_xxxxxxx
   ```

### 运行方式
执行主程序，全量抓取并生成报告：
```bash
uv run python main.py
```
单账号测试链路(可快速验证 Cookie 和 爬虫状态)：
```bash
uv run python test_scraper.py
```