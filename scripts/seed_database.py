#!/usr/bin/env python3
"""
LinkMoney 数据库填充脚本
=======================
1. 扩展工厂数据（目标 50+ 家）
2. 扩展产品数据（目标 300+ 个）
3. 所有邮箱统一为 kevin@coze.email
4. 重建 SQLite 数据库
"""

import json
import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
JSON_PATH = BASE_DIR / "data" / "database.json"
DB_PATH = BASE_DIR / "data" / "linkmoney.db"

# 统一邮箱
OVERRIDE_EMAIL = "kevin@coze.email"
OVERRIDE_PHONE = "+86-186-0000-0000"
OVERRIDE_WECHAT = "linkmoney-kefu"

# ===== 新增供应商数据 =====

NEW_SUPPLIERS = [
    # ===== 紧固件（新增 5 家）=====
    {
        "id": "hz-fastener-003",
        "name_zh": "杭州精工紧固件有限公司",
        "name_en": "Hangzhou Jinggong Fasteners Co., Ltd.",
        "location": {"city": "杭州", "province": "浙江", "port": "Ningbo"},
        "category": "fastener",
        "subcategories": ["bolt", "nut", "rivet", "custom"],
        "year_established": 2008,
        "employees": 180,
        "annual_revenue_usd": 25000000,
        "export_ratio": 0.75,
        "main_markets": ["US", "EU", "Korea"],
        "moq": 5000,
        "lead_time_days": {"standard": 18, "express": 8},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2027-06-30", "file": "/certs/hz-fastener-003/iso9001.pdf"},
            {"type": "CE", "valid_until": "2026-06-30", "file": "/certs/hz-fastener-003/ce.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "刘建国",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "yq-fastener-004",
        "name_zh": "乐清市力达紧固件有限公司",
        "name_en": "Yueqing Lida Fastener Co., Ltd.",
        "location": {"city": "乐清", "province": "浙江", "port": "Wenzhou"},
        "category": "fastener",
        "subcategories": ["screw", "bolt", "self-tapping"],
        "year_established": 2010,
        "employees": 120,
        "annual_revenue_usd": 18000000,
        "export_ratio": 0.70,
        "main_markets": ["EU", "Southeast Asia", "Middle East"],
        "moq": 5000,
        "lead_time_days": {"standard": 15, "express": 7},
        "certifications": [{"type": "ISO 9001", "valid_until": "2026-12-31", "file": "/certs/yq-fastener-004/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "陈伟",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "jx-fastener-005",
        "name_zh": "嘉兴市恒达标准件有限公司",
        "name_en": "Jiaxing Hengda Standard Parts Co., Ltd.",
        "location": {"city": "嘉兴", "province": "浙江", "port": "Shanghai"},
        "category": "fastener",
        "subcategories": ["washer", "spring", "pin", "clip"],
        "year_established": 2003,
        "employees": 250,
        "annual_revenue_usd": 32000000,
        "export_ratio": 0.80,
        "main_markets": ["US", "Japan", "Germany"],
        "moq": 10000,
        "lead_time_days": {"standard": 20, "express": 10},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2028-03-31", "file": "/certs/jx-fastener-005/iso9001.pdf"},
            {"type": "IATF 16949", "valid_until": "2027-09-30", "file": "/certs/jx-fastener-005/iatf16949.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "赵志强",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "nt-fastener-006",
        "name_zh": "南通市长江紧固件有限公司",
        "name_en": "Nantong Changjiang Fastener Co., Ltd.",
        "location": {"city": "南通", "province": "江苏", "port": "Shanghai"},
        "category": "fastener",
        "subcategories": ["bolt", "nut", "stud", "anchor"],
        "year_established": 2006,
        "employees": 200,
        "annual_revenue_usd": 28000000,
        "export_ratio": 0.65,
        "main_markets": ["EU", "US", "Australia"],
        "moq": 8000,
        "lead_time_days": {"standard": 18, "express": 9},
        "certifications": [{"type": "ISO 9001", "valid_until": "2027-01-31", "file": "/certs/nt-fastener-006/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "黄建军",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "dg-fastener-007",
        "name_zh": "东莞市金鹏螺丝有限公司",
        "name_en": "Dongguan Jinpeng Screw Co., Ltd.",
        "location": {"city": "东莞", "province": "广东", "port": "Shenzhen"},
        "category": "fastener",
        "subcategories": ["screw", "self-drilling", "chipboard", "drywall"],
        "year_established": 2012,
        "employees": 150,
        "annual_revenue_usd": 20000000,
        "export_ratio": 0.80,
        "main_markets": ["US", "Southeast Asia", "Africa"],
        "moq": 5000,
        "lead_time_days": {"standard": 12, "express": 5},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2027-08-31", "file": "/certs/dg-fastener-007/iso9001.pdf"},
            {"type": "RoHS", "valid_until": "2028-01-31", "file": "/certs/dg-fastener-007/rohs.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "周明",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },

    # ===== 电子元器件（新增 5 家）=====
    {
        "id": "sz-electronics-003",
        "name_zh": "深圳市芯联电子科技有限公司",
        "name_en": "Shenzhen Xinlian Electronic Technology Co., Ltd.",
        "location": {"city": "深圳", "province": "广东", "port": "Shenzhen"},
        "category": "electronics",
        "subcategories": ["connector", "cable", "PCB", "sensor"],
        "year_established": 2015,
        "employees": 300,
        "annual_revenue_usd": 60000000,
        "export_ratio": 0.90,
        "main_markets": ["US", "EU", "Japan", "Korea"],
        "moq": 1000,
        "lead_time_days": {"standard": 10, "express": 5},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2027-12-31", "file": "/certs/sz-electronics-003/iso9001.pdf"},
            {"type": "RoHS", "valid_until": "2027-12-31", "file": "/certs/sz-electronics-003/rohs.pdf"},
            {"type": "UL", "valid_until": "2027-06-30", "file": "/certs/sz-electronics-003/ul.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "林志鹏",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "dg-electronics-004",
        "name_zh": "东莞市辉达电子有限公司",
        "name_en": "Dongguan Huida Electronics Co., Ltd.",
        "location": {"city": "东莞", "province": "广东", "port": "Shenzhen"},
        "category": "electronics",
        "subcategories": ["LED", "display", "PCB assembly", "power supply"],
        "year_established": 2010,
        "employees": 450,
        "annual_revenue_usd": 80000000,
        "export_ratio": 0.85,
        "main_markets": ["US", "EU", "Southeast Asia"],
        "moq": 500,
        "lead_time_days": {"standard": 12, "express": 6},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2027-03-31", "file": "/certs/dg-electronics-004/iso9001.pdf"},
            {"type": "CE", "valid_until": "2027-03-31", "file": "/certs/dg-electronics-004/ce.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "何永强",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "gz-electronics-005",
        "name_zh": "广州天河电子元件有限公司",
        "name_en": "Guangzhou Tianhe Electronic Components Co., Ltd.",
        "location": {"city": "广州", "province": "广东", "port": "Guangzhou"},
        "category": "electronics",
        "subcategories": ["resistor", "capacitor", "inductor", "transformer"],
        "year_established": 2008,
        "employees": 220,
        "annual_revenue_usd": 35000000,
        "export_ratio": 0.75,
        "main_markets": ["EU", "US", "India"],
        "moq": 1000,
        "lead_time_days": {"standard": 15, "express": 7},
        "certifications": [{"type": "ISO 9001", "valid_until": "2026-11-30", "file": "/certs/gz-electronics-005/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "王建国",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "sz-electronics-006",
        "name_zh": "深圳华强北智能科技有限公司",
        "name_en": "Shenzhen Huaqiangbei Smart Tech Co., Ltd.",
        "location": {"city": "深圳", "province": "广东", "port": "Shenzhen"},
        "category": "electronics",
        "subcategories": ["IoT module", "sensor", "microcontroller", "wireless"],
        "year_established": 2018,
        "employees": 80,
        "annual_revenue_usd": 15000000,
        "export_ratio": 0.95,
        "main_markets": ["US", "EU", "Japan", "Southeast Asia"],
        "moq": 100,
        "lead_time_days": {"standard": 8, "express": 3},
        "certifications": [
            {"type": "FCC", "valid_until": "2027-06-30", "file": "/certs/sz-electronics-006/fcc.pdf"},
            {"type": "CE", "valid_until": "2027-06-30", "file": "/certs/sz-electronics-006/ce.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "杨帆",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "sh-electronics-007",
        "name_zh": "上海微电子科技有限公司",
        "name_en": "Shanghai Microelectronics Technology Co., Ltd.",
        "location": {"city": "上海", "province": "上海", "port": "Shanghai"},
        "category": "electronics",
        "subcategories": ["IC", "semiconductor", "wafer", "testing"],
        "year_established": 2014,
        "employees": 350,
        "annual_revenue_usd": 120000000,
        "export_ratio": 0.60,
        "main_markets": ["US", "Japan", "Korea", "EU"],
        "moq": 500,
        "lead_time_days": {"standard": 20, "express": 10},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2028-06-30", "file": "/certs/sh-electronics-007/iso9001.pdf"},
            {"type": "ISO 14001", "valid_until": "2027-12-31", "file": "/certs/sh-electronics-007/iso14001.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "张伟",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },

    # ===== 包装印刷（新增 3 家）=====
    {
        "id": "sd-packaging-003",
        "name_zh": "青岛市恒达包装有限公司",
        "name_en": "Qingdao Hengda Packaging Co., Ltd.",
        "location": {"city": "青岛", "province": "山东", "port": "Qingdao"},
        "category": "packaging",
        "subcategories": ["corrugated_box", "carton", "display", "kraft"],
        "year_established": 2009,
        "employees": 200,
        "annual_revenue_usd": 30000000,
        "export_ratio": 0.70,
        "main_markets": ["US", "EU", "Japan"],
        "moq": 5000,
        "lead_time_days": {"standard": 15, "express": 7},
        "certifications": [{"type": "ISO 9001", "valid_until": "2027-05-31", "file": "/certs/sd-packaging-003/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "马建国",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "sz-packaging-004",
        "name_zh": "深圳市精美印刷包装有限公司",
        "name_en": "Shenzhen Jingmei Printing & Packaging Co., Ltd.",
        "location": {"city": "深圳", "province": "广东", "port": "Shenzhen"},
        "category": "packaging",
        "subcategories": ["gift_box", "luxury", "printing", "label"],
        "year_established": 2011,
        "employees": 180,
        "annual_revenue_usd": 25000000,
        "export_ratio": 0.65,
        "main_markets": ["US", "EU", "Australia"],
        "moq": 2000,
        "lead_time_days": {"standard": 12, "express": 5},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2027-10-31", "file": "/certs/sz-packaging-004/iso9001.pdf"},
            {"type": "FSC", "valid_until": "2027-10-31", "file": "/certs/sz-packaging-004/fsc.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "吴志强",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "xm-packaging-005",
        "name_zh": "厦门市新源包装有限公司",
        "name_en": "Xiamen Xinyuan Packaging Co., Ltd.",
        "location": {"city": "厦门", "province": "福建", "port": "Xiamen"},
        "category": "packaging",
        "subcategories": ["food_packaging", "plastic_bag", "stand_up_pouch", "zipper"],
        "year_established": 2013,
        "employees": 150,
        "annual_revenue_usd": 22000000,
        "export_ratio": 0.75,
        "main_markets": ["EU", "US", "Southeast Asia"],
        "moq": 5000,
        "lead_time_days": {"standard": 10, "express": 5},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2027-08-31", "file": "/certs/xm-packaging-005/iso9001.pdf"},
            {"type": "FDA", "valid_until": "2026-12-31", "file": "/certs/xm-packaging-005/fda.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "徐志明",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },

    # ===== 五金制品（新增 3 家）=====
    {
        "id": "dg-hardware-003",
        "name_zh": "东莞市恒发五金制品有限公司",
        "name_en": "Dongguan Hengfa Hardware Products Co., Ltd.",
        "location": {"city": "东莞", "province": "广东", "port": "Shenzhen"},
        "category": "hardware",
        "subcategories": ["stamping", "die_casting", "machining", "spring"],
        "year_established": 2007,
        "employees": 280,
        "annual_revenue_usd": 35000000,
        "export_ratio": 0.80,
        "main_markets": ["US", "EU", "Japan"],
        "moq": 3000,
        "lead_time_days": {"standard": 15, "express": 7},
        "certifications": [{"type": "ISO 9001", "valid_until": "2027-04-30", "file": "/certs/dg-hardware-003/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "赵卫国",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "yj-hardware-004",
        "name_zh": "阳江市恒基五金刀具有限公司",
        "name_en": "Yangjiang Hengji Hardware & Cutlery Co., Ltd.",
        "location": {"city": "阳江", "province": "广东", "port": "Guangzhou"},
        "category": "hardware",
        "subcategories": ["kitchenware", "scissors", "knife", "tool"],
        "year_established": 2005,
        "employees": 400,
        "annual_revenue_usd": 50000000,
        "export_ratio": 0.90,
        "main_markets": ["US", "EU", "Middle East", "Southeast Asia"],
        "moq": 2000,
        "lead_time_days": {"standard": 15, "express": 7},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2027-09-30", "file": "/certs/yj-hardware-004/iso9001.pdf"},
            {"type": "FDA", "valid_until": "2027-06-30", "file": "/certs/yj-hardware-004/fda.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "李志华",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "yongkang-hardware-005",
        "name_zh": "永康市鑫源金属制品有限公司",
        "name_en": "Yongkang Xinyuan Metal Products Co., Ltd.",
        "location": {"city": "永康", "province": "浙江", "port": "Ningbo"},
        "category": "hardware",
        "subcategories": ["door_handle", "hinge", "lock", "bracket"],
        "year_established": 2004,
        "employees": 350,
        "annual_revenue_usd": 42000000,
        "export_ratio": 0.75,
        "main_markets": ["EU", "US", "Australia"],
        "moq": 3000,
        "lead_time_days": {"standard": 18, "express": 8},
        "certifications": [{"type": "ISO 9001", "valid_until": "2027-02-28", "file": "/certs/yongkang-hardware-005/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "张建国",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },

    # ===== 注塑模具（新增 3 家）=====
    {
        "id": "dg-injection-003",
        "name_zh": "东莞市精诚模具有限公司",
        "name_en": "Dongguan Jingcheng Mold Co., Ltd.",
        "location": {"city": "东莞", "province": "广东", "port": "Shenzhen"},
        "category": "injection_molding",
        "subcategories": ["precision_mold", "automotive_mold", "connector_mold", "overmolding"],
        "year_established": 2010,
        "employees": 200,
        "annual_revenue_usd": 38000000,
        "export_ratio": 0.70,
        "main_markets": ["US", "EU", "Japan"],
        "moq": 1000,
        "lead_time_days": {"standard": 25, "express": 12},
        "certifications": [{"type": "ISO 9001", "valid_until": "2027-11-30", "file": "/certs/dg-injection-003/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "郑志强",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "nb-injection-004",
        "name_zh": "宁波市新科注塑科技有限公司",
        "name_en": "Ningbo Xinke Injection Technology Co., Ltd.",
        "location": {"city": "宁波", "province": "浙江", "port": "Ningbo"},
        "category": "injection_molding",
        "subcategories": ["household", "appliance", "medical", "toy"],
        "year_established": 2012,
        "employees": 160,
        "annual_revenue_usd": 28000000,
        "export_ratio": 0.65,
        "main_markets": ["EU", "US", "Southeast Asia"],
        "moq": 2000,
        "lead_time_days": {"standard": 20, "express": 10},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2027-07-31", "file": "/certs/nb-injection-004/iso9001.pdf"},
            {"type": "ISO 13485", "valid_until": "2026-12-31", "file": "/certs/nb-injection-004/iso13485.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "孙志明",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "ks-injection-005",
        "name_zh": "昆山市鑫达注塑有限公司",
        "name_en": "Kunshan Xinda Injection Molding Co., Ltd.",
        "location": {"city": "昆山", "province": "江苏", "port": "Shanghai"},
        "category": "injection_molding",
        "subcategories": ["automotive_part", "electrical", "enclosure", "housing"],
        "year_established": 2008,
        "employees": 300,
        "annual_revenue_usd": 55000000,
        "export_ratio": 0.60,
        "main_markets": ["US", "EU", "Japan", "Korea"],
        "moq": 1000,
        "lead_time_days": {"standard": 22, "express": 11},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2028-01-31", "file": "/certs/ks-injection-005/iso9001.pdf"},
            {"type": "IATF 16949", "valid_until": "2027-06-30", "file": "/certs/ks-injection-005/iatf16949.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "高志远",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },

    # ===== 机械设备（新增 2 家）=====
    {
        "id": "cz-machinery-003",
        "name_zh": "常州市华工机械有限公司",
        "name_en": "Changzhou Huagong Machinery Co., Ltd.",
        "location": {"city": "常州", "province": "江苏", "port": "Shanghai"},
        "category": "machinery",
        "subcategories": ["CNC_machine", "lathe", "milling", "drilling"],
        "year_established": 2006,
        "employees": 500,
        "annual_revenue_usd": 90000000,
        "export_ratio": 0.55,
        "main_markets": ["EU", "US", "Southeast Asia", "India"],
        "moq": 1,
        "lead_time_days": {"standard": 45, "express": 30},
        "certifications": [
            {"type": "ISO 9001", "valid_until": "2027-12-31", "file": "/certs/cz-machinery-003/iso9001.pdf"},
            {"type": "CE", "valid_until": "2027-12-31", "file": "/certs/cz-machinery-003/ce.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "吴建国",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "foshan-machinery-004",
        "name_zh": "佛山市南方机械有限公司",
        "name_en": "Foshan Nanfang Machinery Co., Ltd.",
        "location": {"city": "佛山", "province": "广东", "port": "Guangzhou"},
        "category": "machinery",
        "subcategories": ["packaging_machine", "filling", "sealing", "labeling"],
        "year_established": 2009,
        "employees": 280,
        "annual_revenue_usd": 65000000,
        "export_ratio": 0.70,
        "main_markets": ["EU", "Southeast Asia", "Africa", "Middle East"],
        "moq": 1,
        "lead_time_days": {"standard": 35, "express": 20},
        "certifications": [{"type": "ISO 9001", "valid_until": "2027-08-31", "file": "/certs/foshan-machinery-004/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "刘志强",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },

    # ===== 纺织服装（新增 3 家）=====
    {
        "id": "nt-textile-003",
        "name_zh": "南通市天虹纺织有限公司",
        "name_en": "Nantong Tianhong Textile Co., Ltd.",
        "location": {"city": "南通", "province": "江苏", "port": "Shanghai"},
        "category": "textile",
        "subcategories": ["cotton", "polyester", "blended", "yarn"],
        "year_established": 2005,
        "employees": 600,
        "annual_revenue_usd": 100000000,
        "export_ratio": 0.80,
        "main_markets": ["EU", "US", "Southeast Asia", "Bangladesh"],
        "moq": 5000,
        "lead_time_days": {"standard": 20, "express": 10},
        "certifications": [
            {"type": "OEKO-TEX", "valid_until": "2027-06-30", "file": "/certs/nt-textile-003/oeko.pdf"},
            {"type": "ISO 9001", "valid_until": "2027-06-30", "file": "/certs/nt-textile-003/iso9001.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "何志明",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "hz-textile-004",
        "name_zh": "杭州市万事利丝绸有限公司",
        "name_en": "Hangzhou Wanshili Silk Co., Ltd.",
        "location": {"city": "杭州", "province": "浙江", "port": "Ningbo"},
        "category": "textile",
        "subcategories": ["silk", "scarf", "fabric", "garment"],
        "year_established": 2003,
        "employees": 400,
        "annual_revenue_usd": 70000000,
        "export_ratio": 0.85,
        "main_markets": ["EU", "US", "Japan", "Middle East"],
        "moq": 500,
        "lead_time_days": {"standard": 15, "express": 7},
        "certifications": [{"type": "OEKO-TEX", "valid_until": "2027-12-31", "file": "/certs/hz-textile-004/oeko.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "李丽华",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "gz-textile-005",
        "name_zh": "广州市白云服装有限公司",
        "name_en": "Guangzhou Baiyun Garment Co., Ltd.",
        "location": {"city": "广州", "province": "广东", "port": "Guangzhou"},
        "category": "textile",
        "subcategories": ["t-shirt", "jeans", "jacket", "uniform"],
        "year_established": 2010,
        "employees": 350,
        "annual_revenue_usd": 45000000,
        "export_ratio": 0.90,
        "main_markets": ["US", "EU", "Australia", "Canada"],
        "moq": 500,
        "lead_time_days": {"standard": 15, "express": 7},
        "certifications": [{"type": "ISO 9001", "valid_until": "2027-05-31", "file": "/certs/gz-textile-005/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "陈志强",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },

    # ===== 汽车零部件（新增 3 家）=====
    {
        "id": "nb-auto-001",
        "name_zh": "宁波市永达汽车零部件有限公司",
        "name_en": "Ningbo Yongda Auto Parts Co., Ltd.",
        "location": {"city": "宁波", "province": "浙江", "port": "Ningbo"},
        "category": "auto_parts",
        "subcategories": ["brake", "suspension", "bearing", "seal"],
        "year_established": 2005,
        "employees": 450,
        "annual_revenue_usd": 80000000,
        "export_ratio": 0.75,
        "main_markets": ["US", "EU", "Japan", "Korea"],
        "moq": 1000,
        "lead_time_days": {"standard": 20, "express": 10},
        "certifications": [
            {"type": "IATF 16949", "valid_until": "2027-12-31", "file": "/certs/nb-auto-001/iatf16949.pdf"},
            {"type": "ISO 9001", "valid_until": "2027-12-31", "file": "/certs/nb-auto-001/iso9001.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "周志远",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "wz-auto-002",
        "name_zh": "温州市瑞安汽车配件有限公司",
        "name_en": "Wenzhou Ruian Auto Parts Co., Ltd.",
        "location": {"city": "温州", "province": "浙江", "port": "Wenzhou"},
        "category": "auto_parts",
        "subcategories": ["filter", "pump", "valve", "sensor"],
        "year_established": 2008,
        "employees": 300,
        "annual_revenue_usd": 55000000,
        "export_ratio": 0.80,
        "main_markets": ["EU", "US", "Middle East", "South America"],
        "moq": 500,
        "lead_time_days": {"standard": 18, "express": 8},
        "certifications": [
            {"type": "IATF 16949", "valid_until": "2027-08-31", "file": "/certs/wz-auto-002/iatf16949.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "黄志明",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "sh-auto-003",
        "name_zh": "上海博世汽车科技有限公司",
        "name_en": "Shanghai Bosch Auto Technology Co., Ltd.",
        "location": {"city": "上海", "province": "上海", "port": "Shanghai"},
        "category": "auto_parts",
        "subcategories": ["ECU", "injector", "turbo", "sensor"],
        "year_established": 2012,
        "employees": 550,
        "annual_revenue_usd": 150000000,
        "export_ratio": 0.50,
        "main_markets": ["EU", "US", "Japan"],
        "moq": 100,
        "lead_time_days": {"standard": 25, "express": 12},
        "certifications": [
            {"type": "IATF 16949", "valid_until": "2028-03-31", "file": "/certs/sh-auto-003/iatf16949.pdf"},
            {"type": "ISO 14001", "valid_until": "2027-12-31", "file": "/certs/sh-auto-003/iso14001.pdf"},
        ],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "赵志华",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },

    # ===== 家具家居（新增 2 家）=====
    {
        "id": "foshan-furniture-001",
        "name_zh": "佛山市顺德家具有限公司",
        "name_en": "Foshan Shunde Furniture Co., Ltd.",
        "location": {"city": "佛山", "province": "广东", "port": "Guangzhou"},
        "category": "furniture",
        "subcategories": ["sofa", "bed", "table", "chair"],
        "year_established": 2006,
        "employees": 500,
        "annual_revenue_usd": 70000000,
        "export_ratio": 0.80,
        "main_markets": ["US", "EU", "Middle East", "Southeast Asia"],
        "moq": 50,
        "lead_time_days": {"standard": 30, "express": 15},
        "certifications": [{"type": "ISO 9001", "valid_until": "2027-09-30", "file": "/certs/foshan-furniture-001/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "梁志伟",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
    {
        "id": "hz-furniture-002",
        "name_zh": "杭州市佐曼家居有限公司",
        "name_en": "Hangzhou Zuoman Home Co., Ltd.",
        "location": {"city": "杭州", "province": "浙江", "port": "Ningbo"},
        "category": "furniture",
        "subcategories": ["outdoor", "garden", "rattan", "umbrella"],
        "year_established": 2011,
        "employees": 250,
        "annual_revenue_usd": 35000000,
        "export_ratio": 0.85,
        "main_markets": ["EU", "US", "Australia"],
        "moq": 100,
        "lead_time_days": {"standard": 25, "express": 12},
        "certifications": [{"type": "ISO 9001", "valid_until": "2027-04-30", "file": "/certs/hz-furniture-002/iso9001.pdf"}],
        "agent_skill_installed": False,
        "skill_mcp_endpoint": None,
        "skill_installs": 0,
        "contact_person": "王丽",
        "email": OVERRIDE_EMAIL,
        "phone": OVERRIDE_PHONE,
        "wechat": OVERRIDE_WECHAT,
    },
]


def main():
    print("=" * 60)
    print("  LinkMoney 数据库填充脚本")
    print("=" * 60)

    # 读取现有数据
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    old_count = len(data["suppliers"])
    print(f"\n现有供应商: {old_count} 家")

    # 更新现有供应商的邮箱
    for s in data["suppliers"]:
        s["email"] = OVERRIDE_EMAIL
        s["phone"] = OVERRIDE_PHONE
        s["wechat"] = OVERRIDE_WECHAT

    # 更新现有采购方的邮箱
    for b in data.get("overseas_buyers", []):
        b["email"] = OVERRIDE_EMAIL
        if "contact_email" in b:
            b["contact_email"] = OVERRIDE_EMAIL

    # 添加新供应商（去重，避免重复添加）
    existing_ids = {s["id"] for s in data["suppliers"]}
    added_count = 0
    for new_s in NEW_SUPPLIERS:
        if new_s["id"] not in existing_ids:
            data["suppliers"].append(new_s)
            added_count += 1

    # 最终去重保险
    seen_ids = set()
    unique_suppliers = []
    for s in data["suppliers"]:
        if s["id"] not in seen_ids:
            seen_ids.add(s["id"])
            unique_suppliers.append(s)
    data["suppliers"] = unique_suppliers

    print(f"新增供应商: {added_count} 家")
    print(f"总计供应商: {len(data['suppliers'])} 家")

    # 统计品类
    categories = set(s["category"] for s in data["suppliers"])
    print(f"覆盖品类: {len(categories)} 个 → {sorted(categories)}")

    # 更新版本
    data["version"] = "2.1.0"
    data["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    # 写回 database.json
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n数据库 JSON 已更新: {JSON_PATH}")

    # 重建 SQLite 数据库
    print(f"\n重建 SQLite 数据库...")

    # 备份旧数据库
    if DB_PATH.exists():
        backup_path = DB_PATH.with_suffix(".db.backup")
        os.rename(DB_PATH, backup_path)
        print(f"  旧数据库已备份: {backup_path}")

    # 导入 server.py 的 init_db 逻辑
    sys.path.insert(0, str(BASE_DIR / "api"))
    from server import init_db

    init_db()
    print(f"  新数据库已创建: {DB_PATH}")

    # 统计
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    supplier_count = conn.execute("SELECT COUNT(*) as cnt FROM suppliers").fetchone()["cnt"]
    product_count = conn.execute("SELECT COUNT(*) as cnt FROM products").fetchone()["cnt"]
    buyer_count = conn.execute("SELECT COUNT(*) as cnt FROM overseas_buyers").fetchone()["cnt"]
    conn.close()

    print(f"\n{'=' * 60}")
    print(f"  数据库填充完成！")
    print(f"  供应商: {supplier_count} 家")
    print(f"  产品:   {product_count} 个")
    print(f"  采购方: {buyer_count} 个")
    print(f"  所有邮箱 → {OVERRIDE_EMAIL}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()