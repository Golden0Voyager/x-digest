
import asyncio
import os
from pathlib import Path
from pipeline.score import run_score
from pipeline.translate import run_translate
from pipeline.insights import run_insights
from pipeline.assemble import assemble
from pipeline import Color

# 模拟几条硬核推文
MOCK_TWEETS = [
    {
        "tweet_id": "101",
        "username": "JeffDean",
        "text": "The new MoE (Mixture of Experts) architecture in our latest model significantly reduces inference FLOPs while maintaining high accuracy. The routing logic is now much more stable."
    },
    {
        "tweet_id": "102",
        "username": "NVIDIAGeForce",
        "text": "Our Blackwell B200 GPU features 208 billion transistors and is connected by the 1.8TB/s Fifth-Generation NVLink. This is a massive leap for LLM training."
    },
    {
        "tweet_id": "103",
        "username": "Krugman",
        "text": "The latest CPI data suggests that the Fed Pivot might happen sooner than expected. Market is pricing in a 25bps cut in March."
    }
]

async def test_full_ai_logic():
    print(f"{Color.BOLD}🧪 开始测试科普增强版 AI 管线...{Color.RESET}\n")
    
    intermediate_dir = Path("./output/test_intermediate")
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    # 1. 测试打分 (sensenova-6.7-flash-lite + DeepSeek-R1-Distill-Qwen-14B 跨端点双引擎)
    print(f"{Color.CYAN}Step 1: 联合打分海选...{Color.RESET}")
    top_tweets = await run_score(MOCK_TWEETS, intermediate_dir, force_rerun=True)

    # 2. 测试翻译 (DeepSeek-R1-Distill-Qwen-14B)
    print(f"\n{Color.CYAN}Step 2: Distill-14B 深度翻译...{Color.RESET}")
    translations = await run_translate(top_tweets, intermediate_dir, force_rerun=True)

    # 3. 测试科普与洞察 (sensenova-6.7-flash-lite via Token Plan)
    print(f"\n{Color.CYAN}Step 3: sensenova-6.7-flash-lite 背景科普与深度启示...{Color.RESET}")
    insights = await run_insights(top_tweets, translations, intermediate_dir, force_rerun=True)
    
    # 4. 组装结果
    print(f"\n{Color.CYAN}Step 4: 本地排版装配...{Color.RESET}")
    markdown, counts = assemble(top_tweets, translations, insights)
    
    print(f"\n{Color.GREEN}✅ 测试完成！生成的预览内容如下：{Color.RESET}\n")
    print("=" * 50)
    print(markdown)
    print("=" * 50)
    print(f"\n{Color.BOLD}统计摘要：{Color.RESET}")
    print(counts)

if __name__ == "__main__":
    if not os.getenv("SENSENOVA_API_KEY"):
        print(f"{Color.RED}❌ 错误：请先设置 SENSENOVA_API_KEY 环境变量{Color.RESET}")
    else:
        asyncio.run(test_full_ai_logic())
