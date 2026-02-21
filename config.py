"""
配置文件
"""

# 监控的 Twitter 账号列表（15 个）
ACCOUNTS = [
    # AI / 人工智能
    "karpathy",
    "sama",
    "ylecun",
    "drfeifei",
    # 航天
    "elonmusk",
    "EverydayAstronaut",
    # 机器人
    "BostonDynamics",
    "rodneyabrooks",
    # 科技经济
    "naval",
    "chamath",
    "realDonaldTrump",
    # 科技媒体
    "techreview",
    "WIRED",
    "theinformation",
    "technology",
]

# 每个账号最多抓取多少条推文
TWEETS_PER_ACCOUNT = 3

# 输出语言
LANGUAGE = "zh-CN"

# 总结提示词
SUMMARY_PROMPT = """
你是一位科技资讯编辑。请将以下 Twitter 推文内容：
1. 翻译成中文
2. 按领域分类（AI、航天、机器人、经济、其他）
3. 提炼每条的核心要点（1-2 句话）
4. 如果有重要趋势或洞察，在开头写一段总结

保持简洁、专业、信息密度高。
"""
