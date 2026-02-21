"""
配置文件
"""

# 监控的 Twitter 账号列表
ACCOUNTS = [
    # ===== AI / 人工智能（核心人物）=====
    "karpathy",          # Andrej Karpathy - 前特斯拉AI总监
    "sama",              # Sam Altman - OpenAI CEO
    "ylecun",            # Yann LeCun - Meta首席科学家
    "drfeifei",          # 李飞飞 - 斯坦福/World Labs
    "demishassabis",     # Demis Hassabis - DeepMind CEO
    "DarioAmodei",       # Dario Amodei - Anthropic CEO
    "DrJimFan",          # Jim Fan - NVIDIA 具身AI
    "ilyasut",           # Ilya Sutskever - SSI 联合创始人
    "AndrewYNg",         # 吴恩达 - AI教育先驱
    "mustafasuleyman",   # Mustafa Suleyman - Microsoft AI CEO
    "hardmaru",          # David Ha - Sakana AI CEO

    # ===== 科技公司 CEO =====
    "satyanadella",      # Satya Nadella - Microsoft CEO
    "sundarpichai",      # Sundar Pichai - Google CEO
    "elonmusk",          # Elon Musk - SpaceX/Tesla/xAI
    "tim_cook",          # Tim Cook - Apple CEO

    # ===== 芯片 / 硬件 =====
    "nvidia",            # NVIDIA 官方
    "LisaSu",            # Lisa Su - AMD CEO
    "AMD",               # AMD 官方
    "IntelCorp",         # Intel 官方
    "arm",               # ARM 官方
    "Qualcomm",          # 高通官方

    # ===== 航天 =====
    "SpaceX",            # SpaceX 官方
    "blueorigin",        # Blue Origin 官方
    "NASA",              # NASA 官方

    # ===== 机器人 / 自动驾驶 =====
    "BostonDynamics",    # Boston Dynamics
    "rodneyabrooks",     # Rodney Brooks - iRobot创始人
    "figure_robot",      # Figure AI - 人形机器人
    "Waymo",             # Waymo 自动驾驶
    "UnitreeRobotics",   # 宇树科技 - 中国机器人

    # ===== 科技投资 / 经济 =====
    "naval",             # Naval Ravikant - 投资人+哲学
    "chamath",           # Chamath - Social Capital
    "pmarca",            # Marc Andreessen - a16z
    "paulg",             # Paul Graham - YC 创始人
    "RayDalio",          # Ray Dalio - 桥水基金
    "CathieDWood",       # Cathie Wood - ARK Invest
    "balajis",           # Balaji Srinivasan - 科技+加密

    # ===== 科技媒体 / 分析 =====
    "techreview",        # MIT Technology Review
    "WIRED",             # WIRED
    "theinformation",    # The Information
    "technology",        # Bloomberg Technology
    "lexfridman",        # Lex Fridman - 播客/访谈
    "benthompson",       # Ben Thompson - Stratechery

    # ===== 中文科技大V =====
    "kaifulee",          # 李开复 - 创新工场，AI投资
    "dotey",             # 宝玉 - AI前沿内容翻译/科普
    "op7418",            # 歸藏 - AI产品/设计/工具评测
    "vikingmute",        # Viking - 前端/AI开发实践
    "FinanceYF5",        # AI Will - 财经/AI分析
    "9hills",            # 九原客 - 科技投资
    "0xSunNFT",          # 0xSun - AI+Crypto
    "mazhengbo",         # 马正波 - AI创业/产品
    "realGeorgeHotz",    # George Hotz - comma.ai/tinygrad 极客

    # ===== AI 公司/实验室官方（海外）=====
    "OpenAI",            # OpenAI 官方
    "AnthropicAI",       # Anthropic 官方
    "GoogleDeepMind",    # Google DeepMind 官方
    "xAI",               # xAI 官方（Musk）
    "MistralAI",         # Mistral AI 官方
    "MetaAI",            # Meta AI 官方
    "StabilityAI",       # Stability AI 官方
    "midjourney",        # Midjourney 官方
    "perplexity_ai",     # Perplexity AI 官方

    # ===== 科技巨头官方 =====
    "Google",            # Google 官方
    "Microsoft",         # Microsoft 官方
    "Apple",             # Apple 官方
    "Meta",              # Meta 官方
    "Tesla",             # Tesla 官方
    "Amazon",            # Amazon 官方

    # ===== 政治 / 政策 / 经济机构 =====
    "realDonaldTrump",   # Trump
    "POTUS",             # 美国总统官方
    "WhiteHouse",        # 白宫官方
    "federalreserve",    # 美联储
    "IMFNews",           # 国际货币基金组织
    "WorldBank",         # 世界银行
    "EU_Commission",     # 欧盟委员会

    # ===== 中国AI公司官方 =====
    "deepseek_ai",       # DeepSeek 官方
    "zhipuai",           # 智谱AI 官方
    "Baidu_Inc",         # 百度官方
    "BaiduResearch",     # 百度研究院
    "01ai_yi",           # 零一万物 Yi
    "SenseTimeGroup",    # 商汤科技
    "Moonshot_AI",       # Moonshot/Kimi

    # ===== 财经媒体 =====
    "business",          # Bloomberg 彭博
    "FT",                # Financial Times 金融时报
    "TheEconomist",      # The Economist 经济学人
    "WSJ",               # Wall Street Journal 华尔街日报

    # ===== 中国媒体 =====
    "CGTNOfficial",      # CGTN 中国国际电视台
    "XHNews",            # 新华社
    "PDChina",           # 人民日报

    # ===== AIGC / 生成式AI =====
    "runwayml",          # Runway - AI视频生成
    "pika_labs",         # Pika - AI视频生成
    "sunomusic",         # Suno - AI音乐生成
    "elevenlabsio",      # ElevenLabs - AI语音
    "LumaLabsAI",        # Luma AI - 3D生成
    "adobefirefly",      # Adobe Firefly - AI创意工具
    "huggingface",       # Hugging Face - 开源AI社区
    "cursor_ai",         # Cursor - AI编程IDE
    "v0",                # Vercel v0 - AI前端生成
    "cognition_labs",    # Cognition Labs - Devin AI编程

    # ===== 科学/研究机构 =====
    "Nature",            # Nature 自然杂志
    "ScienceMagazine",   # Science 科学杂志
    "arxiv",             # arXiv 预印本
]

# 每个账号最多抓取多少条推文
TWEETS_PER_ACCOUNT = 10

# 只保留最近 N 小时的推文
HOURS_LOOKBACK = 72

# 输出语言
LANGUAGE = "zh-CN"

# 总结提示词
SUMMARY_PROMPT = """
你是一位科技资讯编辑。请将以下 Twitter 推文内容整理为日报格式：

要求：
1. 按领域分类（AI、航天、机器人、经济、其他）
2. 每条推文格式如下：
   - **@用户名（日期）**
   - 原文：[保留英文原文]
   - 翻译：[中文翻译]
   - 要点：[1-2 句核心洞察]
3. 在报告开头写一段「今日趋势总结」（3-5 句话）
4. 过滤掉纯转发、纯表情、无实质内容的推文
5. 政治/情绪化内容如果没有技术或经济洞见，也过滤掉

保持简洁、专业、信息密度高。
"""
