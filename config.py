"""
配置文件
"""

# 监控的 Twitter 账号列表 (字典格式：用户名: 一句话简介)
ACCOUNTS = {
    # ===== AI / 人工智能（核心人物）=====
    "karpathy": "Andrej Karpathy - 前特斯拉AI总监，OpenAI创始成员",
    "sama": "Sam Altman - OpenAI CEO",
    "ylecun": "Yann LeCun - Meta首席科学家，图灵奖得主",
    "drfeifei": "李飞飞 - 斯坦福教授，World Labs创始人",
    "demishassabis": "Demis Hassabis - Google DeepMind CEO",
    "DarioAmodei": "Dario Amodei - Anthropic CEO",
    "DrJimFan": "Jim Fan - NVIDIA 高级研究科学家，具身AI专家",
    "ilyasut": "Ilya Sutskever - SSI 联合创始人，前OpenAI首席科学家",
    "AndrewYNg": "吴恩达 - AI教育先驱，Coursera创始人",
    "mustafasuleyman": "Mustafa Suleyman - Microsoft AI CEO",
    "hardmaru": "David Ha - Sakana AI CEO",

    # ===== 科技公司 CEO =====
    "satyanadella": "Satya Nadella - Microsoft CEO",
    "sundarpichai": "Sundar Pichai - Google CEO",
    "elonmusk": "Elon Musk - SpaceX/Tesla/xAI 创始人",
    "tim_cook": "Tim Cook - Apple CEO",

    # ===== 芯片 / 硬件 =====
    "nvidia": "NVIDIA 官方账号",
    "LisaSu": "Lisa Su - AMD CEO",
    "AMD": "AMD 官方账号",
    "IntelCorp": "Intel 官方账号",
    "arm": "ARM 官方账号",
    "Qualcomm": "高通官方账号",

    # ===== 航天 =====
    "SpaceX": "SpaceX 官方账号",
    "blueorigin": "Blue Origin 官方账号",
    "NASA": "NASA 官方账号",

    # ===== 机器人 / 自动驾驶 =====
    "BostonDynamics": "Boston Dynamics 官方账号",
    "rodneyabrooks": "Rodney Brooks - iRobot创始人，机器人专家",
    "figure_robot": "Figure AI - 人形机器人初创公司",
    "Waymo": "Waymo 自动驾驶官方账号",
    "UnitreeRobotics": "宇树科技 - 中国机器人领先企业",

    # ===== 科技投资 / 经济 =====
    "naval": "Naval Ravikant - 硅谷著名投资人，AngelList创始人",
    "chamath": "Chamath Palihapitiya - Social Capital CEO",
    "pmarca": "Marc Andreessen - a16z 联合创始人",
    "paulg": "Paul Graham - YC 创始人",
    "RayDalio": "Ray Dalio - 桥水基金创始人",
    "CathieDWood": "Cathie Wood - ARK Invest 创始人",
    "balajis": "Balaji Srinivasan - 著名投资人，前Coinbase CTO",

    # ===== 科技媒体 / 分析 =====
    "techreview": "MIT Technology Review 官方",
    "WIRED": "WIRED 杂志官方",
    "theinformation": "The Information 深度科技媒体",
    "technology": "Bloomberg Technology 官方",
    "lexfridman": "Lex Fridman - 知名科技播客主持人",
    "benthompson": "Ben Thompson - Stratechery 创始人",

    # ===== 中文科技大V =====
    "kaifulee": "李开复 - 创新工场董事长，01万物创始人",
    "dotey": "宝玉 - 资深软件工程师，AI内容译者",
    "op7418": "歸藏 - AI产品与工具评测专家",
    "vikingmute": "Viking - 资深前端开发者，AI实践者",
    "FinanceYF5": "AI Will - 财经与AI深度分析师",
    "9hills": "九原客 - 科技投资人",
    "0xSunNFT": "0xSun - AI与加密货币研究员",
    "mazhengbo": "马正波 - AI创业者，前阿里巴巴专家",
    "realGeorgeHotz": "George Hotz - comma.ai/tinygrad 创始人，天才黑客",

    # ===== AI 公司/实验室官方（海外）=====
    "OpenAI": "OpenAI 官方账号",
    "AnthropicAI": "Anthropic 官方账号",
    "GoogleDeepMind": "Google DeepMind 官方账号",
    "xAI": "xAI 官方账号",
    "MistralAI": "Mistral AI 官方账号",
    "MetaAI": "Meta AI 官方账号",
    "StabilityAI": "Stability AI 官方账号",
    "midjourney": "Midjourney 官方账号",
    "perplexity_ai": "Perplexity AI 官方账号",

    # ===== 科技巨头官方 =====
    "Google": "Google 官方账号",
    "Microsoft": "Microsoft 官方账号",
    "Apple": "Apple 官方账号",
    "Meta": "Meta 官方账号",
    "Tesla": "Tesla 官方账号",
    "Amazon": "Amazon 官方账号",

    # ===== 政治 / 政策 / 经济机构 =====
    "realDonaldTrump": "Donald Trump - 美国总统",
    "POTUS": "美国总统官方账号",
    "WhiteHouse": "白宫官方账号",
    "federalreserve": "美联储官方账号",
    "IMFNews": "国际货币基金组织官方",
    "WorldBank": "世界银行官方",
    "EU_Commission": "欧盟委员会官方",

    # ===== 中国AI公司官方 =====
    "deepseek_ai": "DeepSeek 官方账号",
    "zhipuai": "智谱AI 官方账号",
    "Baidu_Inc": "百度官方账号",
    "BaiduResearch": "百度研究院官方",
    "01ai_yi": "零一万物官方账号",
    "SenseTimeGroup": "商汤科技官方账号",
    "Moonshot_AI": "月之暗面 (Kimi) 官方账号",

    # ===== 财经媒体 =====
    "business": "Bloomberg 彭博新闻社官方",
    "FT": "Financial Times 金融时报官方",
    "TheEconomist": "The Economist 经济学人官方",
    "WSJ": "Wall Street Journal 华尔街日报官方",

    # ===== 中国媒体 =====
    "CGTNOfficial": "CGTN 中国国际电视台官方",
    "XHNews": "新华社官方账号",
    "PDChina": "人民日报官方账号",

    # ===== AIGC / 生成式AI =====
    "runwayml": "Runway - AI视频生成领先企业",
    "pika_labs": "Pika - AI视频生成平台",
    "sunomusic": "Suno - AI音乐生成平台",
    "elevenlabsio": "ElevenLabs - AI语音技术平台",
    "LumaLabsAI": "Luma AI - 3D与视频生成平台",
    "adobefirefly": "Adobe Firefly - 创意AI工具",
    "huggingface": "Hugging Face - 全球最大的开源AI社区",
    "cursor_ai": "Cursor - AI编程IDE官方",
    "v0": "Vercel v0 - AI前端生成官方",
    "cognition_labs": "Cognition Labs - Devin AI程序员官方",

    # ===== 科学/研究机构 =====
    "Nature": "Nature 自然杂志官方",
    "ScienceMagazine": "Science 科学杂志官方",
    "arxiv": "arXiv 论文预印本平台",
}

# 每个账号最多抓取多少条推文
TWEETS_PER_ACCOUNT = 15

# 只保留最近 N 小时的推文
HOURS_LOOKBACK = 72

# 输出语言
LANGUAGE = "zh-CN"

# 账号重新抓取的最小间隔 (小时)
ACCOUNT_SCAN_INTERVAL = 9

# AI 翻译总结的单次处理推文数量
AI_BATCH_SIZE = 90

# 总结提示词 (不再需要，main.py 已经内建了逻辑)
SUMMARY_PROMPT = ""
