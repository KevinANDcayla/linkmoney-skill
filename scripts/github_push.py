#!/usr/bin/env python3
"""
通过 GitHub API 直接更新文件（绕过 git push，走 api.github.com）

用法：
  export GITHUB_TOKEN=ghp_xxx
  python3 scripts/github_push.py
"""
import base64, json, os, requests, sys
from pathlib import Path

# 安全：token 从环境变量读取，禁止硬编码
TOKEN = os.getenv("GITHUB_TOKEN", "")
if not TOKEN:
    print("❌ 未配置 GITHUB_TOKEN 环境变量，请运行：export GITHUB_TOKEN=ghp_xxx")
    sys.exit(1)

REPO = os.getenv("GITHUB_REPO", "KevinANDcayla/linkmoney-skill")
HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def update_file(path, content, commit_msg):
    """通过 API 更新文件"""
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    
    # 1. 获取当前文件的 sha
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 404:
        sha = None
        print(f"  新文件: {path}")
    else:
        r.raise_for_status()
        sha = r.json()["sha"]
        print(f"  已有文件 sha: {sha[:12]}...")
    
    # 2. 更新文件
    b64_content = base64.b64encode(content.encode("utf-8")).decode()
    data = {
        "message": commit_msg,
        "content": b64_content,
        "branch": "main"
    }
    if sha:
        data["sha"] = sha
    
    r = requests.put(url, headers=HEADERS, json=data)
    if r.status_code in (200, 201):
        print(f"  ✅ 更新成功")
        return True
    else:
        print(f"  ❌ 失败: {r.status_code} {r.text[:200]}")
        return False

def main():
    base = Path(__file__).parent.parent
    
    files_to_update = [
        ("SKILL.md", "feat: v5.0.2 SKILL.md — 2500家工厂 + API Key + 调用示例"),
        ("README.md", "feat: v5.0.2 README.md — Quick Start + demo key + 2500家"),
        ("mcp_manifest.json", "feat: v5.0.2 manifest — 2500家/30000产品/16品类"),
    ]
    
    for path, msg in files_to_update:
        print(f"\n更新 {path}...")
        content = (base / path).read_text(encoding="utf-8")
        if update_file(path, content, msg):
            print(f"  已提交: {msg}")
        else:
            print(f"  失败!")
            sys.exit(1)
    
    print("\n✅ 所有文件已更新到 GitHub!")

if __name__ == "__main__":
    main()
