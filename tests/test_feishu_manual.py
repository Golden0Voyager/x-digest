import os
import json
import httpx
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 从配置中读取
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_USER_ID = os.getenv("FEISHU_USER_ID", "")

def get_feishu_token() -> str:
    """获取 Token (强制直连)"""
    with httpx.Client(trust_env=False) as client:
        resp = client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=10,
        )
        return resp.json()["tenant_access_token"]

def test_push():
    # 找一个最近生成的本地文件
    files = sorted(Path("output").glob("*.md"), reverse=True)
    files = [f for f in files if f.name != ".gitkeep"]
    if not files:
        print("❌ output/ 下没有 md 文件")
        return
    
    test_file = files[0]
    print(f"🧪 正在测试推送最新文件: {test_file}")
    markdown_content = test_file.read_text(encoding="utf-8")
    title = f"🧪 内容推送测试: {test_file.name}"

    try:
        token = get_feishu_token()
        headers = {"Authorization": f"Bearer {token}"}

        # 1. 创建文档 (强制直连)
        with httpx.Client(trust_env=False, headers=headers) as client:
            print("🛠  1. 正在创建空飞书文档...")
            resp = client.post(
                "https://open.feishu.cn/open-apis/docx/v1/documents",
                json={"title": title},
                timeout=20,
            )
            data = resp.json()
            if data.get("code") != 0:
                print(f"❌ 创建失败: {data.get('msg')}")
                return

            doc_id = data["data"]["document"]["document_id"]
            doc_url = f"https://www.feishu.cn/docx/{doc_id}"
            print(f"✅ 文档已创建: {doc_id}")

            # 2. 转换并写入内容
            print("🛠  2. 正在将 Markdown 内容写入文档...")
            lines = markdown_content.strip().split("\n")
            children = []
            for line in lines:
                stripped = line.strip()
                if not stripped: continue
                
                if stripped.startswith("### "):
                    children.append({"block_type": 5, "heading3": {"elements": [{"text_run": {"content": stripped[4:]}}], "style": {}}})
                elif stripped.startswith("## "):
                    children.append({"block_type": 4, "heading2": {"elements": [{"text_run": {"content": stripped[3:]}}], "style": {}}})
                elif stripped.startswith("# "):
                    children.append({"block_type": 3, "heading1": {"elements": [{"text_run": {"content": stripped[2:]}}], "style": {}}})
                elif stripped.startswith("---"):
                    children.append({"block_type": 22, "divider": {}})
                elif stripped.startswith("- "):
                    children.append({"block_type": 2, "text": {"elements": [{"text_run": {"content": f"• {stripped[2:]}"}}], "style": {}}})
                else:
                    # 处理加粗格式
                    elements = []
                    parts = stripped.split("**")
                    for i, part in enumerate(parts):
                        if not part: continue
                        if i % 2 == 1:
                            elements.append({"text_run": {"content": part, "text_element_style": {"bold": True}}})
                        else:
                            elements.append({"text_run": {"content": part}})
                    if elements:
                        children.append({"block_type": 2, "text": {"elements": elements, "style": {}}})
                    else:
                        children.append({"block_type": 2, "text": {"elements": [{"text_run": {"content": stripped}}], "style": {}}})

            # 分批写入 (飞书 API 限制单次 50 个 block)
            batch_size = 50
            for i in range(0, len(children), batch_size):
                batch_resp = client.post(f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                           json={"children": children[i : i + batch_size]}, timeout=30)
                if batch_resp.json().get("code") == 0:
                    print(f"   ✓ 已写入第 {i//batch_size + 1} 批内容")
                else:
                    print(f"   ❌ 第 {i//batch_size + 1} 批写入失败: {batch_resp.json().get('msg')}")

            # 3. 推送消息
            print("📨 3. 正在发送飞书通知...")
            msg_content = {
                "text": f"📰 X 科技摘要测试 (含内容)\n\n📄 完整在线报告：{doc_url}"
            }
            client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "open_id"},
                json={
                    "receive_id": FEISHU_USER_ID,
                    "msg_type": "text",
                    "content": json.dumps(msg_content),
                },
                timeout=10,
            )
            print(f"🎉 全部完成！请查看手机：{doc_url}")

    except Exception as e:
        print(f"❌ 运行异常: {e}")

if __name__ == "__main__":
    test_push()
