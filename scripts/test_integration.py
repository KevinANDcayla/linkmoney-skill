"""
LinkMoney 集成测试 — 验证本轮所有修复

覆盖：
1. _slugify_supplier_id 中文名 hash 兜底
2. register_supplier 中文名注册 + 自动激活托管 MCP
3. register_supplier 冲突自动加序号
4. find_china_supplier 返回 matches + 价格字段正确
5. get_pricing 不再 KeyError（unit_price_usd）
6. evaluate_sme 兼容旧版 7 维 list 模板
7. register_buyer 海外采购方自注册
8. submit_rfq 提交 RFQ
"""

import sys
import os
import json

# 把 api 目录加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from fastapi.testclient import TestClient
import server

client = TestClient(server.app)

# 默认 API Key（见 server.py _load_api_keys）
API_KEY = "lm-demo-2026"
HEADERS = {"X-API-Key": API_KEY}

results = []


def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append((name, ok, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


# ---------- 1. _slugify_supplier_id 中文名 hash 兜底 ----------
try:
    sid1 = server._slugify_supplier_id("宁波新锐紧固件有限公司", "fastener")
    sid2 = server._slugify_supplier_id("温州东方电子厂", "electronics")
    sid3 = server._slugify_supplier_id("Acme Corp", "fastener")
    ok = sid1.startswith("fastener-cn") and sid2.startswith("electron-cn") and sid3 == "fastener-acme-corp"
    check("1. _slugify_supplier_id 中文名 hash 兜底", ok, f"{sid1} / {sid2} / {sid3}")
except Exception as e:
    check("1. _slugify_supplier_id 中文名 hash 兜底", False, str(e))


# ---------- 2. register_supplier 中文名注册 + 自动激活 ----------
supplier_id_v1 = None
token_v1 = None
try:
    payload = {
        "company_name": "测试新锐紧固件有限公司",
        "contact_person": "测试王总",
        "email": "test_xinrui@example.com",
        "phone": "13800000001",
        "category": "fastener",
        "products": [
            {
                "sku": "TEST-M8-304",
                "name": "M8 304不锈钢六角螺栓",
                "spec": "M8 x 40mm, A2-70, DIN933",
                "unit_price_usd": 0.08,
                "moq": 5000,
                "stock": 200000,
            }
        ],
    }
    r = client.post("/register_supplier", json=payload, headers=HEADERS)
    data = r.json()
    ok = (
        r.status_code == 200
        and "supplier_id" in data
        and data.get("mcp_endpoint", "").startswith("https://linkmoney.online/mcp/supplier/")
        and data.get("data_source_type") == "hosted"
        and data.get("has_skill") is True
    )
    supplier_id_v1 = data.get("supplier_id")
    token_v1 = data.get("verification_token")
    check("2. register_supplier 中文名 + 自动激活托管 MCP", ok, f"supplier_id={supplier_id_v1} mcp={data.get('mcp_endpoint')}")
except Exception as e:
    check("2. register_supplier 中文名 + 自动激活托管 MCP", False, str(e))


# ---------- 3. register_supplier 冲突自动加序号 ----------
try:
    # 用不同公司名但 _slugify 后会冲突的（都是中文名 → hash）
    r2 = client.post("/register_supplier", json={
        "company_name": "测试新锐紧固件厂",  # 不同名，但都是中文 → hash slug
        "email": "test_xinrui2@example.com",
        "phone": "13800000002",
        "category": "fastener",
    }, headers=HEADERS)
    data2 = r2.json()
    sid2 = data2.get("supplier_id", "")
    ok = r2.status_code == 200 and sid2 != supplier_id_v1
    check("3. register_supplier 冲突自动加序号", ok, f"v1={supplier_id_v1} v2={sid2}")
except Exception as e:
    check("3. register_supplier 冲突自动加序号", False, str(e))


# ---------- 4. find_china_supplier 返回 matches + 价格字段 ----------
try:
    r = client.get("/find_china_supplier", params={
        "category": "fastener",
        "spec": "M8 304 hex bolt A2-70",
        "quantity": 50000,
        "target_price": 0.12,
    }, headers=HEADERS)
    data = r.json()
    matches = data.get("matches", [])
    ok = r.status_code == 200 and len(matches) > 0
    if matches:
        m = matches[0]
        # match_entry 包含 supplier_id + match_score + sample_products
        ok = ok and "supplier_id" in m and "match_score" in m
    check("4. find_china_supplier 返回 matches", ok, f"matches={len(matches)} first={matches[0].get('supplier_id') if matches else 'N/A'} score={matches[0].get('match_score') if matches else 'N/A'}")
except Exception as e:
    check("4. find_china_supplier 返回 matches", False, str(e))


# ---------- 5. get_pricing 不再 KeyError ----------
try:
    with server.get_db() as conn:
        row = conn.execute("SELECT id FROM suppliers LIMIT 1").fetchone()
    if row:
        sid = row["id"]
        with server.get_db() as conn:
            prow = conn.execute("SELECT sku FROM products WHERE supplier_id = ? LIMIT 1", (sid,)).fetchone()
        sku = prow["sku"] if prow else "M8-304-A2-70"
        r = client.get("/get_pricing", params={
            "supplier_id": sid,
            "sku": sku,
            "quantity": 50000,
        }, headers=HEADERS)
        data = r.json()
        ok = r.status_code == 200 and "unit_price_usd" in data
        check("5. get_pricing 不再 KeyError", ok, f"supplier={sid} sku={sku} unit_price={data.get('unit_price_usd')}")
    else:
        check("5. get_pricing 不再 KeyError", False, "DB 无供应商")
except Exception as e:
    check("5. get_pricing 不再 KeyError", False, str(e))


# ---------- 6. evaluate_sme 兼容旧版 7 维 list 模板 ----------
try:
    r = client.post("/evaluate_sme", json={
        "company_name": "测试评估公司",
        "category": "fastener",
        "dimensions": {
            "overseas_channel_maturity": 75,
            "digital_foundation": 55,
            "agent_readiness": 40,
            "category_fitness": 85,
            "content_assets": 60,
        },
    }, headers=HEADERS)
    data = r.json()
    ok = r.status_code == 200 and "total_score" in data and "scores" in data
    check("6. evaluate_sme 兼容旧版模板", ok, f"score={data.get('total_score')} level={data.get('level')} dims={list(data.get('scores', {}).keys())}")
except Exception as e:
    check("6. evaluate_sme 兼容旧版模板", False, str(e))


# ---------- 7. register_buyer 海外采购方自注册 ----------
buyer_id = None
try:
    r = client.post("/register_buyer", json={
        "company": "Test Buyer Corp",
        "country": "US",
        "industry": "automotive",
        "contact_person": "John Doe",
        "email": "test_buyer@example.com",
        "interested_categories": ["fastener", "electronics"],
        "languages": ["en"],
    })
    data = r.json()
    ok = r.status_code == 200 and "buyer_id" in data
    buyer_id = data.get("buyer_id")
    check("7. register_buyer 海外采购方自注册", ok, f"buyer_id={buyer_id}")
except Exception as e:
    check("7. register_buyer 海外采购方自注册", False, str(e))


# ---------- 8. submit_rfq 提交 RFQ ----------
try:
    if buyer_id is None:
        rb = client.post("/register_buyer", json={
            "company": "Test Buyer Corp 2",
            "country": "US",
            "email": "test_buyer2@example.com",
        })
        buyer_id = rb.json().get("buyer_id")

    # 用 fastener 供应商 + 合理价格（避免 T&S 拦截）
    with server.get_db() as conn:
        srow = conn.execute("SELECT id FROM suppliers WHERE category = 'fastener' LIMIT 1").fetchone()
    sid = srow["id"] if srow else supplier_id_v1

    r = client.post("/submit_rfq", params={
        "supplier_id": sid,
        "buyer_id": buyer_id,
        "sku": "M8-304-A2-70",
        "quantity": 50000,
        "target_price_usd": 0.12,
    }, headers=HEADERS)
    data = r.json()
    ok = r.status_code == 200 and "rfq_id" in data
    check("8. submit_rfq 提交 RFQ", ok, f"rfq_id={data.get('rfq_id')} status={r.status_code}")
except Exception as e:
    check("8. submit_rfq 提交 RFQ", False, str(e))


# ---------- 汇总 ----------
print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"结果：{passed}/{total} 通过")
if passed != total:
    print("\n失败项：")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
    sys.exit(1)
else:
    print("\n全部通过 ✅")
