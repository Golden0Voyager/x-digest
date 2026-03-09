import os
import httpx
import json

def fetch_free_models():
    api_key = os.getenv("TOGETHER_API_KEY")
    base_url = os.getenv("TOGETHER_BASE_URL", "https://api.together.xyz/v1")
    
    if not api_key:
        print("❌ 错误：未在环境变量中找到 TOGETHER_API_KEY")
        return

    print(f"📡 正在拉取 Together AI 可用模型列表 (API: {base_url})...")

    try:
        with httpx.Client() as client:
            resp = client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30
            )
            resp.raise_for_status()
            models = resp.json()

            free_models = []
            for m in models:
                # 筛选条件：1. 名称包含 "Free" 或 2. 价格属性显示为免费（Together AI 的 API 结构因版本而异）
                if "Free" in m.get("id", "") or "Free" in m.get("display_name", ""):
                    free_models.append(m)
                # 有些模型通过定价策略标注免费，这里尝试根据已知信息进行补充逻辑
                elif m.get("pricing", {}).get("hourly") == 0 or m.get("pricing", {}).get("base") == 0:
                    free_models.append(m)

            if free_models:
                print(f"\n✅ 成功找到 {len(free_models)} 个免费模型：\n")
                for i, m in enumerate(free_models, 1):
                    name = m.get("display_name", "未命名")
                    mid = m.get("id", "无 ID")
                    desc = m.get("description", "无描述")
                    print(f"{i}. {name} | ID: {mid}")
                    if desc:
                        print(f"   💡 {desc[:100]}...")
                
                # 保存到本地 docs 供参考
                output_path = "docs/Together_Free_Models_List.json"
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(free_models, f, ensure_ascii=False, indent=2)
                print(f"\n💾 详细列表已保存至: {output_path}")
            else:
                print("\n⚠️  未通过 API 发现显式标记为 'Free' 的模型。")
                print("   (注：部分免费模型可能仅在 Playground 预览期提供)")

    except Exception as e:
        print(f"❌ 请求失败: {e}")

if __name__ == "__main__":
    fetch_free_models()
