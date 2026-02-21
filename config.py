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
TWEETS_PER_ACCOUNT = 10

# 只保留最近 N 小时的推文
HOURS_LOOKBACK = 24

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
