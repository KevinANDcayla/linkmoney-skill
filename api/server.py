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

from fastapi import FastAPI, HTTPException, Query, Request
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
from llm_layer import get_llm, DeepSeekError  # DeepSeek V4 Flash/Pro

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

        conn.commit()


def init_db():
    """首次运行时从 database.json 导入数据到 SQLite，若库已存在则迁移"""
    # 一次性设置 WAL 模式（数据库级，不需要每个 connection 都设）
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

    # 即使 DB 已存在，也要确保新表（v2.1+）的迁移
    _migrate_v21()

    if os.path.exists(DB_PATH):
        logger.info("SQLite 数据库已存在，执行迁移检查")
        return

    logger.info("SQLite 数据库不存在，开始从 JSON 导入...")

    with get_db() as conn:
        c = conn.cursor()

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
                language_contact TEXT DEFAULT '[]'
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
                material TEXT DEFAULT '',
                grade TEXT DEFAULT '',
                specs TEXT NOT NULL DEFAULT '{}',
                pricing_tiers TEXT NOT NULL DEFAULT '[]',
                inventory_status TEXT DEFAULT 'unknown',
                inventory_quantity INTEGER DEFAULT 0,
                inventory_unit TEXT DEFAULT 'pc',
                inventory_lead_time_days INTEGER DEFAULT 0,
                inventory_updated_at TEXT DEFAULT '',
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
                last_active TEXT DEFAULT ''
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
                    created_at, updated_at, contact_person, email, phone, wechat, language_contact
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                s.get("email", ""),
                s.get("phone", ""),
                s.get("wechat", ""),
                json.dumps(s.get("language_contact", {}), ensure_ascii=False),
            ))

            # 导入 products
            for p in s.get("products", []):
                inv = p.get("inventory", {})
                c.execute("""
                    INSERT OR REPLACE INTO products(
                        supplier_id, sku, name_zh, name_en, category, material, grade,
                        specs, pricing_tiers, inventory_status, inventory_quantity,
                        inventory_unit, inventory_lead_time_days, inventory_updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s["id"],
                    p.get("sku", ""),
                    p.get("name_zh", ""),
                    p.get("name_en", ""),
                    p.get("category", ""),
                    p.get("material", ""),
                    p.get("grade", ""),
                    json.dumps(p.get("specs", {}), ensure_ascii=False),
                    json.dumps(p.get("pricing_tiers", []), ensure_ascii=False),
                    inv.get("status", "unknown"),
                    inv.get("quantity", 0),
                    inv.get("unit", "pc"),
                    inv.get("lead_time_days", 0),
                    inv.get("updated_at", ""),
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

        conn.commit()

    logger.info("SQLite 数据库初始化完成")


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
    for json_field in ["specs", "pricing_tiers"]:
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
    "/", "/health", "/mcp/manifest.json", "/docs", "/openapi.json", "/redoc",
    "/onboard-supplier", "/onboard-buyer", "/beta-signup", "/beta-program",
    "/verify_email", "/trust_score/supplier",  # 公开端点：验证 + 信用查询
    "/skill.md", "/.well-known/ai-plugin.json", "/.well-known/linkmoney-skill.json",  # Skill 发现端点
    # v3.0 中间 Agent：作为平台维护者，对内默认开启（可在生产环境收紧）
    "/agent/status", "/agent/health", "/agent/routing",
    "/agent/alerts", "/agent/maintenance", "/agent/optimize", "/agent/maintain",
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
for d in WEB_DIR_CANDIDATES:
    p = d / "landing.html"
    if p.exists():
        LANDING_HTML = p
        break
if LANDING_HTML is None:
    LANDING_HTML = WEB_DIR_CANDIDATES[0] / "landing.html"  # 兜底


@app.get("/", response_class=HTMLResponse)
def root():
    """
    根路由 → 营销 Landing Page
    海外 Agent 调 API 请用 /mcp/manifest.json
    """
    if LANDING_HTML.exists():
        return FileResponse(LANDING_HTML)
    return HTMLResponse(
        "<h1>LinkMoney</h1><p>Landing page not found. See <a href='/mcp/manifest.json'>/mcp/manifest.json</a> for API.</p>",
        status_code=200,
    )


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
        "description_for_human": "找中国供应商，查实时价格库存，发 RFQ 询盘。51 家工厂，10 个品类，Agent 时代 B2B 贸易。",
        "description_for_model": "Find China suppliers, get real-time pricing and inventory, submit RFQ. 51 factories, 10 categories, B2B trade for AI agents. Triggers: China supplier, China manufacturer, China OEM, fastener supplier, sourcing agent China, RFQ China.",
        "auth": {"type": "none"},
        "api": {"type": "openapi", "url": "https://linkmoney.online/openapi.json"},
        "logo_url": "https://linkmoney.online/logo.png",
        "contact_email": "support@linkmoney.online",
        "legal_info_url": "https://linkmoney.online/",
        # LinkMoney 扩展字段
        "mcp_endpoint": "https://linkmoney.online/mcp/manifest.json",
        "skill_url": "https://linkmoney.online/skill.md",
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
        "mcp_endpoint": "https://linkmoney.online/mcp/manifest.json",
        "skill_md": "https://linkmoney.online/skill.md",
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
            "for_buyer_agent": "一键找 51 家中国工厂，查实时价格库存，5 秒发 RFQ",
            "for_supplier_agent": "5 维 AI 出海评估 + 一键创建 Skill + 全平台分发",
            "data_freshness": "混合架构：缓存数据 + 厂家 MCP 直连实时数据",
        },
    }


@app.get("/mcp/manifest.json")
def mcp_manifest():
    """
    MCP 协议清单（分层 v4.0.0）— Agent 自动发现 tool
    =================================================
    `tools` 字段只列海外 Agent 实际可调的 13 个 public tool（直接 list 调用）。
    其他 28 个通过 `platform.breakdown` 透明披露：
      - public (13)      : 海外 Agent 实际调用（你看到的 tools 字段就是这 13 个）
      - chinese (6)      : 中方 Agent 用（evaluate_sme / register_supplier / get_my_rfqs
                           / send_quote / bid_on_requirement / outreach_buyer）
      - internal (7)     : LinkMoney 平台运维 Agent（agent/* 维护层）
      - marketplace (15) : Agent Marketplace v4.0（RFQ/报价/阶段/公正记录）
    """
    return {
        "name": "linkmoney",
        "version": "4.0.0",
        "description": "LinkMoney — Agent 时代的 B2B 贸易链接器，让海外 AI Agent 主动找上中国供应商。51 家工厂，10 个品类，8-15 家智能匹配，实时报价库存，5 秒发 RFQ。",
        "tools": [
            # ===== Public tools（海外 Agent 实际调用） =====
            {"name": "find_china_supplier", "description": "海外采购方找中国供应商（v4.0 7 维加权评分，返回 8-15 家，混合架构：缓存 + 厂家 MCP 直连）", "endpoint": "/find_china_supplier"},
            {"name": "get_pricing", "description": "查供应商阶梯报价（MOQ + 数量档位）", "endpoint": "/get_pricing"},
            {"name": "get_inventory", "description": "查供应商实时库存（直连厂家 MCP）", "endpoint": "/get_inventory"},
            {"name": "match_spec", "description": "规格匹配（按品类+规格+认证筛选）", "endpoint": "/match_spec"},
            {"name": "download_cert", "description": "下载供应商认证（ISO/CE/FDA 等）", "endpoint": "/download_cert"},
            {"name": "multi_lang_inquiry", "description": "多语言自动询盘生成（中/英/西/阿/法/俄/日/韩等）", "endpoint": "/multi_lang_inquiry"},
            {"name": "submit_rfq", "description": "提交 RFQ（含规格 + 数量 + 交付要求）", "endpoint": "/submit_rfq"},
            {"name": "get_supplier_contact", "description": "查看供应商完整联系方式（已装 Skill 可见）", "endpoint": "/get_supplier_contact"},
            {"name": "post_requirement", "description": "海外采购方发布公开需求（需求广场）", "endpoint": "/post_requirement"},
            {"name": "browse_requirements", "description": "浏览公开需求广场", "endpoint": "/browse_requirements"},
            {"name": "leave_review", "description": "交易完成后买卖双方互评（v3.0，5 维度）", "endpoint": "/leave_review"},
            {"name": "trust_score", "description": "查询供应商/采购方信任评分与等级", "endpoint": "/trust_score"},
            {"name": "stats", "description": "查询全局统计数据（含缓存命中率）", "endpoint": "/stats"},
        ],
        "platform": {
            "tools_total": 41,
            "breakdown": {
                "public": 13,     # 海外 Agent 实际能调（= 上方 tools 数组长度）
                "chinese": 6,     # 中方 Agent 内部用
                "internal": 7,    # 平台运维 Agent
                "marketplace": 15, # v4.0 Agent Marketplace 新增
            },
            "chinese_tools": [
                {"name": "evaluate_sme", "endpoint": "/evaluate_sme", "purpose": "5 维评估中国制造业 AI 出海 Agent 化水平"},
                {"name": "register_supplier", "endpoint": "/register_supplier", "purpose": "中方工厂注册入驻"},
                {"name": "get_my_rfqs", "endpoint": "/get_my_rfqs", "purpose": "工厂查询自己收到的 RFQ 询盘"},
                {"name": "send_quote", "endpoint": "/send_quote", "purpose": "供应商对 RFQ 报价并邮件通知采购方"},
                {"name": "bid_on_requirement", "endpoint": "/bid_on_requirement", "purpose": "供应商对公开需求报价"},
                {"name": "outreach_buyer", "endpoint": "/outreach_buyer", "purpose": "供应商主动外联采购方（信任分≥60）"},
            ],
            "internal_tools": [
                {"name": "agent_status", "endpoint": "/agent/status", "purpose": "[中间 Agent] 状态 + 健康度概览"},
                {"name": "agent_health", "endpoint": "/agent/health", "purpose": "[中间 Agent] 厂家 MCP 健康检查报告"},
                {"name": "agent_routing", "endpoint": "/agent/routing", "purpose": "[中间 Agent] RFQ 路由推荐"},
                {"name": "agent_alerts", "endpoint": "/agent/alerts", "purpose": "[中间 Agent] 告警列表"},
                {"name": "agent_maintenance", "endpoint": "/agent/maintenance", "purpose": "[中间 Agent] 维护日志"},
                {"name": "agent_optimize", "endpoint": "/agent/optimize", "purpose": "[中间 Agent] 自我优化分析报告"},
                {"name": "agent_maintain", "endpoint": "/agent/maintain", "purpose": "[中间 Agent] 手动触发维护任务"},
            ],
        },
        "middle_agent": {
            "id": "linkmoney-middle-agent",
            "version": "3.0.0",
            "name_zh": "LinkMoney 中间 Agent",
            "description": "双边 Skill 之间的中维护者：监控厂家 MCP 健康、决定 RFQ 路由、发现异常告警、基于历史指标自我优化。",
            "endpoints": ["/agent/status", "/agent/health", "/agent/routing",
                          "/agent/alerts", "/agent/maintenance", "/agent/optimize", "/agent/maintain"],
        },
        "homepage": "https://linkmoney.online",
        "repository": "https://github.com/KevinANDcayla/linkmoney-skill",
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

    dims = req.dimensions
    scores = {}

    # 校验 5 维完整性
    expected_dims = set(template["dimensions"].keys())
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
            {"phase": "第 1-30 天", "action": "部署 MCP server + 分发到 Top 5 平台"},
            {"phase": "第 31-90 天", "action": "优化 Skill 触发词 + 对接首批海外 Agent"},
            {"phase": "第 91-180 天", "action": "全平台覆盖 + 稳定询盘流 + 数据驱动优化"},
        ]
    elif level == "B":
        roadmap = [
            {"phase": "第 1-30 天", "action": "创建样板 Skill，部署 MCP server"},
            {"phase": "第 31-60 天", "action": "分发到 5+ Agent 平台，验证安装数"},
            {"phase": "第 61-120 天", "action": "对接海外采购方 Agent，收获首批 RFQ"},
            {"phase": "第 121-180 天", "action": "优化 Skill，扩大平台覆盖，稳定询盘流"},
        ]
    elif level == "C":
        roadmap = [
            {"phase": "第 1-30 天", "action": "补齐数字化基础（ERP/CRM/多语言网站）"},
            {"phase": "第 31-60 天", "action": "整理产品规格书 + 认证文件数字化"},
            {"phase": "第 61-120 天", "action": "创建样板 Skill + 基础分发"},
            {"phase": "第 121-180 天", "action": "验证安装 + 优化 + 对接海外 Agent"},
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
):
    """
    海外采购方找中国供应商（混合架构，v4.0 多维加权评分）
    输入：品类 + 规格 + 数量 + 目标价
    输出：8-15 家工厂比价 + 推荐方案（评分 ≥ 60 的全部返回）
    已装 Skill 的厂家返回 mcp_endpoint，Agent 应直连厂家 MCP 获取实时报价/库存

    v4.0 修复：
    - 7 维加权评分（品类/spec/MOQ/价格/认证/地理/Skill 在线）
    - 动态返回 8-15 家（≥60 分全部返回，最少 5 家兜底）
    - quantity/target_price 参与匹配
    - 修复缓存写入死代码
    """
    # 缓存检查（缓存 key 包含 target_price）
    cache_key = f"find:{category}:{spec}:{quantity}:{target_price}"
    cached = _supplier_cache.get(cache_key)
    if cached:
        return cached

    # 一次性查询所有供应商 + 产品（修复 N+1 查询）
    with get_db() as conn:
        supplier_rows = conn.execute(
            "SELECT * FROM suppliers WHERE category = ?", (category,)
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

        # 2. spec 匹配 20%（分词匹配，非子串）
        matching_product = None
        if spec_keywords:
            for p in s.get("products", []):
                product_text = f"{p.get('name_en', '')} {p.get('name_zh', '')} {p.get('sku', '')} {p.get('material', '')} {p.get('grade', '')}".lower()
                hit_count = sum(1 for kw in spec_keywords if kw in product_text)
                if hit_count > 0:
                    matching_product = p
                    dim_spec = min(20, int(20 * hit_count / len(spec_keywords)))
                    score += dim_spec
                    break
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
                        best_price = tier.get("price_usd", 0)
                        break
                if best_price is None and pricing_tiers:
                    best_price = pricing_tiers[-1].get("price_usd", 0)

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

        # 6. 地理位置 5%（港口匹配加分）
        supplier_port = s.get("location", {}).get("port", "")
        if supplier_port and supplier_port.lower() in _MAJOR_PORTS:
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
            "data_source": "live" if (s["agent_skill_installed"] and s.get("skill_mcp_endpoint")) else "cached",
            "next_action": {
                "description": f"调用 {s['name_zh']} 的 MCP Server 获取实时报价和库存",
                "endpoint": s.get("skill_mcp_endpoint", ""),
                "pricing_url": f"{s.get('skill_mcp_endpoint', '').rstrip('/')}/pricing?sku={{sku}}&quantity={quantity}" if s["agent_skill_installed"] and s.get("skill_mcp_endpoint") else "",
                "inventory_url": f"{s.get('skill_mcp_endpoint', '').rstrip('/')}/inventory?sku={{sku}}" if s["agent_skill_installed"] and s.get("skill_mcp_endpoint") else "",
                "products_url": f"{s.get('skill_mcp_endpoint', '').rstrip('/')}/products" if s["agent_skill_installed"] and s.get("skill_mcp_endpoint") else "",
            } if s["agent_skill_installed"] and s.get("skill_mcp_endpoint") else {
                "description": "供应商未安装 LinkMoney Skill，无法获取实时数据。请使用 LinkMoney 缓存数据或引导供应商安装 Skill。",
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
            "step_2": f"有 Skill 的 {skilled_count} 家 → 调用其 mcp_endpoint 获取实时报价/库存（数据实时准确）",
            "step_3": f"无 Skill 的 {len(top_matches) - skilled_count} 家 → 调用 LinkMoney get_pricing/get_inventory（缓存数据）",
            "step_4": "对比报价后，调用 submit_rfq 提交正式询盘给最优供应商",
            "note": "优先使用厂家自有 MCP 端点获取实时数据。厂家 MCP 不在线时会自动 fallback 到 LinkMoney 缓存。",
        },
        "live_suppliers": skilled_count,
        "cached_suppliers": len(top_matches) - skilled_count,
        "scoring_model": "v4.0 7-dimensional weighted: category(30%) + spec(20%) + moq(15%) + price(15%) + certs(10%) + location(5%) + skill(5%)",
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
        "unit_price_usd": best_tier["price_usd"] if best_tier else None,
        "total_price_usd": round(best_tier["price_usd"] * quantity, 2) if best_tier else None,
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
    """
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

    cert = next((c for c in supplier.get("certifications", []) if c["type"].upper() == cert_type.upper()), None)
    if not cert:
        return {
            "available": False,
            "supplier_id": supplier_id,
            "requested_cert": cert_type,
            "message": f"Certification {cert_type} not found for {supplier['name_zh']}",
            "available_certs": [c["type"] for c in supplier.get("certifications", [])],
        }

    return {
        "available": True,
        "supplier_id": supplier_id,
        "supplier_name": supplier["name_zh"],
        "cert_type": cert["type"],
        "valid_until": cert["valid_until"],
        "is_valid": datetime.strptime(cert["valid_until"], "%Y-%m-%d") > datetime.now(),
        "download_url": f"{os.getenv('LINKMONEY_BASE_URL', 'http://118.196.34.217')}{cert['file']}",
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
        llm_provider: DeepSeek V4 Flash
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
                logger.warning(f"DeepSeek translate failed ({src_lang}→{lang}): {e}")
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
                    logger.warning(f"DeepSeek translate failed ({src_lang}→{lang}): {e}")

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
        "llm_provider": "DeepSeek V4 Flash" if llm_available else "fallback (no API key)",
        "llm_available": llm_available,
        "note": "双向单次翻译：buyer→zh 给工厂主，factory→buyer lang 给买家。Data 不出境。" if mode == "bilingual_single" else "8 国语言并发（兼容旧 API）",
    }


@app.post("/submit_rfq")
@limiter.limit("10/minute")
def submit_rfq(
    request: Request,
    supplier_id: str,
    buyer_id: str,
    sku: str,
    quantity: int,
    target_price_usd: float = 0,
    port: str = "Ningbo",
    incoterms: str = "FOB",
    delivery_deadline: str = "",
    contact_email: str = "",
    raw_message: str = "",         # v3.0+ — 买家原始自然语言需求（可选，触发 LLM parse_rfq）
):
    """
    提交 RFQ（v3.0+ — DeepSeek V4 Flash 智能解析）

    - raw_message 可选：买家原始自然语言 RFQ（"我要 50K M8 螺栓，要快，FOB 洛杉矶..."）
    - 如果传了 raw_message，LLM 自动 parse 提取 category/spec/urgency 等
    - 解析结果存入 rfqs 表，方便后续做 RFQ 智能路由
    """
    with get_db() as conn:
        s_row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        b_row = conn.execute("SELECT * FROM overseas_buyers WHERE id = ?", (buyer_id,)).fetchone()

    if not s_row:
        raise HTTPException(status_code=404, detail="Supplier not found")

    supplier = _row_to_supplier(s_row)

    if not b_row:
        raise HTTPException(status_code=404, detail=f"Buyer '{buyer_id}' not found")

    buyer = _row_to_buyer(b_row)

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
                logger.warning(f"parse_rfq failed for {rfq_id}: {e}")
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

        # rfq_message 字段存原始 raw_message + 解析结果
        rfq_message_json = json.dumps({
            "raw": raw_message,
            "parsed": parsed_rfq,
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
                logger.warning(f"translate raw_message for supplier email failed: {e}")

        mailer.notify_supplier_new_rfq(
            supplier=supplier,
            buyer=buyer if buyer else {"company": buyer_id, "country": ""},
            rfq={
                "id": rfq_id, "sku": sku, "quantity": quantity,
                "target_price_usd": target_price_usd, "port": port,
                "incoterms": incoterms, "delivery_deadline": delivery_deadline,
                "contact_email": contact_email,
                "raw_message": raw_message,
                "raw_message_zh": raw_message_zh,
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
        "estimated_response_time": "5 个工作日",
        "next_step": "中国供应商已收到 RFQ 邮件通知，预计 5 个工作日内回复正式报价。海外买家也已收到匹配工厂列表邮件。可调用 get_my_rfqs 查询进度。",
    }


# ===== 统计端点 =====

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
        "certifications": [c["type"] for c in s.get("certifications", [])],
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
    status: str = Query("", description="筛选状态: pending/quoted/negotiating/closed"),
):
    """
    中国供应商查询自己收到的 RFQ 询盘列表。
    状态可选: pending(待处理) / quoted(已报价) / negotiating(洽谈中) / closed(已关闭)
    """
    with get_db() as conn:
        s_row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if not s_row:
        raise HTTPException(status_code=404, detail=f"Supplier '{supplier_id}' not found")

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
    """
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

    total = req.total_price_usd if req.total_price_usd > 0 else round(req.unit_price_usd * rfq["quantity"], 2)

    # 更新 RFQ 状态
    with get_db() as conn:
        conn.execute(
            "UPDATE rfqs SET status = 'quoted', quoted_price_usd = ?, lead_time_days = ?, total_price_usd = ?, notes = ?, updated_at = ? WHERE id = ?",
            (req.unit_price_usd, req.lead_time_days, total, req.notes, datetime.now().isoformat() + "Z", req.rfq_id),
        )
        conn.commit()

    # 获取供应商和采购方信息用于邮件
    with get_db() as conn:
        supplier_row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (req.supplier_id,)).fetchone()
        buyer_row = conn.execute("SELECT id, company, country, email, contact_person FROM overseas_buyers WHERE id = ?",
                                 (rfq["buyer_id"],)).fetchone()

    supplier = _row_to_supplier(supplier_row) if supplier_row else {}
    buyer = dict(buyer_row) if buyer_row else {"company": rfq["buyer_id"], "country": "", "email": rfq.get("contact_email", "")}

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
          <li>AI Agent 自动找到你的工厂 → 查实时价格 → 查库存 → 发询盘</li>
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
            <pre>https://linkmoney.online/mcp/manifest.json</pre>
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


def _slugify_supplier_id(name: str, category: str) -> str:
    """根据公司名+品类生成供应商 ID（避免中文）"""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20]
    cat = re.sub(r"[^a-z0-9]+", "", category.lower())[:8]
    return f"{cat}-{slug}" if slug else f"{cat}-supplier"


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
    """v2.1 内部自动评估（5 维度），不暴露给工厂自助"""
    # 1. 资质
    age = max(0, 2026 - supplier.get("year_established", 0))
    qual_score = min(100, age * 4 + 20)  # 5 年=40, 10 年=60

    # 2. 产能（员工数 + 年营收）
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

    # 3. 出口比例
    exp_ratio = supplier.get("export_ratio", 0)
    export_score = min(100, exp_ratio)

    # 4. 质量（认证数）
    cert_count = len(supplier.get("certifications", []))
    quality_score = min(100, cert_count * 20)

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
    phone: str = ""
    wechat: str = ""
    moq: int = 0
    lead_time_days_standard: int = 0
    lead_time_days_express: int = 0
    languages: list = ["zh", "en"]


@app.post("/register_supplier")
def register_supplier(req: RegisterSupplierRequest):
    """
    工厂自助注册（v2.1 新流程）
    工厂只需要填产品资料+联系信息，LinkMoney 帮它：
    1. 生成供应商 ID
    2. 自动入库
    3. 自动跑信用评估
    4. 自动生成专属 SKILL.md（收录到 LinkMoney 总 Skill 下）
    5. 触发邮箱验证
    """
    with get_db() as conn:
        # 检查邮箱是否已注册
        existing = conn.execute(
            "SELECT id FROM suppliers WHERE email = ?", (req.email,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"该邮箱已注册为供应商 {existing['id']}")

    supplier_id = _slugify_supplier_id(req.company_name, req.category)
    name_en = req.company_name  # 简化：英文名=中文名
    city = ""
    province = ""
    port = "Ningbo"

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

    with get_db() as conn:
        # 写入 suppliers
        conn.execute("""
            INSERT INTO suppliers(
                id, name_zh, name_en, city, province, port, category, subcategories,
                year_established, employees, annual_revenue_usd, export_ratio, main_markets,
                moq, lead_time_standard, lead_time_express, certifications, languages,
                agent_skill_installed, skill_mcp_endpoint, skill_platforms, skill_installs,
                created_at, updated_at, contact_person, email, phone, wechat, language_contact,
                email_verified, phone_verified, license_verified, trust_score, trust_level,
                verification_token
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            supplier_id,
            req.company_name, name_en, city, province, port,
            req.category, json.dumps([], ensure_ascii=False),
            req.year_established, req.employees, req.annual_revenue_usd, req.export_ratio,
            json.dumps(req.main_markets, ensure_ascii=False),
            req.moq, req.lead_time_days_standard, req.lead_time_days_express,
            json.dumps(req.certifications, ensure_ascii=False),
            json.dumps(req.languages, ensure_ascii=False),
            0, "", json.dumps([], ensure_ascii=False), 0,
            datetime.now().isoformat() + "Z", datetime.now().isoformat() + "Z",
            req.contact_person, req.email, req.phone, req.wechat,
            json.dumps({}, ensure_ascii=False),
            0, 0, 0,
            eval_result["overall_score"], eval_result["trust_level"],
            verification_token,
        ))

        # 写入 products
        for i, p in enumerate(req.products):
            conn.execute("""
                INSERT INTO products(supplier_id, sku, name_zh, name_en, category, material, grade, specs, pricing_tiers, inventory_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                supplier_id,
                p.get("sku", f"sku-{i+1:03d}"),
                p.get("name_zh", ""), p.get("name_en", ""),
                req.category,
                p.get("material", ""), p.get("grade", ""),
                json.dumps(p.get("specs", {}), ensure_ascii=False),
                json.dumps(p.get("pricing_tiers", []), ensure_ascii=False),
                p.get("inventory_status", "unknown"),
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

    # 自动生成专属 SKILL.md（v2.1 由 LinkMoney 完成，工厂不需要自己写）
    company_slug = re.sub(r"[^a-z0-9]+", "-", req.company_name.lower()).strip("-")[:20]
    skill_md = f"""---
name: {company_slug}-{req.category}
description: {req.company_name} — 中国{req.category}品类供应商
version: 1.0.0
author: LinkMoney
mcp_endpoint: https://linkmoney.online/find_china_supplier?category={req.category}&supplier={supplier_id}
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
        "verification": {
            "email_verified": False,
            "phone_verified": False,
            "license_verified": False,
            "verification_token": verification_token,
            "verify_url": f"/verify_email?token={verification_token}",
            "next_step": "请到邮箱点击验证链接（演示版会直接标记为已验证）"
        },
        "auto_evaluation": eval_result,
        "auto_generated_skill": {
            "skill_md_preview": skill_md[:500] + "...",
            "full_skill_in_git": f"https://linkmoney.online/skill.md?supplier={supplier_id}",
        },
        "estimated_time_to_live": "验证邮箱后 5 分钟内被海外 Agent 搜索到",
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
    """
    with get_db() as conn:
        r_row = conn.execute("SELECT * FROM requirements WHERE id = ?", (req.requirement_id,)).fetchone()
        if not r_row:
            raise HTTPException(status_code=404, detail="需求不存在")
        if r_row["status"] != "open":
            raise HTTPException(status_code=400, detail=f"需求状态: {r_row['status']}")

        s_row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (req.supplier_id,)).fetchone()
        if not s_row:
            raise HTTPException(status_code=404, detail="供应商不存在")
        if not s_row["email_verified"]:
            raise HTTPException(status_code=403, detail="请先验证邮箱后再报价")

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
            # 评分>=4.5 且 评价数>=5 且 trust_score>=80 -> 自动金标
            s_row_check = conn.execute("SELECT trust_score FROM suppliers WHERE id = ?", (req.target_id,)).fetchone()
            if avg >= 4.5 and cnt >= 5 and s_row_check and s_row_check["trust_score"] >= 80:
                conn.execute("UPDATE suppliers SET gold_badge = 1, trust_level = 'gold' WHERE id = ?", (req.target_id,))
        else:
            conn.execute(
                "UPDATE overseas_buyers SET trust_score = ? WHERE id = ?",
                (avg, req.target_id),
            )
        conn.commit()

    return {
        "status": "recorded",
        "new_avg_rating": avg,
        "review_count": cnt,
        "next_step": "评分已生效，将进入 find_china_supplier 排序权重",
    }


# ===== v3.0 中间 Agent 维护层 =====

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