"""
LinkMoney Agent Marketplace API（v4.0 扩展）
=============================================

在 linkmoney 主服务之上，新增 4 张表 + 14 个端点，支持：
- 公开 RFQ 市场（多供应商竞价，非原有 supplier-targeted RFQ）
- 报价对比 + 短名单 + 选标
- 9 阶段执行仪表盘
- Aegis 公正 Agent 全链路审计（指纹哈希）

设计原则：
- 新表名加 `marketplace_` 前缀，与原 `rfqs` 表并存不冲突
- 复用主 server 的 get_db / logger，避免循环导入
- 挂载在 FastAPI 主 app 上，端点前缀 `/marketplace`
- 写入 server.py 时只挂载一次 router，无需重复写迁移
"""

import json
import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# ===== 延迟依赖注入（避免循环导入） =====

def _db():
    import server
    return server.get_db

def _logger():
    import server
    return server.logger

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _gen_id(prefix: str) -> str:
    """生成唯一 ID：{prefix}-{ts}-{6位uuid}"""
    return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

def _fingerprint(seed: str) -> str:
    """生成 8 位短哈希指纹"""
    return hashlib.sha256(seed.encode()).hexdigest()[:8]


# ===== 9 阶段执行配置（与前端 RFQ_STAGES 保持一致） =====

STAGES = [
    {"key": "inquiry",    "name": "询盘确认", "description": "RFQ 匹配工厂并确认需求",      "order": 1},
    {"key": "quoting",    "name": "报价收集", "description": "收集供应商报价",                "order": 2},
    {"key": "compare",    "name": "报价对比", "description": "多维度对比供应商报价",          "order": 3},
    {"key": "negotiate",  "name": "商务谈判", "description": "价格/交期/付款条款谈判",        "order": 4},
    {"key": "contract",   "name": "合同签订", "description": "签订采购合同",                  "order": 5},
    {"key": "production", "name": "生产执行", "description": "工厂生产/质检",                  "order": 6},
    {"key": "inspection", "name": "验货出运", "description": "第三方验货 + 物流出运",         "order": 7},
    {"key": "shipping",   "name": "国际物流", "description": "海运/空运/快递",                 "order": 8},
    {"key": "delivery",   "name": "清关收货", "description": "目的港清关 + 收货验收",          "order": 9},
]

# ===== 数据库迁移（v4.0 增量） =====

def _migrate_v40_marketplace():
    """v4.0 — Agent Marketplace 新增 5 张表（幂等）"""
    with _db()() as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS marketplace_agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                avatar TEXT DEFAULT '',
                role TEXT NOT NULL,
                reputation INTEGER DEFAULT 80,
                country TEXT DEFAULT '',
                company TEXT DEFAULT '',
                description TEXT DEFAULT '',
                specialties TEXT DEFAULT '[]',
                certifications TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS marketplace_rfqs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                product_category TEXT NOT NULL,
                specs TEXT DEFAULT '',
                target_unit_price REAL DEFAULT 0,
                moq INTEGER DEFAULT 0,
                quantity INTEGER NOT NULL,
                currency TEXT DEFAULT 'USD',
                trade_term TEXT DEFAULT 'FOB',
                destination_port TEXT DEFAULT '',
                payment_term TEXT DEFAULT '',
                certifications TEXT DEFAULT '[]',
                lead_time_days INTEGER DEFAULT 0,
                status TEXT DEFAULT 'open',
                deadline TEXT DEFAULT '',
                delivery_deadline TEXT DEFAULT '',
                buyer_id TEXT NOT NULL,
                winner_supplier_id TEXT DEFAULT NULL,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS marketplace_quotes (
                id TEXT PRIMARY KEY,
                rfq_id TEXT NOT NULL,
                supplier_id TEXT NOT NULL,
                unit_price REAL NOT NULL,
                moq INTEGER DEFAULT 0,
                lead_time_days INTEGER DEFAULT 0,
                payment_term TEXT DEFAULT '',
                factory_certs TEXT DEFAULT '[]',
                notes TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (rfq_id) REFERENCES marketplace_rfqs(id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS marketplace_stages (
                id TEXT PRIMARY KEY,
                rfq_id TEXT NOT NULL,
                stage_key TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                assignee_id TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'medium',
                start_date TEXT DEFAULT '',
                end_date TEXT DEFAULT '',
                progress INTEGER DEFAULT 0,
                dependencies TEXT DEFAULT '[]',
                stage_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (rfq_id) REFERENCES marketplace_rfqs(id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS marketplace_records (
                id TEXT PRIMARY KEY,
                rfq_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                agent_ids TEXT DEFAULT '[]',
                summary TEXT DEFAULT '',
                fingerprint TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (rfq_id) REFERENCES marketplace_rfqs(id)
            )
        """)

        # 索引
        c.execute("CREATE INDEX IF NOT EXISTS idx_mrfq_status     ON marketplace_rfqs(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mrfq_buyer      ON marketplace_rfqs(buyer_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mrfq_winner     ON marketplace_rfqs(winner_supplier_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mquote_rfq      ON marketplace_quotes(rfq_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mquote_supplier ON marketplace_quotes(supplier_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mstage_rfq      ON marketplace_stages(rfq_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mrecord_rfq     ON marketplace_records(rfq_id)")

        conn.commit()


# ===== Seed 数据（首次运行时插入演示数据） =====

def _seed_demo_data():
    """插入 8 个 Agent + 12 个 RFQ + 18 个 Quote + 45 个 Stage + 公正记录"""
    with _db()() as conn:
        c = conn.cursor()
        if c.execute("SELECT COUNT(*) as cnt FROM marketplace_agents").fetchone()["cnt"] > 0:
            return  # 已 seed 过

        # 8 个 Agent（4 buyers + 4 suppliers + 1 arbitrator）
        agents = [
            # Buyers
            ("agent-buyer-us-01",  "🇺🇸 Mike · 美国亚马逊卖家",   "🇺🇸", "buyer",      88, "美国",   "BayAreaTrade Inc.", "中型亚马逊卖家，主营家居 + 3C 配件",  '["家居", "3C", "亚马逊 FBA"]', '[]'),
            ("agent-buyer-de-01",  "🇩🇪 Hans · 德国工业采购",    "🇩🇪", "buyer",      92, "德国",   "MunichParts GmbH",   "德国工业品采购商，注塑 + 五金",        '["机械", "五金", "注塑"]', '[]'),
            ("agent-buyer-ae-01",  "🇦🇪 Omar · 中东转口贸易",    "🇦🇪", "buyer",      85, "阿联酋","GulfTrade FZE",      "迪拜转口贸易，覆盖中东 + 北非",        '["包装", "纺织", "日用"]', '[]'),
            ("agent-buyer-au-01",  "🇦🇺 Sophie · 澳洲独立站",    "🇦🇺", "buyer",      80, "澳大利亚","BondiBrand Pty",    "澳洲独立站品牌，环保 + 母婴",          '["包装", "母婴", "环保"]', '[]'),
            # Suppliers
            ("agent-supplier-01",  "深圳鸿利精密 · Shenzhen Hongli", "🟡", "supplier", 90, "中国·深圳","鸿利精密电子有限公司", "电子元器件 OEM/ODM，20年出口经验",     '["电子", "3C", "PCB"]',     '["ISO 9001", "CE", "RoHS"]'),
            ("agent-supplier-02",  "义乌环球百货 · Yiwu Universal",  "🟡", "supplier", 85, "中国·义乌","义乌环球百货有限公司", "包装印刷 + 日用百货，一站式外贸",     '["包装", "日用", "礼品"]',   '["ISO 9001", "FSC"]'),
            ("agent-supplier-03",  "佛山恒力机械 · Foshan Hengli",   "🟡", "supplier", 88, "中国·佛山","佛山恒力机械有限公司", "机械设备 + 五金制品，重型出口",        '["机械", "五金", "汽配"]',   '["ISO 9001", "CE", "API"]'),
            ("agent-supplier-04",  "宁波港通紧固件 · Ningbo GT",     "🟡", "supplier", 92, "中国·宁波","宁波港通紧固件有限公司", "紧固件专家，年产能 5000 吨",           '["紧固件", "五金"]',         '["ISO 9001", "IATF 16949"]'),
            # Arbitrator
            ("agent-arbitrator-01", "⚖️ Aegis · 公正官",            "⚖️", "arbitrator", 100, "LinkMoney 平台", "Aegis Arbitrator",  "LinkMoney 内置第三方公正 Agent，全链路审计 RFQ 生命周期", '[]', '[]'),
        ]
        c.executemany("""
            INSERT INTO marketplace_agents(id, name, avatar, role, reputation, country, company, description, specialties, certifications)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, agents)

        # 12 个 RFQ（覆盖 10 个品类）
        rfqs = [
            ("rfq-001", "求购 50K 件 M8 不锈钢内六角螺栓 · ISO 7380", "需符合 ISO 7380-1 标准，A2-70 不锈钢，GB/T 6172 兼容。需提供材质证明 + 盐雾测试报告 96h。",
             "紧固件", "M8 × 20 内六角圆柱头螺栓，A2-70 不锈钢，公制粗牙 1.25mm，GB/T 70.1 / ISO 4762。表面钝化处理，盐雾 96h 无红锈。",
             0.18, 5000, 50000, "USD", "FOB", "Los Angeles", "30% T/T deposit, 70% before shipment", '["ISO 9001", "IATF 16949", "RoHS"]',
             30, "open", "2026-07-01T23:59:59", "2026-08-15T23:59:59", "agent-buyer-us-01", None,
             "2026-06-12T10:30:00", "2026-06-12T10:30:00"),

            ("rfq-002", "20K 件 USB-C 100W PD 快充芯片 · 现货", "E-Marker 芯片 + 协议握手 IC。需支持 PD3.1 EPR 28V/36V/48V，需提供 USB-IF 认证证书。",
             "电子元器件", "USB-C PD3.1 EPR E-Marker 芯片，支持 100W + 240W。需过 USB-IF 认证。",
             1.20, 1000, 20000, "USD", "FOB", "Hamburg", "L/C at sight", '["USB-IF", "RoHS", "REACH"]',
             20, "open", "2026-06-25T23:59:59", "2026-07-30T23:59:59", "agent-buyer-de-01", None,
             "2026-06-13T14:20:00", "2026-06-13T14:20:00"),

            ("rfq-003", "10K 件定制环保牛皮纸包装盒 · 母婴级", "需 FSC 认证大豆油墨印刷，250g 牛卡 + 3mm 灰板。盒型天地盖 + 内托。",
             "包装印刷", "250g FSC 牛卡纸 + 3mm 灰板，天地盖结构，大豆油墨四色印刷。100% 可回收 + 母婴级安全标准。",
             0.85, 1000, 10000, "USD", "FOB", "Sydney", "50% T/T + 50% 见提单", '["FSC", "FDA", "CE-EN71"]',
             25, "open", "2026-07-05T23:59:59", "2026-08-20T23:59:59", "agent-buyer-au-01", None,
             "2026-06-14T09:15:00", "2026-06-14T09:15:00"),

            ("rfq-004", "5K 件注塑周转箱 · 工业级 EU 货架标准", "600×400×320mm 全新 PP 料，自重 1.8kg，承重 30kg，需可堆叠四面进叉。",
             "注塑模具", "600×400×320mm 全新 PP 料，注塑成型。自重 1.8kg ± 5%，承重 ≥ 30kg，可堆叠 8 层，四面进叉。",
             8.50, 500, 5000, "USD", "CIF", "Jebel Ali", "T/T 30/70", '["ISO 9001", "REACH", "FDA"]',
             35, "open", "2026-06-30T23:59:59", "2026-08-30T23:59:59", "agent-buyer-ae-01", None,
             "2026-06-15T16:45:00", "2026-06-15T16:45:00"),

            ("rfq-005", "50K 件男女款速干 T 恤 · 中东市场", "180g 涤纶速干，圆领 + 短袖。需 OEKO-TEX 100 认证。",
             "纺织服装", "180g/m² 涤纶速干面料，圆领短袖，4XL 备码。颜色：白/黑/海军蓝/沙色。中东市场热转印标签。",
             3.20, 1000, 50000, "USD", "FOB", "Jeddah", "L/C 30 days", '["OEKO-TEX 100", "BSCI"]',
             40, "quoting", "2026-06-22T23:59:59", "2026-08-25T23:59:59", "agent-buyer-ae-01", None,
             "2026-06-10T11:00:00", "2026-06-15T11:00:00"),

            ("rfq-006", "200 台商用咖啡机 · 澳洲独立站品牌", "15Bar 意式半自动，1.8L 水箱，304 不锈钢锅炉，OEM 贴牌。",
             "机械设备", "15Bar 意式半自动咖啡机，1.8L 可拆水箱，304 不锈钢锅炉，温控 PID。需提供 OEM 贴牌 + 3C 认证。",
             85.00, 50, 200, "USD", "DDP", "Sydney", "30% T/T + 70% 见提单", '["CE", "3C", "FDA", "SAA"]',
             50, "contracted", "2026-06-08T23:59:59", "2026-09-15T23:59:59", "agent-buyer-au-01", "agent-supplier-03",
             "2026-05-30T10:00:00", "2026-06-15T18:00:00"),

            ("rfq-007", "100K 件 3C 配件彩盒 + 内托 · 美线 FBA", "亚马逊 FBA 标准 5 层瓦楞 + 内卡 EPE 棉。需打 SKU 条码 + Made in China。",
             "包装印刷", "5 层瓦楞彩盒 + EPE 内托，符合亚马逊 FBA 包装标准。需打 SKU 条码 + Made in China 标签。",
             0.42, 5000, 100000, "USD", "FOB", "Los Angeles", "T/T 30/70", '["FSC", "SGS", "ISTA 3A"]',
             22, "in_production", "2026-06-05T23:59:59", "2026-07-20T23:59:59", "agent-buyer-us-01", "agent-supplier-02",
             "2026-05-25T14:30:00", "2026-06-16T08:00:00"),

            ("rfq-008", "20K 件汽车后视镜总成 · 欧美 OEM", "高尔夫 7 / 奥迪 A3 通用，电动折叠 + 加热除雾 + 转向灯。",
             "汽车零部件", "大众高尔夫 7 / 奥迪 A3 通用电动后视镜：折叠 + 加热除雾 + 转向灯。需提供 E-Mark 认证。",
             28.00, 500, 20000, "USD", "FOB", "Hamburg", "L/C 60 days", '["E-Mark", "IATF 16949", "CE"]',
             45, "open", "2026-07-10T23:59:59", "2026-09-30T23:59:59", "agent-buyer-de-01", None,
             "2026-06-15T08:20:00", "2026-06-15T08:20:00"),

            ("rfq-009", "30K 件 LED 智能灯泡 · 家居 IoT", "9W E27，支持 WiFi + 蓝牙双模，兼容 Alexa/Google Home/Tuya。",
             "电子产品", "9W E27 LED 智能灯泡，WiFi + 蓝牙双模，色温 2700-6500K，1600 万色，兼容 Alexa/Google Home/Tuya。",
             4.50, 1000, 30000, "USD", "CIF", "Los Angeles", "T/T 30/70", '["FCC", "CE", "RoHS", "UL"]',
             30, "open", "2026-07-01T23:59:59", "2026-08-30T23:59:59", "agent-buyer-us-01", None,
             "2026-06-14T13:00:00", "2026-06-14T13:00:00"),

            ("rfq-010", "80K 件圣诞节装饰灯串 · 欧洲市场", "20 米 200 灯 LED 暖白，IP44 防水，CE-EN60598 认证。",
             "电子产品", "20 米 200 灯 LED 暖白灯串，IP44 防水，8 种模式控制器，含电源适配器。需提供 CE-EN60598 认证。",
             1.80, 2000, 80000, "EUR", "FOB", "Hamburg", "T/T 30/70", '["CE-EN60598", "RoHS"]',
             35, "open", "2026-07-20T23:59:59", "2026-09-30T23:59:59", "agent-buyer-de-01", None,
             "2026-06-15T11:30:00", "2026-06-15T11:30:00"),

            ("rfq-011", "5K 件实木儿童积木 · 母婴级安全", "100% FSC 榉木，水性漆，1cm³ 颗粒，盒装 100 粒。",
             "家具家居", "100% FSC 榉木，水性漆涂装，1cm³ 颗粒 100 粒套装。需提供 EN71-3 / ASTM F963 母婴级安全认证。",
             6.80, 500, 5000, "USD", "FOB", "Sydney", "T/T 30/70", '["FSC", "EN71-3", "ASTM F963", "CE"]',
             28, "negotiating", "2026-06-20T23:59:59", "2026-08-15T23:59:59", "agent-buyer-au-01", None,
             "2026-06-08T15:00:00", "2026-06-15T15:00:00"),

            ("rfq-012", "1K 件定制不锈钢轴承座 · 工业机械", "304 不锈钢 CNC 加工，公差 ±0.02mm，需 100% 在线三坐标检测。",
             "机械设备", "304 不锈钢 CNC 精密加工轴承座，公差 ±0.02mm，表面 Ra0.8。需 100% 三坐标检测报告。",
             45.00, 200, 1000, "USD", "EXW", "佛山工厂交货", "T/T 30/70", '["ISO 9001", "Material Cert"]',
             20, "open", "2026-06-25T23:59:59", "2026-07-30T23:59:59", "agent-buyer-de-01", None,
             "2026-06-15T17:00:00", "2026-06-15T17:00:00"),
        ]
        c.executemany("""
            INSERT INTO marketplace_rfqs(id, title, description, product_category, specs, target_unit_price, moq, quantity,
                currency, trade_term, destination_port, payment_term, certifications, lead_time_days, status,
                deadline, delivery_deadline, buyer_id, winner_supplier_id, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rfqs)

        # 18 个 Quote
        quotes = [
            ("q-001", "rfq-001", "agent-supplier-04", 0.16, 5000, 28, "30% T/T + 70% 见提单", '["ISO 9001", "IATF 16949"]', "宁波港通 25 年紧固件专家，A2-70 材质证书 + 盐雾 96h 报告齐备。", "pending", "2026-06-12T11:30:00"),
            ("q-002", "rfq-001", "agent-supplier-03", 0.19, 5000, 35, "40% T/T + 60% 见提单", '["ISO 9001"]',              "佛山恒力接单，机械 + 五金综合产线。",                                            "pending", "2026-06-12T12:00:00"),
            ("q-003", "rfq-001", "agent-supplier-02", 0.20, 8000, 40, "T/T 30/70",             '["ISO 9001", "FSC"]',       "义乌环球可生产但 MOQ 8K 起。",                                                  "pending", "2026-06-12T13:15:00"),

            ("q-004", "rfq-002", "agent-supplier-01", 1.10, 1000, 18, "L/C at sight",          '["USB-IF", "RoHS"]',         "鸿利精密 E-Marker 直供，库存 50K。",                                            "shortlisted", "2026-06-13T15:30:00"),
            ("q-005", "rfq-002", "agent-supplier-01", 1.18, 1000, 15, "T/T 30/70",             '["USB-IF", "RoHS"]',         "鸿利精密标准价，含 USB-IF 测试报告。",                                          "pending", "2026-06-13T16:00:00"),

            ("q-006", "rfq-003", "agent-supplier-02", 0.78, 1000, 22, "50% T/T + 50% 见提单", '["FSC", "FDA"]',             "义乌环球自有 FSC 认证林场 + 大豆油墨车间。",                                   "shortlisted", "2026-06-14T10:30:00"),
            ("q-007", "rfq-003", "agent-supplier-02", 0.92, 2000, 28, "T/T 30/70",             '["FSC"]',                   "环保升级版，含 GOTS 认证。",                                                    "pending", "2026-06-14T11:00:00"),

            ("q-008", "rfq-004", "agent-supplier-03", 8.20, 500, 30, "T/T 30/70",             '["ISO 9001", "REACH"]',     "佛山恒力自有模具，60 天可交付。",                                              "pending", "2026-06-15T17:30:00"),
            ("q-009", "rfq-004", "agent-supplier-01", 9.50, 800, 40, "T/T 50/50",             '["ISO 9001"]',              "深圳鸿利可生产但 MOQ 偏高。",                                                  "pending", "2026-06-15T18:00:00"),

            ("q-010", "rfq-005", "agent-supplier-02", 2.95, 1000, 35, "L/C 30 days",           '["OEKO-TEX 100", "BSCI"]', "义乌环球纺织产线，BSCI 验厂齐备。",                                            "pending", "2026-06-11T09:00:00"),
            ("q-011", "rfq-005", "agent-supplier-02", 3.40, 2000, 30, "T/T 30/70",             '["OEKO-TEX 100"]',          "速干升级版，含吸湿排汗处理。",                                                  "shortlisted", "2026-06-11T10:30:00"),

            ("q-012", "rfq-006", "agent-supplier-03", 78.00, 50, 45, "30% T/T + 70% 见提单", '["CE", "3C"]',              "佛山恒力咖啡机 OEM 经验丰富，已与澳洲品牌合作 3 年。",                       "accepted", "2026-06-01T15:00:00"),

            ("q-013", "rfq-007", "agent-supplier-02", 0.38, 5000, 18, "T/T 30/70",             '["FSC", "SGS"]',            "义乌环球彩盒厂，已签合同。",                                                    "accepted", "2026-06-05T14:00:00"),
            ("q-014", "rfq-007", "agent-supplier-02", 0.45, 8000, 20, "T/T 50/50",             '["FSC"]',                   "升级版 EPE 内托。",                                                            "rejected", "2026-06-05T14:30:00"),

            ("q-015", "rfq-008", "agent-supplier-03", 26.50, 500, 40, "L/C 60 days",           '["E-Mark", "IATF 16949"]', "佛山恒力汽配 IATF 16949 认证。",                                              "pending", "2026-06-15T10:00:00"),
            ("q-016", "rfq-008", "agent-supplier-04", 29.80, 1000, 50, "T/T 30/70",             '["E-Mark"]',               "宁波港通可生产。",                                                              "pending", "2026-06-15T11:30:00"),

            ("q-017", "rfq-009", "agent-supplier-01", 4.20, 1000, 25, "T/T 30/70",             '["FCC", "RoHS", "UL"]',     "鸿利智能家居，Tuya 认证模块。",                                                "pending", "2026-06-14T14:30:00"),
            ("q-018", "rfq-012", "agent-supplier-03", 42.00, 200, 18, "T/T 30/70",             '["ISO 9001"]',              "佛山恒力 CNC 车间，自有三坐标。",                                              "pending", "2026-06-15T18:30:00"),
        ]
        c.executemany("""
            INSERT INTO marketplace_quotes(id, rfq_id, supplier_id, unit_price, moq, lead_time_days, payment_term, factory_certs, notes, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, quotes)

        # 45 个 Stage（5 个执行中 RFQ × 9 阶段 = 45）
        for rfq_id in ["rfq-001", "rfq-003", "rfq-005", "rfq-006", "rfq-007", "rfq-011"]:
            for s in STAGES:
                stage_id = f"stage-{rfq_id}-{s['key']}"
                # 根据 RFQ 状态设置阶段状态
                if rfq_id in ["rfq-006", "rfq-007"]:
                    # 完整执行中
                    if s["order"] <= 2:
                        st = "completed"
                    elif s["order"] == 3:
                        st = "in_progress"
                    else:
                        st = "pending"
                elif rfq_id in ["rfq-011"]:
                    if s["order"] <= 4:
                        st = "completed"
                    elif s["order"] == 5:
                        st = "in_progress"
                    else:
                        st = "pending"
                else:
                    # 早期阶段只做前 1-2 个
                    if s["order"] == 1:
                        st = "completed"
                    elif s["order"] == 2:
                        st = "in_progress"
                    else:
                        st = "pending"

                # 日期
                start_offset = (s["order"] - 1) * 7
                end_offset = s["order"] * 7
                start_date = (datetime.now() - timedelta(days=30 - start_offset)).isoformat(timespec="seconds")
                end_date = (datetime.now() - timedelta(days=30 - end_offset)).isoformat(timespec="seconds")

                c.execute("""
                    INSERT INTO marketplace_stages(id, rfq_id, stage_key, name, description, assignee_id, status, priority, start_date, end_date, progress, dependencies, stage_order)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    stage_id, rfq_id, s["key"], s["name"], s["description"],
                    "agent-supplier-04" if rfq_id == "rfq-001" else
                    "agent-supplier-02" if rfq_id in ["rfq-003", "rfq-007"] else
                    "agent-supplier-03" if rfq_id in ["rfq-005", "rfq-006", "rfq-011"] else
                    "agent-supplier-01",
                    st,
                    "high" if s["order"] <= 3 else "medium",
                    start_date, end_date,
                    100 if st == "completed" else (50 if st == "in_progress" else 0),
                    "[]",
                    s["order"],
                ))

        # 公正记录（每条带 fingerprint 指纹哈希）
        records = [
            # rfq-001
            ("rec-001", "rfq-001", "rfq_created",            '["agent-buyer-us-01", "agent-arbitrator-01"]', "🇺🇸 Mike 发布 RFQ：50K M8 不锈钢内六角螺栓，目标价 $0.18，FOB Los Angeles", "2026-06-12T10:30:00"),
            ("rec-002", "rfq-001", "quote_submitted",        '["agent-supplier-04", "agent-arbitrator-01"]', "宁波港通报价 $0.16/件，交期 28 天", "2026-06-12T11:30:00"),
            ("rec-003", "rfq-001", "quote_submitted",        '["agent-supplier-03", "agent-arbitrator-01"]', "佛山恒力报价 $0.19/件，交期 35 天", "2026-06-12T12:00:00"),
            # rfq-002
            ("rec-004", "rfq-002", "rfq_created",            '["agent-buyer-de-01", "agent-arbitrator-01"]', "🇩🇪 Hans 发布 RFQ：20K USB-C PD3.1 E-Marker 芯片", "2026-06-13T14:20:00"),
            ("rec-005", "rfq-002", "quote_submitted",        '["agent-supplier-01", "agent-arbitrator-01"]', "深圳鸿利报价 $1.10/件，库存 50K", "2026-06-13T15:30:00"),
            ("rec-006", "rfq-002", "quote_shortlisted",      '["agent-buyer-de-01", "agent-supplier-01", "agent-arbitrator-01"]', "深圳鸿利报价进入短名单（$1.10）", "2026-06-13T17:00:00"),
            # rfq-003
            ("rec-007", "rfq-003", "rfq_created",            '["agent-buyer-au-01", "agent-arbitrator-01"]', "🇦🇺 Sophie 发布 RFQ：10K 环保牛皮纸包装盒", "2026-06-14T09:15:00"),
            ("rec-008", "rfq-003", "quote_submitted",        '["agent-supplier-02", "agent-arbitrator-01"]', "义乌环球报价 $0.78/件", "2026-06-14T10:30:00"),
            # rfq-005
            ("rec-009", "rfq-005", "rfq_created",            '["agent-buyer-ae-01", "agent-arbitrator-01"]', "🇦🇪 Omar 发布 RFQ：50K 速干 T 恤", "2026-06-10T11:00:00"),
            ("rec-010", "rfq-005", "quote_shortlisted",      '["agent-buyer-ae-01", "agent-supplier-02", "agent-arbitrator-01"]', "义乌环球速干升级版报价 $3.40 进入短名单", "2026-06-11T10:30:00"),
            # rfq-006
            ("rec-011", "rfq-006", "rfq_created",            '["agent-buyer-au-01", "agent-arbitrator-01"]', "🇦🇺 Sophie 发布 RFQ：200 台商用咖啡机 OEM", "2026-05-30T10:00:00"),
            ("rec-012", "rfq-006", "supplier_selected",      '["agent-buyer-au-01", "agent-supplier-03", "agent-arbitrator-01"]', "Sophie 选定佛山恒力，中标价 $78/台，触发 9 阶段执行", "2026-06-01T18:00:00"),
            ("rec-013", "rfq-006", "contract_signed",        '["agent-buyer-au-01", "agent-supplier-03", "agent-arbitrator-01"]', "合同签订：200 台咖啡机 DDP Sydney，总价 $15,600", "2026-06-05T10:00:00"),
            ("rec-014", "rfq-006", "production_started",     '["agent-supplier-03", "agent-arbitrator-01"]', "佛山恒力启动生产，首批模具调试完成", "2026-06-10T14:00:00"),
            # rfq-007
            ("rec-015", "rfq-007", "rfq_created",            '["agent-buyer-us-01", "agent-arbitrator-01"]', "🇺🇸 Mike 发布 RFQ：100K 3C 配件彩盒", "2026-05-25T14:30:00"),
            ("rec-016", "rfq-007", "supplier_selected",      '["agent-buyer-us-01", "agent-supplier-02", "agent-arbitrator-01"]', "Mike 选定义乌环球，中标价 $0.38/件", "2026-06-05T16:00:00"),
            ("rec-017", "rfq-007", "milestone_reached",      '["agent-supplier-02", "agent-arbitrator-01"]', "义乌环球完成 50% 生产，质检通过", "2026-06-16T08:00:00"),
            # rfq-011
            ("rec-018", "rfq-011", "rfq_created",            '["agent-buyer-au-01", "agent-arbitrator-01"]', "🇦🇺 Sophie 发布 RFQ：5K 实木儿童积木", "2026-06-08T15:00:00"),
            # rfq-012
            ("rec-019", "rfq-012", "rfq_created",            '["agent-buyer-de-01", "agent-arbitrator-01"]', "🇩🇪 Hans 发布 RFQ：1K 不锈钢轴承座 CNC 加工", "2026-06-15T17:00:00"),
        ]
        for rec in records:
            rec_id, rfq_id, event_type, agent_ids, summary, created_at = rec
            fp = _fingerprint(f"{rec_id}|{rfq_id}|{event_type}|{summary}|{created_at}")
            c.execute("""
                INSERT INTO marketplace_records(id, rfq_id, event_type, agent_ids, summary, fingerprint, created_at)
                VALUES (?,?,?,?,?,?,?)
            """, (rec_id, rfq_id, event_type, agent_ids, summary, fp, created_at))

        conn.commit()


# ===== 业务辅助 =====

def _record(rfq_id: str, event_type: str, agent_ids: list, summary: str):
    """写入一条公正记录 + 自动生成 fingerprint"""
    rid = _gen_id("rec")
    fp = _fingerprint(f"{rid}|{rfq_id}|{event_type}|{summary}|{_now_iso()}")
    with _db()() as conn:
        conn.execute("""
            INSERT INTO marketplace_records(id, rfq_id, event_type, agent_ids, summary, fingerprint, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (rid, rfq_id, event_type, json.dumps(agent_ids), summary, fp, _now_iso()))
        conn.commit()
    return {"id": rid, "fingerprint": fp}


def _create_9_stages(rfq_id: str, assignee_id: str):
    """中标后自动创建 9 阶段执行"""
    with _db()() as conn:
        for s in STAGES:
            sid = f"stage-{rfq_id}-{s['key']}"
            conn.execute("""
                INSERT OR IGNORE INTO marketplace_stages(id, rfq_id, stage_key, name, description, assignee_id, status, priority, stage_order)
                VALUES (?,?,?,?,?,?, 'pending', 'medium', ?)
            """, (sid, rfq_id, s["key"], s["name"], s["description"], assignee_id, s["order"]))
        conn.commit()


def _row_to_dict(row) -> dict:
    """sqlite3.Row → dict（保留 JSON 字段的反序列化）"""
    d = dict(row)
    for k in ("certifications", "factory_certs", "agent_ids", "dependencies", "specialties"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k]) if d[k] else []
            except Exception:
                d[k] = []
    return d


# ===== Pydantic 模型 =====

class CreateRFQRequest(BaseModel):
    title: str
    description: str = ""
    product_category: str
    specs: str = ""
    target_unit_price: float = 0
    moq: int = 0
    quantity: int
    currency: str = "USD"
    trade_term: str = "FOB"
    destination_port: str = ""
    payment_term: str = ""
    certifications: List[str] = []
    lead_time_days: int = 30
    deadline: str = ""
    delivery_deadline: str = ""
    buyer_id: str


class SubmitQuoteRequest(BaseModel):
    rfq_id: str
    supplier_id: str
    unit_price: float
    moq: int = 0
    lead_time_days: int = 30
    payment_term: str = ""
    factory_certs: List[str] = []
    notes: str = ""


class UpdateStageRequest(BaseModel):
    status: Optional[str] = None
    progress: Optional[int] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None


# ===== Router =====

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


@router.get("/agents")
def list_agents(role: Optional[str] = None):
    """列出所有 Agent（可选 role 过滤）"""
    with _db()() as conn:
        if role:
            rows = conn.execute("SELECT * FROM marketplace_agents WHERE role = ? ORDER BY reputation DESC", (role,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM marketplace_agents ORDER BY role, reputation DESC").fetchall()
    return {"agents": [_row_to_dict(r) for r in rows], "total": len(rows)}


@router.get("/rfqs")
def list_rfqs(
    status: Optional[str] = None,
    category: Optional[str] = None,
    buyer_id: Optional[str] = None,
    supplier_id: Optional[str] = None,
    sort: str = "created_desc",   # created_desc / created_asc / deadline_asc / value_desc
    limit: int = 50,
):
    """列出 RFQ"""
    with _db()() as conn:
        q = "SELECT * FROM marketplace_rfqs WHERE 1=1"
        params = []
        if status:
            q += " AND status = ?"
            params.append(status)
        if category:
            q += " AND product_category = ?"
            params.append(category)
        if buyer_id:
            q += " AND buyer_id = ?"
            params.append(buyer_id)
        if supplier_id:
            q += " AND winner_supplier_id = ?"
            params.append(supplier_id)

        # 排序
        if sort == "created_desc":
            q += " ORDER BY created_at DESC"
        elif sort == "created_asc":
            q += " ORDER BY created_at ASC"
        elif sort == "deadline_asc":
            q += " ORDER BY deadline ASC"
        elif sort == "value_desc":
            q += " ORDER BY (target_unit_price * quantity) DESC"
        else:
            q += " ORDER BY created_at DESC"

        q += " LIMIT ?"
        params.append(limit)

        rows = conn.execute(q, params).fetchall()
    return {"rfqs": [_row_to_dict(r) for r in rows], "total": len(rows)}


@router.get("/rfqs/{rfq_id}")
def get_rfq(rfq_id: str):
    """获取 RFQ 详情"""
    with _db()() as conn:
        row = conn.execute("SELECT * FROM marketplace_rfqs WHERE id = ?", (rfq_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"RFQ {rfq_id} not found")
    return _row_to_dict(row)


@router.post("/rfqs")
def create_rfq(req: CreateRFQRequest):
    """发布 RFQ（采购方 Agent）"""
    rfq_id = _gen_id("rfq")
    now = _now_iso()
    with _db()() as conn:
        conn.execute("""
            INSERT INTO marketplace_rfqs(id, title, description, product_category, specs,
                target_unit_price, moq, quantity, currency, trade_term, destination_port,
                payment_term, certifications, lead_time_days, status, deadline, delivery_deadline,
                buyer_id, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            rfq_id, req.title, req.description, req.product_category, req.specs,
            req.target_unit_price, req.moq, req.quantity, req.currency, req.trade_term, req.destination_port,
            req.payment_term, json.dumps(req.certifications), req.lead_time_days, "open",
            req.deadline, req.delivery_deadline, req.buyer_id, now, now,
        ))
        conn.commit()

    # 写入公正事件
    _record(rfq_id, "rfq_created",
            [req.buyer_id, "agent-arbitrator-01"],
            f"{req.buyer_id} 发布 RFQ：{req.title}，目标价 {req.currency} ${req.target_unit_price}，{req.trade_term} {req.destination_port}")

    return {"rfq_id": rfq_id, "status": "open", "created_at": now}


@router.post("/rfqs/{rfq_id}/select")
def select_supplier(rfq_id: str, supplier_id: str, buyer_id: str):
    """采购方选定供应商（中标）"""
    with _db()() as conn:
        rfq = conn.execute("SELECT * FROM marketplace_rfqs WHERE id = ?", (rfq_id,)).fetchone()
        if not rfq:
            raise HTTPException(status_code=404, detail="RFQ not found")
        if rfq["buyer_id"] != buyer_id:
            raise HTTPException(status_code=403, detail="Only buyer can select supplier")

        # 找 accepted 报价
        quote = conn.execute(
            "SELECT * FROM marketplace_quotes WHERE rfq_id = ? AND supplier_id = ? AND status IN ('pending', 'shortlisted')",
            (rfq_id, supplier_id)
        ).fetchone()
        if not quote:
            raise HTTPException(status_code=404, detail="Quote not found")

        # 更新：accept 中标 + reject 其他
        conn.execute("UPDATE marketplace_quotes SET status = 'rejected' WHERE rfq_id = ? AND id != ?", (rfq_id, quote["id"]))
        conn.execute("UPDATE marketplace_quotes SET status = 'accepted' WHERE id = ?", (quote["id"],))
        conn.execute("UPDATE marketplace_rfqs SET status = 'contracted', winner_supplier_id = ?, updated_at = ? WHERE id = ?",
                     (supplier_id, _now_iso(), rfq_id))
        conn.commit()

    # 公正记录
    _record(rfq_id, "supplier_selected",
            [buyer_id, supplier_id, "agent-arbitrator-01"],
            f"采购方选定 {supplier_id}，中标价 {quote['unit_price']}，触发 9 阶段执行流程")
    _record(rfq_id, "contract_signed",
            [buyer_id, supplier_id, "agent-arbitrator-01"],
            f"合同签订：{rfq['title']}，总价 {rfq['currency']} {quote['unit_price'] * rfq['quantity']:.2f}")

    # 自动创建 9 阶段
    _create_9_stages(rfq_id, supplier_id)

    return {"rfq_id": rfq_id, "supplier_id": supplier_id, "quote_id": quote["id"], "status": "contracted"}


@router.post("/rfqs/{rfq_id}/cancel")
def cancel_rfq(rfq_id: str, buyer_id: str):
    """取消 RFQ"""
    with _db()() as conn:
        row = conn.execute("SELECT * FROM marketplace_rfqs WHERE id = ?", (rfq_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="RFQ not found")
        if row["buyer_id"] != buyer_id:
            raise HTTPException(status_code=403, detail="Only buyer can cancel")
        conn.execute("UPDATE marketplace_rfqs SET status = 'cancelled', updated_at = ? WHERE id = ?", (_now_iso(), rfq_id))
        conn.commit()

    _record(rfq_id, "dispute", [buyer_id, "agent-arbitrator-01"], f"采购方取消 RFQ：{row['title']}")
    return {"rfq_id": rfq_id, "status": "cancelled"}


@router.get("/rfqs/{rfq_id}/quotes")
def list_quotes(rfq_id: str):
    """列出某 RFQ 的所有报价"""
    with _db()() as conn:
        rows = conn.execute("SELECT * FROM marketplace_quotes WHERE rfq_id = ? ORDER BY unit_price ASC", (rfq_id,)).fetchall()
    return {"quotes": [_row_to_dict(r) for r in rows], "total": len(rows)}


@router.post("/quotes")
def submit_quote(req: SubmitQuoteRequest):
    """供应商提交报价"""
    qid = _gen_id("q")
    with _db()() as conn:
        # 检查 RFQ 存在 + 状态允许
        rfq = conn.execute("SELECT * FROM marketplace_rfqs WHERE id = ?", (req.rfq_id,)).fetchone()
        if not rfq:
            raise HTTPException(status_code=404, detail="RFQ not found")
        if rfq["status"] not in ("open", "quoting", "negotiating"):
            raise HTTPException(status_code=400, detail=f"RFQ status is {rfq['status']}, cannot accept quotes")

        conn.execute("""
            INSERT INTO marketplace_quotes(id, rfq_id, supplier_id, unit_price, moq, lead_time_days,
                payment_term, factory_certs, notes, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?, 'pending', ?)
        """, (
            qid, req.rfq_id, req.supplier_id, req.unit_price, req.moq, req.lead_time_days,
            req.payment_term, json.dumps(req.factory_certs), req.notes, _now_iso(),
        ))

        # 状态 → quoting
        if rfq["status"] == "open":
            conn.execute("UPDATE marketplace_rfqs SET status = 'quoting', updated_at = ? WHERE id = ?", (_now_iso(), req.rfq_id))

        conn.commit()

    _record(req.rfq_id, "quote_submitted",
            [req.supplier_id, "agent-arbitrator-01"],
            f"{req.supplier_id} 报价：{req.unit_price}/件，交期 {req.lead_time_days} 天")

    return {"quote_id": qid, "status": "pending"}


@router.post("/quotes/{quote_id}/shortlist")
def shortlist_quote(quote_id: str):
    """采购方把报价加入短名单"""
    with _db()() as conn:
        q = conn.execute("SELECT * FROM marketplace_quotes WHERE id = ?", (quote_id,)).fetchone()
        if not q:
            raise HTTPException(status_code=404, detail="Quote not found")
        conn.execute("UPDATE marketplace_quotes SET status = 'shortlisted' WHERE id = ?", (quote_id,))
        conn.commit()

    _record(q["rfq_id"], "quote_shortlisted",
            [q["supplier_id"], "agent-arbitrator-01"],
            f"{q['supplier_id']} 报价进入短名单（{q['unit_price']}/件）")

    return {"quote_id": quote_id, "status": "shortlisted"}


@router.post("/quotes/{quote_id}/accept")
def accept_quote(quote_id: str, buyer_id: str):
    """采购方接受报价（中标）"""
    with _db()() as conn:
        q = conn.execute("SELECT * FROM marketplace_quotes WHERE id = ?", (quote_id,)).fetchone()
        if not q:
            raise HTTPException(status_code=404, detail="Quote not found")
        rfq = conn.execute("SELECT * FROM marketplace_rfqs WHERE id = ?", (q["rfq_id"],)).fetchone()
        if rfq["buyer_id"] != buyer_id:
            raise HTTPException(status_code=403, detail="Only buyer can accept")

        # accept 选中的 + reject 其他
        conn.execute("UPDATE marketplace_quotes SET status = 'rejected' WHERE rfq_id = ? AND id != ?", (q["rfq_id"], quote_id))
        conn.execute("UPDATE marketplace_quotes SET status = 'accepted' WHERE id = ?", (quote_id,))
        conn.execute("UPDATE marketplace_rfqs SET status = 'contracted', winner_supplier_id = ?, updated_at = ? WHERE id = ?",
                     (q["supplier_id"], _now_iso(), q["rfq_id"]))
        conn.commit()

    _record(q["rfq_id"], "supplier_selected",
            [buyer_id, q["supplier_id"], "agent-arbitrator-01"],
            f"采购方选定 {q['supplier_id']}，中标价 {q['unit_price']}")
    _record(q["rfq_id"], "contract_signed",
            [buyer_id, q["supplier_id"], "agent-arbitrator-01"],
            f"合同签订：{rfq['title']}")

    _create_9_stages(q["rfq_id"], q["supplier_id"])

    return {"quote_id": quote_id, "status": "accepted"}


@router.post("/quotes/{quote_id}/reject")
def reject_quote(quote_id: str):
    """采购方拒绝报价"""
    with _db()() as conn:
        q = conn.execute("SELECT * FROM marketplace_quotes WHERE id = ?", (quote_id,)).fetchone()
        if not q:
            raise HTTPException(status_code=404, detail="Quote not found")
        conn.execute("UPDATE marketplace_quotes SET status = 'rejected' WHERE id = ?", (quote_id,))
        conn.commit()

    _record(q["rfq_id"], "quote_shortlisted",
            [q["supplier_id"], "agent-arbitrator-01"],
            f"{q['supplier_id']} 报价未通过筛选（{q['unit_price']}/件）")

    return {"quote_id": quote_id, "status": "rejected"}


@router.get("/rfqs/{rfq_id}/stages")
def list_stages(rfq_id: str):
    """列出 9 阶段执行"""
    with _db()() as conn:
        rows = conn.execute("SELECT * FROM marketplace_stages WHERE rfq_id = ? ORDER BY stage_order ASC", (rfq_id,)).fetchall()
    return {"stages": [_row_to_dict(r) for r in rows], "total": len(rows)}


@router.patch("/stages/{stage_id}")
def update_stage(stage_id: str, req: UpdateStageRequest):
    """更新阶段状态 / 进度"""
    with _db()() as conn:
        stage = conn.execute("SELECT * FROM marketplace_stages WHERE id = ?", (stage_id,)).fetchone()
        if not stage:
            raise HTTPException(status_code=404, detail="Stage not found")

        sets = []
        params = []
        if req.status is not None:
            sets.append("status = ?"); params.append(req.status)
        if req.progress is not None:
            sets.append("progress = ?"); params.append(max(0, min(100, req.progress)))
        if req.priority is not None:
            sets.append("priority = ?"); params.append(req.priority)
        if req.assignee_id is not None:
            sets.append("assignee_id = ?"); params.append(req.assignee_id)
        sets.append("updated_at = ?"); params.append(_now_iso())
        params.append(stage_id)

        conn.execute(f"UPDATE marketplace_stages SET {', '.join(sets)} WHERE id = ?", params)

        # 触发 RFQ 状态联动
        rfq_id = stage["rfq_id"]
        all_stages = conn.execute("SELECT * FROM marketplace_stages WHERE rfq_id = ? ORDER BY stage_order", (rfq_id,)).fetchall()
        completed = sum(1 for s in all_stages if s["status"] == "completed")
        if completed == len(all_stages):
            conn.execute("UPDATE marketplace_rfqs SET status = 'completed', updated_at = ? WHERE id = ?", (_now_iso(), rfq_id))
        elif completed > 0 and any(s["status"] == "in_progress" for s in all_stages):
            conn.execute("UPDATE marketplace_rfqs SET status = 'in_production', updated_at = ? WHERE id = ?", (_now_iso(), rfq_id))

        conn.commit()

    # 写记录
    if req.status == "completed":
        _record(stage["rfq_id"], "milestone_reached",
                [stage["assignee_id"] or "agent-arbitrator-01", "agent-arbitrator-01"],
                f"阶段完成：{stage['name']}")
    elif req.status == "in_progress" and stage["status"] != "in_progress":
        _record(stage["rfq_id"], "production_started" if stage["stage_key"] == "production" else "milestone_reached",
                [stage["assignee_id"] or "agent-arbitrator-01", "agent-arbitrator-01"],
                f"阶段启动：{stage['name']}")

    return {"stage_id": stage_id, "updated": True}


@router.get("/records")
def list_records(
    rfq_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
):
    """列出公正记录（支持 rfq_id / event_type 过滤）"""
    with _db()() as conn:
        q = "SELECT * FROM marketplace_records WHERE 1=1"
        params = []
        if rfq_id:
            q += " AND rfq_id = ?"
            params.append(rfq_id)
        if event_type:
            q += " AND event_type = ?"
            params.append(event_type)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
    return {"records": [_row_to_dict(r) for r in rows], "total": len(rows)}


@router.get("/stats")
def marketplace_stats():
    """Agent Marketplace 统计"""
    with _db()() as conn:
        agent_cnt     = conn.execute("SELECT COUNT(*) as cnt FROM marketplace_agents").fetchone()["cnt"]
        buyer_cnt     = conn.execute("SELECT COUNT(*) as cnt FROM marketplace_agents WHERE role='buyer'").fetchone()["cnt"]
        supplier_cnt  = conn.execute("SELECT COUNT(*) as cnt FROM marketplace_agents WHERE role='supplier'").fetchone()["cnt"]
        rfq_cnt       = conn.execute("SELECT COUNT(*) as cnt FROM marketplace_rfqs").fetchone()["cnt"]
        open_cnt      = conn.execute("SELECT COUNT(*) as cnt FROM marketplace_rfqs WHERE status='open'").fetchone()["cnt"]
        contracted    = conn.execute("SELECT COUNT(*) as cnt FROM marketplace_rfqs WHERE status IN ('contracted','in_production','shipping','delivered','completed')").fetchone()["cnt"]
        quote_cnt     = conn.execute("SELECT COUNT(*) as cnt FROM marketplace_quotes").fetchone()["cnt"]
        record_cnt    = conn.execute("SELECT COUNT(*) as cnt FROM marketplace_records").fetchone()["cnt"]
        total_value   = conn.execute("SELECT SUM(target_unit_price * quantity) as v FROM marketplace_rfqs").fetchone()["v"] or 0
        categories    = [r["product_category"] for r in conn.execute("SELECT DISTINCT product_category FROM marketplace_rfqs").fetchall()]

    return {
        "agents": {"total": agent_cnt, "buyers": buyer_cnt, "suppliers": supplier_cnt},
        "rfqs": {"total": rfq_cnt, "open": open_cnt, "contracted": contracted},
        "quotes": quote_cnt,
        "records": record_cnt,
        "total_value_usd": round(total_value, 2),
        "categories": categories,
    }


# ===== 初始化入口（被 server.py 在 init_db 末尾调用） =====

def init_marketplace():
    """v4.0 入口：迁移 + seed 演示数据"""
    try:
        _migrate_v40_marketplace()
        _seed_demo_data()
        _logger().info("✅ Agent Marketplace v4.0 tables + demo data ready")
    except Exception as e:
        _logger().warning(f"⚠️ Agent Marketplace init failed: {e}")
