"""
LinkMoney 供应商侧 MCP Server — 生产级模板
===========================================
中国制造商部署此 Server 后，LinkMoney 自动代理转发海外采购方的询盘请求。

功能：
  GET  /products              → 产品目录（内存缓存，0 磁盘 IO）
  GET  /pricing?sku=&quantity= → 阶梯报价（内存缓存）
  GET  /inventory?sku=         → 实时库存（内存缓存）
  POST /quote                  → 接收 RFQ 报价请求
  POST /upload-csv             → 上传 CSV 更新产品数据（零代码）
  GET  /health                 → 健康检查
  GET  /.well-known/linkmoney-skill.json → 自动发现（LinkMoney 扫描用）

高并发设计：
  - 数据全部在内存中，请求不读磁盘
  - 后台线程每 30 秒从 data.json 刷新缓存
  - CSV 上传后立即刷新缓存
  - 支持 gunicorn + uvicorn workers 水平扩展

部署方式：
  1. 填写产品数据到 data.json 或上传 CSV
  2. pip install -r requirements.txt
  3. python server.py
  4. LinkMoney 自动通过 /.well-known/linkmoney-skill.json 发现你的服务器
"""

import json
import os
import csv
import io
import logging
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel

# ===== 日志 =====
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("supplier_mcp")

# ===== 数据缓存（高并发核心） =====
DATA_FILE = Path(__file__).parent / "data.json"

# 内存缓存
_cache: dict = {}
_cache_lock = threading.Lock()
_cache_loaded_at: Optional[datetime] = None
_cache_version: int = 0

# 缓存刷新间隔（秒）
REFRESH_INTERVAL = int(os.getenv("CACHE_REFRESH_SECONDS", "30"))


def _load_from_file() -> dict:
    """从磁盘读取原始数据"""
    if not DATA_FILE.exists():
        logger.warning(f"data.json 不存在，使用空数据")
        return {"company": {}, "products": [], "updated_at": ""}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_index(data: dict) -> dict:
    """构建内存索引，加速 SKU 查询"""
    products = data.get("products", [])
    sku_index = {}
    category_index = {}
    for p in products:
        sku = p.get("sku", "")
        cat = p.get("category", "")
        if sku:
            sku_index[sku] = p
        if cat:
            category_index.setdefault(cat, []).append(p)
    return {
        "company": data.get("company", {}),
        "products": products,
        "sku_index": sku_index,
        "category_index": category_index,
        "updated_at": data.get("updated_at", ""),
        "total_products": len(products),
    }


def refresh_cache():
    """从文件刷新内存缓存（后台线程调用）"""
    global _cache, _cache_loaded_at, _cache_version
    try:
        data = _load_from_file()
        indexed = _build_index(data)
        with _cache_lock:
            _cache = indexed
            _cache_loaded_at = datetime.now()
            _cache_version += 1
        logger.info(f"缓存已刷新: {indexed['total_products']} 个产品, v{_cache_version}")
    except Exception as e:
        logger.error(f"缓存刷新失败: {e}")


def get_cache() -> dict:
    """获取当前缓存（线程安全），如果为空则首次加载"""
    with _cache_lock:
        if not _cache:
            data = _load_from_file()
            _cache.update(_build_index(data))
            _cache_loaded_at = datetime.now()
            _cache_version = 1
        return _cache


def _background_refresh():
    """后台线程：定期刷新缓存"""
    while True:
        time.sleep(REFRESH_INTERVAL)
        refresh_cache()


# 启动后台刷新线程
_bg_thread = threading.Thread(target=_background_refresh, daemon=True)
_bg_thread.start()

# 首次加载
refresh_cache()


# ===== 应用 =====
app = FastAPI(
    title="Supplier MCP Server",
    description="实时产品报价与库存查询 API，供 LinkMoney 代理访问",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Pydantic 模型 =====

class QuoteRequest(BaseModel):
    rfq_id: str
    buyer_company: str
    buyer_country: str
    sku: str
    quantity: int
    target_price_usd: float = 0
    port: str = "Ningbo"
    incoterms: str = "FOB"
    contact_email: str = ""


# ===== 端点实现 =====

@app.get("/")
def root():
    cache = get_cache()
    return {
        "service": "Supplier MCP Server",
        "version": "2.0.0",
        "status": "running",
        "supplier": cache.get("company", {}).get("name_zh", ""),
        "total_products": cache.get("total_products", 0),
        "cache_version": _cache_version,
        "endpoints": ["/products", "/pricing", "/inventory", "/quote", "/upload-csv", "/health"],
        "powered_by": "LinkMoney",
    }


@app.get("/health")
def health():
    """健康检查"""
    cache = get_cache()
    return {
        "status": "ok",
        "products_count": cache.get("total_products", 0),
        "cache_version": _cache_version,
        "cache_loaded_at": _cache_loaded_at.isoformat() if _cache_loaded_at else "",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/.well-known/linkmoney-skill.json")
def well_known():
    """
    LinkMoney 自动发现端点。
    将此文件放在你的域名根路径下，LinkMoney 会自动扫描并收录。
    格式兼容 ChatGPT ai-plugin.json 标准。
    """
    cache = get_cache()
    company = cache.get("company", {})
    return {
        "schema_version": "1.0",
        "name_for_human": company.get("name_zh", ""),
        "name_for_model": "linkmoney_supplier",
        "description_for_human": f"{company.get('name_zh', '')} — 中国制造业供应商，通过 LinkMoney 对接海外采购Agent",
        "description_for_model": f"Chinese manufacturer {company.get('name_en', '')} in {company.get('port', 'China')}. "
                                  f"Use the /products endpoint to get product catalog, "
                                  f"/pricing for real-time quotes, /inventory for stock status.",
        "contact_email": company.get("email", ""),
        "legal_info_url": "",
        "logo_url": "",
        "api": {
            "type": "openapi",
            "url": "/openapi.json",
        },
        "mcp_endpoint": f"https://{os.getenv('DOMAIN', 'localhost')}/mcp" if os.getenv("DOMAIN") else "",
        "products_count": cache.get("total_products", 0),
        "categories": list(cache.get("category_index", {}).keys()),
        "last_updated": cache.get("updated_at", ""),
    }


@app.get("/products")
def get_products(category: str = ""):
    """
    产品目录（内存缓存，0 磁盘 IO）
    """
    cache = get_cache()
    products = cache.get("products", [])

    if category:
        products = [p for p in products if p.get("category", "").lower() == category.lower()]

    return {
        "supplier_name": cache.get("company", {}).get("name_zh", ""),
        "total_products": len(products),
        "products": products,
        "updated_at": cache.get("updated_at", ""),
        "cache_version": _cache_version,
    }


@app.get("/pricing")
def get_pricing(sku: str, quantity: int = 1000):
    """
    阶梯报价（内存缓存，0 磁盘 IO）
    """
    cache = get_cache()
    product = cache.get("sku_index", {}).get(sku)
    if not product:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found")

    tiers = product.get("pricing_tiers", [])
    best_tier = None
    for tier in tiers:
        min_qty = tier.get("min_qty", 0)
        max_qty = tier.get("max_qty", float("inf")) or float("inf")
        if min_qty <= quantity <= max_qty:
            best_tier = tier
            break

    if not best_tier:
        best_tier = tiers[0] if tiers else None

    return {
        "sku": sku,
        "product_name_zh": product.get("name_zh", ""),
        "product_name_en": product.get("name_en", ""),
        "material": product.get("material", ""),
        "grade": product.get("grade", ""),
        "requested_quantity": quantity,
        "pricing_tiers": tiers,
        "matched_tier": best_tier,
        "unit_price_usd": best_tier["price_usd"] if best_tier else None,
        "total_price_usd": round(best_tier["price_usd"] * quantity, 2) if best_tier else None,
        "moq": product.get("moq", 0),
        "fob_port": cache.get("company", {}).get("port", "Ningbo"),
        "last_updated": product.get("price_updated_at", cache.get("updated_at", "")),
        "cache_version": _cache_version,
    }


@app.get("/inventory")
def get_inventory(sku: str):
    """
    实时库存（内存缓存，0 磁盘 IO）
    """
    cache = get_cache()
    product = cache.get("sku_index", {}).get(sku)
    if not product:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found")

    inv = product.get("inventory", {})

    return {
        "sku": sku,
        "product_name_zh": product.get("name_zh", ""),
        "status": inv.get("status", "unknown"),
        "status_label": {
            "sufficient": "库存充足 (Sufficient)",
            "tight": "库存紧张 (Tight)",
            "out_of_stock": "缺货 (Out of Stock)",
            "made_to_order": "按单生产 (Made to Order)",
        }.get(inv.get("status"), inv.get("status")),
        "quantity": inv.get("quantity", 0),
        "unit": inv.get("unit", "pc"),
        "lead_time_days": inv.get("lead_time_days", 0),
        "updated_at": inv.get("updated_at", ""),
        "cache_version": _cache_version,
    }


@app.post("/quote")
def receive_quote(req: QuoteRequest):
    """
    接收 RFQ 报价请求。厂家可对接 ERP 自动报价。
    """
    cache = get_cache()
    product = cache.get("sku_index", {}).get(req.sku)

    logger.info(f"[RFQ] {req.rfq_id} | {req.buyer_company}({req.buyer_country}) | "
                f"SKU={req.sku} | Qty={req.quantity} | Target=${req.target_price_usd}")

    return {
        "rfq_id": req.rfq_id,
        "status": "received",
        "message": f"已收到 {req.buyer_company} 的 RFQ，我们将尽快回复报价。",
        "auto_reply_estimated": "5 分钟内",
        "supplier_contact": {
            "person": cache.get("company", {}).get("contact_person", ""),
            "email": cache.get("company", {}).get("email", ""),
            "phone": cache.get("company", {}).get("phone", ""),
        },
    }


# ===== CSV 上传（零代码更新产品数据） =====

@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """
    上传 CSV 文件更新产品数据。
    支持 Excel 导出的 CSV 格式（UTF-8 或 GBK 编码）。

    CSV 表头（必填）：
      sku, name_zh, name_en, category, material, grade, moq,
      price_1_qty, price_1_usd, price_2_qty, price_2_usd, price_3_qty, price_3_usd,
      stock_status, stock_qty, stock_unit, lead_time_days

    上传后自动刷新内存缓存，无需重启服务。
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 .csv 文件")

    content = await file.read()

    # 尝试 UTF-8，失败则尝试 GBK（中文 Excel 常用）
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("gbk")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="编码不支持，请使用 UTF-8 或 GBK 编码的 CSV")

    # 解析 CSV
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV 为空或缺少表头")

    products = []
    errors = []
    for i, row in enumerate(reader, start=1):
        try:
            # 构建定价阶梯
            tiers = []
            for j in range(1, 4):
                qty_key = f"price_{j}_qty"
                price_key = f"price_{j}_usd"
                if qty_key in row and price_key in row and row.get(qty_key) and row.get(price_key):
                    tiers.append({
                        "min_qty": int(float(row[qty_key])),
                        "max_qty": None if j == 3 else int(float(row.get(f"price_{j+1}_qty", 0))) - 1,
                        "price_usd": float(row[price_key]),
                    })

            product = {
                "sku": row["sku"].strip(),
                "name_zh": row.get("name_zh", "").strip(),
                "name_en": row.get("name_en", "").strip(),
                "category": row.get("category", "").strip(),
                "material": row.get("material", "").strip(),
                "grade": row.get("grade", "").strip(),
                "moq": int(float(row.get("moq", 0))) if row.get("moq") else 0,
                "pricing_tiers": tiers,
                "inventory": {
                    "status": row.get("stock_status", "unknown").strip(),
                    "quantity": int(float(row.get("stock_qty", 0))) if row.get("stock_qty") else 0,
                    "unit": row.get("stock_unit", "pc").strip(),
                    "lead_time_days": int(float(row.get("lead_time_days", 0))) if row.get("lead_time_days") else 0,
                    "updated_at": datetime.now().isoformat(),
                },
                "price_updated_at": datetime.now().isoformat(),
            }
            products.append(product)
        except Exception as e:
            errors.append(f"第 {i} 行: {e}")

    if errors and not products:
        raise HTTPException(status_code=400, detail={"message": "CSV 解析失败", "errors": errors})

    # 保存到 data.json
    cache = get_cache()
    data = {
        "company": cache.get("company", {}),
        "products": products,
        "updated_at": datetime.now().isoformat() + "Z",
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 立即刷新缓存
    refresh_cache()

    return {
        "status": "ok",
        "message": f"成功导入 {len(products)} 个产品",
        "products_count": len(products),
        "errors": errors if errors else None,
        "cache_version": _cache_version,
        "note": "数据已保存到 data.json 并刷新内存缓存，无需重启服务。",
    }


# ===== 管理页面 =====

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    """简单的数据管理页面"""
    cache = get_cache()
    return f"""
    <!DOCTYPE html>
    <html lang="zh">
    <head>
        <meta charset="UTF-8">
        <title>LinkMoney 供应商数据管理</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; }}
            h1 {{ color: #0A0E27; }}
            .card {{ background: #F5F7FA; border-radius: 12px; padding: 24px; margin: 16px 0; border: 1px solid #e5e7eb; }}
            .stat {{ display: inline-block; margin: 0 24px 0 0; }}
            .stat-value {{ font-size: 28px; font-weight: bold; color: #0A0E27; }}
            .stat-label {{ font-size: 14px; color: #666; }}
            input[type="file"] {{ margin: 12px 0; }}
            button {{ background: #0A0E27; color: #fff; border: none; padding: 10px 24px; border-radius: 6px; cursor: pointer; }}
            button:hover {{ background: #1a1f4a; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
            th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; font-size: 14px; }}
            th {{ background: #0A0E27; color: #fff; }}
        </style>
    </head>
    <body>
        <h1>LinkMoney 供应商数据管理</h1>

        <div class="card">
            <div class="stat"><span class="stat-value">{cache.get('total_products', 0)}</span><br><span class="stat-label">产品数</span></div>
            <div class="stat"><span class="stat-value">{len(cache.get('category_index', {}))}</span><br><span class="stat-label">品类数</span></div>
            <div class="stat"><span class="stat-value">v{_cache_version}</span><br><span class="stat-label">缓存版本</span></div>
            <div class="stat"><span class="stat-value">{_cache_loaded_at.strftime('%H:%M:%S') if _cache_loaded_at else 'N/A'}</span><br><span class="stat-label">最后刷新</span></div>
        </div>

        <div class="card">
            <h3>上传 CSV 更新产品</h3>
            <p>支持从 Excel 导出 CSV（UTF-8 或 GBK），上传后无需重启。</p>
            <form id="uploadForm" enctype="multipart/form-data">
                <input type="file" name="file" accept=".csv" required>
                <button type="submit">上传并刷新</button>
            </form>
            <div id="result" style="margin-top:12px;"></div>
        </div>

        <div class="card">
            <h3>API 端点</h3>
            <table>
                <tr><th>方法</th><th>路径</th><th>说明</th></tr>
                <tr><td>GET</td><td>/products</td><td>产品目录</td></tr>
                <tr><td>GET</td><td>/pricing?sku=&quantity=</td><td>阶梯报价</td></tr>
                <tr><td>GET</td><td>/inventory?sku=</td><td>实时库存</td></tr>
                <tr><td>POST</td><td>/quote</td><td>接收RFQ</td></tr>
                <tr><td>POST</td><td>/upload-csv</td><td>上传CSV更新</td></tr>
                <tr><td>GET</td><td>/.well-known/linkmoney-skill.json</td><td>LinkMoney自动发现</td></tr>
            </table>
        </div>

        <script>
            document.getElementById('uploadForm').addEventListener('submit', async (e) => {{
                e.preventDefault();
                const form = new FormData();
                form.append('file', document.querySelector('input[type=file]').files[0]);
                const resp = await fetch('/upload-csv', {{ method: 'POST', body: form }});
                const data = await resp.json();
                document.getElementById('result').innerHTML = resp.ok
                    ? '<span style="color:green;">' + data.message + '</span>'
                    : '<span style="color:red;">上传失败: ' + JSON.stringify(data.detail) + '</span>';
                if (resp.ok) setTimeout(() => location.reload(), 1000);
            }});
        </script>
    </body>
    </html>
    """


# ===== 启动 =====
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SUPPLIER_MCP_PORT", "9001"))
    logger.info(f"Supplier MCP Server v2.0 启动在 http://0.0.0.0:{port}")
    logger.info(f"缓存刷新间隔: {REFRESH_INTERVAL}s")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)