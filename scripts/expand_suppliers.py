#!/usr/bin/env python3
"""
LinkMoney 供应商扩充脚本
========================
读取 data/database.json（当前 51 家工厂），生成 150 家新工厂覆盖 8 大中国产业带，
备份原文件后写入新数据，并打印统计信息。

用法:
    python3 scripts/expand_suppliers.py

无外部依赖，仅使用 Python 标准库。
"""

import json
import random
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# ====================================================================
# 路径与常量
# ====================================================================

BASE_DIR = Path(__file__).resolve().parent.parent
JSON_PATH = BASE_DIR / "data" / "database.json"

RANDOM_SEED = 20260618
random.seed(RANDOM_SEED)

NEW_SUPPLIER_COUNT = 150

# ====================================================================
# 数据池
# ====================================================================

# 字号 (中文, 拼音)
TRADE_NAMES = [
    ("永达", "Yongda"), ("金泰", "Jintai"), ("宏业", "Hongye"),
    ("德盛", "Desheng"), ("正大", "Zhengda"), ("华丰", "Huafeng"),
    ("东方", "Dongfang"), ("恒泰", "Hengtai"), ("兴达", "Xingda"),
    ("利达", "Lida"), ("万达", "Wanda"), ("金龙", "Jinlong"),
    ("凤凰", "Fenghuang"), ("长城", "Changcheng"), ("航天", "Hangtian"),
    ("中信", "Zhongxin"), ("华润", "Huarun"), ("中达", "Zhongda"),
    ("永盛", "Yongsheng"), ("宏达", "Hongda"), ("金鹏", "Jinpeng"),
    ("永固", "Yonggu"), ("精工", "Jinggong"), ("恒发", "Hengfa"),
    ("恒基", "Hengji"), ("鑫源", "Xinyuan"), ("新科", "Xinke"),
    ("精诚", "Jingcheng"), ("华工", "Huagong"), ("南方", "Nanfang"),
    ("天虹", "Tianhong"), ("万事利", "Wanshili"), ("白云", "Baiyun"),
    ("长江", "Changjiang"), ("辉达", "Huida"), ("芯联", "Xinlian"),
    ("新源", "Xinyuan"), ("精美", "Jingmei"), ("力达", "Lida"),
    ("佐曼", "Zuoman"), ("博世", "Boshi"), ("瑞安", "Ruian"),
    ("顺德", "Shunde"), ("永昌", "Yongchang"), ("金鹰", "Jinying"),
    ("宏图", "Hongtu"), ("大业", "Daye"), ("兴业", "Xingye"),
    ("立达", "Lida"), ("通达", "Tongda"), ("远东", "Yuandong"),
    ("金海", "Jinhai"), ("海天", "Haitian"), ("泰山", "Taishan"),
    ("华山", "Huashan"), ("昆仑", "Kunlun"), ("珠江", "Zhujiang"),
    ("黄海", "Huanghai"), ("东海", "Donghai"), ("振兴", "Zhenxing"),
    ("腾飞", "Tengfei"), ("凯达", "Kaida"), ("荣盛", "Rongsheng"),
    ("富康", "Fukang"), ("安达", "Anda"), ("顺达", "Shunda"),
    ("盛达", "Shengda"), ("恒通", "Hengtong"), ("金辉", "Jinhui"),
    ("伟业", "Weiye"), ("昌盛", "Changsheng"), ("鸿运", "Hongyun"),
]

SURNAMES = ["王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
            "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
            "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧"]

GIVEN_NAMES = ["建国", "志强", "志明", "志远", "志华", "卫国", "丽华", "志伟",
               "永强", "志鹏", "伟", "明", "强", "华", "军", "波", "涛",
               "磊", "鹏", "辉", "杰", "斌", "超", "勇", "丽", "艳", "敏",
               "静", "芳", "燕", "婷", "玲", "梅", "兰", "英", "刚", "平",
               "海", "林", "鑫", "宇", "浩", "晨", "帆", "翔"]

PHONE_PREFIXES = ["186", "188", "139", "137", "135", "136", "138",
                  "158", "159", "152", "150", "187", "183", "131"]

CERT_TYPES = ["ISO 9001", "CE", "RoHS", "FDA", "REACH", "SGS"]

MAIN_MARKETS = ["US", "EU", "Japan", "Southeast Asia",
                "Middle East", "South America", "Africa", "Australia"]

LANG_OPTIONS = [
    ["zh", "en"],
    ["zh", "en", "ja"],
    ["zh", "en", "de"],
    ["zh", "en", "es"],
]

# 品类 → ID 后缀
CAT_TO_SUFFIX = {
    "fastener": "fastener",
    "hardware": "hardware",
    "electronics": "electronics",
    "injection_molding": "injection",
    "machinery": "machinery",
    "textile": "textile",
    "packaging": "packaging",
    "auto_parts": "auto",
    "furniture": "furniture",
}

# ====================================================================
# 产业带配置
# ====================================================================

BELTS = [
    # 1. 浙江海盐 — 紧固件之都
    {
        "name": "浙江海盐", "prefix": "hy",
        "city": "海盐", "province": "浙江", "port": "Shanghai",
        "distribution": [("fastener", 25)],
        "subcategories": {
            "fastener": [
                ["bolt", "nut", "washer", "screw"],
                ["bolt", "nut", "rivet", "stud"],
                ["screw", "self_tapping", "self_drilling", "drywall"],
                ["washer", "spring", "pin", "clip"],
                ["bolt", "nut", "anchor", "stud"],
                ["nut", "bolt", "washer", "threaded_rod"],
            ],
        },
        "name_zh": {
            "fastener": [
                "海盐县{trade}紧固件有限公司",
                "海盐{trade}标准件股份有限公司",
                "海盐县{trade}紧固件制造有限公司",
                "嘉兴市海盐{trade}紧固件有限公司",
            ],
        },
        "name_en": {
            "fastener": [
                "Haiyan {trade_en} Fastener Co., Ltd.",
                "Haiyan {trade_en} Standard Parts Co., Ltd.",
            ],
        },
    },
    # 2. 浙江宁波 — 五金/塑料/文具
    {
        "name": "浙江宁波", "prefix": "nb",
        "city": "宁波", "province": "浙江", "port": "Ningbo",
        "distribution": [("hardware", 8), ("injection_molding", 6), ("packaging", 6)],
        "subcategories": {
            "hardware": [
                ["stamping", "die_casting", "machining", "bracket"],
                ["door_handle", "hinge", "lock", "bracket"],
                ["kitchenware", "scissors", "knife", "tool"],
            ],
            "injection_molding": [
                ["household", "appliance", "toy", "container"],
                ["precision_mold", "overmolding", "insert_mold", "custom"],
            ],
            "packaging": [
                ["gift_box", "printing", "label", "carton"],
                ["stationery", "pen", "folder", "notebook"],
            ],
        },
        "name_zh": {
            "hardware": [
                "宁波市{trade}五金制品有限公司",
                "宁波{trade}金属制品有限公司",
            ],
            "injection_molding": [
                "宁波市{trade}塑料科技有限公司",
                "宁波{trade}注塑制品有限公司",
            ],
            "packaging": [
                "宁波市{trade}文具用品有限公司",
                "宁波{trade}包装制品有限公司",
            ],
        },
        "name_en": {
            "hardware": [
                "Ningbo {trade_en} Hardware Products Co., Ltd.",
                "Ningbo {trade_en} Metal Products Co., Ltd.",
            ],
            "injection_molding": [
                "Ningbo {trade_en} Plastic Technology Co., Ltd.",
                "Ningbo {trade_en} Injection Products Co., Ltd.",
            ],
            "packaging": [
                "Ningbo {trade_en} Stationery Co., Ltd.",
                "Ningbo {trade_en} Packaging Products Co., Ltd.",
            ],
        },
    },
    # 3. 广东东莞 — 电子/模具/五金
    {
        "name": "广东东莞", "prefix": "dg",
        "city": "东莞", "province": "广东", "port": "Shenzhen",
        "distribution": [("electronics", 10), ("injection_molding", 8), ("hardware", 7)],
        "subcategories": {
            "electronics": [
                ["connector", "cable", "PCB", "sensor"],
                ["LED", "display", "power_supply", "module"],
                ["resistor", "capacitor", "inductor", "transformer"],
            ],
            "injection_molding": [
                ["precision_mold", "automotive_mold", "connector_mold", "overmolding"],
                ["enclosure", "housing", "bezel", "custom"],
            ],
            "hardware": [
                ["stamping", "die_casting", "machining", "spring"],
                ["screw", "nut", "rivet", "pin"],
            ],
        },
        "name_zh": {
            "electronics": [
                "东莞市{trade}电子科技有限公司",
                "东莞{trade}精密电子有限公司",
            ],
            "injection_molding": [
                "东莞市{trade}模具有限公司",
                "东莞{trade}精密模具科技有限公司",
            ],
            "hardware": [
                "东莞市{trade}精密五金有限公司",
                "东莞{trade}五金制品有限公司",
            ],
        },
        "name_en": {
            "electronics": [
                "Dongguan {trade_en} Electronic Technology Co., Ltd.",
                "Dongguan {trade_en} Precision Electronics Co., Ltd.",
            ],
            "injection_molding": [
                "Dongguan {trade_en} Mold Co., Ltd.",
                "Dongguan {trade_en} Precision Mold Technology Co., Ltd.",
            ],
            "hardware": [
                "Dongguan {trade_en} Precision Hardware Co., Ltd.",
                "Dongguan {trade_en} Hardware Products Co., Ltd.",
            ],
        },
    },
    # 4. 广东佛山 — 家具/建材/陶瓷
    {
        "name": "广东佛山", "prefix": "fs",
        "city": "佛山", "province": "广东", "port": "Guangzhou",
        "distribution": [("furniture", 8), ("hardware", 5), ("machinery", 5)],
        "subcategories": {
            "furniture": [
                ["sofa", "bed", "table", "chair"],
                ["office_chair", "desk", "cabinet", "shelf"],
                ["outdoor", "garden", "rattan", "umbrella"],
            ],
            "hardware": [
                ["hinge", "handle", "lock", "bracket"],
                ["door_handle", "knob", "stopper", "catch"],
            ],
            "machinery": [
                ["packaging_machine", "filling", "sealing", "labeling"],
                ["woodworking", "cutting", "drilling", "sanding"],
            ],
        },
        "name_zh": {
            "furniture": [
                "佛山市{trade}家具有限公司",
                "佛山{trade}金属家具有限公司",
                "佛山市顺德区{trade}家具制造有限公司",
            ],
            "hardware": [
                "佛山市{trade}五金制品有限公司",
                "佛山{trade}建材五金有限公司",
            ],
            "machinery": [
                "佛山市{trade}机械有限公司",
                "佛山{trade}木工机械有限公司",
            ],
        },
        "name_en": {
            "furniture": [
                "Foshan {trade_en} Furniture Co., Ltd.",
                "Foshan {trade_en} Metal Furniture Co., Ltd.",
            ],
            "hardware": [
                "Foshan {trade_en} Hardware Products Co., Ltd.",
                "Foshan {trade_en} Building Materials Hardware Co., Ltd.",
            ],
            "machinery": [
                "Foshan {trade_en} Machinery Co., Ltd.",
                "Foshan {trade_en} Woodworking Machinery Co., Ltd.",
            ],
        },
    },
    # 5. 江苏苏州 — 电子/机械/精密五金
    {
        "name": "江苏苏州", "prefix": "su",
        "city": "苏州", "province": "江苏", "port": "Shanghai",
        "distribution": [("electronics", 7), ("machinery", 7), ("hardware", 6)],
        "subcategories": {
            "electronics": [
                ["connector", "cable", "PCB", "sensor"],
                ["IC", "semiconductor", "testing", "module"],
                ["PCB_assembly", "SMT", "testing", "box_build"],
            ],
            "machinery": [
                ["CNC_machine", "lathe", "milling", "drilling"],
                ["automation", "robot", "conveyor", "controller"],
            ],
            "hardware": [
                ["precision_machining", "stamping", "grinding", "turning"],
                ["screw", "nut", "washer", "pin"],
            ],
        },
        "name_zh": {
            "electronics": [
                "苏州市{trade}电子科技有限公司",
                "苏州{trade}精密电子有限公司",
            ],
            "machinery": [
                "苏州市{trade}精密机械有限公司",
                "苏州{trade}自动化设备有限公司",
            ],
            "hardware": [
                "苏州市{trade}精密五金有限公司",
                "苏州{trade}金属制品有限公司",
            ],
        },
        "name_en": {
            "electronics": [
                "Suzhou {trade_en} Electronic Technology Co., Ltd.",
                "Suzhou {trade_en} Precision Electronics Co., Ltd.",
            ],
            "machinery": [
                "Suzhou {trade_en} Precision Machinery Co., Ltd.",
                "Suzhou {trade_en} Automation Equipment Co., Ltd.",
            ],
            "hardware": [
                "Suzhou {trade_en} Precision Hardware Co., Ltd.",
                "Suzhou {trade_en} Metal Products Co., Ltd.",
            ],
        },
    },
    # 6. 山东青岛 — 汽配/纺织/家电
    {
        "name": "山东青岛", "prefix": "qd",
        "city": "青岛", "province": "山东", "port": "Qingdao",
        "distribution": [("auto_parts", 7), ("textile", 5), ("machinery", 5)],
        "subcategories": {
            "auto_parts": [
                ["brake", "suspension", "bearing", "seal"],
                ["filter", "pump", "valve", "sensor"],
                ["engine_part", "transmission", "exhaust", "cooling"],
            ],
            "textile": [
                ["cotton", "polyester", "blended", "yarn"],
                ["fabric", "knitting", "weaving", "dyeing"],
            ],
            "machinery": [
                ["home_appliance", "assembly_line", "conveyor", "testing"],
                ["welding", "cutting", "stamping", "forming"],
            ],
        },
        "name_zh": {
            "auto_parts": [
                "青岛{trade}汽车配件有限公司",
                "青岛{trade}汽车零部件制造有限公司",
            ],
            "textile": [
                "青岛市{trade}纺织有限公司",
                "青岛{trade}纺织科技有限公司",
            ],
            "machinery": [
                "青岛市{trade}机械设备有限公司",
                "青岛{trade}智能装备有限公司",
            ],
        },
        "name_en": {
            "auto_parts": [
                "Qingdao {trade_en} Auto Parts Co., Ltd.",
                "Qingdao {trade_en} Auto Components Manufacturing Co., Ltd.",
            ],
            "textile": [
                "Qingdao {trade_en} Textile Co., Ltd.",
                "Qingdao {trade_en} Textile Technology Co., Ltd.",
            ],
            "machinery": [
                "Qingdao {trade_en} Machinery Equipment Co., Ltd.",
                "Qingdao {trade_en} Intelligent Equipment Co., Ltd.",
            ],
        },
    },
    # 7. 福建晋江 — 鞋材/纺织/包装
    {
        "name": "福建晋江", "prefix": "jj",
        "city": "晋江", "province": "福建", "port": "Xiamen",
        "distribution": [("textile", 6), ("packaging", 5), ("injection_molding", 4)],
        "subcategories": {
            "textile": [
                ["shoe_material", "upper", "sole", "lining"],
                ["knitting", "yarn", "fabric", "elastic"],
                ["webbing", "strap", "ribbon", "tape"],
            ],
            "packaging": [
                ["shoe_box", "gift_box", "display", "printing"],
                ["plastic_bag", "stand_up_pouch", "zipper", "label"],
            ],
            "injection_molding": [
                ["shoe_component", "sole_mold", "accessory", "custom"],
                ["household", "container", "bucket", "custom"],
            ],
        },
        "name_zh": {
            "textile": [
                "晋江市{trade}纺织有限公司",
                "福建{trade}鞋材有限公司",
                "晋江{trade}纺织科技有限公司",
            ],
            "packaging": [
                "晋江市{trade}包装有限公司",
                "福建{trade}包装制品有限公司",
            ],
            "injection_molding": [
                "晋江市{trade}塑业有限公司",
                "福建{trade}注塑科技有限公司",
            ],
        },
        "name_en": {
            "textile": [
                "Jinjiang {trade_en} Textile Co., Ltd.",
                "Fujian {trade_en} Shoe Material Co., Ltd.",
            ],
            "packaging": [
                "Jinjiang {trade_en} Packaging Co., Ltd.",
                "Fujian {trade_en} Packaging Products Co., Ltd.",
            ],
            "injection_molding": [
                "Jinjiang {trade_en} Plastic Industry Co., Ltd.",
                "Fujian {trade_en} Injection Technology Co., Ltd.",
            ],
        },
    },
    # 8. 河北邢台 — 紧固件/标准件/轴承
    {
        "name": "河北邢台", "prefix": "xt",
        "city": "邢台", "province": "河北", "port": "Tianjin",
        "distribution": [("fastener", 6), ("hardware", 4)],
        "subcategories": {
            "fastener": [
                ["bolt", "nut", "washer", "screw"],
                ["standard_part", "bearing", "stud", "rivet"],
                ["threaded_rod", "anchor", "bolt", "nut"],
            ],
            "hardware": [
                ["bearing", "standard_part", "machining", "stamping"],
                ["screw", "nut", "bolt", "washer"],
            ],
        },
        "name_zh": {
            "fastener": [
                "邢台{trade}紧固件制造有限公司",
                "河北{trade}标准件有限公司",
                "邢台市{trade}紧固件有限公司",
            ],
            "hardware": [
                "邢台{trade}轴承有限公司",
                "河北{trade}标准件制造有限公司",
            ],
        },
        "name_en": {
            "fastener": [
                "Xingtai {trade_en} Fastener Manufacturing Co., Ltd.",
                "Hebei {trade_en} Standard Parts Co., Ltd.",
            ],
            "hardware": [
                "Xingtai {trade_en} Bearing Co., Ltd.",
                "Hebei {trade_en} Standard Parts Manufacturing Co., Ltd.",
            ],
        },
    },
]


# ====================================================================
# 辅助函数
# ====================================================================

def random_phone():
    """生成 +86-1xx-xxxx-xxxx 格式手机号，后 8 位非全 0。"""
    prefix = random.choice(PHONE_PREFIXES)
    while True:
        middle = random.randint(1000, 9999)
        last4 = random.randint(1000, 9999)
        if not (middle == 0 and last4 == 0):
            break
    return f"+86-{prefix}-{middle:04d}-{last4:04d}"


def random_contact_person():
    return random.choice(SURNAMES) + random.choice(GIVEN_NAMES)


def random_created_at():
    """2026-01-01 到 2026-06-17 之间随机时间。"""
    start = datetime(2026, 1, 1)
    end = datetime(2026, 6, 17)
    delta = end - start
    random_seconds = random.randint(0, int(delta.total_seconds()))
    dt = start + timedelta(seconds=random_seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_trust_level(score):
    if score < 50:
        return "basic"
    elif score < 70:
        return "verified"
    elif score < 85:
        return "silver"
    else:
        return "gold"


def generate_certifications(supplier_id):
    """从 ISO 9001/CE/RoHS/FDA/REACH/SGS 中选 1-4 个。"""
    count = random.randint(1, 4)
    selected = random.sample(CERT_TYPES, count)
    certs = []
    for cert_type in selected:
        # valid_until 在 2027-2028 范围
        year = random.choice([2027, 2028])
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        valid_until = f"{year}-{month:02d}-{day:02d}"
        cert_slug = cert_type.lower().replace(" ", "")
        certs.append({
            "type": cert_type,
            "valid_until": valid_until,
            "file": f"/certs/{supplier_id}/{cert_slug}.pdf",
        })
    return certs


def _pricing_tiers(base_price):
    """生成 3 个阶梯定价。"""
    return [
        {"min_qty": 1000, "unit_price_usd": round(base_price, 3)},
        {"min_qty": 10000, "unit_price_usd": round(base_price * 0.85, 3)},
        {"min_qty": 50000, "unit_price_usd": round(base_price * 0.72, 3)},
    ]


def _inv_status():
    return random.choice(["in_stock", "in_stock", "in_stock", "made_to_order", "limited"])


def _inv_qty():
    return random.randint(1000, 100000)


def _sku_code(s):
    """从字符串生成简洁的 SKU 代码（取首单词前 4 字符大写，去除空格/特殊字符）。"""
    first_word = s.split()[0] if s.split() else s
    return first_word[:4].upper()


# ====================================================================
# 产品生成器（按品类）
# ====================================================================

def _p_bolt(sid, idx):
    d = random.choice([6, 8, 10, 12, 16])
    l = random.choice([20, 30, 40, 50, 60, 70, 80])
    mats = [("304不锈钢", "304 Stainless Steel", "304"),
            ("316不锈钢", "316 Stainless Steel", "316"),
            ("碳钢镀锌", "Carbon Steel Zinc Plated", "ZP")]
    mz, me, mc = random.choice(mats)
    grade = random.choice(["A2-70", "A4-80"]) if "不锈钢" in mz else random.choice(["4.8", "8.8", "10.9"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"M{d}-{l}-{mc}-hex-bolt",
        "name_zh": f"M{d}x{l} {mz}六角螺栓 {grade}",
        "name_en": f"M{d}x{l} {me} Hex Bolt {grade}",
        "category": "bolt", "material": me, "grade": grade,
        "specs": {"diameter_mm": d, "length_mm": l, "thread_pitch": round(d * 0.125, 2), "head_type": "hex"},
        "pricing_tiers": _pricing_tiers(0.08 + d * 0.012),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_nut(sid, idx):
    d = random.choice([6, 8, 10, 12, 16])
    mats = [("304不锈钢", "304 Stainless Steel", "304"), ("碳钢镀锌", "Carbon Steel Zinc Plated", "ZP")]
    mz, me, mc = random.choice(mats)
    grade = "A2-70" if "不锈钢" in mz else "8"
    nut_type = random.choice(["hex", "lock", "flange"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"M{d}-{mc}-{nut_type}-nut",
        "name_zh": f"M{d} {mz}{nut_type}螺母 {grade}",
        "name_en": f"M{d} {me} {nut_type.title()} Nut {grade}",
        "category": "nut", "material": me, "grade": grade,
        "specs": {"diameter_mm": d, "thread_pitch": round(d * 0.125, 2), "type": nut_type},
        "pricing_tiers": _pricing_tiers(0.03 + d * 0.005),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_washer(sid, idx):
    d = random.choice([6, 8, 10, 12])
    wtype = random.choice(["flat", "spring", "lock"])
    me = "304 Stainless Steel"
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"M{d}-304-{wtype}-washer",
        "name_zh": f"M{d} 304不锈钢{wtype}垫圈",
        "name_en": f"M{d} 304 SS {wtype.title()} Washer",
        "category": "washer", "material": me, "grade": "A2",
        "specs": {"diameter_mm": d, "type": wtype, "material": "304 SS"},
        "pricing_tiers": _pricing_tiers(0.02 + d * 0.003),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_screw(sid, idx):
    d = random.choice([4, 5, 6, 8])
    l = random.choice([20, 25, 30, 40, 50])
    stype = random.choice(["self_tapping", "self_drilling", "drywall", "chipboard"])
    me = "Carbon Steel"
    finish = random.choice(["Zinc Plated", "Black Oxide", "Ruspert"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"ST{d}-{l}-{stype}-screw",
        "name_zh": f"ST{d}x{l} {finish} {stype}螺丝",
        "name_en": f"ST{d}x{l} {finish} {stype.replace('_', ' ').title()} Screw",
        "category": stype, "material": f"{me} {finish}", "grade": "C1022",
        "specs": {"diameter_mm": d, "length_mm": l, "type": stype, "finish": finish},
        "pricing_tiers": _pricing_tiers(0.04 + d * 0.005),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_threaded_rod(sid, idx):
    d = random.choice([8, 10, 12])
    l = random.choice([500, 1000, 2000])
    me = "304 Stainless Steel"
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"M{d}-{l}-304-threaded-rod",
        "name_zh": f"M{d}x{l}mm 304不锈钢全螺纹螺杆 A2-70",
        "name_en": f"M{d}x{l}mm 304 SS Threaded Rod A2-70",
        "category": "threaded_rod", "material": me, "grade": "A2-70",
        "specs": {"diameter_mm": d, "length_mm": l, "thread_pitch": round(d * 0.125, 2)},
        "pricing_tiers": _pricing_tiers(0.5 + d * 0.1),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_rivet(sid, idx):
    d = random.choice([3, 4, 5])
    l = random.choice([8, 10, 12, 16, 20])
    me = "Aluminum / Steel"
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"R{d}-{l}-pop-rivet",
        "name_zh": f"{d}x{l}mm 抽芯铆钉 铝/钢",
        "name_en": f"{d}x{l}mm Pop Rivet Al/Steel",
        "category": "rivet", "material": me, "grade": "Standard",
        "specs": {"diameter_mm": d, "length_mm": l, "type": "pop"},
        "pricing_tiers": _pricing_tiers(0.02),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_hinge(sid, idx):
    size = random.choice([3, 4, 5, 6])
    me = random.choice(["304 Stainless Steel", "Carbon Steel Zinc Plated"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"{size}inch-{me.split()[0].lower()}-hinge",
        "name_zh": f"{size}英寸 {me}合页铰链",
        "name_en": f"{size}inch {me} Hinge",
        "category": "hinge", "material": me, "grade": "Standard",
        "specs": {"size_inch": size, "material": me, "type": "butt"},
        "pricing_tiers": _pricing_tiers(0.3 + size * 0.1),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_bracket(sid, idx):
    thickness = random.choice([1.5, 2.0, 2.5, 3.0])
    me = "304 Stainless Steel"
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"BR-{thickness}mm-304-stamping",
        "name_zh": f"{thickness}mm 304不锈钢冲压支架",
        "name_en": f"{thickness}mm 304 SS Stamping Bracket",
        "category": "stamping", "material": me, "grade": "Custom",
        "specs": {"thickness_mm": thickness, "process": "stamping", "material": "304 SS"},
        "pricing_tiers": _pricing_tiers(0.5 + thickness * 0.2),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_handle(sid, idx):
    me = random.choice(["Zinc Alloy", "304 Stainless Steel", "Aluminum"])
    length = random.choice([96, 128, 160])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"HD-{length}mm-{me.split()[0].lower()}-handle",
        "name_zh": f"{length}mm {me}门拉手",
        "name_en": f"{length}mm {me} Door Handle",
        "category": "door_handle", "material": me, "grade": "Standard",
        "specs": {"length_mm": length, "material": me, "finish": "satin"},
        "pricing_tiers": _pricing_tiers(1.2 + length * 0.01),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_die_cast(sid, idx):
    me = random.choice(["Zinc Alloy ZAMAK 3", "Aluminum ADC12", "Magnesium AZ91D"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"DC-{me.split()[-1]}-custom-part",
        "name_zh": f"{me} 压铸件 定制",
        "name_en": f"{me} Die Casting Custom Part",
        "category": "die_casting", "material": me, "grade": "Custom",
        "specs": {"process": "die_casting", "material": me, "surface": "polishing"},
        "pricing_tiers": _pricing_tiers(0.8),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_bearing(sid, idx):
    model = random.choice(["6201", "6202", "6203", "6204", "6304", "6205"])
    me = random.choice(["GCr15 Bearing Steel", "Stainless Steel 440C"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"{model}-{me.split()[0]}-bearing",
        "name_zh": f"{model} {me}深沟球轴承",
        "name_en": f"{model} {me} Deep Groove Ball Bearing",
        "category": "bearing", "material": me, "grade": "P0",
        "specs": {"model": model, "type": "deep_groove", "material": me},
        "pricing_tiers": _pricing_tiers(0.5),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_connector(sid, idx):
    ctype = random.choice(["USB-C", "USB 2.0", "HDMI", "D-SUB", "RJ45"])
    pins = random.choice([4, 8, 9, 14, 24])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"CONN-{ctype.replace(' ', '').replace('-', '')}-{pins}pin",
        "name_zh": f"{ctype} {pins}Pin 连接器",
        "name_en": f"{ctype} {pins}Pin Connector",
        "category": "connector", "material": "Brass + LCP", "grade": "Industrial",
        "specs": {"type": ctype, "pins": pins, "voltage": "50V", "current": "3A"},
        "pricing_tiers": _pricing_tiers(0.15 + pins * 0.02),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_cable(sid, idx):
    ctype = random.choice(["USB 2.0", "USB-C", "HDMI 2.0", "RJ45 Cat6"])
    length = random.choice([1, 2, 3, 5])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"CABLE-{ctype.replace(' ', '')}-{length}m",
        "name_zh": f"{ctype} {length}米 数据线",
        "name_en": f"{ctype} {length}m Data Cable",
        "category": "cable", "material": "PVC + Copper", "grade": "Standard",
        "specs": {"type": ctype, "length_m": length, "conductor": "OFC"},
        "pricing_tiers": _pricing_tiers(0.5 + length * 0.3),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_pcb(sid, idx):
    layers = random.choice([1, 2, 4, 6])
    me = "FR-4"
    thickness = random.choice([0.6, 0.8, 1.0, 1.2, 1.6])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"PCB-{layers}L-{thickness}mm-FR4",
        "name_zh": f"{layers}层 {thickness}mm FR-4 PCB板",
        "name_en": f"{layers}Layer {thickness}mm FR-4 PCB",
        "category": "PCB", "material": me, "grade": "IPC-A-600",
        "specs": {"layers": layers, "thickness_mm": thickness, "material": "FR-4", "surface_finish": "HASL"},
        "pricing_tiers": _pricing_tiers(0.3 + layers * 0.15),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_led_strip(sid, idx):
    voltage = random.choice([12, 24])
    ip = random.choice(["IP20", "IP65", "IP67"])
    leds_per_m = random.choice([30, 60, 120])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"LED-{voltage}V-{leds_per_m}LED-{ip}",
        "name_zh": f"{voltage}V {leds_per_m}灯/米 {ip} LED灯带",
        "name_en": f"{voltage}V {leds_per_m}LED/m {ip} LED Strip",
        "category": "LED", "material": "FPC + SMD LED", "grade": "Commercial",
        "specs": {"voltage": f"{voltage}V", "leds_per_m": leds_per_m, "ip_rating": ip, "color": "warm_white"},
        "pricing_tiers": _pricing_tiers(1.5 + leds_per_m * 0.02),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_sensor(sid, idx):
    stype = random.choice(["Temperature", "Humidity", "Pressure", "PIR Motion"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"SENSOR-{_sku_code(stype)}-module",
        "name_zh": f"{stype} 传感器模块",
        "name_en": f"{stype} Sensor Module",
        "category": "sensor", "material": "PCB + Components", "grade": "Industrial",
        "specs": {"type": stype, "voltage": "3.3V/5V", "interface": "I2C/Digital"},
        "pricing_tiers": _pricing_tiers(1.2),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_enclosure(sid, idx):
    me = random.choice(["ABS", "PC", "ABS+PC", "PP"])
    size = random.choice(["100x60x30", "150x90x50", "200x120x60"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"ENC-{me}-{size.replace('x', 'X')}",
        "name_zh": f"{me} {size}mm 注塑外壳",
        "name_en": f"{me} {size}mm Injection Enclosure",
        "category": "enclosure", "material": me, "grade": "UL94 V-0",
        "specs": {"material": me, "size_mm": size, "process": "injection_molding"},
        "pricing_tiers": _pricing_tiers(0.8),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_housing(sid, idx):
    me = random.choice(["ABS", "PC", "PA66"])
    app = random.choice(["Appliance", "Automotive", "Medical Device"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"HSG-{_sku_code(me)}-{_sku_code(app)}",
        "name_zh": f"{me} {app}外壳 注塑件",
        "name_en": f"{me} {app} Housing Injection Part",
        "category": "housing", "material": me, "grade": "Custom",
        "specs": {"material": me, "application": app, "process": "injection_molding"},
        "pricing_tiers": _pricing_tiers(1.0),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_container(sid, idx):
    me = random.choice(["PP", "PE", "PET"])
    capacity = random.choice([500, 750, 1000, 2000])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"CTN-{me}-{capacity}ml",
        "name_zh": f"{me} {capacity}ml 食品级容器",
        "name_en": f"{me} {capacity}ml Food-Grade Container",
        "category": "container", "material": me, "grade": "FDA",
        "specs": {"material": me, "capacity_ml": capacity, "food_grade": True},
        "pricing_tiers": _pricing_tiers(0.15 + capacity * 0.0002),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_mold(sid, idx):
    mtype = random.choice(["Precision Mold", "Automotive Mold", "Connector Mold", "Overmolding Mold"])
    cavities = random.choice([1, 2, 4, 8, 16])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"MOLD-{_sku_code(mtype)}-{cavities}CAV",
        "name_zh": f"{mtype} {cavities}腔 注塑模具",
        "name_en": f"{mtype} {cavities}Cavity Injection Mold",
        "category": "precision_mold", "material": "P20 / 718H Steel", "grade": "Custom",
        "specs": {"type": mtype, "cavities": cavities, "steel": "P20", "life": "500K shots"},
        "pricing_tiers": _pricing_tiers(3000 + cavities * 500),
        "inventory_status": "made_to_order", "inventory_quantity": random.randint(1, 20),
    }


def _p_shoe_material(sid, idx):
    me = random.choice(["PU", "EVA", "Rubber", "TPU"])
    part = random.choice(["Sole", "Upper", "Lining", "Insole"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"SHOE-{me}-{part.upper()}",
        "name_zh": f"{me} 鞋材 {part}",
        "name_en": f"{me} Shoe Material {part}",
        "category": "shoe_material", "material": me, "grade": "Standard",
        "specs": {"material": me, "part": part, "process": "injection/compression"},
        "pricing_tiers": _pricing_tiers(0.5),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_cnc_lathe(sid, idx):
    model = random.choice(["CK6132", "CK6140", "CK6150", "CK6163"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"CNC-{model}",
        "name_zh": f"{model} 数控车床",
        "name_en": f"{model} CNC Lathe",
        "category": "CNC_machine", "material": "Cast Iron", "grade": "Industrial",
        "specs": {"model": model, "type": "CNC_lathe", "control": "FANUC/Siemens", "max_turning_mm": 500},
        "pricing_tiers": _pricing_tiers(15000),
        "inventory_status": "made_to_order", "inventory_quantity": random.randint(1, 50),
    }


def _p_milling(sid, idx):
    model = random.choice(["VMC850", "VMC1060", "X6132", "X5032"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"MILL-{model}",
        "name_zh": f"{model} 铣床/加工中心",
        "name_en": f"{model} Milling Machine",
        "category": "milling", "material": "Cast Iron", "grade": "Industrial",
        "specs": {"model": model, "type": "milling", "travel_mm": "800x500x500"},
        "pricing_tiers": _pricing_tiers(20000),
        "inventory_status": "made_to_order", "inventory_quantity": random.randint(1, 30),
    }


def _p_auto_brake(sid, idx):
    btype = random.choice(["Ceramic", "Semi-Metallic", "Low-Steel"])
    car = random.choice(["Toyota", "Honda", "VW", "BMW", "Ford"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"BRAKE-{_sku_code(btype)}-{car}",
        "name_zh": f"{car} {btype} 刹车片",
        "name_en": f"{car} {btype} Brake Pad",
        "category": "brake", "material": btype, "grade": "ECE R90",
        "specs": {"type": btype, "car_model": car, "friction_coeff": "0.35-0.45"},
        "pricing_tiers": _pricing_tiers(3.5),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_oil_filter(sid, idx):
    car = random.choice(["Toyota", "Honda", "VW", "BMW", "Mercedes"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"FILTER-OIL-{car}",
        "name_zh": f"{car} 机油滤清器",
        "name_en": f"{car} Oil Filter",
        "category": "filter", "material": "Steel + Filter Paper", "grade": "OEM",
        "specs": {"type": "spin_on", "car_model": car, "filtration": "5-10 micron"},
        "pricing_tiers": _pricing_tiers(1.5),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_water_pump(sid, idx):
    car = random.choice(["Toyota", "Honda", "VW", "BMW"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"PUMP-WATER-{car}",
        "name_zh": f"{car} 水泵",
        "name_en": f"{car} Water Pump",
        "category": "pump", "material": "Aluminum Housing", "grade": "OEM",
        "specs": {"type": "mechanical", "car_model": car, "material": "aluminum"},
        "pricing_tiers": _pricing_tiers(12),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_suspension(sid, idx):
    part = random.choice(["Shock Absorber", "Control Arm", "Ball Joint", "Stabilizer Link"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"SUSP-{_sku_code(part)}",
        "name_zh": f"汽车 {part}",
        "name_en": f"Auto {part}",
        "category": "suspension", "material": "Steel + Rubber", "grade": "OEM",
        "specs": {"type": part, "material": "steel"},
        "pricing_tiers": _pricing_tiers(8),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_cotton_fabric(sid, idx):
    weight = random.choice([150, 180, 200, 220])
    width = random.choice([150, 180, 220])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"FAB-100%COT-{weight}gsm-{width}cm",
        "name_zh": f"100%棉 {weight}gsm {width}cm 纯棉面料",
        "name_en": f"100% Cotton {weight}gsm {width}cm Fabric",
        "category": "cotton", "material": "100% Cotton", "grade": f"{weight}gsm",
        "specs": {"material": "100% cotton", "weight_gsm": weight, "width_cm": width, "yarn_count": "20s-40s"},
        "pricing_tiers": _pricing_tiers(1.5 + weight * 0.005),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_polyester_fabric(sid, idx):
    denier = random.choice([75, 150, 300])
    weight = random.choice([60, 80, 100, 150])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"FAB-POLY-{denier}D-{weight}gsm",
        "name_zh": f"{denier}D 涤纶 {weight}gsm 化纤面料",
        "name_en": f"{denier}D Polyester {weight}gsm Fabric",
        "category": "polyester", "material": "100% Polyester", "grade": f"{denier}D",
        "specs": {"material": "100% polyester", "denier": denier, "weight_gsm": weight, "width_cm": 150},
        "pricing_tiers": _pricing_tiers(0.8 + denier * 0.003),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_yarn(sid, idx):
    material = random.choice(["Cotton", "Polyester", "CVC (60/40)", "TR (65/35)"])
    count = random.choice([20, 32, 40, 60])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"YARN-{_sku_code(material)}-{count}S",
        "name_zh": f"{material} {count}S 纱线",
        "name_en": f"{material} {count}S Yarn",
        "category": "yarn", "material": material, "grade": f"{count}S",
        "specs": {"material": material, "count": f"{count}S", "type": "ring_spun"},
        "pricing_tiers": _pricing_tiers(2.5),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_webbing(sid, idx):
    me = random.choice(["Polyester", "Nylon", "PP"])
    width = random.choice([10, 15, 20, 25, 38, 50])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"WEB-{_sku_code(me)}-{width}mm",
        "name_zh": f"{me} {width}mm 织带/松紧带",
        "name_en": f"{me} {width}mm Webbing/Elastic",
        "category": "webbing", "material": me, "grade": "Standard",
        "specs": {"material": me, "width_mm": width, "type": "elastic"},
        "pricing_tiers": _pricing_tiers(0.1 + width * 0.01),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_corrugated_box(sid, idx):
    ply = random.choice([3, 5, 7])
    size = random.choice(["300x200x200", "400x300x300", "500x400x400"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"BOX-{ply}PLY-{size}",
        "name_zh": f"{ply}层 {size}mm 瓦楞纸箱",
        "name_en": f"{ply}Ply {size}mm Corrugated Box",
        "category": "corrugated_box", "material": "Kraft Paper", "grade": f"{ply}Ply",
        "specs": {"ply": ply, "size_mm": size, "material": "kraft_paper"},
        "pricing_tiers": _pricing_tiers(0.3 + ply * 0.1),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_gift_box(sid, idx):
    me = random.choice(["Cardboard", "Rigid Board", "Art Paper"])
    size = random.choice(["200x150x50", "250x200x80", "300x250x100"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"GIFT-{_sku_code(me)}-{size}",
        "name_zh": f"{me} {size}mm 礼品盒 定制印刷",
        "name_en": f"{me} {size}mm Gift Box Custom Printing",
        "category": "gift_box", "material": me, "grade": "Custom",
        "specs": {"material": me, "size_mm": size, "printing": "CMYK + Spot UV"},
        "pricing_tiers": _pricing_tiers(0.8),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_stand_up_pouch(sid, idx):
    capacity = random.choice([100, 250, 500, 1000])
    me = random.choice(["PET/PE", "PET/AL/PE", "Kraft/PE"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"POUCH-{me.replace('/', '')}-{capacity}ml",
        "name_zh": f"{me} {capacity}ml 自立袋 食品级",
        "name_en": f"{me} {capacity}ml Stand-Up Pouch Food Grade",
        "category": "stand_up_pouch", "material": me, "grade": "FDA",
        "specs": {"material": me, "capacity_ml": capacity, "feature": "zip_lock"},
        "pricing_tiers": _pricing_tiers(0.05 + capacity * 0.0001),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_shoe_box(sid, idx):
    me = random.choice(["Cardboard", "Kraft Paper", "Corrugated"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"SHOEBOX-{_sku_code(me)}",
        "name_zh": f"{me} 鞋盒 定制印刷",
        "name_en": f"{me} Shoe Box Custom Printing",
        "category": "shoe_box", "material": me, "grade": "Custom",
        "specs": {"material": me, "size": "330x210x120mm", "printing": "CMYK"},
        "pricing_tiers": _pricing_tiers(0.3),
        "inventory_status": _inv_status(), "inventory_quantity": _inv_qty(),
    }


def _p_office_chair(sid, idx):
    me = random.choice(["Mesh", "PU Leather", "Fabric"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"CHAIR-OFFICE-{_sku_code(me)}",
        "name_zh": f"{me} 办公椅 人体工学",
        "name_en": f"{me} Office Chair Ergonomic",
        "category": "office_chair", "material": me, "grade": "BIFMA",
        "specs": {"material": me, "type": "ergonomic", "armrest": "3D adjustable"},
        "pricing_tiers": _pricing_tiers(25),
        "inventory_status": _inv_status(), "inventory_quantity": random.randint(100, 5000),
    }


def _p_sofa(sid, idx):
    me = random.choice(["Fabric", "PU Leather", "Genuine Leather"])
    seats = random.choice([2, 3, 4])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"SOFA-{_sku_code(me)}-{seats}SEAT",
        "name_zh": f"{me} {seats}座 沙发",
        "name_en": f"{me} {seats}-Seat Sofa",
        "category": "sofa", "material": me, "grade": "Standard",
        "specs": {"material": me, "seats": seats, "frame": "solid_wood"},
        "pricing_tiers": _pricing_tiers(80 + seats * 30),
        "inventory_status": _inv_status(), "inventory_quantity": random.randint(50, 3000),
    }


def _p_dining_table(sid, idx):
    me = random.choice(["Solid Wood", "Tempered Glass", "Marble + Steel"])
    size = random.choice(["120x60", "140x70", "160x80"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"TABLE-DINING-{_sku_code(me)}-{size}",
        "name_zh": f"{me} {size}cm 餐桌",
        "name_en": f"{me} {size}cm Dining Table",
        "category": "table", "material": me, "grade": "Standard",
        "specs": {"material": me, "size_cm": size, "seats": 4 if "120" in size else 6},
        "pricing_tiers": _pricing_tiers(60),
        "inventory_status": _inv_status(), "inventory_quantity": random.randint(50, 2000),
    }


def _p_bed_frame(sid, idx):
    me = random.choice(["Solid Wood", "Metal Steel", "Upholstered"])
    size = random.choice(["Queen", "King", "Double"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"BED-{_sku_code(me)}-{size}",
        "name_zh": f"{me} {size} 床架",
        "name_en": f"{me} {size} Bed Frame",
        "category": "bed", "material": me, "grade": "Standard",
        "specs": {"material": me, "size": size},
        "pricing_tiers": _pricing_tiers(90),
        "inventory_status": _inv_status(), "inventory_quantity": random.randint(50, 2000),
    }


def _p_packaging_machine(sid, idx):
    mtype = random.choice(["VFFS", "Blister", "Flow Pack", "Shrink Wrap"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"MAC-PKG-{_sku_code(mtype)}",
        "name_zh": f"{mtype} 包装机 全自动",
        "name_en": f"{mtype} Packaging Machine Automatic",
        "category": "packaging_machine", "material": "Stainless Steel 304", "grade": "Industrial",
        "specs": {"type": mtype, "speed": "30-60 ppm", "control": "PLC + HMI"},
        "pricing_tiers": _pricing_tiers(8000),
        "inventory_status": "made_to_order", "inventory_quantity": random.randint(1, 30),
    }


def _p_automation(sid, idx):
    mtype = random.choice(["Robotic Arm", "Conveyor System", "Pick & Place", "Palletizer"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"AUTO-{_sku_code(mtype)}",
        "name_zh": f"{mtype} 自动化设备",
        "name_en": f"{mtype} Automation Equipment",
        "category": "automation", "material": "Aluminum + Steel", "grade": "Industrial",
        "specs": {"type": mtype, "control": "PLC/Servo", "payload": "5-50kg"},
        "pricing_tiers": _pricing_tiers(12000),
        "inventory_status": "made_to_order", "inventory_quantity": random.randint(1, 20),
    }


def _p_home_appliance(sid, idx):
    app = random.choice(["Electric Fan", "Air Cooler", "Water Dispenser", "Humidifier"])
    return {
        "id": f"{sid}-p{idx:03d}", "supplier_id": sid,
        "sku": f"APP-{_sku_code(app)}",
        "name_zh": f"{app} 家电",
        "name_en": f"{app} Home Appliance",
        "category": "home_appliance", "material": "ABS + Steel", "grade": "CE/CB",
        "specs": {"type": app, "voltage": "220V/50Hz", "power": "45-200W"},
        "pricing_tiers": _pricing_tiers(15),
        "inventory_status": _inv_status(), "inventory_quantity": random.randint(100, 5000),
    }


# 产品生成器映射表
PRODUCT_GENERATORS = {
    "fastener": [_p_bolt, _p_nut, _p_washer, _p_screw, _p_threaded_rod, _p_rivet],
    "hardware": [_p_hinge, _p_bracket, _p_handle, _p_die_cast, _p_bearing, _p_screw],
    "electronics": [_p_connector, _p_cable, _p_pcb, _p_led_strip, _p_sensor],
    "injection_molding": [_p_enclosure, _p_housing, _p_container, _p_mold, _p_shoe_material],
    "machinery": [_p_cnc_lathe, _p_milling, _p_packaging_machine, _p_automation, _p_home_appliance],
    "textile": [_p_cotton_fabric, _p_polyester_fabric, _p_yarn, _p_webbing, _p_shoe_material],
    "packaging": [_p_corrugated_box, _p_gift_box, _p_stand_up_pouch, _p_shoe_box],
    "auto_parts": [_p_auto_brake, _p_oil_filter, _p_water_pump, _p_suspension, _p_bearing],
    "furniture": [_p_office_chair, _p_sofa, _p_dining_table, _p_bed_frame],
}


def generate_products(supplier_id, category, count):
    """为一家工厂生成 count 个产品。"""
    generators = PRODUCT_GENERATORS.get(category, [_p_bolt])
    products = []
    # 打乱生成器顺序，取前 count 个（允许重复但优先不重复）
    shuffled = generators[:]
    random.shuffle(shuffled)
    for i in range(1, count + 1):
        gen = shuffled[(i - 1) % len(shuffled)]
        products.append(gen(supplier_id, i))
    return products


# ====================================================================
# 供应商生成
# ====================================================================

def generate_supplier(belt, category, seq_num, existing_ids):
    """生成一家供应商。"""
    prefix = belt["prefix"]
    cat_suffix = CAT_TO_SUFFIX[category]
    supplier_id = f"{prefix}-{cat_suffix}-{seq_num:03d}"

    # 防止 ID 冲突
    while supplier_id in existing_ids:
        seq_num += 1
        supplier_id = f"{prefix}-{cat_suffix}-{seq_num:03d}"
    existing_ids.add(supplier_id)

    # 字号
    trade_zh, trade_en = random.choice(TRADE_NAMES)

    # 名称
    name_zh_template = random.choice(belt["name_zh"][category])
    name_en_template = random.choice(belt["name_en"][category])
    name_zh = name_zh_template.format(trade=trade_zh, trade_en=trade_en)
    name_en = name_en_template.format(trade=trade_zh, trade_en=trade_en)

    # 子品类
    subcats = random.choice(belt["subcategories"][category])

    # 基础字段
    year_established = random.randint(1995, 2018)
    employees = random.randint(50, 800)
    annual_revenue_usd = random.randint(2, 80) * 1000000  # 200万-8000万
    export_ratio = round(random.uniform(0.3, 0.95), 2)
    main_markets = random.sample(MAIN_MARKETS, random.randint(2, 4))
    moq = random.randint(1000, 50000)
    lead_standard = random.randint(10, 30)
    lead_express = random.randint(5, min(10, lead_standard - 1))
    certifications = generate_certifications(supplier_id)
    languages = random.choice(LANG_OPTIONS)

    # Skill 安装
    agent_skill_installed = random.random() < 0.30
    skill_mcp_endpoint = f"https://api.linkmoney.online/mcp/{supplier_id}" if agent_skill_installed else None

    # 信任与评价
    trust_score = random.randint(40, 95)
    trust_level = compute_trust_level(trust_score)
    review_count = random.randint(0, 50)
    review_avg = round(random.uniform(3.5, 5.0), 1)
    gold_badge = trust_score >= 85 and review_avg >= 4.5

    # 联系方式
    contact_person = random_contact_person()
    email = f"supplier-{supplier_id}@linkmoney.online"
    phone = random_phone()
    wechat = f"lm-{supplier_id}"

    created_at = random_created_at()

    # 产品
    product_count = random.randint(2, 5)
    products = generate_products(supplier_id, category, product_count)

    supplier = {
        "id": supplier_id,
        "name_zh": name_zh,
        "name_en": name_en,
        "location": {
            "city": belt["city"],
            "province": belt["province"],
            "port": belt["port"],
        },
        "category": category,
        "subcategories": subcats,
        "year_established": year_established,
        "employees": employees,
        "annual_revenue_usd": annual_revenue_usd,
        "export_ratio": export_ratio,
        "main_markets": main_markets,
        "moq": moq,
        "lead_time_days": {
            "standard": lead_standard,
            "express": lead_express,
        },
        "certifications": certifications,
        "languages": languages,
        "agent_skill_installed": agent_skill_installed,
        "skill_mcp_endpoint": skill_mcp_endpoint,
        "contact_person": contact_person,
        "email": email,
        "phone": phone,
        "wechat": wechat,
        "trust_score": trust_score,
        "trust_level": trust_level,
        "review_count": review_count,
        "review_avg": review_avg,
        "gold_badge": gold_badge,
        "created_at": created_at,
        "products": products,
    }

    # 如果安装了 Skill，添加额外字段
    if agent_skill_installed:
        supplier["skill_platforms"] = random.sample(
            ["github", "claude", "agentrun", "cursor", "coze"],
            random.randint(1, 3)
        )
        supplier["skill_installs"] = random.randint(5, 500)

    return supplier


# ====================================================================
# 主函数
# ====================================================================

def main():
    print("=" * 70)
    print("  LinkMoney 供应商扩充脚本")
    print("  目标: 新增 150 家工厂，覆盖 8 大中国产业带")
    print("=" * 70)

    # 1. 读取现有数据
    if not JSON_PATH.exists():
        print(f"错误: 找不到 {JSON_PATH}")
        return

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    old_count = len(data["suppliers"])
    print(f"\n现有供应商: {old_count} 家")

    # 收集现有 ID
    existing_ids = {s["id"] for s in data["suppliers"]}

    # 2. 生成新供应商
    new_suppliers = []
    belt_stats = {}  # 产业带统计
    category_stats = {}  # 品类统计
    skill_installed_count = 0

    for belt in BELTS:
        belt_name = belt["name"]
        belt_count = 0
        for category, count in belt["distribution"]:
            for i in range(1, count + 1):
                supplier = generate_supplier(belt, category, i, existing_ids)
                new_suppliers.append(supplier)
                belt_count += 1
                category_stats[category] = category_stats.get(category, 0) + 1
                if supplier["agent_skill_installed"]:
                    skill_installed_count += 1
        belt_stats[belt_name] = belt_count

    print(f"新增供应商: {len(new_suppliers)} 家")

    # 3. 合并
    data["suppliers"].extend(new_suppliers)
    total_count = len(data["suppliers"])
    print(f"总计供应商: {total_count} 家")

    # 更新版本信息
    data["version"] = "3.0.0"
    data["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    # 4. 备份原文件
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = JSON_PATH.with_suffix(f".json.bak.{timestamp}")
    shutil.copy2(JSON_PATH, backup_path)
    print(f"\n原文件已备份: {backup_path}")

    # 5. 写入新数据
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"新数据已写入: {JSON_PATH}")

    # 6. 打印统计
    print(f"\n{'=' * 70}")
    print(f"  统计信息")
    print(f"{'=' * 70}")

    print(f"\n📊 各产业带工厂数:")
    for belt_name, count in belt_stats.items():
        print(f"   {belt_name:12s}: {count:3d} 家")
    print(f"   {'合计':12s}: {sum(belt_stats.values()):3d} 家")

    print(f"\n📊 各品类工厂数（新增）:")
    for cat, count in sorted(category_stats.items(), key=lambda x: -x[1]):
        print(f"   {cat:20s}: {count:3d} 家")

    # 全部品类统计（含原有）
    all_category_stats = {}
    for s in data["suppliers"]:
        cat = s["category"]
        all_category_stats[cat] = all_category_stats.get(cat, 0) + 1
    print(f"\n📊 各品类工厂数（总计 {total_count} 家）:")
    for cat, count in sorted(all_category_stats.items(), key=lambda x: -x[1]):
        print(f"   {cat:20s}: {count:3d} 家")

    skill_rate = skill_installed_count / len(new_suppliers) * 100 if new_suppliers else 0
    print(f"\n📊 Skill 安装情况（新增）:")
    print(f"   已安装: {skill_installed_count} 家")
    print(f"   未安装: {len(new_suppliers) - skill_installed_count} 家")
    print(f"   安装率: {skill_rate:.1f}%")

    # 产品统计
    total_products = sum(len(s.get("products", [])) for s in new_suppliers)
    print(f"\n📊 产品统计（新增）:")
    print(f"   产品总数: {total_products} 个")
    print(f"   平均每厂: {total_products / len(new_suppliers):.1f} 个")

    # 信任等级统计
    trust_stats = {}
    for s in new_suppliers:
        level = s["trust_level"]
        trust_stats[level] = trust_stats.get(level, 0) + 1
    print(f"\n📊 信任等级分布（新增）:")
    for level in ["gold", "silver", "verified", "basic"]:
        count = trust_stats.get(level, 0)
        print(f"   {level:10s}: {count:3d} 家")

    gold_badge_count = sum(1 for s in new_suppliers if s["gold_badge"])
    print(f"   金牌徽章: {gold_badge_count:3d} 家")

    print(f"\n{'=' * 70}")
    print(f"  扩充完成！供应商从 {old_count} 家增加到 {total_count} 家")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
