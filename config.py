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

    # ===== 航天 =====
    "SpaceX",            # SpaceX 官方
    "blueorigin",        # Blue Origin 官方
    "NASA",              # NASA 官方

    # ===== 机器人 =====
    "BostonDynamics",    # Boston Dynamics
    "rodneyabrooks",     # Rodney Brooks - iRobot创始人
    "figure_robot",      # Figure AI - 人形机器人

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
    "dotey",             # 宝玉 - AI前沿内容翻译/科普，更新极高频
    "op7418",            # 歸藏 - AI产品/设计/工具评测
    "vikingmute",        # Viking - 前端/AI开发实践
    "FinanceYF5",        # AI Will - 财经/AI分析
    "9hills",            # 九原客 - 科技投资
    "0xSunNFT",          # 0xSun - AI+Crypto
    "mazhengbo",         # 马正波 - AI创业/产品
    "realGeorgeHotz",    # George Hotz - comma.ai/tinygrad 极客

    # ===== 政治 / 政策 =====
    "realDonaldTrump",   # Trump - 政策+经济影响
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
