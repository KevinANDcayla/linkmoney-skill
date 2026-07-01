"""
LinkMoney MCP Server — Agent 时代的 B2B 贸易链接器 API
混合架构：LinkMoney 做黄页+路由，厂家自有 MCP Server 提供实时数据
"""

import json
import os
import re
import hashlib
import sqlite3
import logging
import time
import requests
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
from urllib.parse import urljoin

from fastapi import FastAPI, HTTPException, Query, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from mailer import mailer
from middle_agent import (
    middle_agent_status, middle_agent_health, middle_agent_routing,
    middle_agent_alerts, middle_agent_maintenance, middle_agent_optimize,
    middle_agent_maintain, bootstrap_agent,
)
from llm_layer import get_llm, DeepSeekError  # 火山引擎豆包 (Ark API)

# ===== 工具函数 =====
_PINYIN_INITIAL = {
    "宁波": "nb", "温州": "wz", "杭州": "hz", "绍兴": "sx", "台州": "tz",
    "金华": "jh", "嘉兴": "jx", "湖州": "hz2", "昆山": "ks", "苏州": "sz",
    "无锡": "wx", "常州": "cz", "南京": "nj", "深圳": "sz2", "广州": "gz",
    "东莞": "dg", "佛山": "fs", "上海": "sh", "北京": "bj", "天津": "tj",
    "重庆": "cq", "成都": "cd", "武汉": "wh", "青岛": "qd", "大连": "dl",
    "厦门": "xm", "福州": "fz", "西安": "xa", "郑州": "zz",
}

_CATEGORY_MAP = {
    "fastener": "fastener", "packaging": "pack", "electronic": "elec",
    "hardware": "hdwr", "injection_molding": "injmold", "machinery": "mach",
    "textile": "textile",
}


def slugify_company(name: str, category: str = "") -> str:
    """将中文公司名转为合法的英文标识符，确保 URL 安全"""
    city_prefix = ""
    for city, abbr in _PINYIN_INITIAL.items():
        if city in name:
            city_prefix = abbr
            break
    if not city_prefix:
        city_prefix = "cn"

    cat_abbr = _CATEGORY_MAP.get(category, category[:4])

    clean = re.sub(r'[（）()\s]', '', name)
    short = clean[:4] if len(clean) >= 4 else clean

    name_hash = hashlib.md5(name.encode()).hexdigest()[:6]

    result = f"{city_prefix}-{cat_abbr}-{name_hash}"
    result = re.sub(r'[^a-zA-Z0-9-]', '', result)
    return result.lower()


def slugify_to_github(name: str, category: str = "") -> str:
    """为 GitHub 仓库名生成有效的 slug"""
    slug = slugify_company(name, category)
    return re.sub(r'[^a-zA-Z0-9-]', '-', slug).strip('-').lower()

# ===== 日志配置 =====

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("linkmoney")
logger.setLevel(logging.INFO)

# 文件 handler — 按天轮转
from logging.handlers import TimedRotatingFileHandler
file_handler = TimedRotatingFileHandler(
    filename=str(LOG_DIR / "api.log"),
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logger.addHandler(file_handler)

# 控制台 handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logger.addHandler(console_handler)

# ===== 数据库路径 =====

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
JSON_FILE = DATA_DIR / "database.json"
DB_PATH = str(DATA_DIR / "linkmoney.db")


# ===== 数据库初始化与连接 =====

@contextmanager
def get_db():
    """每个请求使用独立连接（WAL 模式 + busy_timeout 防多 worker 写入竞态）"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


# ===== v2.1+ 数据库迁移（幂等） =====

def _migrate_v21():
    """创建 v2.1 引入的新表和列；幂等，可重复执行"""
    with get_db() as conn:
        c = conn.cursor()

        # suppliers 表新列：验证状态、评分
        for col_name, col_type in [
            ("email_verified", "INTEGER DEFAULT 0"),
            ("phone_verified", "INTEGER DEFAULT 0"),
            ("license_verified", "INTEGER DEFAULT 0"),
            ("trust_score", "REAL DEFAULT 0"),
            ("trust_level", "TEXT DEFAULT 'unverified'"),
            ("review_count", "INTEGER DEFAULT 0"),
            ("review_avg", "REAL DEFAULT 0"),
            ("gold_badge", "INTEGER DEFAULT 0"),
            ("verification_token", "TEXT DEFAULT ''"),
            ("outreach_used_this_month", "INTEGER DEFAULT 0"),
            ("outreach_reset_at", "TEXT DEFAULT ''"),
            ("data_source_type", "TEXT DEFAULT 'hosted'"),  # v3.3: hosted(托管)/self(自部署)/tunnel(隧道)
            ("access_token", "TEXT DEFAULT ''"),  # v5.2.4: 工厂身份凭证（长期有效，区别于 verification_token）
        ]:
            try:
                c.execute(f"ALTER TABLE suppliers ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

        # buyers 表新列：邮箱验证（防垃圾询盘）
        for col_name, col_type in [
            ("email_verified", "INTEGER DEFAULT 0"),
            ("email_domain", "TEXT DEFAULT ''"),
            ("company_domain", "TEXT DEFAULT ''"),
            ("trust_score", "REAL DEFAULT 0"),
        ]:
            try:
                c.execute(f"ALTER TABLE overseas_buyers ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

        # 需求广场（v2.2）
        c.execute("""
            CREATE TABLE IF NOT EXISTS requirements (
                id TEXT PRIMARY KEY,
                buyer_id TEXT NOT NULL,
                category TEXT NOT NULL,
                sku TEXT DEFAULT '',
                spec TEXT DEFAULT '',
                quantity INTEGER DEFAULT 0,
                target_price_usd REAL DEFAULT 0,
                destination_port TEXT DEFAULT '',
                incoterms TEXT DEFAULT 'FOB',
                delivery_deadline TEXT DEFAULT '',
                public INTEGER DEFAULT 1,
                status TEXT DEFAULT 'open',
                bid_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT '',
                expires_at TEXT DEFAULT ''
            )
        """)

        # 报价（v2.2 工厂对公开需求报价）
        c.execute("""
            CREATE TABLE IF NOT EXISTS bids (
                id TEXT PRIMARY KEY,
                requirement_id TEXT NOT NULL,
                supplier_id TEXT NOT NULL,
                unit_price_usd REAL DEFAULT 0,
                lead_time_days INTEGER DEFAULT 0,
                moq INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                status TEXT DEFAULT 'submitted',
                created_at TEXT DEFAULT ''
            )
        """)

        # 验证令牌（v2.1 邮箱/电话验证）
        c.execute("""
            CREATE TABLE IF NOT EXISTS verifications (
                token TEXT PRIMARY KEY,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                contact TEXT NOT NULL,
                purpose TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        # 互评（v3.0）
        c.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rfq_id TEXT DEFAULT '',
                reviewer_id TEXT NOT NULL,
                reviewer_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                rating INTEGER NOT NULL,
                dimension_quality INTEGER DEFAULT 0,
                dimension_speed INTEGER DEFAULT 0,
                dimension_communication INTEGER DEFAULT 0,
                dimension_price INTEGER DEFAULT 0,
                dimension_payment INTEGER DEFAULT 0,
                comment TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        # 主动外联（v2.3）
        c.execute("""
            CREATE TABLE IF NOT EXISTS outreach (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id TEXT NOT NULL,
                target_buyer_id TEXT NOT NULL,
                message TEXT NOT NULL,
                value_proposition TEXT DEFAULT '',
                samples_offered INTEGER DEFAULT 0,
                status TEXT DEFAULT 'sent',
                opened INTEGER DEFAULT 0,
                replied INTEGER DEFAULT 0,
                sent_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        # 信用评分历史（v2.1 评估记录）
        c.execute("""
            CREATE TABLE IF NOT EXISTS trust_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                overall_score REAL DEFAULT 0,
                dimensions TEXT DEFAULT '{}',
                trust_level TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        # beta_signups 表（旧）
        c.execute("""
            CREATE TABLE IF NOT EXISTS beta_signups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factory_name TEXT NOT NULL,
                contact_person TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                source TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        # rfqs 表迁移（v3.0+ — DeepSeek LLM 集成后新增的 message + parsed_data 列）
        # 先确保 rfqs 表存在（防止 DB 文件已存在但表未创建的情况）
        c.execute("""
            CREATE TABLE IF NOT EXISTS rfqs (
                id TEXT PRIMARY KEY,
                supplier_id TEXT NOT NULL,
                buyer_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                target_price_usd REAL DEFAULT 0,
                port TEXT DEFAULT '',
                incoterms TEXT DEFAULT 'FOB',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT '',
                delivery_deadline TEXT DEFAULT '',
                contact_email TEXT DEFAULT '',
                raw_message TEXT DEFAULT ''
            )
        """)
        for col_name, col_type in [
            ("quoted_price_usd", "REAL DEFAULT 0"),
            ("lead_time_days", "INTEGER DEFAULT 0"),
            ("total_price_usd", "REAL DEFAULT 0"),
            ("notes", "TEXT DEFAULT ''"),
            ("updated_at", "TEXT DEFAULT ''"),
            ("message", "TEXT DEFAULT ''"),
            ("parsed_data", "TEXT DEFAULT ''"),
        ]:
            try:
                c.execute(f"ALTER TABLE rfqs ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass  # 列已存在

        # products 表迁移（v3.1+ — 对齐 Alibaba/schema.org 完整字段）
        c.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                name_zh TEXT DEFAULT '',
                name_en TEXT DEFAULT '',
                category TEXT DEFAULT '',
                material TEXT DEFAULT '',
                grade TEXT DEFAULT '',
                specs TEXT NOT NULL DEFAULT '{}',
                pricing_tiers TEXT NOT NULL DEFAULT '[]',
                inventory_status TEXT DEFAULT 'unknown',
                inventory_quantity INTEGER DEFAULT 0,
                inventory_unit TEXT DEFAULT 'pc',
                inventory_lead_time_days INTEGER DEFAULT 0,
                inventory_updated_at TEXT DEFAULT ''
            )
        """)
        for col_name, col_type in [
            ("subcategory", "TEXT DEFAULT ''"),
            ("attributes", "TEXT NOT NULL DEFAULT '[]'"),
            ("description", "TEXT DEFAULT ''"),
            ("description_en", "TEXT DEFAULT ''"),
            ("images", "TEXT NOT NULL DEFAULT '[]'"),
            ("weight_kg", "REAL DEFAULT 0"),
            ("package_size", "TEXT DEFAULT ''"),
            ("package_qty", "INTEGER DEFAULT 1"),
            ("hs_code", "TEXT DEFAULT ''"),
            ("origin", "TEXT DEFAULT 'China'"),
            ("warranty", "TEXT DEFAULT ''"),
            ("payment_terms", "TEXT DEFAULT ''"),
            ("sample_available", "INTEGER DEFAULT 0"),
            ("sample_price_usd", "REAL DEFAULT 0"),
            ("customized", "INTEGER DEFAULT 0"),
            ("status", "TEXT DEFAULT 'active'"),
            ("created_at", "TEXT DEFAULT ''"),
            ("updated_at", "TEXT DEFAULT ''"),
            # v3.2: P0+P1 字段（对齐 Alibaba/1688/schema.org）
            ("moq", "INTEGER DEFAULT 1"),
            ("trade_terms", "TEXT DEFAULT 'FOB'"),
            ("port", "TEXT DEFAULT ''"),
            ("price_currency", "TEXT DEFAULT 'USD'"),
            ("price_type", "TEXT DEFAULT 'FOB'"),
            ("price_unit", "TEXT DEFAULT 'pc'"),
            ("price_validity", "TEXT DEFAULT ''"),
            ("certifications", "TEXT NOT NULL DEFAULT '[]'"),
            ("packaging_details", "TEXT DEFAULT ''"),
            ("supply_ability_monthly", "INTEGER DEFAULT 0"),
        ]:
            try:
                c.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass  # 列已存在

        # v3.2: 唯一索引（防止重复注册 + 产品重复）
        # suppliers: email 唯一（允许空值共存）、name_zh 唯一、phone 唯一
        for idx_name, idx_sql in [
            ("idx_suppliers_email_unique", "CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_email_unique ON suppliers(email) WHERE email != ''"),
            ("idx_suppliers_name_zh_unique", "CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_name_zh_unique ON suppliers(name_zh) WHERE name_zh != ''"),
            ("idx_suppliers_phone_unique", "CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_phone_unique ON suppliers(phone) WHERE phone != ''"),
            # products: (supplier_id, sku) 唯一
            ("idx_products_supplier_sku_unique", "CREATE UNIQUE INDEX IF NOT EXISTS idx_products_supplier_sku_unique ON products(supplier_id, sku)"),
        ]:
            try:
                c.execute(idx_sql)
            except sqlite3.IntegrityError as e:
                # 已有重复数据时创建唯一索引会失败，记录但不阻塞
                logger.warning(f"创建唯一索引 {idx_name} 失败（可能已有重复数据）: {e}")
            except sqlite3.OperationalError:
                pass  # 索引已存在

        conn.commit()


def _get_json_version() -> tuple:
    """读取 database.json 的版本号和最后更新时间。返回 (version, last_updated)"""
    if not JSON_FILE.exists():
        return ("", "")
    try:
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (data.get("version", ""), data.get("last_updated", ""))
    except Exception as e:
        logger.warning(f"读取 JSON 版本失败: {e}")
        return ("", "")


def _get_db_json_version() -> tuple:
    """读取 SQLite 中记录的 JSON 版本号。返回 (version, last_updated)"""
    try:
        with get_db() as conn:
            row = conn.execute("SELECT value FROM config WHERE key = 'json_version'").fetchone()
            version = row["value"] if row else ""
            row = conn.execute("SELECT value FROM config WHERE key = 'json_last_updated'").fetchone()
            last_updated = row["value"] if row else ""
        return (version, last_updated)
    except Exception:
        return ("", "")


def _set_db_json_version(version: str, last_updated: str):
    """记录当前 DB 导入的 JSON 版本号"""
    try:
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO config(key, value) VALUES (?, ?)", ("json_version", version))
            conn.execute("INSERT OR REPLACE INTO config(key, value) VALUES (?, ?)", ("json_last_updated", last_updated))
            conn.commit()
    except Exception as e:
        logger.warning(f"写入 JSON 版本号失败: {e}")


def init_db(force: bool = False):
    """首次运行时从 database.json 导入数据到 SQLite，若库已存在则迁移。

    v3.2: 新增版本号比对机制。当 database.json 的 version/last_updated 与 DB 记录的不一致时，
    自动重新导入（使用 INSERT OR REPLACE，幂等，不丢失运行时表如 rfqs/quotes）。

    Args:
        force: True 时强制重新导入 JSON（无论版本号是否变化）
    """
    # 一次性设置 WAL 模式（数据库级，不需要每个 connection 都设）
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

    # 即使 DB 已存在，也要确保新表（v2.1+）的迁移
    _migrate_v21()

    # v3.2: 版本号比对 — 判断是否需要重新导入
    json_ver, json_updated = _get_json_version()
    db_ver, db_updated = _get_db_json_version()

    if force:
        logger.info(f"强制重新导入 JSON (force=True)")
    elif not os.path.exists(DB_PATH):
        logger.info("SQLite 数据库不存在，开始从 JSON 导入...")
    elif json_ver and json_ver != db_ver:
        logger.info(f"JSON 版本变化: DB={db_ver} -> JSON={json_ver}，触发重新导入")
    elif json_updated and json_updated != db_updated:
        logger.info(f"JSON last_updated 变化: DB={db_updated} -> JSON={json_updated}，触发重新导入")
    else:
        # 版本一致，无需重新导入
        if json_ver:
            logger.info(f"SQLite 数据库已是最新 (json_version={db_ver})，跳过导入")
        else:
            logger.info("SQLite 数据库已存在，执行迁移检查")
        return

    with get_db() as conn:
        c = conn.cursor()
        # v3.2: 导入数据时临时关闭外键检查（INSERT OR REPLACE suppliers 时会触发 products 外键约束）
        c.execute("PRAGMA foreign_keys=OFF")

        # --- 创建表 ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id TEXT PRIMARY KEY,
                name_zh TEXT NOT NULL,
                name_en TEXT NOT NULL,
                city TEXT NOT NULL DEFAULT '',
                province TEXT NOT NULL DEFAULT '',
                port TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL,
                subcategories TEXT NOT NULL DEFAULT '[]',
                year_established INTEGER DEFAULT 0,
                employees INTEGER DEFAULT 0,
                annual_revenue_usd REAL DEFAULT 0,
                export_ratio REAL DEFAULT 0,
                main_markets TEXT NOT NULL DEFAULT '[]',
                moq INTEGER DEFAULT 0,
                lead_time_standard INTEGER DEFAULT 0,
                lead_time_express INTEGER DEFAULT 0,
                certifications TEXT NOT NULL DEFAULT '[]',
                languages TEXT NOT NULL DEFAULT '[]',
                agent_skill_installed INTEGER DEFAULT 0,
                skill_mcp_endpoint TEXT DEFAULT '',
                skill_platforms TEXT NOT NULL DEFAULT '[]',
                skill_installs INTEGER DEFAULT 0,
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                contact_person TEXT DEFAULT '',
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                wechat TEXT DEFAULT '',
                language_contact TEXT NOT NULL DEFAULT '[]',
                -- v2.1+ 列（fresh DB 时直接建好，避免 _migrate_v21 时序问题）
                email_verified INTEGER DEFAULT 0,
                phone_verified INTEGER DEFAULT 0,
                license_verified INTEGER DEFAULT 0,
                trust_score REAL DEFAULT 0,
                trust_level TEXT DEFAULT 'unverified',
                review_count INTEGER DEFAULT 0,
                review_avg REAL DEFAULT 0,
                gold_badge INTEGER DEFAULT 0,
                verification_token TEXT DEFAULT '',
                outreach_used_this_month INTEGER DEFAULT 0,
                outreach_reset_at TEXT DEFAULT '',
                data_source_type TEXT DEFAULT 'hosted',
                access_token TEXT DEFAULT ''
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                name_zh TEXT DEFAULT '',
                name_en TEXT DEFAULT '',
                category TEXT DEFAULT '',
                subcategory TEXT DEFAULT '',           -- v3.1: 子品类（bolt/nut/washer 等）
                material TEXT DEFAULT '',
                grade TEXT DEFAULT '',
                specs TEXT NOT NULL DEFAULT '{}',      -- 规格参数 JSON（diameter/length/finish 等）
                attributes TEXT NOT NULL DEFAULT '[]', -- v3.1: 属性列表 [{name,value,unit}] 对齐 Alibaba attributes
                description TEXT DEFAULT '',           -- v3.1: 产品详细描述
                description_en TEXT DEFAULT '',        -- v3.1: 英文描述
                images TEXT NOT NULL DEFAULT '[]',     -- v3.1: 图片 URL 列表
                pricing_tiers TEXT NOT NULL DEFAULT '[]',  -- [{min_qty,max_qty,unit_price_usd}]
                moq INTEGER DEFAULT 1,                 -- v3.2: 最小起订量（B2B 核心，对齐 Alibaba/1688）
                trade_terms TEXT DEFAULT 'FOB',        -- v3.2: 贸易术语 FOB/CIF/EXW/FCA/DDP
                port TEXT DEFAULT '',                  -- v3.2: 起运港（Ningbo/Shanghai/Shenzhen）
                price_currency TEXT DEFAULT 'USD',     -- v3.2: 计价币种
                price_type TEXT DEFAULT 'FOB',         -- v3.2: 价格基础 FOB/CIF/EXW（与 trade_terms 对齐）
                price_unit TEXT DEFAULT 'pc',          -- v3.2: 计价单位 pc/kg/m/set
                price_validity TEXT DEFAULT '',        -- v3.2: 报价有效期 ISO 日期
                certifications TEXT NOT NULL DEFAULT '[]', -- v3.2: 产品级认证 ["CE","RoHS","ISO9001"]
                packaging_details TEXT DEFAULT '',     -- v3.2: 包装详情文本 "100 pcs/bag, 50 bags/carton"
                supply_ability_monthly INTEGER DEFAULT 0, -- v3.2: 月产能
                inventory_status TEXT DEFAULT 'unknown',
                inventory_quantity INTEGER DEFAULT 0,
                inventory_unit TEXT DEFAULT 'pc',
                inventory_lead_time_days INTEGER DEFAULT 0,
                inventory_updated_at TEXT DEFAULT '',
                weight_kg REAL DEFAULT 0,              -- v3.1: 单件重量（物流计算用）
                package_size TEXT DEFAULT '',          -- v3.1: 包装尺寸 "LxWxH cm"
                package_qty INTEGER DEFAULT 1,         -- v3.1: 每包数量
                hs_code TEXT DEFAULT '',               -- v3.1: 海关编码（出口报关用）
                origin TEXT DEFAULT 'China',           -- v3.1: 原产地
                warranty TEXT DEFAULT '',              -- v3.1: 质保
                payment_terms TEXT DEFAULT '',         -- v3.1: 付款条件 "T/T, L/C, PayPal"
                sample_available INTEGER DEFAULT 0,    -- v3.1: 是否提供样品
                sample_price_usd REAL DEFAULT 0,       -- v3.1: 样品价格
                customized INTEGER DEFAULT 0,          -- v3.1: 是否支持定制
                status TEXT DEFAULT 'active',          -- v3.1: active/draft/discontinued
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS overseas_buyers (
                id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                country TEXT NOT NULL,
                industry TEXT NOT NULL DEFAULT '',
                annual_import_usd REAL DEFAULT 0,
                interested_categories TEXT NOT NULL DEFAULT '[]',
                preferred_supplier_locations TEXT NOT NULL DEFAULT '[]',
                certifications_required TEXT NOT NULL DEFAULT '[]',
                contact_person TEXT DEFAULT '',
                email TEXT DEFAULT '',
                languages TEXT NOT NULL DEFAULT '[]',
                agent_platform TEXT DEFAULT 'unknown',
                agent_installed_linkmoney INTEGER DEFAULT 0,
                last_active TEXT DEFAULT '',
                -- v2.1+ 列（fresh DB 时直接建好）
                email_verified INTEGER DEFAULT 0,
                email_domain TEXT DEFAULT '',
                company_domain TEXT DEFAULT '',
                trust_score REAL DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS rfqs (
                id TEXT PRIMARY KEY,
                supplier_id TEXT NOT NULL,
                buyer_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                target_price_usd REAL DEFAULT 0,
                port TEXT DEFAULT 'Ningbo',
                incoterms TEXT DEFAULT 'FOB',
                delivery_deadline TEXT DEFAULT '',
                contact_email TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT '',
                quoted_price_usd REAL DEFAULT 0,
                lead_time_days INTEGER DEFAULT 0,
                total_price_usd REAL DEFAULT 0,
                notes TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                message TEXT DEFAULT '',                -- v3.0+ — 买家原始自然语言 RFQ
                parsed_data TEXT DEFAULT ''             -- v3.0+ — DeepSeek V4 Flash 解析结果 JSON
            )
        """)
        # 注: rfqs 表的 ALTER TABLE 迁移已移到 _migrate_v21() 里（v3.0+），确保 DB 已存在也能跑

        c.execute("""
            CREATE TABLE IF NOT EXISTS api_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                method TEXT NOT NULL,
                api_key_hash TEXT DEFAULT '',
                ip TEXT DEFAULT '',
                status_code INTEGER DEFAULT 200,
                duration_ms REAL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS beta_signups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factory_name TEXT NOT NULL,
                category TEXT NOT NULL,
                contact_person TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                source TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        # --- 从 JSON 导入数据 ---
        if not JSON_FILE.exists():
            logger.warning(f"JSON 数据文件不存在: {JSON_FILE}，创建空数据库")
            # 写入默认配置
            c.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?, ?)",
                      ("evaluation_template", json.dumps(_default_evaluation_template(), ensure_ascii=False)))
            c.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?, ?)",
                      ("distributions", "[]"))
            c.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?, ?)",
                      ("skill_analytics", "{}"))
            conn.commit()
            return

        with open(JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 导入 suppliers
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        for s in data.get("suppliers", []):
            loc = s.get("location", {})
            ltd = s.get("lead_time_days", {})
            c.execute("""
                INSERT OR REPLACE INTO suppliers(
                    id, name_zh, name_en, city, province, port, category, subcategories,
                    year_established, employees, annual_revenue_usd, export_ratio, main_markets,
                    moq, lead_time_standard, lead_time_express, certifications, languages,
                    agent_skill_installed, skill_mcp_endpoint, skill_platforms, skill_installs,
                    created_at, updated_at, contact_person, email, phone, wechat, language_contact,
                    email_verified, phone_verified, license_verified, trust_score, trust_level,
                    review_count, review_avg, gold_badge, data_source_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                s["id"],
                s["name_zh"],
                s["name_en"],
                loc.get("city", ""),
                loc.get("province", ""),
                loc.get("port", ""),
                s["category"],
                json.dumps(s.get("subcategories", []), ensure_ascii=False),
                s.get("year_established", 0),
                s.get("employees", 0),
                s.get("annual_revenue_usd", 0),
                s.get("export_ratio", 0),
                json.dumps(s.get("main_markets", []), ensure_ascii=False),
                s.get("moq", 0),
                ltd.get("standard", 0),
                ltd.get("express", 0),
                json.dumps(s.get("certifications", []), ensure_ascii=False),
                json.dumps(s.get("languages", []), ensure_ascii=False),
                1 if s.get("agent_skill_installed") else 0,
                s.get("skill_mcp_endpoint", ""),
                json.dumps(s.get("skill_platforms", []), ensure_ascii=False),
                s.get("skill_installs", 0),
                now_iso,
                now_iso,
                s.get("contact_person", ""),
                s.get("email", s.get("contact_email", "")),
                s.get("phone", s.get("contact_phone", "")),
                s.get("wechat", ""),
                json.dumps(s.get("language_contact", {}), ensure_ascii=False),
                1 if s.get("email_verified") else 0,
                1 if s.get("phone_verified") else 0,
                1 if s.get("license_verified") else 0,
                s.get("trust_score", 0),
                s.get("trust_level", "unverified"),
                s.get("review_count", 0),
                s.get("review_avg", 0),
                1 if s.get("gold_badge") else 0,
                s.get("data_source_type", "hosted"),
            ))

            # 导入 products（v3.2: 支持完整字段，对齐 Alibaba/1688/schema.org）
            for p in s.get("products", []):
                inv = p.get("inventory", {})
                c.execute("""
                    INSERT OR REPLACE INTO products(
                        supplier_id, sku, name_zh, name_en, category, subcategory,
                        material, grade, specs, attributes, description, description_en, images,
                        pricing_tiers, moq, trade_terms, port,
                        price_currency, price_type, price_unit, price_validity,
                        certifications, packaging_details, supply_ability_monthly,
                        inventory_status, inventory_quantity, inventory_unit,
                        inventory_lead_time_days, inventory_updated_at,
                        weight_kg, package_size, package_qty, hs_code, origin,
                        warranty, payment_terms, sample_available, sample_price_usd,
                        customized, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s["id"],
                    p.get("sku", ""),
                    p.get("name_zh", ""),
                    p.get("name_en", ""),
                    p.get("category", ""),
                    p.get("subcategory", ""),
                    p.get("material", ""),
                    p.get("grade", ""),
                    json.dumps(p.get("specs", {}), ensure_ascii=False),
                    json.dumps(p.get("attributes", []), ensure_ascii=False),
                    p.get("description", ""),
                    p.get("description_en", ""),
                    json.dumps(p.get("images", []), ensure_ascii=False),
                    json.dumps(p.get("pricing_tiers", []), ensure_ascii=False),
                    p.get("moq", 1),
                    p.get("trade_terms", "FOB"),
                    p.get("port", s.get("location", {}).get("port", "")),
                    p.get("price_currency", "USD"),
                    p.get("price_type", "FOB"),
                    p.get("price_unit", "pc"),
                    p.get("price_validity", ""),
                    json.dumps(p.get("certifications", []), ensure_ascii=False),
                    p.get("packaging_details", ""),
                    p.get("supply_ability_monthly", 0),
                    p.get("inventory_status", inv.get("status", "unknown")),
                    p.get("inventory_quantity", inv.get("quantity", 0)),
                    p.get("inventory_unit", inv.get("unit", "pc")),
                    p.get("inventory_lead_time_days", inv.get("lead_time_days", 0)),
                    p.get("inventory_updated_at", inv.get("updated_at", "")),
                    p.get("weight_kg", 0),
                    p.get("package_size", ""),
                    p.get("package_qty", 1),
                    p.get("hs_code", ""),
                    p.get("origin", "China"),
                    p.get("warranty", ""),
                    p.get("payment_terms", ""),
                    p.get("sample_available", 0),
                    p.get("sample_price_usd", 0),
                    p.get("customized", 0),
                    p.get("status", "active"),
                    p.get("created_at", ""),
                    p.get("updated_at", ""),
                ))

        # 导入 overseas_buyers
        for b in data.get("overseas_buyers", []):
            c.execute("""
                INSERT OR REPLACE INTO overseas_buyers(
                    id, company, country, industry, annual_import_usd, interested_categories,
                    preferred_supplier_locations, certifications_required, contact_person, email,
                    languages, agent_platform, agent_installed_linkmoney, last_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                b["id"],
                b["company"],
                b["country"],
                b.get("industry", ""),
                b.get("annual_import_usd", 0),
                json.dumps(b.get("interested_categories", []), ensure_ascii=False),
                json.dumps(b.get("preferred_supplier_locations", []), ensure_ascii=False),
                json.dumps(b.get("certifications_required", []), ensure_ascii=False),
                b.get("contact_person", ""),
                b.get("email", ""),
                json.dumps(b.get("languages", []), ensure_ascii=False),
                b.get("agent_platform", "unknown"),
                1 if b.get("agent_installed_linkmoney") else 0,
                b.get("last_active", ""),
            ))

        # 导入 rfqs
        for r in data.get("rfqs", []):
            c.execute("""
                INSERT OR REPLACE INTO rfqs(
                    id, supplier_id, buyer_id, sku, quantity, target_price_usd,
                    port, incoterms, delivery_deadline, contact_email, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["id"],
                r.get("supplier_id", ""),
                r.get("buyer_id", ""),
                r.get("sku", ""),
                r.get("quantity", 0),
                r.get("target_price_usd", 0),
                r.get("port", "Ningbo"),
                r.get("incoterms", "FOB"),
                r.get("delivery_deadline", ""),
                r.get("contact_email", ""),
                r.get("status", "pending"),
                r.get("created_at", ""),
            ))

        # 导入 config: skill_analytics, evaluation_template, distributions
        skill_analytics = data.get("skill_analytics", {})
        c.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?, ?)",
                  ("skill_analytics", json.dumps(skill_analytics, ensure_ascii=False)))

        eval_template = data.get("evaluation_template", _default_evaluation_template())
        c.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?, ?)",
                  ("evaluation_template", json.dumps(eval_template, ensure_ascii=False)))

        distributions = data.get("distributions", [])
        c.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?, ?)",
                  ("distributions", json.dumps(distributions, ensure_ascii=False)))

        # v3.2: 记录导入的 JSON 版本号（用于后续版本比对）
        c.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?, ?)",
                  ("json_version", json_ver))
        c.execute("INSERT OR REPLACE INTO config(key, value) VALUES(?, ?)",
                  ("json_last_updated", json_updated))

        conn.commit()
        # 重新开启外键检查
        c.execute("PRAGMA foreign_keys=ON")

    logger.info(f"SQLite 数据库初始化完成 (json_version={json_ver}, json_last_updated={json_updated})")


def _default_evaluation_template():
    """返回默认评估模板（与 SKILL.md 文档一致）"""
    return {
        "dimensions": {
            "overseas_channel_maturity": {"name_zh": "海外渠道成熟度", "name_en": "Overseas Channel Maturity", "weight": 0.25},
            "digital_foundation": {"name_zh": "数字化基础", "name_en": "Digital Foundation", "weight": 0.20},
            "agent_readiness": {"name_zh": "AI/Agent 就绪度", "name_en": "AI/Agent Readiness", "weight": 0.25},
            "category_fitness": {"name_zh": "品类适配度", "name_en": "Category Fitness", "weight": 0.15},
            "content_assets": {"name_zh": "内容资产沉淀", "name_en": "Content Assets", "weight": 0.15},
        },
        "scoring": {
            "A": {"range": [85, 100], "label": "A 级领先", "desc": "已具备 AI 出海 Agent 化条件，建议立即创建 Skill"},
            "B": {"range": [60, 84], "label": "B 级合格", "desc": "基础良好，180 天可达 A 级"},
            "C": {"range": [40, 59], "label": "C 级起步", "desc": "需要补齐数字化基础"},
            "D": {"range": [0, 39], "label": "D 级待建", "desc": "建议先建基础能力再做 Agent 化"},
        },
    }


def _get_config(conn, key, default=None):
    """从 config 表读取配置项"""
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    if row:
        return json.loads(row["value"])
    return default


def _row_to_supplier(row, products_rows=None):
    """将 suppliers 表行转换为原有 dict 格式"""
    if not row:
        return None
    s = dict(row)
    # 重建嵌套结构
    s["location"] = {
        "city": s.pop("city", ""),
        "province": s.pop("province", ""),
        "port": s.pop("port", ""),
    }
    s["lead_time_days"] = {
        "standard": s.pop("lead_time_standard", 0),
        "express": s.pop("lead_time_express", 0),
    }
    # 解析 JSON 字段
    for json_field in ["subcategories", "main_markets", "certifications", "languages", "skill_platforms", "language_contact"]:
        if json_field in s and isinstance(s[json_field], str):
            try:
                s[json_field] = json.loads(s[json_field])
            except (json.JSONDecodeError, TypeError):
                s[json_field] = []
    # 布尔字段
    s["agent_skill_installed"] = bool(s.get("agent_skill_installed", 0))
    return s


def _row_to_product(row):
    """将 products 表行转换为原有 dict 格式"""
    if not row:
        return None
    p = dict(row)
    # 重建 inventory 嵌套
    p["inventory"] = {
        "status": p.pop("inventory_status", "unknown"),
        "quantity": p.pop("inventory_quantity", 0),
        "unit": p.pop("inventory_unit", "pc"),
        "updated_at": p.pop("inventory_updated_at", ""),
    }
    # 解析 JSON 字段
    for json_field in ["specs", "pricing_tiers", "attributes", "images", "certifications"]:
        if json_field in p and isinstance(p[json_field], str):
            try:
                p[json_field] = json.loads(p[json_field])
            except (json.JSONDecodeError, TypeError):
                p[json_field] = {} if json_field == "specs" else []
    return p


def _row_to_buyer(row):
    """将 overseas_buyers 表行转换为原有 dict 格式"""
    if not row:
        return None
    b = dict(row)
    for json_field in ["interested_categories", "preferred_supplier_locations", "certifications_required", "languages"]:
        if json_field in b and isinstance(b[json_field], str):
            try:
                b[json_field] = json.loads(b[json_field])
            except (json.JSONDecodeError, TypeError):
                b[json_field] = []
    b["agent_installed_linkmoney"] = bool(b.get("agent_installed_linkmoney", 0))
    return b


def _log_api(endpoint: str, method: str, api_key_hash: str, ip: str, status_code: int, duration_ms: float):
    """将 API 请求记录写入 api_logs 表"""
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO api_logs(endpoint, method, api_key_hash, ip, status_code, duration_ms) VALUES(?, ?, ?, ?, ?, ?)",
                (endpoint, method, api_key_hash, ip, status_code, duration_ms),
            )
            conn.commit()
    except Exception:
        pass  # 日志写入失败不影响主流程


# ===== TTL 内存缓存（减少数据库查询，提升高并发性能） =====

class TTLCache:
    """简单的 TTL 内存缓存"""

    def __init__(self, ttl_seconds: int = 60):
        self._store: dict = {}
        self._ttl = ttl_seconds

    def get(self, key: str):
        entry = self._store.get(key)
        if entry and time.time() - entry["ts"] < self._ttl:
            return entry["value"]
        if entry:
            del self._store[key]
        return None

    def set(self, key: str, value):
        self._store[key] = {"value": value, "ts": time.time()}

    def invalidate(self, prefix: str = ""):
        if prefix:
            keys = [k for k in self._store if k.startswith(prefix)]
        else:
            keys = list(self._store.keys())
        for k in keys:
            del self._store[k]

    def stats(self):
        return {"entries": len(self._store), "ttl": self._ttl}


# 全局缓存实例
_supplier_cache = TTLCache(ttl_seconds=int(os.getenv("LINKMONEY_CACHE_TTL", "60")))
_buyer_cache = TTLCache(ttl_seconds=int(os.getenv("LINKMONEY_CACHE_TTL", "120")))


# ===== 翻译 API 接入准备 =====

class TranslationProvider:
    """翻译服务抽象基类"""
    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        raise NotImplementedError


class NoOpTranslationProvider(TranslationProvider):
    """空实现翻译器，返回原文 + 标注未翻译"""
    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        return f"[未翻译 | {source_lang}→{target_lang}] {text}"


class DeepLTranslationProvider(TranslationProvider):
    """DeepL 翻译器（空壳，需填入 API Key）"""
    def __init__(self):
        self.api_key = os.getenv("DEEPL_API_KEY", "")
        if not self.api_key:
            logger.warning("DeepLTranslationProvider: DEEPL_API_KEY 未设置，将回退到原文输出")
        # TODO: 填入 DeepL API Key 并实现真实翻译逻辑

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not self.api_key:
            return f"[DeepL 未配置] {text}"
        # TODO: 调用 DeepL API 进行翻译
        # response = requests.post("https://api-free.deepl.com/v2/translate", ...)
        return f"[TODO: DeepL 翻译] {text}"


def _get_translation_provider() -> TranslationProvider:
    """根据环境变量选择翻译 Provider"""
    provider_name = os.getenv("LINKMONEY_TRANSLATION_PROVIDER", "noop").lower()
    if provider_name == "deepl":
        return DeepLTranslationProvider()
    return NoOpTranslationProvider()


# ===== 厂家 MCP 代理转发（混合架构核心） =====

# 代理请求超时配置
MCP_PROXY_TIMEOUT = int(os.getenv("LINKMONEY_MCP_PROXY_TIMEOUT", "8"))  # 厂家 MCP 超时秒数
MCP_PROXY_ENABLED = os.getenv("LINKMONEY_MCP_PROXY_ENABLED", "true").lower() == "true"

# SSRF 防护：禁止访问内网 / 元数据端点
_SSRF_BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal", "100.100.100.200"}
_SSRF_BLOCKED_PREFIXES = ("10.", "127.", "192.168.", "172.16.", "172.17.", "172.18.",
                          "172.19.", "172.20.", "172.21.", "172.22.", "172.23.",
                          "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
                          "172.29.", "172.30.", "172.31.", "169.254.", "::1", "fc", "fd")


def _is_safe_mcp_url(url: str) -> bool:
    """检查 URL 是否指向内网 / 元数据端点（SSRF 防护）"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if host in _SSRF_BLOCKED_HOSTS:
            return False
        if any(host.startswith(p) for p in _SSRF_BLOCKED_PREFIXES):
            return False
        return True
    except Exception:
        return False


def _proxy_to_supplier_mcp(supplier_id: str, mcp_endpoint: str, path: str, params: dict = None) -> dict:
    """
    将请求转发到厂家自己的 MCP Server，获取实时数据。
    成功返回 {"success": true, "data": ...}
    失败返回 {"success": false, "reason": "..."}
    """
    if not MCP_PROXY_ENABLED:
        return {"success": False, "reason": "MCP proxy disabled by config"}

    if not mcp_endpoint:
        return {"success": False, "reason": "Supplier has no MCP endpoint (Skill not installed)"}

    # SSRF 防护：拒绝指向内网 / 元数据端点的 URL
    if not _is_safe_mcp_url(mcp_endpoint):
        logger.error(f"[MCP PROXY] SSRF blocked: {supplier_id} | {mcp_endpoint}")
        return {"success": False, "reason": "Blocked: MCP endpoint points to internal network"}

    try:
        url = urljoin(mcp_endpoint.rstrip("/") + "/", path.lstrip("/"))
        logger.info(f"[MCP PROXY] → {supplier_id} | {url}")
        resp = requests.get(url, params=params or {}, timeout=MCP_PROXY_TIMEOUT,
                            headers={"User-Agent": "LinkMoney-Proxy/1.0"})
        if resp.status_code == 200:
            logger.info(f"[MCP PROXY] ✓ {supplier_id} | {url} | {resp.status_code}")
            return {"success": True, "data": resp.json()}
        else:
            logger.warning(f"[MCP PROXY] ✗ {supplier_id} | {url} | HTTP {resp.status_code}")
            return {"success": False, "reason": f"Supplier MCP returned HTTP {resp.status_code}"}
    except requests.exceptions.Timeout:
        logger.warning(f"[MCP PROXY] ✗ {supplier_id} | timeout after {MCP_PROXY_TIMEOUT}s")
        return {"success": False, "reason": f"Supplier MCP timed out after {MCP_PROXY_TIMEOUT}s"}
    except requests.exceptions.ConnectionError:
        logger.warning(f"[MCP PROXY] ✗ {supplier_id} | connection refused (offline)")
        return {"success": False, "reason": "Supplier MCP is offline"}
    except Exception as e:
        logger.error(f"[MCP PROXY] ✗ {supplier_id} | error: {e}")
        return {"success": False, "reason": str(e)}


# ===== API Key 认证 =====

_API_KEYS: set[str] = set()

def _load_api_keys():
    global _API_KEYS
    keys_str = os.getenv("LINKMONEY_API_KEYS", "lm-demo-2026")
    _API_KEYS = {k.strip() for k in keys_str.split(",") if k.strip()}
    logger.info(f"已加载 {len(_API_KEYS)} 个 API Key(s)")


# ===== 应用初始化 =====

app = FastAPI(
    title="LinkMoney MCP Server",
    description="让全球采购 Agent 主动找上中国供应商的链接器 Skill",
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== SlowAPI 频率限制 =====

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ===== 认证豁免路径 =====

_AUTH_EXEMPT_PATHS = {
    "/", "/en", "/zh", "/health", "/track", "/stats/visits",
    "/mcp/manifest.json", "/docs", "/openapi.json", "/redoc",
    "/onboard-supplier", "/onboard-buyer", "/beta-signup", "/beta-program",
    "/verify_email", "/trust_score/supplier",  # 公开端点：验证 + 信用查询
    "/skill.md", "/.well-known/ai-plugin.json", "/.well-known/linkmoney-skill.json",  # Skill 发现端点
    "/register_buyer",  # v3.3: 海外采购方自注册（公开，降低 W 端闭环门槛）
    "/register_supplier",  # v5.2.3: 中方工厂自注册（公开，降低 C 端闭环门槛，限流 5/hour/IP）
    # v3.0 中间 Agent：作为平台维护者，对内默认开启（可在生产环境收紧）
    "/agent/status", "/agent/health", "/agent/routing",
    "/agent/alerts", "/agent/maintenance", "/agent/optimize", "/agent/maintain",
    "/admin/dashboard",  # v5.1.0 监控看板页面（HTML 公开，数据接口仍需 API Key）
}


# ===== 请求日志与认证中间件 =====

@app.middleware("http")
async def auth_and_logging_middleware(request: Request, call_next):
    start_time = time.time()
    api_key_hash = ""
    status_code = 200

    # 认证检查
    path = request.url.path
    is_exempt = (
        path in _AUTH_EXEMPT_PATHS
        or path.startswith("/verify_email")
        or path.startswith("/trust_score/")
        or path.startswith("/docs")
        or path.startswith("/openapi")
        or path == "/health"
        or path.startswith("/marketplace/")   # v4.0 Agent Marketplace 公开端点
        or path.startswith("/mcp/supplier/")  # v3.3 工厂托管 MCP 端点（公开，海外 Agent 直接调用）
    )
    if not is_exempt:
        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            status_code = 401
            logger.warning(f"缺少 API Key | {request.method} {path} | IP: {request.client.host if request.client else 'unknown'}")
            duration_ms = (time.time() - start_time) * 1000
            _log_api(path, request.method, "", request.client.host if request.client else "", 401, duration_ms)
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "缺少 X-API-Key 请求头，请在请求中提供有效的 API Key"},
            )
        if api_key not in _API_KEYS:
            status_code = 401
            logger.warning(f"无效 API Key | {request.method} {path} | IP: {request.client.host if request.client else 'unknown'}")
            duration_ms = (time.time() - start_time) * 1000
            _log_api(path, request.method, hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else "",
                     request.client.host if request.client else "", 401, duration_ms)
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "API Key 无效"},
            )
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]

    # 执行请求
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as e:
        status_code = 500
        raise e
    finally:
        duration_ms = (time.time() - start_time) * 1000
        logger.info(f"{request.method} {path} | {status_code} | {duration_ms:.1f}ms")
        _log_api(path, request.method, api_key_hash,
                 request.client.host if request.client else "", status_code, duration_ms)

    return response


# ===== Pydantic 模型 =====

class EvaluateRequest(BaseModel):
    company_name: str
    category: str
    dimensions: dict


class InquiryRequest(BaseModel):
    """多语言询盘请求 — v3.0 双向单次设计

    新设计（v3.0+）：
    - 默认走双向单次翻译：buyer_lang → zh 给工厂，zh → buyer_lang 给工厂主回复
    - 旧版 8 国语言参数 target_languages 仍保留（向后兼容），会自动逐个翻译
    - 接入 DeepSeek V4 Flash，data 不出境
    """
    # 新版：双向单次
    inquiry_text: Optional[str] = None    # 任意语言原文（自动检测）
    buyer_lang: str = "en"                # 买家语言
    target_lang: str = "zh"               # 目标语言（默认给中国工厂）

    # 旧版兼容
    inquiry_zh: Optional[str] = None      # 旧版中文输入
    target_languages: Optional[list[str]] = None  # 旧版多语言输出


class DistributionsResponse(BaseModel):
    platform: str
    status: str
    url: str


class SupplierMatch(BaseModel):
    id: str
    name_zh: str
    name_en: str
    location: dict
    match_score: float
    certifications: list
    has_skill: bool


class PricingResponse(BaseModel):
    supplier_id: str
    sku: str
    quantity: int
    tiers: list
    best_tier: dict


class InventoryResponse(BaseModel):
    supplier_id: str
    sku: str
    status: str
    quantity: int
    lead_time_days: dict


# ===== 根路由 =====

# Landing Page 路径（多种可能：build 镜像放 /web/，或运行时 cp 到 /app/web/）
WEB_DIR_CANDIDATES = [
    Path("/web"),                                  # Dockerfile 风格
    Path(__file__).parent / "web",                 # 单层目录
    Path(__file__).parent.parent / "web",         # 双层目录（api/server.py）
]
LANDING_HTML = None
LANDING_EN_HTML = None
for d in WEB_DIR_CANDIDATES:
    p_zh = d / "landing.html"
    p_en = d / "landing_en.html"
    if LANDING_HTML is None and p_zh.exists():
        LANDING_HTML = p_zh
    if LANDING_EN_HTML is None and p_en.exists():
        LANDING_EN_HTML = p_en
    if LANDING_HTML and LANDING_EN_HTML:
        break
if LANDING_HTML is None:
    LANDING_HTML = WEB_DIR_CANDIDATES[0] / "landing.html"  # 兜底
if LANDING_EN_HTML is None:
    LANDING_EN_HTML = WEB_DIR_CANDIDATES[0] / "landing_en.html"  # 兜底


def _detect_lang(accept_language: str) -> str:
    """根据 Accept-Language 头判断语言：en 或 zh。默认 en（海外优先）。"""
    if not accept_language:
        return "en"
    al = accept_language.lower()
    # 中文优先级判断：zh-CN, zh-TW, zh
    for part in al.split(","):
        tag = part.split(";")[0].strip()
        if tag.startswith("zh"):
            return "zh"
    # 默认英文（海外用户优先）
    return "en"


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    """
    根路由 → 营销 Landing Page
    根据 Accept-Language 自动切换：中文 → 中文版，其他 → 英文版
    海外 Agent 调 API 请用 /mcp/manifest.json
    """
    accept_lang = request.headers.get("accept-language", "")
    lang = _detect_lang(accept_lang)
    if lang == "zh" and LANDING_HTML.exists():
        return FileResponse(LANDING_HTML)
    if LANDING_EN_HTML.exists():
        return FileResponse(LANDING_EN_HTML)
    if LANDING_HTML.exists():
        return FileResponse(LANDING_HTML)
    return HTMLResponse(
        "<h1>LinkMoney</h1><p>Landing page not found. See <a href='/mcp/manifest.json'>/mcp/manifest.json</a> for API.</p>",
        status_code=200,
    )


@app.get("/en", response_class=HTMLResponse)
def landing_en():
    """英文版 Landing Page（强制英文）"""
    if LANDING_EN_HTML.exists():
        return FileResponse(LANDING_EN_HTML)
    return HTMLResponse("<h1>LinkMoney</h1><p>English landing page not found.</p>", status_code=200)


@app.get("/zh", response_class=HTMLResponse)
def landing_zh():
    """中文版 Landing Page（强制中文）"""
    if LANDING_HTML.exists():
        return FileResponse(LANDING_HTML)
    return HTMLResponse("<h1>LinkMoney</h1><p>中文页面未找到。</p>", status_code=200)


# ===== MCP 协议端点 =====

@app.get("/skill.md")
def get_skill_md():
    """
    暴露 SKILL.md 给 Agent 自动发现和安装
    Agent 平台（Claude/ChatGPT/Coze）通过此端点获取 Skill 定义
    """
    import os as _os
    skill_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "SKILL.md")
    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="SKILL.md not found")


@app.get("/.well-known/ai-plugin.json")
def ai_plugin_json():
    """
    ChatGPT Plugin 标准发现端点
    ChatGPT 等 Agent 平台通过 /.well-known/ai-plugin.json 自动发现插件

    Agent 行为：发现后会向用户展示插件信息并询问是否安装，不会静默自动安装。
    """
    return {
        "schema_version": "v1",
        "name_for_human": "LinkMoney",
        "name_for_model": "linkmoney",
        "description_for_human": "找中国供应商，查价格库存（verified 工厂实时，其余缓存），发 RFQ 询盘。73 verified + 2700 目录缓存，16 品类，Agent 时代 B2B 贸易。",
        "description_for_model": "Find China suppliers, get pricing and inventory (verified factories real-time, others cached), submit RFQ. 73 verified + 2700 directory listings, 16 categories, B2B trade for AI agents. Triggers: China supplier, China manufacturer, China OEM, fastener supplier, sourcing agent China, RFQ China.",
        "auth": {"type": "none"},
        "api": {"type": "openapi", "url": "http://118.196.34.217:8765/openapi.json"},
        "logo_url": "http://118.196.34.217:8765/logo.png",
        "contact_email": "support@linkmoney.online",
        "legal_info_url": "http://118.196.34.217:8765/",
        # LinkMoney 扩展字段
        "mcp_endpoint": "http://118.196.34.217:8765/mcp/manifest.json",
        "skill_url": "http://118.196.34.217:8765/skill.md",
        "install_command": "npx skills add KevinANDcayla/linkmoney-skill",
        "requires_user_confirmation": True,
        "activation_policy": "strong_trigger_suggest_install, weak_trigger_hint_availability",
    }


@app.get("/.well-known/linkmoney-skill.json")
def linkmoney_skill_json():
    """
    LinkMoney Skill 自动发现端点（兼容 supplier_mcp_template 标准）
    Agent 平台通过此端点发现 LinkMoney 平台 Skill

    Agent 安装行为说明：
    - 强信号触发词命中 → Agent 主动建议用户安装（如 Claude/ChatGPT 询问"是否安装此 Skill？"）
    - 弱信号触发词命中 → Agent 在相关上下文中提示用户可安装
    - 用户确认后 → Agent 执行 install_command 或加载 mcp_endpoint
    - Agent 不会"静默自动安装"，所有安装都需用户确认（安全设计）
    """
    return {
        "skill_name": "linkmoney",
        "version": "4.0.0",
        "description": "LinkMoney — Agent 时代的 B2B 贸易链接器，让海外 AI Agent 主动找上中国供应商",
        "mcp_endpoint": "http://118.196.34.217:8765/mcp/manifest.json",
        "skill_md": "http://118.196.34.217:8765/skill.md",
        "install_command": "npx skills add KevinANDcayla/linkmoney-skill",
        "triggers": {
            "strong_cn": ["中国供应商", "找中国工厂", "紧固件 OEM", "中国制造出口", "螺栓供应商", "AI 出海 Agent 化"],
            "weak_cn": ["找工厂", "工厂合作", "想做点东西", "代工厂", "sourcing", "采购", "外贸", "出口", "跨境"],
            "strong_en": ["China supplier", "China manufacturer", "China OEM", "fastener supplier", "sourcing agent China", "RFQ China"],
            "weak_en": ["looking for a factory", "source from China", "source in China", "Made in China", "Chinese factory", "procure from China", "OEM China", "supplier in China"],
        },
        "tools_count": 41,
        "categories": ["fastener", "electronic", "packaging", "mechanical", "hardware", "injection_molding", "textile", "automotive", "furniture"],
        "supplier_count": 51,
        # Agent 安装指引（让 Agent 知道如何安装）
        "installation": {
            "method": "mcp_or_skill",
            "steps": [
                "1. Agent 读取 skill_md 获取完整 Skill 定义",
                "2. Agent 读取 mcp_endpoint 获取可用工具清单",
                "3. 用户确认后，执行 install_command 或将 mcp_endpoint 加入 Agent 配置",
                "4. 安装完成后，Agent 可调用 find_china_supplier 等工具",
            ],
            "auto_activate": False,
            "requires_user_confirmation": True,
            "activation_policy": "strong_trigger_suggest_install, weak_trigger_hint_availability",
        },
        # Agent 快速理解 Skill 价值
        "value_proposition": {
            "for_buyer_agent": "一键找中国工厂（73 verified + 2700 目录缓存），查价格库存，5 秒发 RFQ",
            "for_supplier_agent": "5 维 AI 出海评估 + 一键创建 Skill + 全平台分发",
            "data_freshness": "混合架构：缓存数据 + 厂家 MCP 直连实时数据",
        },
    }


@app.get("/mcp/manifest.json")
def mcp_manifest():
    """
    MCP 协议清单 — 从 mcp_manifest.json 文件读取，确保与 GitHub 仓库一致
    """
    import json as _json
    import os as _os
    manifest_path = _os.path.join(_os.path.dirname(__file__), "mcp_manifest.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        # fallback to minimal manifest
        return {
            "name": "linkmoney",
            "version": "5.2.1",
            "description": "LinkMoney — B2B Trade Connector for AI Agents. 73 verified + 2700 directory listings, 16 categories. API Key: lm-demo-2026",
            "api_key": "lm-demo-2026",
            "api_key_header": "X-API-Key",
            "base_url": "http://118.196.34.217:8765",
            "tools": [
                {"name": "find_china_supplier", "description": "Find Chinese manufacturers. REQUIRED when user asks to find suppliers/factories. Returns 8-15 ranked suppliers. Params: category (required), spec, quantity, target_price", "endpoint": "GET /find_china_supplier"},
            ],
            "homepage": "http://118.196.34.217:8765",
        }


# ===== C 端（中国制造业老板侧）Tools =====

@app.post("/evaluate_sme")
def evaluate_sme(req: EvaluateRequest):
    """
    5 维 AI 出海 Agent 化评估
    输入：企业名称 + 品类 + 5 维分数
    输出：总分 + 5 维雷达图 + 180 天路线图
    """
    with get_db() as conn:
        template = _get_config(conn, "evaluation_template", _default_evaluation_template())

    # v3.3.2: 兼容旧版 list 格式的 dimensions
    # 如果 DB 中存的是旧版 7 维 list（price_competitiveness 等），回退到默认 5 维模板
    default_template = _default_evaluation_template()
    dims_template = template.get("dimensions", {})
    if isinstance(dims_template, list):
        # 旧版 list 格式 → 检查维度名是否与默认模板匹配
        list_keys = {d.get("key") for d in dims_template if "key" in d}
        default_keys = set(default_template["dimensions"].keys())
        if list_keys != default_keys:
            # 维度名不匹配（旧版 7 维），使用默认 5 维模板
            template = default_template
            dims_template = template["dimensions"]
        else:
            # 维度名匹配，转换为 dict 格式
            dims_template = {d["key"]: d for d in dims_template if "key" in d}
            template["dimensions"] = dims_template

    dims = req.dimensions
    scores = {}

    # 校验 5 维完整性
    expected_dims = set(dims_template.keys())
    provided_dims = set(dims.keys())
    missing_dims = expected_dims - provided_dims
    if missing_dims:
        raise HTTPException(
            status_code=422,
            detail=f"缺少维度: {', '.join(missing_dims)}。请提供全部 {len(expected_dims)} 个维度: {', '.join(expected_dims)}",
        )

    total = 0
    for key, info in template["dimensions"].items():
        score = dims.get(key, 0)
        weight = info["weight"]
        scores[key] = {
            "score": score,
            "weight": weight,
            "name_zh": info["name_zh"],
            "name_en": info.get("name_en", key),
        }
        total += score * weight

    total_rounded = round(total)

    # 确定分级
    level = "D"
    level_label = "D 级待建"
    level_desc = "建议先建数字化基础"
    for grade_key in ["A", "B", "C", "D"]:
        g = template["scoring"][grade_key]
        if g["range"][0] <= total_rounded <= g["range"][1]:
            level = grade_key
            level_label = g["label"]
            level_desc = g["desc"]
            break

    # 180 天路线图
    if level == "A":
        roadmap = [
            {"phase": "第 1-30 天", "action": "注册入驻 LinkMoney + 托管 MCP 自动激活 + 产品上线"},
            {"phase": "第 31-90 天", "action": "完善产品目录（阶梯报价/库存/认证）+ 对接首批海外 Agent"},
            {"phase": "第 91-180 天", "action": "优化数据质量 + 稳定询盘流 + 数据驱动提升路由评分"},
        ]
    elif level == "B":
        roadmap = [
            {"phase": "第 1-30 天", "action": "注册入驻 LinkMoney，托管 MCP 自动激活，产品上线"},
            {"phase": "第 31-60 天", "action": "完善产品目录（阶梯报价/库存/认证），海外 Agent 开始查询"},
            {"phase": "第 61-120 天", "action": "对接海外采购方 Agent，收获首批 RFQ，完成报价成交"},
            {"phase": "第 121-180 天", "action": "优化产品数据质量，提升路由评分，稳定询盘流"},
        ]
    elif level == "C":
        roadmap = [
            {"phase": "第 1-30 天", "action": "补齐数字化基础（ERP/CRM/多语言网站）"},
            {"phase": "第 31-60 天", "action": "整理产品规格书 + 认证文件数字化"},
            {"phase": "第 61-120 天", "action": "注册入驻 LinkMoney + 产品上线 + 基础对接"},
            {"phase": "第 121-180 天", "action": "验证询盘 + 优化 + 对接海外 Agent"},
        ]
    else:
        roadmap = [
            {"phase": "第 1-60 天", "action": "建设数字化基础设施"},
            {"phase": "第 61-120 天", "action": "积累内容资产 + 出口能力建设"},
            {"phase": "第 121-180 天", "action": "准备 Agent 化 + 评估重测"},
        ]

    target_score = min(total_rounded + 25, 100) if level != "A" else total_rounded

    return {
        "company_name": req.company_name,
        "category": req.category,
        "total_score": total_rounded,
        "level": level,
        "level_label": level_label,
        "level_desc": level_desc,
        "scores": scores,
        "target_180d_score": target_score,
        "roadmap": roadmap,
        "next_action": "register_supplier" if level in ["A", "B"] else "digital_foundation",
    }


# ===== W 端（海外采购方侧）Tools =====

@app.get("/find_china_supplier")
@limiter.limit("30/minute")
def find_china_supplier(
    request: Request,
    category: str = Query(..., description="品类：fastener/packaging/electronic/hardware/injection_molding/machinery/textile"),
    spec: str = Query("", description="规格描述"),
    quantity: int = Query(0, description="采购数量"),
    target_price: str = Query("", description="目标价格（如 0.15 USD）"),
    port: str = Query("", description="指定 FOB 港口（如 Ningbo/Shanghai/Shenzhen），优先返回该港口附近供应商"),
    include_directory: bool = Query(False, description="是否包含 cached 目录数据（非签约工厂）。默认 false 只返回 verified+hosted"),
):
    """
    海外采购方找中国供应商（混合架构，v4.0 多维加权评分）
    输入：品类 + 规格 + 数量 + 目标价 + 港口（可选）
    输出：8-15 家工厂比价 + 推荐方案（评分 ≥ 60 的全部返回）
    已装 Skill 的 verified 厂家返回 mcp_endpoint，支持实时报价/库存查询

    v5.2.1 数据透明度：
    - 默认只返回 verified + hosted 工厂（data_provenance 标注）
    - include_directory=true 才返回 cached 目录数据（非签约）
    - 每条结果标注 data_provenance: verified | hosted | cached
    - 每条结果标注 data_source: live | cache（live 仅 verified 工厂）

    v4.0 修复：
    - 7 维加权评分（品类/spec/MOQ/价格/认证/地理/Skill 在线）
    - 动态返回 8-15 家（≥60 分全部返回，最少 5 家兜底）
    - quantity/target_price 参与匹配
    - 修复缓存写入死代码
    - v5.0.5: 支持 port 参数，港口匹配加分；spec 匹配优先产品名
    """
    # 缓存检查（缓存 key 包含 target_price + port + include_directory）
    cache_key = f"find:{category}:{spec}:{quantity}:{target_price}:{port}:{include_directory}"
    cached = _supplier_cache.get(cache_key)
    if cached:
        return cached

    # 一次性查询所有供应商 + 产品（修复 N+1 查询）
    # v5.2.1: 默认过滤掉 cached 目录数据（非签约），仅 include_directory=true 时包含
    with get_db() as conn:
        if include_directory:
            supplier_rows = conn.execute(
                "SELECT * FROM suppliers WHERE category = ?", (category,)
            ).fetchall()
        else:
            supplier_rows = conn.execute(
                "SELECT * FROM suppliers WHERE category = ? AND data_source_type IN ('verified', 'hosted')",
                (category,),
            ).fetchall()
        if supplier_rows:
            supplier_ids = [row["id"] for row in supplier_rows]
            placeholders = ",".join("?" * len(supplier_ids))
            product_rows = conn.execute(
                f"SELECT * FROM products WHERE supplier_id IN ({placeholders})",
                supplier_ids,
            ).fetchall()
        else:
            product_rows = []
        # v5.2: 加载动态权重（积累学习层），失败回退默认值
        match_weights_data = _load_match_weights(conn)
        dynamic_weights = match_weights_data["weights"]

    if not supplier_rows:
        return {"matches": [], "message": f"No supplier found for category: {category}"}

    # 按供应商 ID 分组产品
    products_by_supplier = {}
    for pr in product_rows:
        products_by_supplier.setdefault(pr["supplier_id"], []).append(_row_to_product(pr))

    # 解析目标价
    target_price_value = 0.0
    if target_price:
        try:
            target_price_value = float(target_price.replace("USD", "").replace("usd", "").strip())
        except (ValueError, AttributeError):
            pass

    # spec 分词（用于多关键词匹配，而非子串包含）
    spec_keywords = [w.strip().lower() for w in spec.replace(",", " ").replace("，", " ").split() if w.strip()] if spec else []

    # 主要出口港口集合
    _MAJOR_PORTS = {"ningbo", "shanghai", "shenzhen", "guangzhou"}

    matches = []
    for s_row in supplier_rows:
        s = _row_to_supplier(s_row)
        s["products"] = products_by_supplier.get(s["id"], [])

        # ===== v4.0: 7 维加权评分（0-100） =====
        score = 0
        # 用独立变量记录每个维度得分，用于 match_breakdown
        dim_category = 0
        dim_spec = 0
        dim_moq = 0
        dim_price = 0
        dim_certs = 0
        dim_location = 0
        dim_skill = 0

        # 1. 品类匹配 30%（已通过 SQL 硬过滤，给满分）
        dim_category = 30
        score += dim_category

        # 2. spec 匹配 20%（优先匹配产品名，其次 SKU/材质）
        matching_product = None
        if spec_keywords:
            # 第一轮：优先匹配产品名（name_en / name_zh）
            best_hit_count = 0
            for p in s.get("products", []):
                name_text = f"{p.get('name_en', '')} {p.get('name_zh', '')}".lower()
                name_hit = sum(1 for kw in spec_keywords if kw in name_text)
                if name_hit > best_hit_count:
                    best_hit_count = name_hit
                    matching_product = p
            # 第二轮：如果产品名没命中，再匹配 SKU/材质/等级
            if not matching_product:
                for p in s.get("products", []):
                    product_text = f"{p.get('sku', '')} {p.get('material', '')} {p.get('grade', '')}".lower()
                    hit_count = sum(1 for kw in spec_keywords if kw in product_text)
                    if hit_count > 0:
                        matching_product = p
                        best_hit_count = hit_count
                        break
            if matching_product and best_hit_count > 0:
                dim_spec = min(20, int(20 * best_hit_count / len(spec_keywords)))
                score += dim_spec
        else:
            # 无 spec 输入，给基础分
            dim_spec = 10
            score += dim_spec

        if not matching_product and s.get("products"):
            matching_product = s["products"][0]

        # 3. MOQ 满足 15%（采购量 ≥ MOQ 才得分）
        supplier_moq = s.get("moq", 0) or 0
        if quantity > 0:
            if supplier_moq == 0 or quantity >= supplier_moq:
                dim_moq = 15
            elif quantity >= supplier_moq * 0.5:
                dim_moq = 8  # 接近 MOQ 给半分
        else:
            dim_moq = 7  # 未提供数量给半分
        score += dim_moq

        # 4. 价格区间 15%（目标价 ± 30% 内加分）
        if target_price_value > 0 and matching_product:
            pricing_tiers = matching_product.get("pricing_tiers", [])
            if pricing_tiers:
                # 找到匹配数量的报价档
                best_price = None
                for tier in pricing_tiers:
                    min_qty = tier.get("min_qty", 0)
                    max_qty = tier.get("max_qty")
                    if quantity >= min_qty and (max_qty is None or quantity <= max_qty):
                        best_price = tier.get("unit_price_usd", 0)
                        break
                if best_price is None and pricing_tiers:
                    best_price = pricing_tiers[-1].get("unit_price_usd", 0)

                if best_price and best_price > 0:
                    price_diff = abs(best_price - target_price_value) / target_price_value
                    if price_diff <= 0.1:
                        dim_price = 15  # ±10% 内满分
                    elif price_diff <= 0.3:
                        dim_price = 10  # ±30% 内大部分分
                    elif price_diff <= 0.5:
                        dim_price = 5   # ±50% 内半分
                    # 超过 50% 不加分
            else:
                dim_price = 5  # 无报价数据给基础分
        else:
            dim_price = 5  # 无目标价给基础分
        score += dim_price

        # 5. 认证匹配 10%
        certs = s.get("certifications", [])
        if isinstance(certs, list):
            cert_count = len(certs)
        else:
            cert_count = 0
        dim_certs = min(10, cert_count * 2)  # 每张认证 +2，最多 10
        score += dim_certs

        # 6. 地理位置 5%（港口匹配加分 — 支持用户指定 port 参数）
        supplier_port = s.get("location", {}).get("port", "")
        if port and supplier_port:
            # 用户指定了港口，精确匹配加分
            if supplier_port.lower() == port.lower():
                dim_location = 5  # 精确匹配满分
            elif supplier_port.lower() in _MAJOR_PORTS:
                dim_location = 3  # 主要港口部分分
            else:
                dim_location = 1  # 其他港口
        elif supplier_port and supplier_port.lower() in _MAJOR_PORTS:
            dim_location = 5  # 主要出口港口加分
        else:
            dim_location = 2  # 其他港口给基础分
        score += dim_location

        # 7. Skill 在线 5%
        if s["agent_skill_installed"]:
            dim_skill = 5
            # 安装数额外微调（不超 5 分上限）
            installs = s.get("skill_installs", 0) or 0
            if installs > 100:
                dim_skill = min(5, dim_skill + 2)  # 安装数高微加
        score += dim_skill

        # v5.2: 用动态权重重新归一化（积累学习层）
        # 每个维度先转为 0-1 比例（dim_value / default_max），再用动态权重加权
        # 当 weights = defaults 时，score 不变；weights 变化时，score 按学习结果重加权
        # 除以权重总和确保 score ∈ [0, 100]（即使权重因步长限制总和不等于 100）
        _weight_sum = sum(dynamic_weights.values()) or 100
        ratio_category = dim_category / 30.0
        ratio_spec = dim_spec / 20.0
        ratio_moq = dim_moq / 15.0
        ratio_price = dim_price / 15.0
        ratio_certs = dim_certs / 10.0
        ratio_location = dim_location / 5.0
        ratio_skill = dim_skill / 5.0
        score = int(
            (
                ratio_category * dynamic_weights["category"] +
                ratio_spec * dynamic_weights["spec"] +
                ratio_moq * dynamic_weights["moq"] +
                ratio_price * dynamic_weights["price"] +
                ratio_certs * dynamic_weights["certs"] +
                ratio_location * dynamic_weights["location"] +
                ratio_skill * dynamic_weights["skill"]
            ) * 100 / _weight_sum
        )

        # 确保分数在 0-100
        score = max(0, min(100, score))

        # 样板产品列表（用于 Agent 初步判断匹配度）
        sample_products = []
        for p in s.get("products", [])[:5]:
            sample_products.append({
                "sku": p.get("sku", ""),
                "name_zh": p.get("name_zh", ""),
                "name_en": p.get("name_en", ""),
                "material": p.get("material", ""),
            })

        match_entry = {
            "supplier_id": s["id"],
            "name_zh": s["name_zh"],
            "name_en": s["name_en"],
            "location": s["location"],
            "match_score": score,
            "match_breakdown": {
                "category": dim_category,
                "spec": dim_spec,
                "moq": dim_moq,
                "price": dim_price,
                "certs": dim_certs,
                "location": dim_location,
                "skill": dim_skill,
                "total": score,
                # v5.2: 动态权重（积累学习层），让 Agent 看到当前实际权重
                "dynamic_weights": dynamic_weights,
                "weights_source": "learned" if match_weights_data["sample_count"] > 0 else "default",
            },
            "certifications": [c["type"] if isinstance(c, dict) else c for c in s.get("certifications", [])],
            "has_skill": s["agent_skill_installed"],
            "skill_installs": s.get("skill_installs", 0),
            "moq": supplier_moq,
            "lead_time_days": s.get("lead_time_days", {}),
            "matching_product": matching_product["sku"] if matching_product else None,
            "sample_products": sample_products,
            # ===== 混合架构关键字段 =====
            "mcp_endpoint": s.get("skill_mcp_endpoint", "") if s["agent_skill_installed"] else "",
            "data_provenance": s.get("data_source_type", "cached"),  # v5.2.1: verified | hosted | cached
            "data_source": "live" if (s["agent_skill_installed"] and s.get("skill_mcp_endpoint") and s.get("data_source_type") == "verified") else "cache",
            "next_action": {
                "description": f"调用 {s['name_zh']} 的 MCP Server 获取报价和库存（verified 工厂支持实时查询）",
                "endpoint": s.get("skill_mcp_endpoint", ""),
                "pricing_url": f"{s.get('skill_mcp_endpoint', '').rstrip('/')}/pricing?sku={{sku}}&quantity={quantity}" if s["agent_skill_installed"] and s.get("skill_mcp_endpoint") else "",
                "inventory_url": f"{s.get('skill_mcp_endpoint', '').rstrip('/')}/inventory?sku={{sku}}" if s["agent_skill_installed"] and s.get("skill_mcp_endpoint") else "",
                "products_url": f"{s.get('skill_mcp_endpoint', '').rstrip('/')}/products" if s["agent_skill_installed"] and s.get("skill_mcp_endpoint") else "",
            } if s["agent_skill_installed"] and s.get("skill_mcp_endpoint") else {
                "description": "供应商未安装 LinkMoney Skill，返回 LinkMoney 缓存数据。verified 工厂安装 Skill 后支持实时查询。",
                "action": "invite_supplier_to_install_skill",
            },
            "contact": {
                "person": s.get("contact_person", "") if s["agent_skill_installed"] else "",
                "email": s.get("email", "") if s["agent_skill_installed"] else "",
                "phone": s.get("phone", "") if s["agent_skill_installed"] else "",
                "available": s["agent_skill_installed"],
                "hint": "" if s["agent_skill_installed"] else "该供应商尚未安装 LinkMoney Skill，联系方式暂不可见。供应商安装 Skill 后自动公开。",
            },
        }
        matches.append(match_entry)

    # 按分数排序：评分降序 → Skill 在线优先 → 安装数降序
    matches.sort(key=lambda x: (x["match_score"], x["has_skill"], x["skill_installs"]), reverse=True)

    # v4.0: 动态返回 8-15 家（≥60 分的全部，最少 5 家兜底）
    qualified = [m for m in matches if m["match_score"] >= 60]
    if len(qualified) >= 5:
        top_matches = qualified[:15]  # 最多 15 家
    else:
        top_matches = matches[:max(5, len(qualified))]  # 兜底至少 5 家

    # 引导 Agent 下一步操作
    skilled_count = len([m for m in top_matches if m["has_skill"] and m.get("mcp_endpoint")])

    result = {
        "total_matches": len(matches),
        "returned_matches": len(top_matches),
        "category": category,
        "recommendation": top_matches[0]["name_zh"] if top_matches else None,
        "recommendation_reason": "综合匹配度最高（7 维加权评分）" if top_matches else "",
        "matches": top_matches,
        # Agent 操作指引
        "agent_workflow": {
            "step_1": f"从 {len(top_matches)} 家匹配厂家中，选择 {min(skilled_count, 3) if skilled_count > 0 else 2} 家进一步询价",
            "step_2": f"有 Skill 的 {skilled_count} 家 → 调用其 mcp_endpoint 获取报价/库存（verified 工厂返回实时数据）",
            "step_3": f"无 Skill 的 {len(top_matches) - skilled_count} 家 → 调用 LinkMoney get_pricing/get_inventory（缓存数据）",
            "step_4": "对比报价后，调用 submit_rfq 提交正式询盘给最优供应商",
            "note": "每条结果标注 data_provenance (verified|hosted|cached) 和 data_source (live|cache)。verified 工厂支持 MCP 实时查询，其余返回缓存档案。",
        },
        "live_suppliers": skilled_count,
        "cached_suppliers": len(top_matches) - skilled_count,
        "scoring_model": f"v5.2 7-dimensional weighted (dynamic): category({dynamic_weights['category']}) + spec({dynamic_weights['spec']}) + moq({dynamic_weights['moq']}) + price({dynamic_weights['price']}) + certs({dynamic_weights['certs']}) + location({dynamic_weights['location']}) + skill({dynamic_weights['skill']})",
    }

    # 写入缓存（修复：移到 return 之前）
    _supplier_cache.set(cache_key, result)
    return result


@app.get("/get_pricing")
@limiter.limit("30/minute")
def get_pricing(
    request: Request,
    supplier_id: str,
    sku: str,
    quantity: int = 1000,
):
    """
    查供应商阶梯价格（混合架构：优先实时 MCP，fallback 缓存）
    1. 如果供应商有 MCP 端点 → 代理转发到厂家 MCP 获取实时价格
    2. 如果厂家 MCP 不可达 → fallback 到 LinkMoney 本地缓存
    """
    with get_db() as conn:
        s_row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()

    if not s_row:
        raise HTTPException(status_code=404, detail="Supplier not found")

    supplier = _row_to_supplier(s_row)
    mcp_endpoint = supplier.get("skill_mcp_endpoint", "")

    # 尝试从厂家 MCP 获取实时价格
    if supplier.get("agent_skill_installed") and mcp_endpoint:
        proxy_result = _proxy_to_supplier_mcp(supplier_id, mcp_endpoint, "/pricing",
                                               params={"sku": sku, "quantity": quantity})
        if proxy_result["success"]:
            live_data = proxy_result["data"]
            live_data["_meta"] = {
                "source": "supplier_mcp",
                "supplier_id": supplier_id,
                "is_live": True,
                "note": "此数据直接来自厂家 MCP Server，实时准确",
            }
            return live_data
        # fallback 到本地缓存
        fallback_reason = proxy_result["reason"]
    else:
        fallback_reason = "Supplier has no MCP endpoint"

    # --- Fallback: 从本地 SQLite 缓存获取 ---
    with get_db() as conn:
        p_row = conn.execute(
            "SELECT * FROM products WHERE supplier_id = ? AND sku = ?", (supplier_id, sku)
        ).fetchone()

    if not p_row:
        raise HTTPException(status_code=404, detail=f"SKU {sku} not found in cache (supplier MCP also unreachable: {fallback_reason})")

    product = _row_to_product(p_row)

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
        "supplier_id": supplier_id,
        "supplier_name": supplier["name_zh"],
        "sku": sku,
        "product_name": product["name_zh"],
        "requested_quantity": quantity,
        "pricing_tiers": tiers,
        "matched_tier": best_tier,
        "unit_price_usd": best_tier.get("unit_price_usd") if best_tier else None,
        "total_price_usd": round(best_tier.get("unit_price_usd", 0) * quantity, 2) if best_tier else None,
        "moq": supplier.get("moq", 0),
        "fob_port": supplier["location"]["port"],
        "_meta": {
            "source": "linkmoney_cache",
            "supplier_id": supplier_id,
            "is_live": False,
            "fallback_reason": fallback_reason,
            "note": "此数据来自 LinkMoney 本地缓存，可能不是最新。建议供应商安装 LinkMoney Skill 以提供实时数据。",
        },
    }


@app.get("/get_inventory")
def get_inventory(supplier_id: str, sku: str):
    """
    查供应商实时库存（混合架构：优先实时 MCP，fallback 缓存）
    1. 如果供应商有 MCP 端点 → 代理转发到厂家 MCP 获取实时库存
    2. 如果厂家 MCP 不可达 → fallback 到 LinkMoney 本地缓存
    """
    with get_db() as conn:
        s_row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()

    if not s_row:
        raise HTTPException(status_code=404, detail="Supplier not found")

    supplier = _row_to_supplier(s_row)
    mcp_endpoint = supplier.get("skill_mcp_endpoint", "")

    # 尝试从厂家 MCP 获取实时库存
    if supplier.get("agent_skill_installed") and mcp_endpoint:
        proxy_result = _proxy_to_supplier_mcp(supplier_id, mcp_endpoint, "/inventory",
                                               params={"sku": sku})
        if proxy_result["success"]:
            live_data = proxy_result["data"]
            live_data["_meta"] = {
                "source": "supplier_mcp",
                "supplier_id": supplier_id,
                "is_live": True,
                "note": "此库存数据直接来自厂家 ERP/MCP，实时准确",
            }
            return live_data
        fallback_reason = proxy_result["reason"]
    else:
        fallback_reason = "Supplier has no MCP endpoint"

    # --- Fallback: 从本地 SQLite 缓存获取 ---
    with get_db() as conn:
        p_row = conn.execute(
            "SELECT * FROM products WHERE supplier_id = ? AND sku = ?", (supplier_id, sku)
        ).fetchone()

    if not p_row:
        raise HTTPException(status_code=404, detail=f"SKU {sku} not found in cache (supplier MCP also unreachable: {fallback_reason})")

    product = _row_to_product(p_row)
    inv = product.get("inventory", {})

    return {
        "supplier_id": supplier_id,
        "sku": sku,
        "status": inv.get("status", "unknown"),
        "status_label": {
            "sufficient": "库存充足",
            "tight": "库存紧张",
            "out_of_stock": "缺货",
            "made_to_order": "按单生产",
        }.get(inv.get("status"), inv.get("status")),
        "quantity": inv.get("quantity", 0),
        "unit": inv.get("unit", "pc"),
        "lead_time_days": supplier.get("lead_time_days", {}),
        "updated_at": inv.get("updated_at", ""),
        "_meta": {
            "source": "linkmoney_cache",
            "supplier_id": supplier_id,
            "is_live": False,
            "fallback_reason": fallback_reason,
            "note": "此数据来自 LinkMoney 本地缓存，可能不是最新。建议供应商安装 LinkMoney Skill 以提供实时数据。",
        },
    }


@app.get("/match_spec")
def match_spec(category: str, specification: str):
    """
    规格匹配咨询
    输入：品类 + 规格需求
    输出：匹配方案 + 公差建议

    v5.2: 优先用 LLM 解析 specification（能理解 M8/DIN933/304SS 等具体参数），
    LLM 不可用时降级回硬编码知识库（仅按品类返回通用建议）。
    """
    # v5.2: LLM 增强 — 解析具体 specification，给出针对性的公差/材料建议
    try:
        llm = get_llm()
        if llm.is_available():
            prompt = f"""你是 B2B 工业品规格匹配专家。给定品类和规格需求，输出严格 JSON：
{{
  "industry_standards": ["..."],
  "tolerance_advice": {{"standard": "±Xmm", "precision": "±Xmm"}},
  "material_options": ["..."],
  "additional_options": {{}},
  "advice": "一句话匹配建议，必须引用 specification 中的具体参数"
}}

品类: {category}
规格需求: {specification}

约束:
1. 仅输出 JSON，不要 markdown 代码块
2. 若 specification 包含具体数值（如 M8 / 304SS / PN16），tolerance 和 material 必须与之匹配
3. 若品类未知，industry_standards 返回 ["GB"]，advice 写明"该品类建议人工确认\""""
            result = llm._call(
                model=llm.flash_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.2,
            )
            parsed = json.loads(result)
            parsed["source"] = "llm"
            parsed["category"] = category
            parsed["specification"] = specification
            return parsed
    except Exception as e:
        logger.warning(f"match_spec LLM failed, fallback to hardcoded: {e}")

    # Fallback: 硬编码知识库（7 品类）
    spec_knowledge = {
        "fastener": {
            "standards": ["DIN", "ISO", "ANSI", "JIS", "GB"],
            "tolerance": {"standard": "±0.1mm", "precision": "±0.05mm"},
            "material_options": ["304 SS", "316 SS", "Carbon Steel", "Alloy Steel", "Brass"],
            "surface_treatment": ["Zinc Plated", "Hot Dip Galvanized", "Black Oxide", "Passivated"],
        },
        "hardware": {
            "standards": ["DIN", "ANSI", "JIS", "GB"],
            "tolerance": {"standard": "±0.2mm", "precision": "±0.1mm"},
            "material_options": ["304 SS", "316 SS", "Carbon Steel", "Brass", "Bronze"],
            "pressure_rating": ["PN10", "PN16", "PN25", "PN40", "150LB", "300LB", "600LB"],
        },
        "electronic": {
            "standards": ["IPC-A-600", "IPC-6012", "UL"],
            "tolerance": {"standard": "±0.1mm", "precision": "±0.05mm"},
            "material_options": ["FR4", "High-Tg FR4", "Aluminum", "Ceramic", "Rogers"],
        },
        "injection_molding": {
            "standards": ["DIN 16742", "ISO 20457"],
            "tolerance": {"standard": "±0.1mm", "precision": "±0.05mm"},
            "material_options": ["ABS", "PC", "PA6", "PA66", "POM", "PP", "TPE"],
        },
        "textile": {
            "standards": ["OEKO-TEX", "GOTS", "AATCC"],
            "tolerance": {"standard": "±2%", "precision": "±1%"},
            "material_options": ["Cotton", "Polyester", "Nylon", "Wool", "Blend"],
        },
        "machinery": {
            "standards": ["ISO 2768", "DIN 7168"],
            "tolerance": {"standard": "±0.05mm", "precision": "±0.01mm"},
            "material_options": ["Aluminum 6061", "Steel 45#", "Stainless 304", "Brass", "Titanium"],
        },
        "packaging": {
            "standards": ["FEFCO", "ISTA"],
            "tolerance": {"standard": "±2mm", "precision": "±1mm"},
            "material_options": ["Kraft", "White Kraft", "Corrugated", "Duplex Board"],
        },
    }

    info = spec_knowledge.get(category, {})
    return {
        "category": category,
        "specification": specification,
        "industry_standards": info.get("standards", []),
        "tolerance_advice": info.get("tolerance", {}),
        "material_options": info.get("material_options", []),
        "additional_options": {k: v for k, v in info.items() if k not in ["standards", "tolerance", "material_options"]},
        "advice": f"建议使用 {info.get('standards', ['GB'])[0]} 标准，公差取 {info.get('tolerance', {}).get('standard', '标准级')}",
        "source": "hardcoded_fallback",
    }


@app.get("/download_cert")
def download_cert(supplier_id: str, cert_type: str):
    """
    下载供应商认证
    """
    with get_db() as conn:
        row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Supplier not found")

    supplier = _row_to_supplier(row)

    cert = next((c for c in supplier.get("certifications", []) if (c["type"] if isinstance(c, dict) else c).upper() == cert_type.upper()), None)
    if not cert:
        return {
            "available": False,
            "supplier_id": supplier_id,
            "requested_cert": cert_type,
            "message": f"Certification {cert_type} not found for {supplier['name_zh']}",
            "available_certs": [c["type"] if isinstance(c, dict) else c for c in supplier.get("certifications", [])],
        }

    # 兼容 certifications 为字符串列表的情况
    if isinstance(cert, str):
        return {
            "available": True,
            "supplier_id": supplier_id,
            "supplier_name": supplier.get("name_en") or supplier["name_zh"],
            "cert_type": cert,
            "valid_until": "unknown",
            "is_valid": True,
            "download_url": None,
            "note": "Certification type recorded but no document file available. Contact supplier directly for certificate copy.",
        }

    # dict 形式的认证（含 type/valid_until/file）
    cert_type = cert.get("type", "unknown")
    valid_until = cert.get("valid_until", "unknown")

    # 解析有效期（容错处理）
    is_valid = True
    if valid_until and valid_until != "unknown":
        try:
            is_valid = datetime.strptime(valid_until, "%Y-%m-%d") > datetime.now()
        except (ValueError, TypeError):
            is_valid = True  # 日期解析失败，默认有效

    # v5.2: 校验文件是否真实存在，避免返回虚假 URL 导致 404
    cert_file = cert.get("file", "")
    download_url = None
    file_note = "No document file attached. Contact supplier directly for certificate copy."

    if cert_file:
        # 构造文件绝对路径（cert_file 通常是 /uploads/xxx.pdf 形式）
        upload_dir = Path(__file__).parent.parent / "data" / "uploads"
        file_path = upload_dir / cert_file.lstrip("/").replace("uploads/", "")
        if file_path.exists() and file_path.is_file():
            # 文件存在，返回真实下载 URL（修复：默认 URL 包含端口）
            base_url = os.getenv("LINKMONEY_BASE_URL", "http://118.196.34.217:8765").rstrip("/")
            download_url = f"{base_url}/uploads/{cert_file.lstrip('/').replace('uploads/', '')}"
            file_note = "Document file available for download."
        else:
            file_note = f"Document file path recorded ({cert_file}) but file not found on server. Contact supplier directly."

    return {
        "available": True,
        "supplier_id": supplier_id,
        "supplier_name": supplier.get("name_en") or supplier["name_zh"],
        "cert_type": cert_type,
        "valid_until": valid_until,
        "is_valid": is_valid,
        "download_url": download_url,
        "note": file_note,
    }


@app.post("/multi_lang_inquiry")
async def multi_lang_inquiry(req: InquiryRequest):
    """
    多语言询盘生成（v3.0 — DeepSeek V4 Flash 双向单次设计）

    设计原则：
    - 实际采购场景只需要 2 次翻译（buyer→zh 给工厂，工厂→buyer lang 给买家）
    - 不再过度翻译成 8 国语言
    - 旧版 8 国语言参数 target_languages 仍兼容（自动逐个翻译）
    - async + asyncio.gather 并发执行 key_terms + translate（从串行 10-20s 降到并行 5-10s）

    输入:
        inquiry_text: 任意语言原文（新版）/ inquiry_zh: 中文（旧版）
        buyer_lang: 买家语言 (en/zh/ja/de/es/fr/ar/pt/ru)，默认 en
        target_lang: 目标语言（新版双向单次），默认 zh
        target_languages: 旧版 8 国语言列表

    输出:
        translations: {lang: {language, inquiry}} 字典
        llm_provider: 火山引擎豆包 (Ark API)
        key_terms: 提取的关键术语（避免翻译时丢失）
    """
    import asyncio as _asyncio

    llm = get_llm()
    llm_available = llm.is_available()

    # 兼容旧版 + 新版输入
    src_text = req.inquiry_text or req.inquiry_zh
    if not src_text:
        raise HTTPException(status_code=400, detail="inquiry_text or inquiry_zh required")

    # 决定要翻译成哪些目标语言
    if req.target_languages:
        # 旧版：多语言并发
        target_languages = req.target_languages
        mode = "multi_lang_legacy"
    else:
        # 新版：双向单次
        target_languages = [req.target_lang]
        mode = "bilingual_single"

    lang_names = llm.SUPPORTED_LANGS

    # 决定源语言
    if mode == "bilingual_single":
        src_lang = req.buyer_lang
    else:
        # 旧版：源语言固定是中文
        src_lang = "zh"

    # bilingual_single + LLM 可用：并发执行 key_terms + translate
    if mode == "bilingual_single" and llm_available:
        async def _do_key_terms():
            try:
                return await _asyncio.to_thread(llm.extract_key_terms, src_text, src_lang)
            except DeepSeekError as e:
                logger.warning(f"extract_key_terms failed: {e}")
                return []

        async def _do_translate(lang: str):
            if lang not in lang_names:
                return lang, {"language": lang, "inquiry": src_text,
                              "_note": f"unsupported language '{lang}', returned original"}
            if lang == src_lang:
                return lang, {"language": lang_names[lang], "inquiry": src_text}
            try:
                translated = await _asyncio.to_thread(llm.translate, src_text, src_lang, lang)
            except DeepSeekError as e:
                logger.warning(f"Ark translate failed ({src_lang}→{lang}): {e}")
                translated = None
            if translated is None:
                translated = f"[{lang_names[lang]} | 翻译未配置] {src_text}"
            return lang, {"language": lang_names[lang], "inquiry": translated}

        # 并发：key_terms + 所有翻译同时跑（总耗时 = max 而非 sum）
        tasks = [_do_key_terms()] + [_do_translate(lang) for lang in target_languages]
        results = await _asyncio.gather(*tasks)
        key_terms = results[0]
        translations = {lang: trans for lang, trans in results[1:]}
    else:
        # fallback 模式或旧版多语言：无 LLM 调用，串行很快
        key_terms = []
        translations = {}
        for lang in target_languages:
            if lang not in lang_names:
                translations[lang] = {
                    "language": lang,
                    "inquiry": src_text,
                    "_note": f"unsupported language '{lang}', returned original",
                }
                continue

            if lang == src_lang:
                translations[lang] = {"language": lang_names[lang], "inquiry": src_text}
                continue

            translated = None
            if llm_available:
                try:
                    translated = llm.translate(src_text, src_lang, lang)
                except DeepSeekError as e:
                    logger.warning(f"Ark translate failed ({src_lang}→{lang}): {e}")

            if translated is None:
                translated = f"[{lang_names[lang]} | 翻译未配置] {src_text}"

            translations[lang] = {
                "language": lang_names[lang],
                "inquiry": translated,
            }

    return {
        "mode": mode,
        "source_language": src_lang,
        "source_text": src_text,
        "translations": translations,
        "key_terms": key_terms,
        "total_languages": len(translations),
        "llm_provider": "火山引擎豆包 (Ark API)" if llm_available else "fallback (no API key)",
        "llm_available": llm_available,
        "note": "双向单次翻译：buyer→zh 给工厂主，factory→buyer lang 给买家。Data 不出境。" if mode == "bilingual_single" else "8 国语言并发（兼容旧 API）",
    }


class SubmitRFQRequest(BaseModel):
    supplier_id: str
    buyer_id: str = "buyer-demo"
    sku: str = ""
    quantity: int = 0
    target_price_usd: float = 0
    port: str = "Ningbo"
    incoterms: str = "FOB"
    delivery_deadline: str = ""
    contact_email: str = ""
    raw_message: str = ""
    product_sku: str = ""  # 别名，兼容 Agent 传入
    delivery_port: str = ""  # 别名，兼容 Agent 传入
    notes: str = ""


@app.post("/submit_rfq")
@limiter.limit("10/minute")
def submit_rfq(
    request: Request,
    supplier_id: str = "",
    buyer_id: str = "buyer-demo",
    sku: str = "",
    quantity: int = 0,
    target_price_usd: float = 0,
    port: str = "Ningbo",
    incoterms: str = "FOB",
    delivery_deadline: str = "",
    contact_email: str = "",
    raw_message: str = "",         # v3.0+ — 买家原始自然语言需求（可选，触发 LLM parse_rfq）
    body: SubmitRFQRequest = None,  # JSON body 支持
    confirm_data_sharing: bool = False,  # v5.1.1 — 二次确认数据共享
    anonymize_contact: bool = False,     # v5.1.1 — 匿名化联系方式
):
    """
    提交 RFQ（v5.1.1 — 火山引擎豆包智能解析 + 二次确认 + 匿名化）

    支持两种调用方式：
    1. Query params: POST /submit_rfq?supplier_id=xxx&sku=xxx&quantity=50000&confirm_data_sharing=true
    2. JSON body: POST /submit_rfq  {"supplier_id": "xxx", "product_sku": "xxx", "quantity": 50000, "delivery_port": "Ningbo"}

    安全要求（v5.1.1）：
    - confirm_data_sharing=true 必传，否则返回 400 错误
    - anonymize_contact=true 时，供应商邮件中买家联系方式替换为 LinkMoney 中转邮箱

    - raw_message 可选：买家原始自然语言 RFQ（"我要 50K M8 螺栓，要快，FOB 洛杉矶..."）
    - 如果传了 raw_message，LLM 自动 parse 提取 category/spec/urgency 等
    - 解析结果存入 rfqs 表，方便后续做 RFQ 智能路由
    """
    # v5.1.1 安全检查：二次确认数据共享
    if not confirm_data_sharing:
        raise HTTPException(
            status_code=400,
            detail="数据共享未确认：提交 RFQ 会将询价信息发送给指定供应商，请传入 confirm_data_sharing=true 确认您知晓此数据流向"
        )

    # 如果有 JSON body，优先使用 body 中的值（兼容 query params）
    if body is not None:
        supplier_id = body.supplier_id or supplier_id
        buyer_id = body.buyer_id if body.buyer_id != "buyer-demo" else buyer_id
        sku = body.sku or body.product_sku or sku
        quantity = body.quantity or quantity
        target_price_usd = body.target_price_usd or target_price_usd
        port = body.port or body.delivery_port or port
        incoterms = body.incoterms or incoterms
        delivery_deadline = body.delivery_deadline or delivery_deadline
        contact_email = body.contact_email or contact_email
        raw_message = body.raw_message or body.notes or raw_message

    if not supplier_id:
        raise HTTPException(status_code=400, detail="supplier_id is required")
    if not sku:
        raise HTTPException(status_code=400, detail="sku (or product_sku) is required")
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")
    with get_db() as conn:
        s_row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        b_row = conn.execute("SELECT * FROM overseas_buyers WHERE id = ?", (buyer_id,)).fetchone()

    if not s_row:
        raise HTTPException(status_code=404, detail="Supplier not found")

    supplier = _row_to_supplier(s_row)

    if not b_row:
        raise HTTPException(status_code=404, detail=f"Buyer '{buyer_id}' not found")

    buyer = _row_to_buyer(b_row)

    # ===== Trust & Safety 审核买家询单 =====
    try:
        from trust_safety import audit_buyer_inquiry
        audit = audit_buyer_inquiry(
            email=contact_email or buyer.get("email", ""),
            raw_message=raw_message,
            quantity=quantity,
            target_price_usd=target_price_usd,
            category=supplier.get("category", ""),
            llm_provider=get_llm() if get_llm().is_available() else None,
        )
        if audit.blocked:
            logger.warning(f"[T&S BLOCK] submit_rfq blocked: {audit.reasons}")
            try:
                from middle_agent import report_ts_alert
                report_ts_alert("critical", "buyer_inquiry", audit.reasons, audit.details)
            except Exception:
                pass
            raise HTTPException(status_code=400, detail={
                "error": "RFQ blocked by Trust & Safety audit",
                "reasons": audit.reasons,
                "audit": audit.to_dict(),
            })
        if audit.level == "review":
            logger.info(f"[T&S REVIEW] submit_rfq flagged: {audit.reasons}")
            try:
                from middle_agent import report_ts_alert
                report_ts_alert("warn", "buyer_inquiry", audit.reasons, audit.details)
            except Exception:
                pass
        # 审核结果存入 parsed_data，供后续追溯
        _ts_audit = audit.to_dict()
    except ImportError:
        _ts_audit = None
        logger.warning("trust_safety module not available, skipping audit")
    except HTTPException:
        raise
    except Exception as e:
        _ts_audit = None
        logger.warning(f"Trust & Safety audit failed: {e}")

    with get_db() as conn:
        # 用 UUID4 保证全局唯一，彻底消除多 worker 微秒级碰撞
        import uuid as _uuid
        rfq_id = f"rfq-{datetime.now().strftime('%Y%m%d')}-{_uuid.uuid4().hex[:12]}"
        created_at = datetime.now().isoformat() + "Z"

        # v3.0+ — DeepSeek V4 Flash 智能解析 raw_message（买家自然语言 RFQ）
        parsed_rfq = None
        if raw_message and raw_message.strip():
            try:
                llm = get_llm()
                if llm.is_available():
                    parsed_rfq = llm.parse_rfq(raw_message, lang="auto")
                    logger.info(f"RFQ {rfq_id} parsed: {parsed_rfq.get('category')}/{parsed_rfq.get('urgency')}")
            except DeepSeekError as e:
                logger.warning(f"Ark parse_rfq failed for {rfq_id}: {e}")
                parsed_rfq = None

        # 用 LLM 解析结果覆盖默认（如有）
        if parsed_rfq:
            # 提取后用解析结果更新 port / delivery_deadline（如果买家没传）
            if not port or port == "Ningbo":
                if parsed_rfq.get("destination_port"):
                    port = parsed_rfq["destination_port"]
            if not delivery_deadline and parsed_rfq.get("deadline"):
                delivery_deadline = parsed_rfq["deadline"]
            # quantity 也用解析的
            if not quantity and parsed_rfq.get("quantity"):
                quantity = int(parsed_rfq["quantity"])
            # target_price_usd
            if (not target_price_usd or target_price_usd == 0) and parsed_rfq.get("target_price_usd"):
                target_price_usd = float(parsed_rfq["target_price_usd"])

        # rfq_message 字段存原始 raw_message + 解析结果 + T&S 审核结果
        rfq_message_json = json.dumps({
            "raw": raw_message,
            "parsed": parsed_rfq,
            "ts_audit": _ts_audit,
        }, ensure_ascii=False) if raw_message else None

        conn.execute("""
            INSERT INTO rfqs(id, supplier_id, buyer_id, sku, quantity, target_price_usd,
                             port, incoterms, delivery_deadline, contact_email, status, created_at,
                             message, parsed_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rfq_id, supplier_id, buyer_id, sku, quantity, target_price_usd,
            port, incoterms, delivery_deadline, contact_email, "pending", created_at,
            raw_message, rfq_message_json,
        ))
        conn.commit()

    # 异步发送邮件通知供应商
    try:
        # 如果 raw_message 是英文，翻译成中文给工厂看
        raw_message_zh = ""
        if raw_message and raw_message.strip():
            try:
                llm = get_llm()
                if llm.is_available():
                    raw_message_zh = llm.translate(raw_message, "en", "zh") or ""
            except DeepSeekError as e:
                logger.warning(f"Ark translate raw_message for supplier email failed: {e}")

        # v5.1.1 — 匿名化联系方式：供应商邮件中买家联系方式替换为 LinkMoney 中转邮箱
        supplier_visible_email = contact_email
        anonymized_note = ""
        if anonymize_contact and contact_email:
            supplier_visible_email = "relay@linkmoney.online"
            anonymized_note = "（买家已启用联系方式匿名化，请通过 relay@linkmoney.online 中转回复）"
            logger.info(f"RFQ {rfq_id}: anonymize_contact=true, supplier email relay enabled")

        mailer.notify_supplier_new_rfq(
            supplier=supplier,
            buyer=buyer if buyer else {"company": buyer_id, "country": ""},
            rfq={
                "id": rfq_id, "sku": sku, "quantity": quantity,
                "target_price_usd": target_price_usd, "port": port,
                "incoterms": incoterms, "delivery_deadline": delivery_deadline,
                "contact_email": supplier_visible_email,
                "raw_message": raw_message,
                "raw_message_zh": raw_message_zh,
                "anonymized_note": anonymized_note,
            },
            product_name=sku,
        )
    except Exception:
        pass  # 邮件发送失败不影响RFQ提交

    # 异步发送邮件通知海外买家（含匹配到的工厂列表 + 5 工作日回复预期）
    try:
        # 查同品类其他匹配工厂（给买家邮件展示用，最多 5 家）
        with get_db() as conn:
            other_rows = conn.execute(
                "SELECT * FROM suppliers WHERE category = ? AND id != ? LIMIT 4",
                (supplier.get("category", ""), supplier_id),
            ).fetchall()

        matches_for_buyer = [{
            "supplier_id": supplier["id"],
            "name_zh": supplier["name_zh"],
            "name_en": supplier.get("name_en", ""),
            "location": supplier.get("location", {}),
            "certifications": [c["type"] if isinstance(c, dict) else c for c in supplier.get("certifications", [])],
            "match_score": 100,  # 被选中的工厂
            "moq": supplier.get("moq", 0),
            "has_skill": supplier.get("agent_skill_installed", False),
            "mcp_endpoint": supplier.get("skill_mcp_endpoint", "") if supplier.get("agent_skill_installed") else "",
        }]
        for r in other_rows:
            s = _row_to_supplier(r)
            matches_for_buyer.append({
                "supplier_id": s["id"],
                "name_zh": s["name_zh"],
                "name_en": s.get("name_en", ""),
                "location": s.get("location", {}),
                "certifications": [c["type"] if isinstance(c, dict) else c for c in s.get("certifications", [])],
                "match_score": 80,  # 同品类备选
                "moq": s.get("moq", 0),
                "has_skill": s.get("agent_skill_installed", False),
                "mcp_endpoint": s.get("skill_mcp_endpoint", "") if s.get("agent_skill_installed") else "",
            })

        mailer.notify_buyer_rfq_received(
            buyer=buyer if buyer else {"company": buyer_id, "email": contact_email},
            supplier=supplier,
            rfq={
                "id": rfq_id, "sku": sku, "quantity": quantity,
                "target_price_usd": target_price_usd, "port": port,
                "incoterms": incoterms, "contact_email": contact_email,
            },
            matches=matches_for_buyer,
        )
    except Exception as e:
        logger.warning(f"notify_buyer_rfq_received failed for {rfq_id}: {e}")

    return {
        "rfq_id": rfq_id,
        "status": "submitted",
        "supplier_name": supplier["name_zh"],
        "buyer_company": buyer["company"] if buyer else buyer_id,
        "contact_anonymized": anonymize_contact,
        "estimated_response_time": "5 个工作日",
        "next_step": "中国供应商已收到 RFQ 邮件通知，预计 5 个工作日内回复正式报价。海外买家也已收到匹配工厂列表邮件。可调用 get_my_rfqs 查询进度。",
    }


# ===== 统计端点 =====

# ===== v5.1.0 监控看板 =====

DASHBOARD_HTML = None
for _d in WEB_DIR_CANDIDATES:
    _p = _d / "dashboard.html"
    if _p.exists():
        DASHBOARD_HTML = _p
        break
if DASHBOARD_HTML is None and WEB_DIR_CANDIDATES:
    DASHBOARD_HTML = WEB_DIR_CANDIDATES[-1] / "dashboard.html"  # 兜底


@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard():
    """监控看板页面（HTML 公开访问，数据接口需 API Key）"""
    if DASHBOARD_HTML and DASHBOARD_HTML.exists():
        return FileResponse(DASHBOARD_HTML)
    return HTMLResponse("<h1>dashboard.html not found</h1>", status_code=404)


@app.get("/admin/overview")
def admin_overview():
    """看板聚合数据：系统状态 + 业务数据 + API 统计 + 邮件统计 + LLM 状态"""
    import os as _os
    from datetime import datetime, timedelta

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    with get_db() as conn:
        # === 业务数据 ===
        total_suppliers = conn.execute("SELECT COUNT(*) as cnt FROM suppliers").fetchone()["cnt"]
        suppliers_with_skill = conn.execute(
            "SELECT COUNT(*) as cnt FROM suppliers WHERE agent_skill_installed = 1"
        ).fetchone()["cnt"]
        total_buyers = conn.execute("SELECT COUNT(*) as cnt FROM overseas_buyers").fetchone()["cnt"]
        buyers_with_linkmoney = conn.execute(
            "SELECT COUNT(*) as cnt FROM overseas_buyers WHERE agent_installed_linkmoney = 1"
        ).fetchone()["cnt"]
        total_rfqs = conn.execute("SELECT COUNT(*) as cnt FROM rfqs").fetchone()["cnt"]
        today_rfqs = conn.execute(
            "SELECT COUNT(*) as cnt FROM rfqs WHERE created_at >= ?", (today_str,)
        ).fetchone()["cnt"]

        # 供应商分类分布
        category_dist = [
            dict(r) for r in conn.execute("""
                SELECT category, COUNT(*) as count FROM suppliers
                WHERE category IS NOT NULL AND category != ''
                GROUP BY category ORDER BY count DESC LIMIT 10
            """).fetchall()
        ]

        # === API 调用统计 ===
        # 今日调用数
        today_api_calls = conn.execute(
            "SELECT COUNT(*) as cnt FROM api_logs WHERE created_at >= ?", (today_str,)
        ).fetchone()["cnt"]
        # 总调用数
        total_api_calls = conn.execute("SELECT COUNT(*) as cnt FROM api_logs").fetchone()["cnt"]
        # 今日错误数
        today_errors = conn.execute(
            "SELECT COUNT(*) as cnt FROM api_logs WHERE created_at >= ? AND status_code >= 400",
            (today_str,)
        ).fetchone()["cnt"]
        # 独立 IP 数
        unique_ips = conn.execute(
            "SELECT COUNT(DISTINCT ip) as cnt FROM api_logs WHERE created_at >= ?", (today_str,)
        ).fetchone()["cnt"]
        # 平均响应时间
        avg_latency = conn.execute(
            "SELECT AVG(duration_ms) as avg FROM api_logs WHERE created_at >= ?", (today_str,)
        ).fetchone()["avg"] or 0
        # P99 响应时间
        p99_latency = conn.execute(
            "SELECT MAX(duration_ms) as p99 FROM api_logs WHERE created_at >= ?", (today_str,)
        ).fetchone()["p99"] or 0

        # 24 小时趋势（按小时聚合）
        hourly_calls = [
            dict(r) for r in conn.execute("""
                SELECT
                    strftime('%H', created_at) as hour,
                    COUNT(*) as count,
                    SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) as errors
                FROM api_logs
                WHERE created_at >= datetime('now', '-24 hours')
                GROUP BY strftime('%H', created_at)
                ORDER BY hour
            """).fetchall()
        ]

        # Top 10 端点
        top_endpoints = [
            dict(r) for r in conn.execute("""
                SELECT endpoint, COUNT(*) as count, AVG(duration_ms) as avg_ms
                FROM api_logs
                WHERE created_at >= ?
                GROUP BY endpoint
                ORDER BY count DESC LIMIT 10
            """, (today_str,)).fetchall()
        ]

        # === 邮件统计 ===
        try:
            today_mail_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM mail_logs WHERE created_at >= ?", (today_str,)
            ).fetchone()["cnt"]
            today_mail_sent = conn.execute(
                "SELECT COUNT(*) as cnt FROM mail_logs WHERE created_at >= ? AND status = 'sent'",
                (today_str,)
            ).fetchone()["cnt"]
            today_mail_failed = conn.execute(
                "SELECT COUNT(*) as cnt FROM mail_logs WHERE created_at >= ? AND status = 'failed'",
                (today_str,)
            ).fetchone()["cnt"]
        except Exception:
            today_mail_count = today_mail_sent = today_mail_failed = 0

        # === 数据库版本 ===
        db_version_row = conn.execute(
            "SELECT value FROM config WHERE key = 'json_version'"
        ).fetchone()
        db_version = db_version_row["value"] if db_version_row else "unknown"

    # === 系统状态 ===
    import subprocess
    try:
        # 容器启动时间
        uptime_result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", "1"], capture_output=True, text=True, timeout=3
        )
        started_at = uptime_result.stdout.strip() if uptime_result.returncode == 0 else "unknown"
    except Exception:
        started_at = "unknown"

    # Worker 数
    workers = int(_os.getenv("WEB_CONCURRENCY", "2"))

    # === LLM 状态 ===
    from llm_layer import is_llm_enabled, get_llm
    llm_enabled = is_llm_enabled()
    llm_provider_name = "火山引擎豆包 (Ark API)" if llm_enabled else "fallback (disabled)"
    ark_key_configured = bool(_os.getenv("ARK_API_KEY", ""))
    text_model = _os.getenv("ARK_TEXT_MODEL", "doubao-pro-32k")
    vision_model = _os.getenv("ARK_VISION_MODEL", "doubao-vision-pro-32k")

    # === 邮件配置状态 ===
    mail_enabled = _os.getenv("LINKMONEY_MAIL_ENABLED", "false").lower() == "true"
    smtp_user = _os.getenv("LINKMONEY_SMTP_USER", "")
    smtp_configured = bool(smtp_user and _os.getenv("LINKMONEY_SMTP_PASSWORD", ""))
    override_email = _os.getenv("LINKMONEY_RFQ_OVERRIDE_EMAIL", "")

    return {
        "system": {
            "healthy": True,
            "started_at": started_at,
            "workers": workers,
            "db_version": db_version,
        },
        "business": {
            "total_suppliers": total_suppliers,
            "suppliers_with_skill": suppliers_with_skill,
            "total_buyers": total_buyers,
            "buyers_with_linkmoney": buyers_with_linkmoney,
            "total_rfqs": total_rfqs,
            "today_rfqs": today_rfqs,
            "category_dist": category_dist,
        },
        "api": {
            "today_calls": today_api_calls,
            "total_calls": total_api_calls,
            "today_errors": today_errors,
            "unique_ips": unique_ips,
            "avg_latency_ms": avg_latency,
            "p99_latency_ms": p99_latency,
            "hourly_calls": hourly_calls,
            "top_endpoints": top_endpoints,
        },
        "mail": {
            "enabled": mail_enabled,
            "smtp_configured": smtp_configured,
            "today_count": today_mail_count,
            "today_sent": today_mail_sent,
            "today_failed": today_mail_failed,
        },
        "llm": {
            "enabled": llm_enabled,
            "provider": llm_provider_name,
            "api_key_configured": ark_key_configured,
            "text_model": text_model,
            "vision_model": vision_model,
            "mail_enabled": mail_enabled,
            "smtp_configured": smtp_configured,
            "override_email": override_email,
        },
    }


@app.get("/admin/api_logs")
def admin_api_logs(limit: int = 30):
    """最近 API 调用日志"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT endpoint, method, status_code, duration_ms, ip, created_at
            FROM api_logs
            ORDER BY created_at DESC
            LIMIT ?
        """, (min(limit, 100),)).fetchall()

    logs = []
    for r in rows:
        ca = r["created_at"]
        # 提取时间部分
        time_str = ca.split(" ")[1] if " " in ca else ca
        logs.append({
            "endpoint": r["endpoint"],
            "method": r["method"],
            "status_code": r["status_code"],
            "duration_ms": r["duration_ms"],
            "ip": r["ip"],
            "time": time_str,
        })

    return {"logs": logs, "count": len(logs)}


@app.get("/admin/recent_rfqs")
def admin_recent_rfqs(limit: int = 10):
    """最近 RFQ 询盘 + 报价"""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM rfqs").fetchone()["cnt"]

        rfq_rows = conn.execute("""
            SELECT id, sku, quantity, status, created_at, target_price_usd
            FROM rfqs
            ORDER BY created_at DESC
            LIMIT ?
        """, (min(limit, 50),)).fetchall()

        rfqs = []
        for r in rfq_rows:
            ca = r["created_at"]
            time_str = ca.split(" ")[1] if " " in ca else ca
            rfqs.append({
                "id": r["id"],
                "sku": r["sku"],
                "quantity": r["quantity"],
                "status": r["status"],
                "target_price": r["target_price_usd"],
                "time": time_str,
            })

        # 最近报价（从 bids 表）
        quotes = []
        try:
            bid_rows = conn.execute("""
                SELECT b.rfq_id, b.unit_price_usd, b.total_price_usd, b.status, b.created_at,
                       s.name_zh as supplier_name
                FROM bids b
                LEFT JOIN suppliers s ON s.id = b.supplier_id
                ORDER BY b.created_at DESC
                LIMIT ?
            """, (min(limit, 20),)).fetchall()

            for r in bid_rows:
                ca = r["created_at"]
                time_str = ca.split(" ")[1] if " " in ca else ca
                quotes.append({
                    "rfq_id": r["rfq_id"],
                    "supplier_name": r["supplier_name"] or "Unknown",
                    "unit_price": r["unit_price_usd"],
                    "total_price": r["total_price_usd"],
                    "status": r["status"],
                    "time": time_str,
                })
        except Exception:
            pass  # bids 表可能不存在或字段不同

    return {"rfqs": rfqs, "quotes": quotes, "total": total}


@app.get("/admin/mail_logs")
def admin_mail_logs(limit: int = 20):
    """邮件发送日志"""
    with get_db() as conn:
        try:
            total = conn.execute("SELECT COUNT(*) as cnt FROM mail_logs").fetchone()["cnt"]
            rows = conn.execute("""
                SELECT to_email, subject, status, error_msg, mail_type, created_at
                FROM mail_logs
                ORDER BY created_at DESC
                LIMIT ?
            """, (min(limit, 100),)).fetchall()
        except Exception:
            return {"logs": [], "total": 0}

    logs = []
    for r in rows:
        ca = r["created_at"]
        time_str = ca.split(" ")[1] if " " in ca else ca
        logs.append({
            "to_email": r["to_email"],
            "subject": r["subject"],
            "status": r["status"],
            "error_msg": r["error_msg"],
            "mail_type": r["mail_type"],
            "time": time_str,
        })

    return {"logs": logs, "total": total}


@app.get("/stats")
def get_stats():
    """全局统计数据"""
    with get_db() as conn:
        total_suppliers = conn.execute("SELECT COUNT(*) as cnt FROM suppliers").fetchone()["cnt"]
        suppliers_with_skill = conn.execute(
            "SELECT COUNT(*) as cnt FROM suppliers WHERE agent_skill_installed = 1"
        ).fetchone()["cnt"]
        total_buyers = conn.execute("SELECT COUNT(*) as cnt FROM overseas_buyers").fetchone()["cnt"]
        buyers_with_linkmoney = conn.execute(
            "SELECT COUNT(*) as cnt FROM overseas_buyers WHERE agent_installed_linkmoney = 1"
        ).fetchone()["cnt"]
        total_rfqs = conn.execute("SELECT COUNT(*) as cnt FROM rfqs").fetchone()["cnt"]
        analytics = _get_config(conn, "skill_analytics", {})
        beta_signups = conn.execute("SELECT COUNT(*) as cnt FROM beta_signups").fetchone()["cnt"]

    return {
        "total_suppliers": total_suppliers,
        "suppliers_with_skill": suppliers_with_skill,
        "suppliers_without_skill": total_suppliers - suppliers_with_skill,
        "total_buyers": total_buyers,
        "buyers_with_linkmoney": buyers_with_linkmoney,
        "total_skill_installs": analytics.get("total_installs", 0),
        "total_rfqs": total_rfqs,
        "conversion_rate": analytics.get("conversion_rate", 0),
        "platforms": analytics.get("platform_breakdown", {}),
        "cache_stats": {
            "supplier_cache": _supplier_cache.stats(),
            "buyer_cache": _buyer_cache.stats(),
        },
        "beta_signups": beta_signups,
    }


@app.get("/weekly-report")
def weekly_report():
    """
    Day 7 周报数据 — 自动化周报生成
    返回：本周 RFQ 数、报价数、新增供应商、待处理事项
    """
    with get_db() as conn:
        # 本周日期范围
        now = datetime.now()
        week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        week_start_full = week_start + " 00:00:00"

        # 本周 RFQ
        rfqs_this_week = conn.execute(
            "SELECT COUNT(*) as cnt FROM rfqs WHERE created_at >= ?", (week_start_full,)
        ).fetchone()["cnt"]

        # 本周报价（quoted 状态）
        quoted_this_week = conn.execute(
            "SELECT COUNT(*) as cnt FROM rfqs WHERE status = 'quoted' AND updated_at >= ?",
            (week_start_full,)
        ).fetchone()["cnt"]

        # 本周新增内测申请
        beta_this_week = conn.execute(
            "SELECT COUNT(*) as cnt FROM beta_signups WHERE created_at >= ?", (week_start_full,)
        ).fetchone()["cnt"]

        # 总览
        total_rfqs = conn.execute("SELECT COUNT(*) as cnt FROM rfqs").fetchone()["cnt"]
        total_quoted = conn.execute(
            "SELECT COUNT(*) as cnt FROM rfqs WHERE status = 'quoted'"
        ).fetchone()["cnt"]
        total_accepted = conn.execute(
            "SELECT COUNT(*) as cnt FROM rfqs WHERE status IN ('accepted', 'negotiating')"
        ).fetchone()["cnt"]

        # 按状态分组
        rfq_by_status = {}
        for row in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM rfqs GROUP BY status"
        ).fetchall():
            rfq_by_status[row["status"]] = row["cnt"]

        # 最新 5 条 RFQ
        latest_rfqs = []
        for row in conn.execute(
            "SELECT id, supplier_id, buyer_id, sku, quantity, status, created_at "
            "FROM rfqs ORDER BY created_at DESC LIMIT 5"
        ).fetchall():
            latest_rfqs.append({
                "rfq_id": row["id"],
                "supplier_id": row["supplier_id"],
                "sku": row["sku"],
                "quantity": row["quantity"],
                "status": row["status"],
                "created_at": row["created_at"],
            })

        # 内测申请
        beta_total = conn.execute("SELECT COUNT(*) as cnt FROM beta_signups").fetchone()["cnt"]
        beta_pending = conn.execute(
            "SELECT COUNT(*) as cnt FROM beta_signups WHERE status = 'pending'"
        ).fetchone()["cnt"]

    return {
        "report_period": f"{week_start} ~ {now.strftime('%Y-%m-%d')}",
        "generated_at": now.isoformat(),
        "summary": {
            "rfqs_this_week": rfqs_this_week,
            "quotes_this_week": quoted_this_week,
            "beta_signups_this_week": beta_this_week,
            "total_rfqs": total_rfqs,
            "total_quoted": total_quoted,
            "total_accepted": total_accepted,
            "quote_conversion_rate": f"{round(total_quoted / total_rfqs * 100, 1)}%" if total_rfqs > 0 else "N/A",
            "rfq_by_status": rfq_by_status,
            "pending_beta_review": beta_pending,
            "total_beta_signups": beta_total,
        },
        "actions_needed": [
            f"审核 {beta_pending} 个工厂内测申请" if beta_pending > 0 else "无需审核的内测申请",
            f"跟进 {rfqs_this_week - quoted_this_week} 个未报价 RFQ" if rfqs_this_week > quoted_this_week else "本周 RFQ 均已处理",
        ],
        "latest_rfqs": latest_rfqs,
    }


# ===== 新增端点: 采购方查供应商完整联系方式 =====

@app.get("/get_supplier_contact")
def get_supplier_contact(
    request: Request,
    supplier_id: str = Query(..., description="供应商ID"),
):
    """
    海外采购方查看指定供应商的完整联系方式。
    已装 Skill 的供应商返回完整联系人信息；
    未装 Skill 的供应商提示需安装后可见。
    """
    with get_db() as conn:
        row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Supplier '{supplier_id}' not found")

    s = _row_to_supplier(row)
    has_skill = s["agent_skill_installed"]

    return {
        "supplier_id": supplier_id,
        "name_zh": s["name_zh"],
        "name_en": s["name_en"],
        "location": s["location"],
        "category": s["category"],
        "certifications": [c["type"] if isinstance(c, dict) else c for c in s.get("certifications", [])],
        "contact_available": has_skill,
        "contact": {
            "person": s.get("contact_person", ""),
            "email": s.get("email", ""),
            "phone": s.get("phone", ""),
            "wechat": s.get("wechat", ""),
            "languages": s.get("languages", ["zh", "en"]),
        } if has_skill else {
            "person": "",
            "email": "",
            "phone": "",
            "wechat": "",
            "languages": [],
        },
        "hint": "可以直接联系该供应商" if has_skill else "该供应商尚未安装 LinkMoney Skill，联系方式暂不可见。请提示供应商安装 LinkMoney Skill 以公开联系方式。",
        "next_step": "submit_rfq" if has_skill else "invite_supplier_to_install_linkmoney",
    }


# ===== 新增端点: 厂商查询自己收到的 RFQ =====

@app.get("/get_rfq_status")
def get_rfq_status(
    request: Request,
    rfq_id: str = Query(..., description="RFQ ID"),
):
    """海外买家/Agent 通过 RFQ ID 查询询盘状态（无需 supplier_id）"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM rfqs WHERE id = ?", (rfq_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"RFQ '{rfq_id}' not found")
    rfq = dict(row)
    # 查供应商名
    with get_db() as conn:
        s = conn.execute("SELECT name_zh, name_en FROM suppliers WHERE id = ?", (rfq["supplier_id"],)).fetchone()
    supplier_name = s["name_zh"] if s else rfq["supplier_id"]
    supplier_name_en = s["name_en"] if s else ""
    return {
        "rfq_id": rfq["id"],
        "status": rfq["status"],
        "supplier_id": rfq["supplier_id"],
        "supplier_name": supplier_name,
        "supplier_name_en": supplier_name_en,
        "sku": rfq["sku"],
        "quantity": rfq["quantity"],
        "target_price_usd": rfq["target_price_usd"],
        "port": rfq["port"],
        "incoterms": rfq["incoterms"],
        "created_at": rfq["created_at"],
        "quoted_at": rfq.get("quoted_at", ""),
        "unit_price_usd": rfq.get("unit_price_usd", 0),
        "lead_time_days": rfq.get("lead_time_days", 0),
        "notes": rfq.get("notes", ""),
    }


@app.get("/get_my_rfqs")
def get_my_rfqs(
    request: Request,
    supplier_id: str = Query(..., description="供应商ID"),
    access_token: str = Query("", description="v5.2.4: 工厂身份凭证"),
    status: str = Query("", description="筛选状态: pending/quoted/negotiating/closed"),
):
    """
    中国供应商查询自己收到的 RFQ 询盘列表。
    状态可选: pending(待处理) / quoted(已报价) / negotiating(洽谈中) / closed(已关闭)
    v5.2.4: 需携带 access_token 校验身份
    """
    with get_db() as conn:
        # v5.2.4: 统一身份校验
        s_row = _verify_supplier_access(conn, supplier_id, access_token)

    supplier = _row_to_supplier(s_row)

    with get_db() as conn:
        if status:
            rfq_rows = conn.execute(
                "SELECT * FROM rfqs WHERE supplier_id = ? AND status = ? ORDER BY created_at DESC",
                (supplier_id, status),
            ).fetchall()
        else:
            rfq_rows = conn.execute(
                "SELECT * FROM rfqs WHERE supplier_id = ? ORDER BY created_at DESC",
                (supplier_id,),
            ).fetchall()

    if not rfq_rows:
        return {
            "supplier_id": supplier_id,
            "supplier_name": supplier["name_zh"],
            "total_rfqs": 0,
            "rfqs": [],
            "message": "暂无询盘。安装 LinkMoney Skill 并分发到更多平台可增加曝光。",
        }

    rfqs = []
    for r_row in rfq_rows:
        r = dict(r_row)
        # 获取采购方信息
        with get_db() as conn:
            b_row = conn.execute(
                "SELECT company, country, email, contact_person FROM overseas_buyers WHERE id = ?",
                (r["buyer_id"],),
            ).fetchone()

        buyer_info = {
            "company": b_row["company"] if b_row else r["buyer_id"],
            "country": b_row["country"] if b_row else "",
            "contact_email": b_row["email"] if b_row else "",
            "contact_person": b_row["contact_person"] if b_row else "",
        } if b_row else {"company": r["buyer_id"], "country": "", "contact_email": "", "contact_person": ""}

        # 获取 SKU 详情
        with get_db() as conn:
            p_row = conn.execute(
                "SELECT name_zh, name_en FROM products WHERE supplier_id = ? AND sku = ?",
                (supplier_id, r["sku"]),
            ).fetchone()

        product_name = p_row["name_zh"] if p_row else r["sku"]

        rfqs.append({
            "rfq_id": r["id"],
            "buyer": buyer_info,
            "sku": r["sku"],
            "product_name": product_name,
            "quantity": r["quantity"],
            "target_price_usd": r["target_price_usd"],
            "port": r["port"],
            "incoterms": r["incoterms"],
            "delivery_deadline": r["delivery_deadline"],
            "status": r["status"],
            "status_label": {
                "pending": "待处理",
                "quoted": "已报价",
                "negotiating": "洽谈中",
                "closed": "已关闭",
                "accepted": "已成交",
            }.get(r["status"], r["status"]),
            "created_at": r["created_at"],
        })

    # 按状态统计
    status_counts = {}
    for rfq in rfqs:
        s_ = rfq["status"]
        status_counts[s_] = status_counts.get(s_, 0) + 1

    return {
        "supplier_id": supplier_id,
        "supplier_name": supplier["name_zh"],
        "total_rfqs": len(rfqs),
        "status_summary": status_counts,
        "rfqs": rfqs,
        "action_required": "pending" in status_counts,
        "pending_count": status_counts.get("pending", 0),
        "latest_rfq": rfqs[0] if rfqs else None,
    }


# ===== 新增端点: 供应商报价并通知采购方 =====

class QuoteRequest(BaseModel):
    rfq_id: str
    supplier_id: str
    access_token: str = ""  # v5.2.4: 工厂身份凭证
    unit_price_usd: float
    lead_time_days: int
    total_price_usd: float = 0
    notes: str = ""


@app.post("/send_quote")
@limiter.limit("10/minute")
def send_quote(req: QuoteRequest, request: Request):
    """
    中国供应商对 RFQ 进行报价，并自动邮件通知海外采购方。
    报价后 RFQ 状态从 pending → quoted。
    v5.2.4: 需携带 access_token 校验身份
    """
    # v5.2.4: 统一身份校验
    with get_db() as conn:
        _verify_supplier_access(conn, req.supplier_id, req.access_token)

    with get_db() as conn:
        rfq_row = conn.execute("SELECT * FROM rfqs WHERE id = ?", (req.rfq_id,)).fetchone()
    if not rfq_row:
        raise HTTPException(status_code=404, detail=f"RFQ '{req.rfq_id}' not found")

    rfq = dict(rfq_row)

    # 校验供应商归属
    if rfq["supplier_id"] != req.supplier_id:
        raise HTTPException(status_code=403, detail="This RFQ does not belong to your supplier ID")

    # 校验状态
    if rfq["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"RFQ is already {rfq['status']}, cannot quote again")

    # ===== Trust & Safety 审核工厂报价 =====
    try:
        from trust_safety import audit_supplier_quote
        # 获取供应商 category + trust_score + moq
        with get_db() as conn:
            s = conn.execute("SELECT category, moq, trust_score FROM suppliers WHERE id = ?",
                             (req.supplier_id,)).fetchone()
        supplier_cat = s["category"] if s else ""
        supplier_moq = s["moq"] if s else 0
        supplier_trust = s["trust_score"] if s and s["trust_score"] else 100

        quote_audit = audit_supplier_quote(
            unit_price_usd=req.unit_price_usd,
            target_price_usd=rfq["target_price_usd"] or 0,
            quantity=rfq["quantity"],
            lead_time_days=req.lead_time_days,
            moq=supplier_moq,
            category=supplier_cat,
            supplier_trust_score=supplier_trust,
        )
        if quote_audit.blocked:
            logger.warning(f"[T&S BLOCK] send_quote blocked: {quote_audit.reasons}")
            try:
                from middle_agent import report_ts_alert
                report_ts_alert("critical", "supplier_quote", quote_audit.reasons, quote_audit.details)
            except Exception:
                pass
            raise HTTPException(status_code=400, detail={
                "error": "Quote blocked by Trust & Safety audit",
                "reasons": quote_audit.reasons,
                "audit": quote_audit.to_dict(),
            })
        if quote_audit.level == "review":
            logger.info(f"[T&S REVIEW] send_quote flagged: {quote_audit.reasons}")
            try:
                from middle_agent import report_ts_alert
                report_ts_alert("warn", "supplier_quote", quote_audit.reasons, quote_audit.details)
            except Exception:
                pass
        _quote_ts_audit = quote_audit.to_dict()
    except ImportError:
        _quote_ts_audit = None
    except HTTPException:
        raise
    except Exception as e:
        _quote_ts_audit = None
        logger.warning(f"Quote T&S audit failed: {e}")

    total = req.total_price_usd if req.total_price_usd > 0 else round(req.unit_price_usd * rfq["quantity"], 2)

    # 更新 RFQ 状态
    with get_db() as conn:
        conn.execute(
            "UPDATE rfqs SET status = 'quoted', quoted_price_usd = ?, lead_time_days = ?, total_price_usd = ?, notes = ?, updated_at = ? WHERE id = ?",
            (req.unit_price_usd, req.lead_time_days, total, req.notes, datetime.now().isoformat() + "Z", req.rfq_id),
        )
        # v5.2: 报价响应后重算 trust_score（活跃行为，未来可加权）
        _recalculate_trust_score(conn, req.supplier_id)
        conn.commit()

    # 获取供应商和采购方信息用于邮件
    with get_db() as conn:
        supplier_row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (req.supplier_id,)).fetchone()
        buyer_row = conn.execute("SELECT id, company, country, email, contact_person FROM overseas_buyers WHERE id = ?",
                                 (rfq["buyer_id"],)).fetchone()

    supplier = _row_to_supplier(supplier_row) if supplier_row else {}
    buyer = dict(buyer_row) if buyer_row else {"company": rfq["buyer_id"], "country": "", "email": rfq.get("contact_email", "")}

    # v5.2: 用 LLM 草拟专业报价邮件（失败降级回写死模板）
    drafted = None
    try:
        llm = get_llm()
        if llm.is_available():
            # 字段映射：_row_to_supplier 返回 name_zh/name_en，draft_quote_email 读 name
            supplier_for_llm = {
                **supplier,
                "name": supplier.get("name_en") or supplier.get("name_zh", ""),
                "city": supplier.get("city", ""),
            }
            drafted = llm.draft_quote_email(
                rfq=rfq,
                supplier=supplier_for_llm,
                quote_price_usd=req.unit_price_usd,
                lead_time_days=req.lead_time_days,
                buyer_lang=buyer.get("language", "en") if isinstance(buyer, dict) else "en",
            )
            logger.info(f"draft_quote_email success: subject={drafted.get('subject','?')[:50]}")
    except Exception as e:
        logger.warning(f"draft_quote_email failed, fallback to template: {e}")
        drafted = None

    # 异步发送邮件通知采购方
    try:
        mailer.notify_buyer_quote_received(
            buyer=buyer,
            supplier=supplier,
            rfq=rfq,
            quote={
                "unit_price_usd": req.unit_price_usd,
                "total_price_usd": total,
                "lead_time_days": req.lead_time_days,
                "status": "quoted",
            },
            drafted=drafted,  # v5.2: 传入 LLM 草稿（None 时用模板）
        )
    except Exception:
        pass

    # 报价后失效 find_china_supplier 缓存（价格信息变了）
    _supplier_cache.invalidate("find:")

    return {
        "rfq_id": req.rfq_id,
        "supplier_id": req.supplier_id,
        "supplier_name": supplier.get("name_zh", ""),
        "buyer_company": buyer.get("company", ""),
        "status": "quoted",
        "status_label": "已报价",
        "unit_price_usd": req.unit_price_usd,
        "total_price_usd": total,
        "lead_time_days": req.lead_time_days,
        "next_step": f"报价已通过邮件发送给 {buyer.get('company', '')}（{buyer.get('email', '')}）。采购方可在 24 小时内回复。",
    }


# ===== 新手引导页（上线推广用） =====

@app.get("/onboard-supplier", response_class=HTMLResponse)
def onboard_supplier():
    """中方厂家新手引导页 — 微信可直接转发"""
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LinkMoney — 中国工厂 AI 获客指南</title>
    <style>
      *{margin:0;padding:0;box-sizing:border-box}
      body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:linear-gradient(180deg,#0A0E27 0%,#1a1f4a 100%);color:#fff;min-height:100vh}
      .hero{text-align:center;padding:60px 20px 40px}
      .hero h1{font-size:32px;font-weight:800;margin-bottom:12px;line-height:1.3}
      .hero h1 span{background:linear-gradient(135deg,#FF6B35,#FFB347);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
      .hero p{font-size:16px;color:#a0a4b8;max-width:500px;margin:0 auto 24px;line-height:1.6}
      .hero .badge{display:inline-block;background:rgba(255,107,53,0.15);color:#FF6B35;padding:6px 16px;border-radius:20px;font-size:14px;margin-bottom:16px}
      .container{max-width:720px;margin:0 auto;padding:0 20px 60px}
      .card{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:28px;margin-bottom:16px}
      .card h3{font-size:18px;margin-bottom:12px;display:flex;align-items:center;gap:8px}
      .card .emoji{font-size:24px}
      .card p,.card li{font-size:15px;color:#c4c7d4;line-height:1.7}
      .card ul{padding-left:20px;margin-top:8px}
      .card li{margin-bottom:6px}
      code{background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:6px;font-size:13px;color:#FFB347}
      pre{background:rgba(0,0,0,0.4);padding:16px;border-radius:10px;overflow-x:auto;font-size:13px;line-height:1.6;margin-top:8px}
      .step{display:flex;align-items:flex-start;gap:14px;margin-bottom:20px}
      .step-num{background:#FF6B35;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px;flex-shrink:0}
      .step-text h4{font-size:16px;margin-bottom:4px}
      .step-text p{font-size:14px;color:#a0a4b8}
      .cta{text-align:center;margin-top:32px}
      .cta a{display:inline-block;background:linear-gradient(135deg,#FF6B35,#FFB347);color:#fff;padding:14px 40px;border-radius:50px;text-decoration:none;font-size:18px;font-weight:700;transition:transform .2s}
      .cta a:hover{transform:scale(1.05)}
      .cta .sub{font-size:13px;color:#a0a4b8;margin-top:10px}
      .footer{text-align:center;padding:20px;color:#666;font-size:13px}
    </style>
    </head>
    <body>

    <div class="hero">
      <div class="badge">Agent 时代的支付宝</div>
      <h1>你的工厂，<br>让 <span>AI Agent</span> 帮你接单</h1>
      <p>海外采购方的 AI Agent 正在搜索中国供应商。<br>你的工厂装上 LinkMoney Skill，就有机会被找到。</p>
    </div>

    <div class="container">
      <div class="card">
        <h3><span class="emoji">🤔</span> 这是什么？</h3>
        <p>LinkMoney（连钱）是一个 <strong>AI Agent 之间的 B2B 贸易桥梁</strong>。</p>
        <ul>
          <li>海外采购方用 AI Agent（Claude/GPT）搜"我需要 M10 304 螺栓 50000 个"</li>
          <li>AI Agent 自动找到你的工厂 → 查价格 → 查库存 → 发询盘</li>
          <li>你收到邮件通知 → 一键报价 → 成交</li>
        </ul>
        <p style="margin-top:12px;color:#FFB347;font-weight:600;">不用烧 P4P，不用熬夜回邮件，AI Agent 24 小时帮你获客。</p>
      </div>

      <div class="card">
        <h3><span class="emoji">⚡</span> 3 步接入（5 分钟）</h3>

        <div class="step">
          <div class="step-num">1</div>
          <div class="step-text">
            <h4>下载模板</h4>
            <p>克隆或下载 <code>supplier_mcp_template/</code> 文件夹到你电脑</p>
          </div>
        </div>

        <div class="step">
          <div class="step-num">2</div>
          <div class="step-text">
            <h4>填产品数据</h4>
            <p>编辑 <code>data.json</code> 填入你的产品、价格、库存，或从 Excel 导出 CSV 上传</p>
          </div>
        </div>

        <div class="step">
          <div class="step-num">3</div>
          <div class="step-text">
            <h4>启动服务</h4>
            <pre>pip install -r requirements.txt
python server.py</pre>
            <p style="margin-top:8px;">服务默认跑在 <code>http://localhost:9001</code>，部署到服务器后通知 LinkMoney 即可被 Agent 搜到</p>
          </div>
        </div>
      </div>

      <div class="card">
        <h3><span class="emoji">📦</span> 3 种更新数据方式</h3>
        <table style="width:100%;border-collapse:collapse;margin-top:8px">
          <tr style="background:rgba(255,255,255,0.05)">
            <td style="padding:12px;font-weight:600">CSV 上传</td>
            <td style="padding:12px;color:#a0a4b8">Excel 导出 → 网页上传 → 秒级生效</td>
            <td style="padding:12px;color:#4CAF50;font-weight:600">零代码</td>
          </tr>
          <tr>
            <td style="padding:12px;font-weight:600">编辑 JSON</td>
            <td style="padding:12px;color:#a0a4b8">改文件 → 30秒自动刷新</td>
            <td style="padding:12px;color:#4CAF50;font-weight:600">零代码</td>
          </tr>
          <tr style="background:rgba(255,255,255,0.05)">
            <td style="padding:12px;font-weight:600">ERP 直连</td>
            <td style="padding:12px;color:#a0a4b8">改一行代码连金蝶/用友</td>
            <td style="padding:12px;color:#FF9800;font-weight:600">需开发</td>
          </tr>
        </table>
      </div>

      <div class="card">
        <h3><span class="emoji">💰</span> 费用？</h3>
        <p><strong style="color:#FFB347;font-size:18px">前 3 个月免费。</strong></p>
        <p style="margin-top:8px">后续按成交金额收取 3% 服务费，<strong>不成交不收费</strong>。</p>
        <p style="color:#a0a4b8;margin-top:4px">比阿里国际站（年费 3-8 万）和展会（单次 5 万+）便宜一个数量级。</p>
      </div>

      <div class="card">
        <h3><span class="emoji">🛡️</span> 谁适合用？</h3>
        <ul>
          <li>✅ 有出口经验、想降低获客成本的工厂</li>
          <li>✅ 产品标准化程度高（紧固件/电子/包装/五金）</li>
          <li>✅ 愿意让 AI Agent 处理初筛询盘</li>
          <li>❌ 产品高度定制、需要大量售前沟通的工厂（暂不适合）</li>
        </ul>
      </div>

      <div class="cta">
        <a href="https://github.com/linkmoney-ai/linkmoney-skill" target="_blank">去 GitHub 下载模板</a>
        <p class="sub">首批 50 家工厂免费入驻，满额即止</p>
      </div>
    </div>

    <div class="footer">LinkMoney · Agent 时代的 B2B 贸易链接器 · linkmoney.online</div>
    </body>
    </html>
    """


@app.get("/onboard-buyer", response_class=HTMLResponse)
def onboard_buyer():
    """海外采购方新手引导页 — 英文"""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LinkMoney — Source from China with AI Agents</title>
    <style>
      *{margin:0;padding:0;box-sizing:border-box}
      body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:linear-gradient(180deg,#0A0E27 0%,#1a1f4a 100%);color:#fff;min-height:100vh}
      .hero{text-align:center;padding:60px 20px 40px}
      .hero h1{font-size:36px;font-weight:800;margin-bottom:12px;line-height:1.3}
      .hero h1 span{background:linear-gradient(135deg,#FF6B35,#FFB347);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
      .hero p{font-size:18px;color:#a0a4b8;max-width:550px;margin:0 auto 24px;line-height:1.6}
      .hero .badge{display:inline-block;background:rgba(255,107,53,0.15);color:#FF6B35;padding:6px 16px;border-radius:20px;font-size:14px;margin-bottom:16px}
      .container{max-width:720px;margin:0 auto;padding:0 20px 60px}
      .card{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:28px;margin-bottom:16px}
      .card h3{font-size:18px;margin-bottom:12px;display:flex;align-items:center;gap:8px}
      .card .emoji{font-size:24px}
      .card p,.card li{font-size:15px;color:#c4c7d4;line-height:1.7}
      .card ul{padding-left:20px;margin-top:8px}
      .card li{margin-bottom:6px}
      code{background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:6px;font-size:13px;color:#FFB347}
      pre{background:rgba(0,0,0,0.4);padding:16px;border-radius:10px;overflow-x:auto;font-size:13px;line-height:1.6;margin-top:8px}
      .step{display:flex;align-items:flex-start;gap:14px;margin-bottom:20px}
      .step-num{background:#FF6B35;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px;flex-shrink:0}
      .step-text h4{font-size:16px;margin-bottom:4px}
      .step-text p{font-size:14px;color:#a0a4b8}
      .cta{text-align:center;margin-top:32px}
      .cta a{display:inline-block;background:linear-gradient(135deg,#FF6B35,#FFB347);color:#fff;padding:14px 40px;border-radius:50px;text-decoration:none;font-size:18px;font-weight:700;transition:transform .2s}
      .cta a:hover{transform:scale(1.05)}
      .cta .sub{font-size:13px;color:#a0a4b8;margin-top:10px}
      .footer{text-align:center;padding:20px;color:#666;font-size:13px}
      table{width:100%;border-collapse:collapse;margin-top:8px}
      td{padding:12px;border-bottom:1px solid rgba(255,255,255,0.05)}
    </style>
    </head>
    <body>

    <div class="hero">
      <div class="badge">MCP Skill for AI Agents</div>
      <h1>Source from China<br>with <span>AI Agents</span></h1>
      <p>Your AI agent finds Chinese factories, compares live pricing, checks inventory, and submits RFQs — while you sleep.</p>
    </div>

    <div class="container">
      <div class="card">
        <h3><span class="emoji">❓</span> What is LinkMoney?</h3>
        <p>LinkMoney is an <strong>MCP Skill</strong> that gives your AI agent (Claude, GPT, Cursor) the ability to source products directly from Chinese factories.</p>
        <ul>
          <li>Agent searches real manufacturers, not Alibaba middlemen</li>
          <li>Gets <strong>live pricing</strong> and <strong>real-time inventory</strong> from factory ERP systems</li>
          <li>Compares 3-5 suppliers automatically</li>
          <li>Submits RFQs, receives quotes, negotiates — all through your agent</li>
        </ul>
      </div>

      <div class="card">
        <h3><span class="emoji">⚡</span> How to install (30 seconds)</h3>
        <div class="step">
          <div class="step-num">1</div>
          <div class="step-text">
            <h4>Copy the install command</h4>
            <pre>http://118.196.34.217:8765/mcp/manifest.json</pre>
          </div>
        </div>
        <div class="step">
          <div class="step-num">2</div>
          <div class="step-text">
            <h4>Add to your AI agent</h4>
            <p>Paste the URL into Claude / Cursor / GPT's MCP settings. Set API key to <code>lm-demo-2026</code>.</p>
          </div>
        </div>
        <div class="step">
          <div class="step-num">3</div>
          <div class="step-text">
            <h4>Start sourcing</h4>
            <p>Tell your agent: <code>"Find M10 304 stainless steel bolts, 50K pcs, FOB Ningbo, target $0.12/pc"</code></p>
          </div>
        </div>
      </div>

      <div class="card">
        <h3><span class="emoji">🔧</span> What your agent can do</h3>
        <table>
          <tr><td><code>find_china_supplier</code></td><td>Search factories by category, spec, quantity</td></tr>
          <tr><td><code>get_pricing</code></td><td>Real-time tiered pricing from factory MCP</td></tr>
          <tr><td><code>get_inventory</code></td><td>Live stock status from factory ERP</td></tr>
          <tr><td><code>match_spec</code></td><td>Match specs to industry standards</td></tr>
          <tr><td><code>download_cert</code></td><td>Download ISO/CE/RoHS certifications</td></tr>
          <tr><td><code>multi_lang_inquiry</code></td><td>Generate inquiries in 6 languages</td></tr>
          <tr><td><code>submit_rfq</code></td><td>Send RFQ to factory + email notification</td></tr>
        </table>
        <p style="margin-top:12px;color:#FFB347;font-size:14px">8 tools total. Factories get email notifications. You get quotes back in your agent.</p>
      </div>

      <div class="card">
        <h3><span class="emoji">🆚</span> LinkMoney vs Alibaba</h3>
        <table>
          <tr style="background:rgba(255,255,255,0.05)"><td style="font-weight:600">Real manufacturers</td><td style="color:#4CAF50">Direct factory connection</td><td style="color:#f44336">40%+ are traders/middlemen</td></tr>
          <tr><td style="font-weight:600">Data freshness</td><td style="color:#4CAF50">Live from factory ERP</td><td style="color:#f44336">Weeks-old listings</td></tr>
          <tr style="background:rgba(255,255,255,0.05)"><td style="font-weight:600">Pricing</td><td style="color:#4CAF50">3% success fee only</td><td style="color:#f44336">Annual fee + P4P ads</td></tr>
          <tr><td style="font-weight:600">Communication</td><td style="color:#4CAF50">AI agent handles it</td><td style="color:#f44336">Manual WeChat/email</td></tr>
          <tr style="background:rgba(255,255,255,0.05)"><td style="font-weight:600">Agent-compatible</td><td style="color:#4CAF50">Built for AI agents</td><td style="color:#f44336">Not compatible</td></tr>
        </table>
      </div>

      <div class="cta">
        <a href="https://github.com/linkmoney-ai/linkmoney-skill" target="_blank">Install on GitHub</a>
        <p class="sub">Open source · MCP protocol · No vendor lock-in</p>
      </div>
    </div>

    <div class="footer">LinkMoney · AI-native B2B trade linker · linkmoney.online</div>
    </body>
    </html>
    """


# ===== 内测邀请页（Day 4-5） =====

@app.get("/beta-program", response_class=HTMLResponse)
def beta_program():
    """工厂内测邀请页 — 5 家补贴计划"""
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LinkMoney 内测邀请 — 首批工厂免费入驻</title>
    <style>
      *{margin:0;padding:0;box-sizing:border-box}
      body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:linear-gradient(180deg,#0A0E27 0%,#1a1f4a 100%);color:#fff;min-height:100vh}
      .hero{text-align:center;padding:50px 20px 30px}
      .hero h1{font-size:28px;font-weight:800;margin-bottom:8px}
      .hero h1 span{background:linear-gradient(135deg,#FF6B35,#FFB347);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
      .hero .sub{font-size:16px;color:#a0a4b8}
      .container{max-width:700px;margin:0 auto;padding:0 20px 60px}
      .card{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:24px;margin-bottom:16px}
      .card h3{margin-bottom:12px;font-size:18px}
      .highlight-box{background:rgba(255,107,53,0.1);border:1px solid rgba(255,107,53,0.3);border-radius:12px;padding:20px;margin:16px 0}
      .highlight-box h3{color:#FFB347;font-size:20px}
      .benefit{display:flex;gap:12px;margin:12px 0;align-items:flex-start}
      .benefit-icon{color:#FFB347;font-size:20px;flex-shrink:0}
      form{display:flex;flex-direction:column;gap:12px;margin-top:16px}
      input,select,textarea{background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);border-radius:8px;padding:12px;color:#fff;font-size:15px;font-family:inherit}
      input:focus,select:focus,textarea:focus{outline:none;border-color:#FF6B35}
      button{background:linear-gradient(135deg,#FF6B35,#FFB347);color:#fff;border:none;padding:14px;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer;transition:transform .2s}
      button:hover{transform:scale(1.02)}
      .footer{text-align:center;padding:20px;color:#666;font-size:13px}
      .counter{background:rgba(255,107,53,0.2);display:inline-block;padding:4px 12px;border-radius:20px;color:#FFB347;font-size:14px;font-weight:600}
    </style>
    </head>
    <body>

    <div class="hero">
      <h1>LinkMoney <span>首批内测</span>邀请</h1>
      <p class="sub">5 家工厂 · 3 个月免费 · 一对一接入指导</p>
      <div class="counter" style="margin-top:12px">仅剩 5 个名额</div>
    </div>

    <div class="container">
      <div class="highlight-box">
        <h3>内测工厂权益</h3>
        <div class="benefit">
          <span class="benefit-icon">✅</span>
          <span><strong>3 个月免费</strong> — 所有功能免费使用，零成本测试</span>
        </div>
        <div class="benefit">
          <span class="benefit-icon">✅</span>
          <span><strong>优先展示</strong> — 在 Agent 搜索结果中排名前 3</span>
        </div>
        <div class="benefit">
          <span class="benefit-icon">✅</span>
          <span><strong>一对一接入</strong> — 技术团队远程协助部署，你不需要懂代码</span>
        </div>
        <div class="benefit">
          <span class="benefit-icon">✅</span>
          <span><strong>专属标签</strong> — 标注"Verified Factory"，提升采购方信任</span>
        </div>
        <div class="benefit">
          <span class="benefit-icon">✅</span>
          <span><strong>数据反馈</strong> — 每周收到询盘数据分析报告</span>
        </div>
      </div>

      <div class="card">
        <h3>我们需要什么样的工厂？</h3>
        <p style="color:#a0a4b8;line-height:1.7">
          有出口经验、产品标准化程度高、愿意尝试 AI 获客。<br>
          优先品类：紧固件、电子元器件、包装材料、五金件、注塑件。
        </p>
      </div>

      <div class="card">
        <h3>提交申请</h3>
        <form id="signupForm">
          <input type="text" name="factory_name" placeholder="工厂名称 *" required>
          <input type="text" name="category" placeholder="产品品类（如：紧固件、电子） *" required>
          <input type="text" name="contact_person" placeholder="联系人 *" required>
          <input type="text" name="phone" placeholder="手机号 *" required>
          <input type="email" name="email" placeholder="邮箱">
          <textarea name="notes" placeholder="一句话介绍你的工厂和产品（选填）" rows="2"></textarea>
          <select name="source">
            <option value="">从哪里知道 LinkMoney？（选填）</option>
            <option>微信群</option>
            <option>朋友推荐</option>
            <option>抖音/B站</option>
            <option>知乎</option>
            <option>GitHub</option>
            <option>其他</option>
          </select>
          <button type="submit">提交申请</button>
        </form>
        <div id="result" style="margin-top:12px;text-align:center"></div>
      </div>

      <div class="card">
        <h3>内测时间线</h3>
        <p style="color:#a0a4b8;line-height:1.7">
          <strong>Day 1-2</strong>：提交申请 → 审核通过 → 拉群<br>
          <strong>Day 3</strong>：技术团队远程协助部署 MCP Server<br>
          <strong>Day 4-7</strong>：产品数据上线，开始接收海外 Agent 询盘<br>
          <strong>Week 2</strong>：收集反馈，优化产品
        </p>
      </div>
    </div>

    <div class="footer">LinkMoney · Agent 时代的 B2B 贸易链接器 · linkmoney.online</div>

    <script>
    document.getElementById('signupForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      const data = {};
      form.forEach((v,k) => data[k]=v);
      try {
        const resp = await fetch('/beta-signup', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(data)
        });
        const result = await resp.json();
        document.getElementById('result').innerHTML = resp.ok
          ? '<span style="color:#4CAF50;font-size:16px">' + result.message + '</span>'
          : '<span style="color:#f44336">提交失败: ' + (result.detail || '请重试') + '</span>';
        if (resp.ok) e.target.reset();
      } catch(err) {
        document.getElementById('result').innerHTML = '<span style="color:#f44336">网络错误，请重试</span>';
      }
    });
    </script>
    </body>
    </html>
    """


class BetaSignupRequest(BaseModel):
    factory_name: str
    category: str
    contact_person: str
    phone: str
    email: str = ""
    notes: str = ""
    source: str = ""


@app.post("/beta-signup")
@limiter.limit("5/minute")
def beta_signup(req: BetaSignupRequest, request: Request):
    """工厂内测申请提交"""
    with get_db() as conn:
        # 确保 beta_signups 表存在
        conn.execute("""
            CREATE TABLE IF NOT EXISTS beta_signups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factory_name TEXT NOT NULL,
                category TEXT NOT NULL,
                contact_person TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                source TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute(
            "INSERT INTO beta_signups (factory_name, category, contact_person, phone, email, notes, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (req.factory_name, req.category, req.contact_person, req.phone, req.email, req.notes, req.source),
        )
        conn.commit()

    logger.info(f"[BETA SIGNUP] {req.factory_name} | {req.category} | {req.contact_person}")

    return {
        "status": "ok",
        "message": f"申请已提交！{req.contact_person}，我们会在 24 小时内联系你。",
        "next_step": "请保持手机/微信畅通，我们会拉你进内测群。",
    }


# ============================================================
# v2.1+ 新端点：注册、验证、需求广场、主动外联、互评
# ============================================================

# 工具函数
def _gen_token(length: int = 32) -> str:
    """生成随机 token"""
    return hashlib.sha256(os.urandom(length)).hexdigest()[:length]


def _verify_supplier_access(conn, supplier_id: str, access_token: str) -> dict:
    """v5.2.4: 统一校验工厂身份 — supplier_id + access_token 绑定。

    Args:
        conn: SQLite 连接
        supplier_id: 供应商 ID
        access_token: 工厂长期身份凭证（注册时返回，不随邮箱验证失效）

    Returns:
        供应商行 dict（校验通过）

    Raises:
        HTTPException 404: 供应商不存在
        HTTPException 401: access_token 缺失或错误
    """
    s = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if not s:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
    if not access_token or access_token != s["access_token"]:
        raise HTTPException(status_code=401, detail="access_token 无效或缺失。请用注册时返回的 access_token 调用。")
    return dict(s)


def _slugify_supplier_id(name: str, category: str) -> str:
    """根据公司名+品类生成供应商 ID（避免中文，保证唯一性）

    v3.3.3: 中文名经过滤后 slug 为空时，使用公司名 hash 保证唯一性
    """
    cat = re.sub(r"[^a-z0-9]+", "", category.lower())[:8] or "supplier"
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20]

    if not slug:
        # 中文名或纯特殊字符 → 用公司名 hash 生成唯一 slug
        name_hash = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
        slug = f"cn{name_hash}"

    return f"{cat}-{slug}"


def _compute_trust_level(score: float, email_v: int, phone_v: int, license_v: int) -> str:
    """根据验证项+评分计算信任等级"""
    if license_v and phone_v and email_v and score >= 80:
        return "gold"
    if email_v and phone_v and score >= 60:
        return "verified"
    if email_v and score >= 30:
        return "basic"
    return "unverified"


def _auto_evaluate_supplier(supplier: dict) -> dict:
    """v2.1 内部自动评估（5 维度），不暴露给工厂自助
    v5.2.3: 营业执照未验证（license_verified=0）时，资质/产能/出口/质量4维度只给基础分，
    防止虚构自填数据刷分。验证营业执照后才按真实数据计分。
    """
    license_verified = supplier.get("license_verified", 0)

    # 1. 资质（成立年份，需营业执照验证才计分）
    if license_verified:
        age = max(0, datetime.now().year - supplier.get("year_established", 0))
        qual_score = min(100, age * 4 + 20)  # 5 年=40, 10 年=60
    else:
        qual_score = 30  # 未验证：基础分

    # 2. 产能（员工数 + 年营收，需营业执照验证才计分）
    if license_verified:
        employees = supplier.get("employees", 0)
        revenue = supplier.get("annual_revenue_usd", 0)
        if employees >= 200 or revenue >= 5_000_000:
            cap_score = 90
        elif employees >= 50 or revenue >= 1_000_000:
            cap_score = 70
        elif employees >= 20 or revenue >= 300_000:
            cap_score = 50
        else:
            cap_score = 30
    else:
        cap_score = 30  # 未验证：基础分

    # 3. 出口比例（需营业执照验证才计分）
    if license_verified:
        exp_ratio = supplier.get("export_ratio", 0)
        export_score = min(100, exp_ratio)
    else:
        export_score = 20  # 未验证：基础分

    # 4. 质量（认证数，需营业执照验证才计分；评价加权不受影响）
    if license_verified:
        cert_count = len(supplier.get("certifications", []))
        quality_score = min(100, cert_count * 20)
    else:
        quality_score = 20  # 未验证：基础分
    # v5.2: 若有评价，叠加 review 加权（4.5 星→+15, 3.0 星→0, 2.0 星→-10）
    review_count = supplier.get("review_count", 0)
    review_avg = supplier.get("review_avg", 0)
    if review_count and review_count > 0 and review_avg:
        review_bonus = (review_avg - 3.0) * 10
        quality_score = max(0, min(100, quality_score + int(review_bonus)))

    # 5. 合规（简化版：有邮箱 + 已装 Skill +25）
    compliance_score = 30
    if supplier.get("agent_skill_installed"):
        compliance_score += 40
    if supplier.get("email_verified"):
        compliance_score += 30

    scores = {
        "qualification": round(qual_score),
        "capacity": round(cap_score),
        "export": round(export_score),
        "quality": round(quality_score),
        "compliance": round(compliance_score),
    }
    overall = round(sum(scores.values()) / 5)

    return {
        "overall_score": overall,
        "dimensions": scores,
        "trust_level": _compute_trust_level(
            overall,
            supplier.get("email_verified", 0),
            supplier.get("phone_verified", 0),
            supplier.get("license_verified", 0),
        ),
    }


def _recalculate_trust_score(conn, supplier_id: str):
    """v5.2: 动态重算供应商 trust_score 并写入数据库。

    在以下 5 个事件后触发：
    1. verify_email — 邮箱验证通过
    2. link_supplier_mcp — 装上 MCP Skill
    3. unlink_supplier_mcp — 取消 MCP Skill
    4. leave_review — 收到新评价
    5. send_quote — 报价响应

    安全约束：
    - 分数范围 [0, 100]（_auto_evaluate_supplier 内部已 clamp）
    - 失败时静默降级（不影响业务流程）
    - 每次重算都写入 trust_evaluations 表留审计快照
    """
    try:
        row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not row:
            return
        s = _row_to_supplier(row)
        eval_result = _auto_evaluate_supplier({
            "year_established": s.get("year_established", 0),
            "employees": s.get("employees", 0),
            "annual_revenue_usd": s.get("annual_revenue_usd", 0),
            "export_ratio": s.get("export_ratio", 0),
            "certifications": s.get("certifications", []),
            "agent_skill_installed": s.get("agent_skill_installed", 0),
            "email_verified": s.get("email_verified", 0),
            "license_verified": s.get("license_verified", 0),  # v5.2.3: 营业执照验证状态
            "review_avg": s.get("review_avg", 0),
            "review_count": s.get("review_count", 0),
        })
        # 边界保护：分数必须在 [0, 100]
        overall = max(0, min(100, eval_result["overall_score"]))
        trust_level = eval_result["trust_level"]
        conn.execute(
            "UPDATE suppliers SET trust_score = ?, trust_level = ?, updated_at = ? WHERE id = ?",
            (overall, trust_level, datetime.now().isoformat() + "Z", supplier_id),
        )
        # 写入评估快照（审计追溯）
        conn.execute(
            "INSERT INTO trust_evaluations(target_id, target_type, overall_score, dimensions, trust_level) "
            "VALUES (?, 'supplier', ?, ?, ?)",
            (supplier_id, overall,
             json.dumps(eval_result["dimensions"], ensure_ascii=False),
             trust_level),
        )
        logger.info(f"trust_score recalculated for {supplier_id}: {overall} ({trust_level})")
    except Exception as e:
        logger.warning(f"_recalculate_trust_score failed for {supplier_id}: {e}")


# ===== v5.2 积累学习层：match_score 权重动态调整 =====
#
# 设计目标：基于历史 RFQ→报价→评价数据，自动微调 find_china_supplier 的 7 维权重，
# 让评分更精准地反映"实际成交转化率"。
#
# 安全约束（用户明确要求：参数范围 + 时效控制，避免累计后多次修改导致运行错误崩盘）：
# 1. 每个权重必须在 _WEIGHT_BOUNDS 边界内（防止极端值）
# 2. 单次调整幅度 ≤ _MAX_ADJUST_STEP（防止突变）
# 3. 冷却时间 24 小时（避免频繁修改导致不稳定）
# 4. 最小样本量 _MIN_SAMPLES_TO_LEARN（避免噪声）
# 5. 持久化到 config 表（重启不丢失）
# 6. 失败时静默降级到默认权重（不影响业务流程）
# 7. 所有权重归一化为总和 = 100（保证 score 范围 [0, 100]）

_DEFAULT_MATCH_WEIGHTS = {
    "category": 30,
    "spec": 20,
    "moq": 15,
    "price": 15,
    "certs": 10,
    "location": 5,
    "skill": 5,
}

# 每个维度的边界 [min, max]（防止极端值导致评分失衡）
_WEIGHT_BOUNDS = {
    "category": (10, 50),
    "spec": (5, 40),
    "moq": (5, 30),
    "price": (5, 30),
    "certs": (2, 20),
    "location": (0, 15),
    "skill": (0, 15),
}

_MAX_ADJUST_STEP = 3          # 单次调整最大幅度（防止突变）
_MIN_SAMPLES_TO_LEARN = 10    # 最小样本量（不足不学习，避免噪声）
_LEARN_COOLDOWN_SECONDS = 86400  # 学习冷却时间：24 小时


def _load_match_weights(conn) -> dict:
    """从 config 表加载 match_weights，失败回退默认值。

    返回结构：
    {
        "weights": {"category": 30, "spec": 20, ...},  # 归一化后的权重
        "last_adjusted_at": "2026-06-25T12:00:00Z",     # 上次调整时间
        "sample_count": 25,                              # 上次学习时的样本量
    }
    """
    try:
        row = conn.execute("SELECT value FROM config WHERE key = 'match_weights'").fetchone()
        if row:
            data = json.loads(row["value"])
            weights = data.get("weights", {})
            # 校验结构完整性：7 个维度必须都在
            if all(k in weights for k in _DEFAULT_MATCH_WEIGHTS):
                # 边界保护：每个权重必须在允许范围内
                sanitized = {}
                for k, default_v in _DEFAULT_MATCH_WEIGHTS.items():
                    v = weights.get(k, default_v)
                    lo, hi = _WEIGHT_BOUNDS[k]
                    sanitized[k] = max(lo, min(hi, int(v)))
                return {
                    "weights": sanitized,
                    "last_adjusted_at": data.get("last_adjusted_at", ""),
                    "sample_count": data.get("sample_count", 0),
                }
    except Exception as e:
        logger.warning(f"_load_match_weights failed, use defaults: {e}")
    return {
        "weights": dict(_DEFAULT_MATCH_WEIGHTS),
        "last_adjusted_at": "",
        "sample_count": 0,
    }


def _save_match_weights(conn, weights_data: dict):
    """保存 match_weights 到 config 表（持久化，重启不丢失）。"""
    try:
        conn.execute(
            "INSERT OR REPLACE INTO config(key, value) VALUES (?, ?)",
            ("match_weights", json.dumps(weights_data, ensure_ascii=False)),
        )
    except Exception as e:
        logger.warning(f"_save_match_weights failed: {e}")


def _learn_match_weights(conn):
    """v5.2: 基于历史 RFQ→报价→评价数据调整 7 维权重。

    学习信号：
    - 正向：RFQ 被报价且评价 ≥ 4 星 → 匹配维度有效，权重微增
    - 负向：RFQ 被报价但评价 ≤ 2 星 → 匹配维度失效，权重微减

    安全约束：
    - 冷却期 24 小时（避免频繁修改导致运行错误）
    - 最小样本量 10（避免噪声）
    - 单次调整幅度 ≤ 3（防止突变）
    - 每个权重在边界范围内（防止极端值）
    - 归一化总和 = 100（保证 score 范围稳定）
    - 失败时静默降级（不影响业务流程）
    """
    try:
        current = _load_match_weights(conn)

        # 时效控制：冷却期内不学习
        if current["last_adjusted_at"]:
            try:
                last_ts = datetime.fromisoformat(
                    current["last_adjusted_at"].replace("Z", "")
                )
                elapsed = (datetime.now() - last_ts).total_seconds()
                if elapsed < _LEARN_COOLDOWN_SECONDS:
                    return  # 冷却中，跳过
            except Exception:
                pass  # 时间戳解析失败，继续学习

        # 收集历史样本：已报价的 RFQ + 对应评价
        # 注意：rfqs 表无 category 列；suppliers 表无 location 列（拆为 city/province/port）
        rows = conn.execute("""
            SELECT r.rating, rfq.quantity, rfq.target_price_usd,
                   s.moq, s.certifications, s.port, s.agent_skill_installed
            FROM reviews r
            JOIN rfqs rfq ON r.rfq_id = rfq.id
            JOIN suppliers s ON r.target_id = s.id
            WHERE r.target_type = 'supplier' AND rfq.status = 'quoted'
        """).fetchall()

        sample_count = len(rows)
        if sample_count < _MIN_SAMPLES_TO_LEARN:
            return  # 样本不足，不学习

        # 统计每个维度在"高分评价"和"低分评价"中的表现
        positive_counts = {k: 0 for k in _DEFAULT_MATCH_WEIGHTS}
        negative_counts = {k: 0 for k in _DEFAULT_MATCH_WEIGHTS}
        total_positive = 0
        total_negative = 0

        for row in rows:
            rating = row["rating"] if row["rating"] else 0
            # 解析 certifications（可能是 JSON 字符串）
            certs = row["certifications"] or "[]"
            if isinstance(certs, str):
                try:
                    certs = json.loads(certs)
                except Exception:
                    certs = []
            has_certs = isinstance(certs, list) and len(certs) > 0
            moq_ok = row["quantity"] and row["moq"] and row["quantity"] >= row["moq"]
            has_price = row["target_price_usd"] and row["target_price_usd"] > 0
            has_skill = row["agent_skill_installed"]
            has_port = bool(row["port"])  # suppliers 表用 port 列表示出口港口

            if rating >= 4:
                total_positive += 1
                positive_counts["category"] += 1  # RFQ 已匹配到供应商
                positive_counts["spec"] += 1      # RFQ 已到报价阶段
                if moq_ok:
                    positive_counts["moq"] += 1
                if has_price:
                    positive_counts["price"] += 1
                if has_certs:
                    positive_counts["certs"] += 1
                if has_skill:
                    positive_counts["skill"] += 1
                if has_port:
                    positive_counts["location"] += 1
            elif rating <= 2:
                total_negative += 1
                negative_counts["category"] += 1
                negative_counts["spec"] += 1
                if moq_ok:
                    negative_counts["moq"] += 1
                if has_price:
                    negative_counts["price"] += 1
                if has_certs:
                    negative_counts["certs"] += 1
                if has_skill:
                    negative_counts["skill"] += 1
                if has_port:
                    negative_counts["location"] += 1

        if total_positive == 0 and total_negative == 0:
            return  # 无有效信号

        # 计算调整方向：正样本占比高 → 权重微增；负样本占比高 → 权重微减
        new_weights = dict(current["weights"])
        for dim in _DEFAULT_MATCH_WEIGHTS:
            pos_rate = positive_counts[dim] / total_positive if total_positive > 0 else 0
            neg_rate = negative_counts[dim] / total_negative if total_negative > 0 else 0
            # 调整信号：正向比例 - 负向比例，范围 [-1, 1]
            signal = pos_rate - neg_rate
            # 调整幅度：signal * _MAX_ADJUST_STEP，范围 [-3, +3]
            adjustment = int(signal * _MAX_ADJUST_STEP)
            if adjustment == 0:
                continue  # 无显著信号，不调整

            new_v = new_weights[dim] + adjustment
            # 边界保护
            lo, hi = _WEIGHT_BOUNDS[dim]
            new_v = max(lo, min(hi, new_v))
            new_weights[dim] = new_v

        # 归一化：按比例缩放使总和接近 100
        total = sum(new_weights.values())
        if total > 0 and total != 100:
            scale = 100.0 / total
            new_weights = {
                k: max(_WEIGHT_BOUNDS[k][0], min(_WEIGHT_BOUNDS[k][1], int(v * scale)))
                for k, v in new_weights.items()
            }

        # 最终安全保护：确保每个维度相对原值的偏移 ≤ _MAX_ADJUST_STEP
        # （归一化可能导致某个维度超出步长限制，此处强制拉回）
        for dim in _DEFAULT_MATCH_WEIGHTS:
            original = current["weights"][dim]
            new_v = new_weights[dim]
            if new_v - original > _MAX_ADJUST_STEP:
                new_weights[dim] = original + _MAX_ADJUST_STEP
            elif original - new_v > _MAX_ADJUST_STEP:
                new_weights[dim] = original - _MAX_ADJUST_STEP

        # 检查是否真的有变化
        if new_weights == current["weights"]:
            return  # 无变化，不写入

        # 持久化
        new_data = {
            "weights": new_weights,
            "last_adjusted_at": datetime.now().isoformat() + "Z",
            "sample_count": sample_count,
        }
        _save_match_weights(conn, new_data)
        conn.commit()
        # 失效 find_china_supplier 缓存，让新权重立即生效
        _supplier_cache.invalidate("find:")
        logger.info(
            f"[LEARN] match_weights adjusted: sample_count={sample_count}, "
            f"new_weights={new_weights}"
        )
    except Exception as e:
        # 失败时静默降级（不影响业务流程）
        logger.warning(f"_learn_match_weights failed (silent fallback): {e}")


# ===== v2.1 注册端点 =====

class RegisterSupplierRequest(BaseModel):
    company_name: str
    category: str
    products: list = []
    certifications: list = []
    employees: int = 0
    year_established: int = 0
    annual_revenue_usd: float = 0
    export_ratio: float = 0
    main_markets: list = []
    contact_person: str = ""
    email: str
    phone: str                     # v5.2.3: phone 改必填（审核对空手机号 block）
    wechat: str = ""
    moq: int = 0
    lead_time_days_standard: int = 0
    lead_time_days_express: int = 0
    languages: list = ["zh", "en"]
    # v5.2: BD 现场采集 — 传图片 URL 时用 LLM 多模态抽取结构化字段
    image_urls: list = []          # 工厂照片公网 URL（最多 10 张）
    audio_text: str = ""           # BD 录音转写（可选）
    factory_location: str = ""     # 工厂地址（可选）
    uscc: str = ""                 # v5.2.3: 统一社会信用代码（18 位，用于营业执照验证）


@app.post("/register_supplier")
@limiter.limit("5/hour")
def register_supplier(request: Request, req: RegisterSupplierRequest):
    """
    工厂自助注册（v2.1 新流程）
    工厂只需要填产品资料+联系信息，LinkMoney 帮它：
    1. 生成供应商 ID
    2. 自动入库
    3. 自动跑信用评估
    4. 自动生成专属 SKILL.md（收录到 LinkMoney 总 Skill 下）
    5. 触发邮箱验证
    """
    # ===== Trust & Safety 审核工厂注册信息 =====
    try:
        from trust_safety import audit_supplier_registration
        reg_audit = audit_supplier_registration(
            company_name=req.company_name,
            email=req.email,
            phone=req.phone or "",
            uscc=req.uscc,
            country="CN",
            llm_provider=get_llm() if get_llm().is_available() else None,
        )
        if reg_audit.blocked:
            logger.warning(f"[T&S BLOCK] register_supplier blocked: {reg_audit.reasons}")
            try:
                from middle_agent import report_ts_alert
                report_ts_alert("critical", "supplier_registration", reg_audit.reasons, reg_audit.details)
            except Exception:
                pass
            raise HTTPException(status_code=400, detail={
                "error": "Registration blocked by Trust & Safety audit",
                "reasons": reg_audit.reasons,
                "audit": reg_audit.to_dict(),
            })
        if reg_audit.level == "review":
            logger.info(f"[T&S REVIEW] register_supplier flagged: {reg_audit.reasons}")
            try:
                from middle_agent import report_ts_alert
                report_ts_alert("warn", "supplier_registration", reg_audit.reasons, reg_audit.details)
            except Exception:
                pass
        _reg_ts_audit = reg_audit.to_dict()
    except ImportError:
        _reg_ts_audit = None  # trust_safety 模块缺失时放行（开发环境）
    except HTTPException:
        raise
    except Exception as e:
        # v5.2.3: fail-closed — 审核模块异常时拒绝注册（防审核被绕过）
        logger.error(f"Registration T&S audit failed (fail-closed): {e}")
        raise HTTPException(status_code=503, detail={
            "error": "Registration temporarily unavailable due to audit system error",
            "reason": "安全审核系统异常，请稍后重试",
        })

    supplier_id = _slugify_supplier_id(req.company_name, req.category)
    name_en = req.company_name  # 简化：英文名=中文名
    city = ""
    province = ""
    port = "Ningbo"

    # v5.2: BD 现场采集 — 若传了图片 URL，用 LLM 多模态抽取结构化字段
    # 仅当原字段为空时用 LLM 结果覆盖（不覆盖工厂已填的数据）
    llm_profile = None
    if req.image_urls:
        try:
            llm = get_llm()
            if llm.is_available():
                llm_profile = llm.extract_factory_profile(
                    image_urls=req.image_urls,
                    audio_text=req.audio_text,
                    location=req.factory_location,
                )
                if not req.employees and llm_profile.get("employees"):
                    req.employees = llm_profile["employees"]
                if not req.year_established and llm_profile.get("year_established"):
                    req.year_established = llm_profile["year_established"]
                if not req.certifications and llm_profile.get("certifications"):
                    req.certifications = llm_profile["certifications"]
                if not req.moq and llm_profile.get("moq"):
                    req.moq = llm_profile["moq"]
                if not req.main_markets and llm_profile.get("main_export_markets"):
                    req.main_markets = llm_profile["main_export_markets"]
                if req.category in ("", "other") and llm_profile.get("suggested_category"):
                    req.category = llm_profile["suggested_category"]
                logger.info(f"extract_factory_profile success: confidence={llm_profile.get('confidence','?')}")
        except Exception as e:
            logger.warning(f"extract_factory_profile failed, fallback to text-only: {e}")
            # 失败不阻塞注册，继续走纯文本流程

    # 信用评估
    eval_result = _auto_evaluate_supplier({
        "year_established": req.year_established,
        "employees": req.employees,
        "annual_revenue_usd": req.annual_revenue_usd,
        "export_ratio": req.export_ratio,
        "certifications": req.certifications,
        "agent_skill_installed": 0,
        "email_verified": 0,
    })

    verification_token = _gen_token(16)
    access_token = _gen_token(32)  # v5.2.4: 工厂长期身份凭证，不随邮箱验证失效
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    # v3.3: 中心化托管 — 注册即自动生成 MCP endpoint，工厂无需自己部署
    hosted_mcp_endpoint = f"http://118.196.34.217:8765/mcp/supplier/{supplier_id}"

    # v3.2: 查重 + 插入在同一事务内（消除 TOCTOU 竞态）
    # v5.2.3: 查重维度增强 — 邮箱、公司名（模糊匹配）、手机号、邮箱域名（限 3 个）
    import re as _re
    _normalize_name = _re.sub(r"[\s\u3000\.,，。·\-_()（）]+", "", req.company_name).lower()

    with get_db() as conn:
        # 1. 邮箱查重
        existing = conn.execute("SELECT id FROM suppliers WHERE email = ?", (req.email,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"该邮箱已注册为供应商 {existing['id']}")

        # 2. 公司名查重（v5.2.3: 模糊匹配 — 去空格/标点/大小写后比较，防"加个空格"绕过）
        all_suppliers = conn.execute("SELECT id, name_zh, category FROM suppliers").fetchall()
        for s in all_suppliers:
            if _re.sub(r"[\s\u3000\.,，。·\-_()（）]+", "", s["name_zh"] or "").lower() == _normalize_name:
                raise HTTPException(status_code=409, detail=f"该公司名已注册为供应商 {s['id']}（品类: {s['category']}）。如需修改信息，请联系管理员。")

        # 3. 手机号查重
        existing = conn.execute("SELECT id FROM suppliers WHERE phone = ?", (req.phone,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"该手机号已注册为供应商 {existing['id']}")

        # 4. 邮箱域名查重（v5.2.3: 同域名限 3 个，防批量注册）
        _email_domain = req.email.split("@")[-1].lower() if "@" in req.email else ""
        if _email_domain:
            domain_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM suppliers WHERE LOWER(SUBSTR(email, INSTR(email, '@') + 1)) = ?",
                (_email_domain,)
            ).fetchone()["cnt"]
            if domain_count >= 3:
                raise HTTPException(status_code=429, detail=f"该邮箱域名（@{_email_domain}）已注册 {domain_count} 个供应商，达到上限。如需更多，请联系管理员。")

        # 4. supplier_id 查重（v3.3.3: 冲突时自动加序号后缀，而非直接报错）
        base_id = supplier_id
        suffix = 2
        while conn.execute("SELECT id FROM suppliers WHERE id = ?", (supplier_id,)).fetchone():
            supplier_id = f"{base_id}-{suffix}"
            suffix += 1

        # 5. 写入 suppliers（在同一事务内，消除竞态）
        # v3.2: 捕获 UNIQUE 约束冲突，返回友好的 409 而非 500
        # v3.3: 自动激活托管 MCP — 工厂无需自己部署
        try:
            # 写入 suppliers
            conn.execute("""
                INSERT INTO suppliers(
                    id, name_zh, name_en, city, province, port, category, subcategories,
                    year_established, employees, annual_revenue_usd, export_ratio, main_markets,
                    moq, lead_time_standard, lead_time_express, certifications, languages,
                    agent_skill_installed, skill_mcp_endpoint, skill_platforms, skill_installs,
                    created_at, updated_at, contact_person, email, phone, wechat, language_contact,
                    email_verified, phone_verified, license_verified, trust_score, trust_level,
                    verification_token, data_source_type, access_token
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                supplier_id,
                req.company_name, name_en, city, province, port,
                req.category, json.dumps([], ensure_ascii=False),
                req.year_established, req.employees, req.annual_revenue_usd, req.export_ratio,
                json.dumps(req.main_markets, ensure_ascii=False),
                req.moq, req.lead_time_days_standard, req.lead_time_days_express,
                json.dumps(req.certifications, ensure_ascii=False),
                json.dumps(req.languages, ensure_ascii=False),
                1, hosted_mcp_endpoint, json.dumps([], ensure_ascii=False), 0,
                datetime.now().isoformat() + "Z", datetime.now().isoformat() + "Z",
                req.contact_person, req.email, req.phone, req.wechat,
                json.dumps({}, ensure_ascii=False),
                0, 0, 0,
                eval_result["overall_score"], eval_result["trust_level"],
                verification_token,
                "hosted",
                access_token,
            ))

            # 写入 products（使用 INSERT OR REPLACE，防止 sku 重复时更新而非报错）
            for i, p in enumerate(req.products):
                conn.execute("""
                    INSERT OR REPLACE INTO products(supplier_id, sku, name_zh, name_en, category, material, grade, specs, pricing_tiers,
                        moq, trade_terms, port, price_currency, price_type, price_unit,
                        inventory_status, inventory_quantity, inventory_unit, inventory_lead_time_days,
                        hs_code, payment_terms, sample_available, customized, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    supplier_id,
                    p.get("sku", f"sku-{i+1:03d}"),
                    p.get("name_zh", ""), p.get("name_en", ""),
                    req.category,
                    p.get("material", ""), p.get("grade", ""),
                    json.dumps(p.get("specs", {}), ensure_ascii=False),
                    json.dumps(p.get("pricing_tiers", []), ensure_ascii=False),
                    p.get("moq", req.moq or 1),
                    p.get("trade_terms", "FOB"),
                    p.get("port", port),
                    p.get("price_currency", "USD"),
                    p.get("price_type", "FOB"),
                    p.get("price_unit", "pc"),
                    p.get("inventory_status", "unknown"),
                    p.get("inventory_quantity", 0),
                    p.get("inventory_unit", "pc"),
                    p.get("inventory_lead_time_days", 0),
                    p.get("hs_code", ""),
                    p.get("payment_terms", ""),
                    1 if p.get("sample_available") else 0,
                    1 if p.get("customized") else 0,
                    p.get("status", "active"),
                    now_iso, now_iso,
                ))

            # 记录评估
            conn.execute("""
                INSERT INTO trust_evaluations(target_id, target_type, overall_score, dimensions, trust_level)
                VALUES (?, ?, ?, ?, ?)
            """, (
                supplier_id, "supplier",
                eval_result["overall_score"],
                json.dumps(eval_result["dimensions"], ensure_ascii=False),
                eval_result["trust_level"],
            ))

            # 创建验证 token
            conn.execute("""
                INSERT INTO verifications(token, target_type, target_id, contact, purpose, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                verification_token, "supplier_email", supplier_id, req.email, "verify_email",
                (datetime.now() + timedelta(days=7)).isoformat() + "Z",
            ))

            conn.commit()

        except sqlite3.IntegrityError as e:
            conn.rollback()
            err_msg = str(e).lower()
            if "email" in err_msg:
                raise HTTPException(status_code=409, detail=f"该邮箱已被注册（数据库唯一约束）: {req.email}")
            elif "name_zh" in err_msg or "suppliers.name_zh" in err_msg:
                raise HTTPException(status_code=409, detail=f"该公司名已被注册（数据库唯一约束）: {req.company_name}")
            elif "phone" in err_msg:
                raise HTTPException(status_code=409, detail=f"该手机号已被注册（数据库唯一约束）: {req.phone}")
            elif "idx_products_supplier_sku_unique" in err_msg or "supplier_id, sku" in err_msg:
                raise HTTPException(status_code=409, detail=f"产品 SKU 重复（同一供应商下 SKU 必须唯一）")
            else:
                logger.error(f"注册时数据库唯一约束冲突: {e}", exc_info=True)
                raise HTTPException(status_code=409, detail=f"注册失败（数据冲突）: {e}")

    # 自动生成专属 SKILL.md（v2.1 由 LinkMoney 完成，工厂不需要自己写）
    company_slug = re.sub(r"[^a-z0-9]+", "-", req.company_name.lower()).strip("-")[:20]
    skill_md = f"""---
name: {company_slug}-{req.category}
description: {req.company_name} — 中国{req.category}品类供应商
version: 1.0.0
author: LinkMoney
mcp_endpoint: http://118.196.34.217:8765/find_china_supplier?category={req.category}&supplier={supplier_id}
trust_level: {eval_result['trust_level']}
trust_score: {eval_result['overall_score']}
---

# {req.company_name}

## 核心产品
"""
    for p in req.products[:5]:
        skill_md += f"- {p.get('name_zh', '')} / {p.get('name_en', '')}\n"

    skill_md += f"""
## 资质
- 评分: {eval_result['overall_score']}/100
- 信任等级: {eval_result['trust_level']}
- 成立年份: {req.year_established}
- 员工数: {req.employees}
- 出口比例: {req.export_ratio}%

## 联系方式
- 邮箱: {req.email}（未验证）
- 电话: {req.phone or '未填写'}

## 安装方式
无需单独安装。LinkMoney 总 Skill 1.0+ 已自动收录此供应商。
"""

    # 新工厂注册后失效 find_china_supplier 缓存，让新工厂立即可被搜索到
    _supplier_cache.invalidate("find:")

    return {
        "supplier_id": supplier_id,
        "company_name": req.company_name,
        "status": "registered",
        "mcp_endpoint": hosted_mcp_endpoint,
        "data_source_type": "hosted",
        "has_skill": True,
        "agent_skill_installed": True,
        "access_token": access_token,  # v5.2.4: 工厂长期身份凭证，后续所有写操作需携带
        "verification": {
            "email_verified": False,
            "phone_verified": False,
            "license_verified": False,
            "verification_token": verification_token,
            "verify_url": f"/verify_email?token={verification_token}",
            "next_step": "请到邮箱点击验证链接（演示版会直接标记为已验证）"
        },
        "auto_evaluation": eval_result,
        "llm_profile_extracted": llm_profile,  # v5.2: BD 图片抽取结果（None 表示未用）
        "auto_generated_skill": {
            "skill_md_preview": skill_md[:500] + "...",
            "full_skill_in_git": f"http://118.196.34.217:8765/skill.md?supplier={supplier_id}",
        },
        "next_action": {
            "step_1": "验证邮箱：访问 verify_url 或调用 /verify_email?token=xxx",
            "step_2": f"你的工厂已自动激活，MCP endpoint: {hosted_mcp_endpoint}",
            "step_3": "通过对话管理产品：调用 POST /suppliers/{supplier_id}/products 增删改产品（需带 access_token）",
            "step_4": "海外 Agent 现在可以通过 find_china_supplier 搜索到你",
        },
        "estimated_time_to_live": "验证邮箱后立即被海外 Agent 搜索到（托管模式，实时数据）",
    }


# ===== v3.3: 海外采购方自注册（打通 W 端闭环）=====

class RegisterBuyerRequest(BaseModel):
    """海外采购方自注册（海外 Agent 可代为调用）"""
    company: str
    country: str
    industry: str = ""
    contact_person: str = ""
    email: str
    interested_categories: list = []  # ["fastener", "electronics", ...]
    preferred_supplier_locations: list = []  # ["Ningbo", "Shenzhen", ...]
    certifications_required: list = []  # ["ISO 9001", "CE", ...]
    languages: list = ["en"]
    agent_platform: str = "unknown"  # "chatgpt" / "claude" / "coze" / ...
    annual_import_usd: float = 0


@app.post("/register_buyer")
def register_buyer(req: RegisterBuyerRequest, request: Request):
    """海外采购方自注册 — 让海外 Agent 能自发发 RFQ

    使用场景：
    - 海外 Agent 装了 LinkMoney Skill 后，首次发 RFQ 前自动注册
    - 无需管理员预存，降低 W 端闭环门槛
    """
    # 邮箱查重
    with get_db() as conn:
        if req.email:
            existing = conn.execute("SELECT id FROM overseas_buyers WHERE email = ?", (req.email,)).fetchone()
            if existing:
                # 已存在，直接返回（幂等）
                return {
                    "buyer_id": existing["id"],
                    "status": "already_registered",
                    "message": f"该邮箱已注册，buyer_id={existing['id']}",
                }

        # 生成 buyer_id
        buyer_id = _slugify_supplier_id(req.company, "buyer") or f"buyer-{int(time.time())}"
        # 确保 buyer_id 唯一
        base_id = buyer_id
        suffix = 2
        while conn.execute("SELECT id FROM overseas_buyers WHERE id = ?", (buyer_id,)).fetchone():
            buyer_id = f"{base_id}-{suffix}"
            suffix += 1

        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("""
            INSERT INTO overseas_buyers(
                id, company, country, industry, annual_import_usd,
                interested_categories, preferred_supplier_locations, certifications_required,
                contact_person, email, languages, agent_platform,
                agent_installed_linkmoney, last_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            buyer_id, req.company, req.country, req.industry, req.annual_import_usd,
            json.dumps(req.interested_categories, ensure_ascii=False),
            json.dumps(req.preferred_supplier_locations, ensure_ascii=False),
            json.dumps(req.certifications_required, ensure_ascii=False),
            req.contact_person, req.email,
            json.dumps(req.languages, ensure_ascii=False),
            req.agent_platform,
            now_iso,
        ))
        conn.commit()

    return {
        "buyer_id": buyer_id,
        "status": "registered",
        "company": req.company,
        "country": req.country,
        "next_action": f"现在可以调用 submit_rfq 发送询价了（buyer_id={buyer_id}）",
        "example": f'find_china_supplier → get_pricing → submit_rfq(supplier_id=xxx, buyer_id={buyer_id}, sku=xxx, quantity=1000)',
    }


# ===== v2.1 验证端点 =====

@app.get("/verify_email")
def verify_email(token: str):
    """通过 token 验证邮箱（演示版直接通过）"""
    with get_db() as conn:
        v = conn.execute(
            "SELECT * FROM verifications WHERE token = ? AND used = 0", (token,)
        ).fetchone()
        if not v:
            raise HTTPException(status_code=404, detail="验证链接无效或已使用")

        # 标记为已使用
        conn.execute("UPDATE verifications SET used = 1 WHERE token = ?", (token,))

        # 更新对应 supplier/buyer 邮箱验证状态
        if v["target_type"] == "supplier_email":
            conn.execute(
                "UPDATE suppliers SET email_verified = 1, verification_token = '' WHERE id = ?",
                (v["target_id"],),
            )
            # v5.2: 邮箱验证后重算 trust_score（compliance +30）
            _recalculate_trust_score(conn, v["target_id"])
        elif v["target_type"] == "buyer_email":
            conn.execute(
                "UPDATE overseas_buyers SET email_verified = 1 WHERE id = ?",
                (v["target_id"],),
            )

        conn.commit()

    return {
        "status": "verified",
        "target_type": v["target_type"],
        "target_id": v["target_id"],
        "message": "邮箱已验证！现在可以接收询盘通知。",
    }


# ===== v3.2: 供应商 MCP 端点回写（打通混合架构实时数据流）=====

class LinkMcpRequest(BaseModel):
    """工厂部署完自有 MCP Server 后，回写 endpoint 到中央库"""
    mcp_endpoint: str                           # 如 https://factory.com/mcp
    access_token: str = ""                      # v5.2.4: 工厂身份凭证
    verification_token: str = ""                # 向后兼容（已弃用）
    skill_platforms: list = []                  # 已发布到哪些平台 ["github","claude","coze"]
    skill_installs: int = 0                     # 安装数


@app.post("/suppliers/{supplier_id}/link_mcp")
def link_supplier_mcp(supplier_id: str, req: LinkMcpRequest):
    """工厂部署完自有 MCP Server 后，回写 endpoint 并激活实时数据流。

    这是打通"混合架构 v2.0"的关键端点：
    - 工厂部署 supplier_mcp_template 后调用此端点
    - 中央库写入 skill_mcp_endpoint 并置 agent_skill_installed=1
    - 之后 find_china_supplier 返回 has_skill=true，联系方式自动公开
    - get_pricing / get_inventory 走实时 MCP 而非缓存
    """
    mcp_endpoint = (req.mcp_endpoint or "").strip().rstrip("/")
    if not mcp_endpoint or not mcp_endpoint.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="mcp_endpoint 必须是 http(s):// 开头的 URL")

    with get_db() as conn:
        # v5.2.4: 统一身份校验
        _verify_supplier_access(conn, supplier_id, req.access_token)

        # 3. 可选：探测 MCP endpoint 可达性（best-effort，失败不阻塞）
        mcp_reachable = False
        probe_error = ""
        try:
            import urllib.request
            r = urllib.request.urlopen(mcp_endpoint, timeout=5)
            mcp_reachable = r.status == 200
        except Exception as e:
            probe_error = str(e)[:100]

        # 4. 写入 endpoint + 激活 skill
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("""
            UPDATE suppliers SET
                skill_mcp_endpoint = ?,
                agent_skill_installed = 1,
                skill_platforms = ?,
                skill_installs = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            mcp_endpoint,
            json.dumps(req.skill_platforms, ensure_ascii=False),
            req.skill_installs,
            now_iso,
            supplier_id,
        ))
        # v5.2: 装上 Skill 后重算 trust_score（compliance +40）
        _recalculate_trust_score(conn, supplier_id)
        conn.commit()

        # 5. 失效缓存，让 find_china_supplier 立即返回 has_skill=true
        _supplier_cache.invalidate("find:")

    logger.info(f"[link_mcp] supplier={supplier_id} endpoint={mcp_endpoint} reachable={mcp_reachable}")

    return {
        "status": "linked",
        "supplier_id": supplier_id,
        "mcp_endpoint": mcp_endpoint,
        "agent_skill_installed": True,
        "mcp_reachable": mcp_reachable,
        "probe_error": probe_error,
        "message": "MCP 端点已登记。海外 Agent 现在可以通过 LinkMoney 获取你的实时库存和价格。" if mcp_reachable else "MCP 端点已登记，但探测失败（不影响登记，稍后中间层会自动重试）。",
        "next_step": "你的工厂现在 data_source=live，联系方式已对海外采购方公开。",
    }


@app.post("/suppliers/{supplier_id}/unlink_mcp")
def unlink_supplier_mcp(supplier_id: str, req: LinkMcpRequest):
    """取消 MCP 端点登记（回退到缓存模式）"""
    with get_db() as conn:
        # v5.2.4: 统一身份校验
        _verify_supplier_access(conn, supplier_id, req.access_token)

        conn.execute("""
            UPDATE suppliers SET
                skill_mcp_endpoint = '',
                agent_skill_installed = 0,
                updated_at = ?
            WHERE id = ?
        """, (datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"), supplier_id))
        # v5.2: 取消 Skill 后重算 trust_score（compliance -40）
        _recalculate_trust_score(conn, supplier_id)
        conn.commit()
        _supplier_cache.invalidate("find:")

    return {"status": "unlinked", "supplier_id": supplier_id, "message": "MCP 端点已取消，回退到缓存模式"}


# ===== v3.3: 中心化托管 — 多租户 MCP 路由 =====
# 每个工厂自动获得一个虚拟 MCP endpoint: /mcp/supplier/{supplier_id}/*
# 数据直接读 SQLite，工厂无需自己部署任何服务器

@app.get("/mcp/supplier/{supplier_id}/manifest.json")
def supplier_mcp_manifest(supplier_id: str):
    """工厂专属 MCP 清单（兼容 ChatGPT ai-plugin.json / MCP 发现格式）"""
    with get_db() as conn:
        s = conn.execute("SELECT id, name_zh, name_en, category, agent_skill_installed, skill_mcp_endpoint FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not s:
            raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
        if not s["agent_skill_installed"]:
            raise HTTPException(status_code=403, detail="该供应商尚未激活 MCP")
        p_count = conn.execute("SELECT COUNT(*) as c FROM products WHERE supplier_id = ?", (supplier_id,)).fetchone()["c"]

    base = f"http://118.196.34.217:8765/mcp/supplier/{supplier_id}"
    return {
        "schema_version": "v1",
        "name": s["name_zh"],
        "name_en": s["name_en"],
        "supplier_id": supplier_id,
        "category": s["category"],
        "description": f"{s['name_zh']} — 中国{s['category']}品类供应商，提供实时产品/价格/库存查询",
        "product_count": p_count,
        "tools": [
            {"name": "get_products", "description": "获取该工厂的产品目录", "endpoint": f"{base}/products"},
            {"name": "get_pricing", "description": "查阶梯报价", "endpoint": f"{base}/pricing"},
            {"name": "get_inventory", "description": "查实时库存", "endpoint": f"{base}/inventory"},
            {"name": "submit_quote", "description": "提交询价单", "endpoint": f"{base}/quote"},
        ],
        "_meta": {"source": "linkmoney_hosted", "data_source_type": "hosted"},
    }


@app.get("/mcp/supplier/{supplier_id}/.well-known/linkmoney-skill.json")
def supplier_mcp_well_known(supplier_id: str):
    """自动发现端点（兼容 ChatGPT ai-plugin.json）"""
    return supplier_mcp_manifest(supplier_id)


@app.get("/mcp/supplier/{supplier_id}/products")
def supplier_mcp_products(supplier_id: str, limit: int = 50, offset: int = 0):
    """该工厂的产品目录"""
    with get_db() as conn:
        s = conn.execute("SELECT id, name_zh, agent_skill_installed FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not s:
            raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
        rows = conn.execute(
            "SELECT * FROM products WHERE supplier_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (supplier_id, limit, offset),
        ).fetchall()

    products = [_row_to_product(r) for r in rows]
    return {
        "supplier_id": supplier_id,
        "supplier_name": s["name_zh"],
        "count": len(products),
        "products": products,
        "_meta": {"source": "linkmoney_hosted", "is_live": True},
    }


@app.get("/mcp/supplier/{supplier_id}/pricing")
def supplier_mcp_pricing(supplier_id: str, sku: str, quantity: int = 1000):
    """阶梯报价 — 直接读 SQLite pricing_tiers"""
    with get_db() as conn:
        s = conn.execute("SELECT id, name_zh, moq FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not s:
            raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
        p = conn.execute("SELECT * FROM products WHERE supplier_id = ? AND sku = ?", (supplier_id, sku)).fetchone()

    if not p:
        raise HTTPException(status_code=404, detail=f"SKU {sku} 不存在")

    product = _row_to_product(p)
    tiers = product.get("pricing_tiers", [])
    best_tier = None
    for tier in tiers:
        min_q = tier.get("min_qty", 0)
        max_q = tier.get("max_qty", float("inf")) or float("inf")
        if min_q <= quantity <= max_q:
            best_tier = tier
            break
    if not best_tier:
        best_tier = tiers[0] if tiers else None

    unit_price = best_tier.get("unit_price_usd") if best_tier else None
    return {
        "supplier_id": supplier_id,
        "supplier_name": s["name_zh"],
        "sku": sku,
        "product_name": product["name_zh"],
        "requested_quantity": quantity,
        "pricing_tiers": tiers,
        "matched_tier": best_tier,
        "unit_price_usd": unit_price,
        "total_price_usd": round(unit_price * quantity, 2) if unit_price else None,
        "moq": product.get("moq", s["moq"]),
        "trade_terms": product.get("trade_terms", "FOB"),
        "port": product.get("port", ""),
        "_meta": {"source": "linkmoney_hosted", "is_live": True},
    }


@app.get("/mcp/supplier/{supplier_id}/inventory")
def supplier_mcp_inventory(supplier_id: str, sku: str):
    """实时库存 — 直接读 SQLite"""
    with get_db() as conn:
        s = conn.execute("SELECT id, name_zh FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not s:
            raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
        p = conn.execute("SELECT * FROM products WHERE supplier_id = ? AND sku = ?", (supplier_id, sku)).fetchone()

    if not p:
        raise HTTPException(status_code=404, detail=f"SKU {sku} 不存在")

    product = _row_to_product(p)
    return {
        "supplier_id": supplier_id,
        "supplier_name": s["name_zh"],
        "sku": sku,
        "product_name": product["name_zh"],
        "inventory_status": product["inventory"]["status"],
        "quantity": product["inventory"]["quantity"],
        "unit": product["inventory"]["unit"],
        "lead_time_days": product.get("inventory_lead_time_days", 0),
        "supply_ability_monthly": product.get("supply_ability_monthly", 0),
        "_meta": {"source": "linkmoney_hosted", "is_live": True},
    }


class SupplierQuoteRequest(BaseModel):
    """海外采购方通过工厂专属 MCP 提交询价"""
    buyer_id: str = ""
    buyer_email: str = ""
    quantity: int = 1000
    target_price_usd: float = 0
    message: str = ""
    delivery_deadline: str = ""


@app.post("/mcp/supplier/{supplier_id}/quote")
def supplier_mcp_submit_quote(supplier_id: str, req: SupplierQuoteRequest):
    """接收 RFQ，写入 rfqs 表"""
    with get_db() as conn:
        s = conn.execute("SELECT id, name_zh, email FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not s:
            raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")

        rfq_id = f"rfq-{supplier_id}-{int(time.time())}"
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("""
            INSERT INTO rfqs(id, supplier_id, buyer_id, sku, quantity, target_price_usd,
                           contact_email, status, created_at, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (
            rfq_id, supplier_id, req.buyer_id or "anonymous", "",
            req.quantity, req.target_price_usd,
            req.buyer_email, now_iso, req.message,
        ))
        conn.commit()

    return {
        "status": "submitted",
        "rfq_id": rfq_id,
        "supplier_id": supplier_id,
        "supplier_name": s["name_zh"],
        "message": f"询价已提交给 {s['name_zh']}，工厂会通过邮箱 {s['email']} 收到通知",
    }


# ===== v3.3: 工厂产品管理 API（对话式，无需 Web UI）=====

class ProductItem(BaseModel):
    """单个产品（增删改用）"""
    sku: str
    name_zh: str = ""
    name_en: str = ""
    material: str = ""
    grade: str = ""
    specs: dict = {}
    pricing_tiers: list = []
    moq: int = 1
    trade_terms: str = "FOB"
    port: str = ""
    price_currency: str = "USD"
    price_unit: str = "pc"
    inventory_status: str = "in_stock"
    inventory_quantity: int = 0
    inventory_unit: str = "pc"
    inventory_lead_time_days: int = 7
    hs_code: str = ""
    payment_terms: str = ""
    sample_available: int = 0
    customized: int = 0
    certifications: list = []
    packaging_details: str = ""
    supply_ability_monthly: int = 0
    description: str = ""
    description_en: str = ""
    images: list = []


class UpdateProductsRequest(BaseModel):
    """批量增删改产品"""
    access_token: str = ""   # v5.2.4: 工厂身份凭证（替代 verification_token）
    verification_token: str = ""  # 向后兼容（已弃用，access_token 优先）
    upsert: list = []   # 新增或更新（按 supplier_id + sku 去重）
    delete_skus: list = []  # 要删除的 SKU 列表


@app.post("/suppliers/{supplier_id}/products")
def update_supplier_products(supplier_id: str, req: UpdateProductsRequest):
    """工厂通过 Agent 对话增删改产品（托管模式核心管理端点）

    使用场景：
    - 工厂老板说"帮我添加一个 M10 螺栓产品，单价 0.5 美元"
    - Agent 调用此端点，传入 upsert 列表
    - 产品立即生效，海外 Agent 可查询
    """
    with get_db() as conn:
        # v5.2.4: 统一身份校验 — supplier_id + access_token 绑定
        _verify_supplier_access(conn, supplier_id, req.access_token)

        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        upserted = 0
        deleted = 0

        # 3. upsert 产品
        for p in req.upsert:
            # 兼容 dict 和 ProductItem 对象
            get = (lambda k: p.get(k, "") if isinstance(p, dict) else getattr(p, k, ""))
            conn.execute("""
                INSERT OR REPLACE INTO products(
                    supplier_id, sku, name_zh, name_en, category, material, grade,
                    specs, pricing_tiers, moq, trade_terms, port,
                    price_currency, price_type, price_unit,
                    inventory_status, inventory_quantity, inventory_unit, inventory_lead_time_days,
                    hs_code, payment_terms, sample_available, customized,
                    certifications, packaging_details, supply_ability_monthly,
                    description, description_en, images,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                supplier_id, get("sku"), get("name_zh"), get("name_en"),
                "", get("material"), get("grade"),
                json.dumps(get("specs") or {}, ensure_ascii=False),
                json.dumps(get("pricing_tiers") or [], ensure_ascii=False),
                get("moq") or 1, get("trade_terms") or "FOB", get("port") or "",
                get("price_currency") or "USD", get("trade_terms") or "FOB", get("price_unit") or "pc",
                get("inventory_status") or "in_stock", get("inventory_quantity") or 0, get("inventory_unit") or "pc", get("inventory_lead_time_days") or 7,
                get("hs_code") or "", get("payment_terms") or "", get("sample_available") or 0, get("customized") or 0,
                json.dumps(get("certifications") or [], ensure_ascii=False),
                get("packaging_details") or "", get("supply_ability_monthly") or 0,
                get("description") or "", get("description_en") or "",
                json.dumps(get("images") or [], ensure_ascii=False),
                "active", now_iso, now_iso,
            ))
            upserted += 1

        # 4. 删除产品
        for sku in req.delete_skus:
            conn.execute("DELETE FROM products WHERE supplier_id = ? AND sku = ?", (supplier_id, sku))
            deleted += 1

        conn.commit()
        _supplier_cache.invalidate("find:")

    return {
        "status": "updated",
        "supplier_id": supplier_id,
        "upserted": upserted,
        "deleted": deleted,
        "message": f"产品已更新：新增/修改 {upserted} 个，删除 {deleted} 个。海外 Agent 可立即查询。",
    }


@app.post("/suppliers/{supplier_id}/upload_csv")
async def upload_products_csv(supplier_id: str, request: Request):
    """CSV 批量导入产品（工厂通过 Agent 上传 Excel 导出的 CSV）

    CSV 列（顺序无关，按表头匹配）：
    sku, name_zh, name_en, material, grade, moq, unit_price_usd,
    inventory_quantity, trade_terms, port, hs_code, payment_terms

    鉴权：请求头 X-Access-Token 或查询参数 access_token（v5.2.4 起）
    """
    # v5.2.4: 鉴权 — supplier_id + access_token 绑定
    access_token = request.headers.get("X-Access-Token", "") or request.query_params.get("access_token", "")
    with get_db() as conn:
        s = _verify_supplier_access(conn, supplier_id, access_token)
        supplier_category = s["category"]

    # 读取 CSV 内容
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="请求体为空，请上传 CSV 内容")

    # 尝试 UTF-8 和 GBK 解码（兼容中文 Excel）
    csv_text = None
    for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
        try:
            csv_text = body.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if not csv_text:
        raise HTTPException(status_code=400, detail="CSV 解码失败，请用 UTF-8 编码")

    import csv as csv_module
    import io
    reader = csv_module.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV 无数据行")

    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    imported = 0
    errors = []
    with get_db() as conn:
        for i, row in enumerate(rows, start=2):  # 行号从 2 开始（1 是表头）
            sku = (row.get("sku") or row.get("SKU") or "").strip()
            if not sku:
                errors.append(f"第 {i} 行：sku 为空，跳过")
                continue
            name_zh = (row.get("name_zh") or row.get("产品名") or sku).strip()
            name_en = (row.get("name_en") or "").strip()
            material = (row.get("material") or "").strip()
            grade = (row.get("grade") or "").strip()
            moq = int(row.get("moq") or 1)
            unit_price = float(row.get("unit_price_usd") or row.get("price") or 0)
            inv_qty = int(row.get("inventory_quantity") or row.get("stock") or 0)
            trade_terms = (row.get("trade_terms") or "FOB").strip()
            port = (row.get("port") or "Ningbo").strip()
            hs_code = (row.get("hs_code") or "").strip()
            payment_terms = (row.get("payment_terms") or "").strip()

            # 构造阶梯价
            pricing_tiers = [
                {"min_qty": 1, "max_qty": 999, "unit_price_usd": unit_price},
                {"min_qty": 1000, "max_qty": 9999, "unit_price_usd": round(unit_price * 0.85, 3)},
                {"min_qty": 10000, "max_qty": None, "unit_price_usd": round(unit_price * 0.72, 3)},
            ] if unit_price > 0 else []

            try:
                conn.execute("""
                    INSERT OR REPLACE INTO products(
                        supplier_id, sku, name_zh, name_en, category, material, grade,
                        specs, pricing_tiers, moq, trade_terms, port,
                        price_currency, price_type, price_unit,
                        inventory_status, inventory_quantity, inventory_unit, inventory_lead_time_days,
                        hs_code, payment_terms, sample_available, customized,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    supplier_id, sku, name_zh, name_en, supplier_category,
                    material, grade, "{}",
                    json.dumps(pricing_tiers, ensure_ascii=False),
                    moq, trade_terms, port,
                    "USD", trade_terms, "pc",
                    "in_stock" if inv_qty > 0 else "unknown", inv_qty, "pc", 7,
                    hs_code, payment_terms, 0, 0,
                    "active", now_iso, now_iso,
                ))
                imported += 1
            except Exception as e:
                errors.append(f"第 {i} 行 {sku}: {e}")

        conn.commit()
        _supplier_cache.invalidate("find:")

    return {
        "status": "imported",
        "supplier_id": supplier_id,
        "imported": imported,
        "errors": errors[:10],
        "error_count": len(errors),
        "message": f"CSV 导入完成：成功 {imported} 个，失败 {len(errors)} 个",
    }


# ===== v3.2: 数据库管理端点 =====

@app.post("/admin/reload")
def admin_reload_db(x_api_key: str = Header(None, alias="X-API-Key")):
    """强制重新从 database.json 导入数据到 SQLite（管理端点，需 API key）。

    使用场景：
    - database.json 更新后（新增工厂/产品/价格修改），触发此端点同步到 SQLite
    - 不需要删除 DB 文件，不丢失运行时数据（rfqs/quotes/verifications 等）
    - 使用 INSERT OR REPLACE，幂等

    鉴权：需要有效的 API key（LINKMONEY_API_KEYS 之一）
    """
    # 鉴权
    if not _API_KEYS:
        raise HTTPException(status_code=503, detail="服务端未配置 API keys，无法鉴权")
    if x_api_key not in _API_KEYS:
        raise HTTPException(status_code=403, detail="无效的 API key")

    # 记录导入前的状态
    before_count = 0
    try:
        with get_db() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM suppliers").fetchone()
            before_count = row["cnt"] if row else 0
    except Exception:
        pass

    # 强制重新导入
    try:
        init_db(force=True)
    except Exception as e:
        logger.error(f"/admin/reload 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重新导入失败: {e}")

    # 记录导入后的状态
    after_count = 0
    product_count = 0
    try:
        with get_db() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM suppliers").fetchone()
            after_count = row["cnt"] if row else 0
            row = conn.execute("SELECT COUNT(*) as cnt FROM products").fetchone()
            product_count = row["cnt"] if row else 0
    except Exception:
        pass

    # 失效所有缓存
    _supplier_cache.invalidate("find:")

    json_ver, json_updated = _get_json_version()
    logger.info(f"[admin/reload] 重新导入完成: suppliers {before_count} -> {after_count}, products={product_count}")

    return {
        "status": "reloaded",
        "json_version": json_ver,
        "json_last_updated": json_updated,
        "suppliers_before": before_count,
        "suppliers_after": after_count,
        "products_count": product_count,
        "cache_invalidated": True,
        "message": f"数据库已重新导入：{after_count} 家工厂，{product_count} 个产品",
    }


@app.get("/admin/db_status")
def admin_db_status(x_api_key: str = Header(None, alias="X-API-Key")):
    """查看数据库状态（管理端点，需 API key）"""
    if not _API_KEYS:
        raise HTTPException(status_code=503, detail="服务端未配置 API keys")
    if x_api_key not in _API_KEYS:
        raise HTTPException(status_code=403, detail="无效的 API key")

    json_ver, json_updated = _get_json_version()
    db_ver, db_updated = _get_db_json_version()

    with get_db() as conn:
        s_count = conn.execute("SELECT COUNT(*) as cnt FROM suppliers").fetchone()["cnt"]
        p_count = conn.execute("SELECT COUNT(*) as cnt FROM products").fetchone()["cnt"]
        b_count = conn.execute("SELECT COUNT(*) as cnt FROM overseas_buyers").fetchone()["cnt"]
        r_count = conn.execute("SELECT COUNT(*) as cnt FROM rfqs").fetchone()["cnt"]
        skill_count = conn.execute("SELECT COUNT(*) as cnt FROM suppliers WHERE agent_skill_installed = 1").fetchone()["cnt"]

    needs_reload = (json_ver != db_ver) or (json_updated != db_updated)

    return {
        "json": {"version": json_ver, "last_updated": json_updated, "path": str(JSON_FILE)},
        "db": {"version": db_ver, "last_updated": db_updated, "path": DB_PATH},
        "counts": {
            "suppliers": s_count,
            "products": p_count,
            "buyers": b_count,
            "rfqs": r_count,
            "suppliers_with_skill": skill_count,
        },
        "needs_reload": needs_reload,
        "message": "JSON 版本与 DB 不一致，建议调用 /admin/reload" if needs_reload else "数据库已是最新",
    }


@app.get("/trust_score/{target_type}/{target_id}")
def get_trust_score(target_type: str, target_id: str):
    """查看工厂/买家的信用评分（公开）"""
    with get_db() as conn:
        if target_type == "supplier":
            row = conn.execute(
                "SELECT id, name_zh, trust_score, trust_level, email_verified, phone_verified, license_verified, review_count, review_avg, gold_badge, year_established, employees, annual_revenue_usd, export_ratio FROM suppliers WHERE id = ?",
                (target_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Supplier not found")

            evals = conn.execute(
                "SELECT * FROM trust_evaluations WHERE target_id = ? AND target_type = 'supplier' ORDER BY created_at DESC LIMIT 1",
                (target_id,),
            ).fetchone()
            dimensions = json.loads(evals["dimensions"]) if evals and evals["dimensions"] else {}

            return {
                "target_type": "supplier",
                "target_id": row["id"],
                "name": row["name_zh"],
                "trust_score": row["trust_score"],
                "trust_level": row["trust_level"],
                "gold_badge": bool(row["gold_badge"]),
                "verification": {
                    "email": bool(row["email_verified"]),
                    "phone": bool(row["phone_verified"]),
                    "license": bool(row["license_verified"]),
                },
                "review": {
                    "count": row["review_count"],
                    "avg": row["review_avg"],
                },
                "dimensions": dimensions,
                "raw_indicators": {
                    "year_established": row["year_established"],
                    "employees": row["employees"],
                    "annual_revenue_usd": row["annual_revenue_usd"],
                    "export_ratio": row["export_ratio"],
                },
            }
        else:
            raise HTTPException(status_code=400, detail="Only supplier trust score supported currently")


@app.get("/trust_score/{supplier_id}")
def get_trust_score_short(supplier_id: str):
    """trust_score 快捷路由 — 自动识别为 supplier"""
    return get_trust_score("supplier", supplier_id)


# ===== v2.2 需求广场 =====

class PostRequirementRequest(BaseModel):
    buyer_id: str
    category: str
    sku: str = ""
    spec: str = ""
    quantity: int = 1
    target_price_usd: float = 0
    destination_port: str = ""
    incoterms: str = "FOB"
    delivery_deadline: str = ""
    public: bool = True
    expires_days: int = 30


@app.post("/post_requirement")
def post_requirement(req: PostRequirementRequest):
    """
    海外买家发布公开采购需求（v2.2 需求广场）。
    注意：买家邮箱永不暴露给工厂，平台撮合。
    """
    with get_db() as conn:
        b_row = conn.execute("SELECT * FROM overseas_buyers WHERE id = ?", (req.buyer_id,)).fetchone()
        if not b_row:
            raise HTTPException(status_code=404, detail=f"Buyer '{req.buyer_id}' not found")

    req_id = f"req-{datetime.now().strftime('%Y%m%d')}-{_gen_token(4)}"
    expires_at = (datetime.now() + timedelta(days=req.expires_days)).isoformat() + "Z"

    with get_db() as conn:
        conn.execute("""
            INSERT INTO requirements(id, buyer_id, category, sku, spec, quantity, target_price_usd, destination_port, incoterms, delivery_deadline, public, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
        """, (
            req_id, req.buyer_id, req.category, req.sku, req.spec, req.quantity,
            req.target_price_usd, req.destination_port, req.incoterms, req.delivery_deadline,
            1 if req.public else 0,
            datetime.now().isoformat() + "Z", expires_at,
        ))
        conn.commit()

    return {
        "requirement_id": req_id,
        "status": "open",
        "public_url": f"/browse_requirements?category={req.category}",
        "expires_at": expires_at,
        "estimated_bids": "5-15 家工厂将在 24 小时内报价",
        "next_step": "工厂会通过 LinkMoney 看到您的需求，但不会直接拿到您的邮箱。",
    }


@app.get("/browse_requirements")
@limiter.limit("30/minute")
def browse_requirements(
    request: Request,
    category: str = Query("", description="按品类筛选"),
    min_quantity: int = Query(0, description="最小数量"),
    max_price: float = Query(0, description="目标最高价"),
    limit: int = Query(20, description="返回数量"),
):
    """
    工厂浏览公开需求（v2.2 需求广场）。
    注意：买家邮箱/公司/联系人永不暴露，只返回公开字段。
    """
    with get_db() as conn:
        query = "SELECT * FROM requirements WHERE public = 1 AND status = 'open' AND expires_at > ?"
        params = [datetime.now().isoformat() + "Z"]
        if category:
            query += " AND category = ?"
            params.append(category)
        if min_quantity > 0:
            query += " AND quantity >= ?"
            params.append(min_quantity)
        if max_price > 0:
            query += " AND (target_price_usd = 0 OR target_price_usd <= ?)"
            params.append(max_price)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

    # 关键：买家信息脱敏
    public_requirements = []
    for r in rows:
        # 只暴露国家，不暴露公司名/邮箱/联系人
        with get_db() as conn:
            b_row = conn.execute(
                "SELECT country, industry FROM overseas_buyers WHERE id = ?", (r["buyer_id"],)
            ).fetchone()

        public_requirements.append({
            "requirement_id": r["id"],
            "buyer_region": b_row["country"] if b_row else "unknown",
            "buyer_industry": b_row["industry"] if b_row else "",
            "category": r["category"],
            "sku": r["sku"],
            "spec": r["spec"],
            "quantity": r["quantity"],
            "target_price_usd": r["target_price_usd"],
            "destination_port": r["destination_port"],
            "incoterms": r["incoterms"],
            "delivery_deadline": r["delivery_deadline"],
            "bid_count": r["bid_count"],
            "created_at": r["created_at"],
            "expires_at": r["expires_at"],
            "masked_buyer_id": hashlib.md5(r["buyer_id"].encode()).hexdigest()[:8],  # 工厂看到的只是匿名 ID
        })

    return {
        "total_open": len(public_requirements),
        "requirements": public_requirements,
        "note": "买家邮箱/公司名/联系人已脱敏。报价后由 LinkMoney 撮合双方。",
    }


class BidOnRequirementRequest(BaseModel):
    requirement_id: str
    supplier_id: str
    access_token: str = ""  # v5.2.4: 工厂身份凭证
    unit_price_usd: float
    lead_time_days: int = 0
    moq: int = 0
    notes: str = ""


@app.post("/bid_on_requirement")
@limiter.limit("10/minute")
def bid_on_requirement(req: BidOnRequirementRequest, request: Request):
    """
    工厂对公开需求报价（v2.2 需求广场）。
    关键：买家邮箱不直接暴露给工厂，LinkMoney 撮合。
    v5.2.4: 需携带 access_token 校验身份
    """
    # v5.2.4: 统一身份校验
    with get_db() as conn:
        s_row = _verify_supplier_access(conn, req.supplier_id, req.access_token)
    if not s_row["email_verified"]:
        raise HTTPException(status_code=403, detail="请先验证邮箱后再报价")

    with get_db() as conn:
        r_row = conn.execute("SELECT * FROM requirements WHERE id = ?", (req.requirement_id,)).fetchone()
        if not r_row:
            raise HTTPException(status_code=404, detail="需求不存在")
        if r_row["status"] != "open":
            raise HTTPException(status_code=400, detail=f"需求状态: {r_row['status']}")

    bid_id = f"bid-{datetime.now().strftime('%Y%m%d')}-{_gen_token(4)}"
    with get_db() as conn:
        conn.execute("""
            INSERT INTO bids(id, requirement_id, supplier_id, unit_price_usd, lead_time_days, moq, notes, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted', ?)
        """, (
            bid_id, req.requirement_id, req.supplier_id,
            req.unit_price_usd, req.lead_time_days, req.moq, req.notes,
            datetime.now().isoformat() + "Z",
        ))
        conn.execute("UPDATE requirements SET bid_count = bid_count + 1 WHERE id = ?", (req.requirement_id,))
        conn.commit()

    # 异步通知买家（走 LinkMoney 撮合通道，不暴露工厂邮箱）
    try:
        with get_db() as conn:
            b_row = conn.execute("SELECT * FROM overseas_buyers WHERE id = ?", (r_row["buyer_id"],)).fetchone()
        if b_row:
            mailer.notify_buyer_quote_received(
                buyer=dict(b_row),
                supplier={"name_zh": s_row["name_zh"], "id": req.supplier_id},
                rfq={"id": req.requirement_id, "sku": r_row["sku"]},
                quote={
                    "unit_price_usd": req.unit_price_usd,
                    "lead_time_days": req.lead_time_days,
                    "status": "bid_submitted",
                },
            )
    except Exception:
        pass

    return {
        "bid_id": bid_id,
        "requirement_id": req.requirement_id,
        "supplier_id": req.supplier_id,
        "status": "submitted",
        "next_step": f"买家将在 24 小时内查看报价。如中标，LinkMoney 会把您的联系方式释放给买家。",
    }


# ===== v2.3 主动外联（工厂主动联系买家） =====

class OutreachRequest(BaseModel):
    supplier_id: str
    target_buyer_id: str
    message: str
    value_proposition: str = ""
    samples_offered: bool = False


@app.post("/outreach_buyer")
@limiter.limit("5/day")
def outreach_buyer(req: OutreachRequest, request: Request):
    """
    工厂主动外联买家（v2.3）。
    严格门控：
    - 工厂必须已验证邮箱+电话
    - 工厂评分 >= 60
    - 每月最多 10 条外联
    - 走 LinkMoney 官方身份发送（不是工厂邮箱）
    """
    with get_db() as conn:
        s_row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (req.supplier_id,)).fetchone()
        if not s_row:
            raise HTTPException(status_code=404, detail="供应商不存在")
        if not s_row["email_verified"]:
            raise HTTPException(status_code=403, detail="请先验证邮箱（POST /verify_email）")
        if not s_row["phone_verified"]:
            raise HTTPException(status_code=403, detail="请先验证电话")
        if s_row["trust_score"] < 60:
            raise HTTPException(status_code=403, detail=f"信任评分 {s_row['trust_score']} 不足 60，暂不能主动外联")
        if s_row["outreach_used_this_month"] >= 10:
            raise HTTPException(status_code=429, detail="本月外联配额已用完（10条）")

        b_row = conn.execute("SELECT * FROM overseas_buyers WHERE id = ?", (req.target_buyer_id,)).fetchone()
        if not b_row:
            raise HTTPException(status_code=404, detail="买家不存在")

    with get_db() as conn:
        conn.execute("""
            INSERT INTO outreach(supplier_id, target_buyer_id, message, value_proposition, samples_offered, status)
            VALUES (?, ?, ?, ?, ?, 'sent')
        """, (req.supplier_id, req.target_buyer_id, req.message, req.value_proposition, 1 if req.samples_offered else 0))
        conn.execute(
            "UPDATE suppliers SET outreach_used_this_month = outreach_used_this_month + 1 WHERE id = ?",
            (req.supplier_id,),
        )
        conn.commit()

    return {
        "status": "queued",
        "supplier_id": req.supplier_id,
        "target_buyer_id": req.target_buyer_id,
        "delivery": "通过 LinkMoney 官方邮箱发送，工厂邮箱不暴露",
        "quota_remaining": 10 - s_row["outreach_used_this_month"] - 1,
        "next_step": "买家收到后可在 LinkMoney 平台回复。打开率/回复率可在 /stats 查询。",
    }


# ===== v3.0 互评系统 =====

class LeaveReviewRequest(BaseModel):
    rfq_id: str = ""
    reviewer_id: str
    reviewer_type: str  # "buyer" | "supplier"
    target_id: str
    target_type: str  # "supplier" | "buyer"
    rating: int  # 1-5
    dimension_quality: int = 0
    dimension_speed: int = 0
    dimension_communication: int = 0
    dimension_price: int = 0
    dimension_payment: int = 0
    comment: str = ""


@app.post("/leave_review")
def leave_review(req: LeaveReviewRequest):
    """
    交易完成后买卖双方互评（v3.0）。
    评分进入 find_china_supplier 排序权重。
    """
    if not (1 <= req.rating <= 5):
        raise HTTPException(status_code=400, detail="评分必须在 1-5 之间")

    with get_db() as conn:
        conn.execute("""
            INSERT INTO reviews(rfq_id, reviewer_id, reviewer_type, target_id, target_type, rating, dimension_quality, dimension_speed, dimension_communication, dimension_price, dimension_payment, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            req.rfq_id, req.reviewer_id, req.reviewer_type,
            req.target_id, req.target_type, req.rating,
            req.dimension_quality, req.dimension_speed,
            req.dimension_communication, req.dimension_price, req.dimension_payment,
            req.comment,
        ))

        # 重新计算目标实体的平均分
        agg = conn.execute("""
            SELECT AVG(rating) as avg_rating, COUNT(*) as cnt FROM reviews
            WHERE target_id = ? AND target_type = ?
        """, (req.target_id, req.target_type)).fetchone()
        avg = round(agg["avg_rating"], 2)
        cnt = agg["cnt"]

        if req.target_type == "supplier":
            conn.execute(
                "UPDATE suppliers SET review_avg = ?, review_count = ? WHERE id = ?",
                (avg, cnt, req.target_id),
            )
            # v5.2: 收到评价后重算 trust_score（quality 维度会叠加 review 加权）
            # 必须在 gold_badge 判定之前，否则金标检查用的还是旧 trust_score
            _recalculate_trust_score(conn, req.target_id)
            # 评分>=4.5 且 评价数>=5 且 trust_score>=80 -> 自动金标
            s_row_check = conn.execute("SELECT trust_score FROM suppliers WHERE id = ?", (req.target_id,)).fetchone()
            if avg >= 4.5 and cnt >= 5 and s_row_check and s_row_check["trust_score"] >= 80:
                conn.execute("UPDATE suppliers SET gold_badge = 1, trust_level = 'gold' WHERE id = ?", (req.target_id,))
        else:
            conn.execute(
                "UPDATE overseas_buyers SET trust_score = ? WHERE id = ?",
                (avg, req.target_id),
            )
        # v5.2: 积累学习层 — 评价是 RFQ 闭环最后一步，触发权重学习
        # 安全约束：24 小时冷却 + 最小样本量 10 + 单次调整 ≤ 3 + 边界保护
        _learn_match_weights(conn)
        conn.commit()

    return {
        "status": "recorded",
        "new_avg_rating": avg,
        "review_count": cnt,
        "next_step": "评分已生效，将进入 find_china_supplier 排序权重",
    }


# ===== v3.0 中间 Agent 维护层 =====

@app.get("/health")
def health_check():
    """简单健康检查端点（供 Docker healthcheck / 外部监控使用）"""
    return {"status": "ok", "service": "linkmoney-api", "version": "5.2.1"}


# ===== 轻量访问统计 =====

import threading as _threading
from collections import defaultdict as _defaultdict

_VISIT_STATS = _defaultdict(int)
_VISIT_LOCK = _threading.Lock()
_VISIT_START = time.time()


@app.post("/track")
async def track_visit(request: Request):
    """轻量访问统计端点（无需第三方服务）"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    page = body.get("page", "unknown")
    lang = body.get("lang", "unknown")
    key = f"{page}:{lang}"
    with _VISIT_LOCK:
        _VISIT_STATS[key] += 1
    return {"status": "ok"}


@app.get("/stats/visits")
def visit_stats():
    """访问统计数据"""
    with _VISIT_LOCK:
        stats = dict(_VISIT_STATS)
    uptime_hours = (time.time() - _VISIT_START) / 3600
    return {
        "uptime_hours": round(uptime_hours, 1),
        "total_visits": sum(stats.values()),
        "breakdown": stats,
    }


@app.get("/agent/status")
def agent_status():
    """中间 Agent 元信息 + 当前健康度概览。"""
    return middle_agent_status()


@app.get("/agent/health")
def agent_health(force: bool = False):
    """中间 Agent 健康检查报告：所有厂家 MCP 端点。"""
    return middle_agent_health(force_refresh=force)


@app.get("/agent/routing")
def agent_routing(
    category: str = Query(..., description="品类，如 fastener / packaging / electronic"),
    quantity: int = Query(0, description="RFQ 数量，用于 MOQ 过滤加分"),
    target_price_usd: float = Query(0.0, description="目标单价（USD），用于 lead_time 加分"),
    need_live_data: bool = Query(True, description="是否需要实时数据（offline 厂家会被过滤）"),
    limit: int = Query(5, ge=1, le=20),
):
    """中间 Agent 路由推荐：综合信任分 + 评价 + 健康度，给出 RFQ 该走哪家。"""
    return middle_agent_routing(category, quantity, target_price_usd, need_live_data, limit)


@app.get("/agent/alerts")
def agent_alerts(limit: int = 20, severity: Optional[str] = None):
    """中间 Agent 告警列表。"""
    return middle_agent_alerts(limit=limit, severity=severity)


@app.get("/agent/maintenance")
def agent_maintenance(limit: int = 30):
    """中间 Agent 维护日志。"""
    return middle_agent_maintenance(limit=limit)


@app.get("/agent/optimize")
def agent_optimize():
    """触发一次自我优化分析。"""
    return middle_agent_optimize()


class AgentMaintainRequest(BaseModel):
    """保留 Pydantic 模型（API 调用方传 JSON body 时用），但路由优先接受 Query params。"""
    action: str  # health_check / optimize / clear_alerts / ping_supplier / reroute_requirement
    target: str = ""
    notes: str = ""


@app.post("/agent/maintain")
def agent_maintain(
    request: Request,
    action: str = "",
    target: str = "",
    notes: str = "",
):
    """
    手动触发维护任务。同时支持两种调用方式：
      1. POST /agent/maintain?action=optimize
      2. POST /agent/maintain  body={"action":"optimize","target":"","notes":""}
    """
    # 优先用 query params；如果都没传，尝试读 JSON body
    if not action:
        try:
            body = AgentMaintainRequest(**(request.json() or {}))
            action = body.action
            target = target or body.target
            notes = notes or body.notes
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="action 参数必传（query 或 JSON body）")
    try:
        return middle_agent_maintain(action, target, notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===== 模块级初始化（uvicorn reload 子进程也会执行） =====

_load_api_keys()
init_db()

# v4.0: Agent Marketplace（延迟导入，避开循环依赖）
marketplace_router = None
init_marketplace = lambda: None
try:
    import marketplace as _marketplace
    marketplace_router = _marketplace.router
    init_marketplace = _marketplace.init_marketplace
    logger.info("✅ Agent Marketplace 模块加载成功")
except Exception as _me:
    import traceback as _tb
    logger.warning(f"⚠️ Agent Marketplace 模块加载失败: {_me}\n{_tb.format_exc()}")

# v4.0: 初始化 Agent Marketplace（公开 RFQ 市场 + 9 阶段执行 + 公正审计）
try:
    init_marketplace()
    if marketplace_router is not None:
        app.include_router(marketplace_router)
        logger.info("✅ Agent Marketplace 路由已挂载（/marketplace/*）")
except Exception as _e:  # noqa: BLE001
    logger.warning(f"Agent Marketplace 初始化失败: {_e}")

# v3.0: 启动时基线巡检一次，写入告警 + 维护日志
try:
    bootstrap_agent()
except Exception as _e:  # noqa: BLE001
    logger.warning(f"中间 Agent 启动巡检被跳过: {_e}")

# ===== 启动入口 =====

if __name__ == "__main__":
    import uvicorn

    logger.info("LinkMoney MCP Server 启动中...")
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=True)