"""
LinkMoney Trust & Safety 审核模块
对买家询单、工厂报价、工厂注册做真实性/合理性/合规性审核

审核分级：
- pass    低风险，放行
- review  中风险，标记 + 记录（仍放行，但降 trust_score）
- block   高风险，拦截
"""
import re
import socket
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ===== 一次性邮箱域名黑名单 =====
DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "throwaway.email", "yopmail.com", "getnada.com", "temp-mail.org",
    "sharklasers.com", "guerrillamailblock.com", "spam4.me", "dispostable.com",
    "fakeinbox.com", "mailnesia.com", "maildrop.cc", "discard.email",
}

# ===== 违禁品/敏感词（LLM 审核前置过滤）=====
FORBIDDEN_KEYWORDS = [
    # 武器
    "weapon", "firearm", "ammunition", "explosive", "枪支", "弹药", "爆炸物",
    # 毒品
    "drug", "cocaine", "heroin", "methamphetamine", "毒品", "可卡因", "海洛因",
    # 制假
    "counterfeit", "fake brand", "replica luxury", "假冒", "高仿", "A货",
    # 其他
    "ivory", "rhino horn", "象牙", "犀角", "熊胆",
]

# ===== 钓鱼/垃圾特征 =====
SPAM_PATTERNS = [
    r"click\s+here\s+to\s+claim",
    r"you\s+have\s+won",
    r"free\s+money",
    r"bitcoin\s+investment",
    r"cryptocurrency\s+giveaway",
    r"https?://bit\.ly",
    r"https?://t\.co/\S{5,}",
]

# ===== 品类价格区间表（USD/pc，基于市场调研）=====
# 格式: category: (min, max, unit)
# 注意：这是"合理区间"而非"硬性上下限"。B2B 大单常有量价优惠，
# 审核时 block 阈值放宽到 min*0.01 和 max*100，避免误伤。
CATEGORY_PRICE_RANGES = {
    "fastener":          (0.005, 10.00, "pc"),    # 紧固件（量大可低至 $0.005）
    "hardware":          (0.02, 200.00, "pc"),    # 五金
    "machinery":         (50, 100000, "set"),      # 机械
    "electronics":       (0.05, 2000.00, "pc"),    # 电子元件
    "electronic":        (0.05, 2000.00, "pc"),    # 兼容旧品类名
    "textile":           (0.01, 50.00, "pc"),      # 纺织
    "packaging":         (0.001, 20.00, "pc"),     # 包装
    "injection_molding": (0.005, 500.00, "pc"),    # 注塑
    "auto_parts":        (0.20, 10000.00, "pc"),   # 汽配
    "furniture":         (0.50, 20000.00, "pc"),   # 家具
}

# ===== 合理数量区间 =====
# B2B 场景：样品单 1-99 件正常（review 但不 block），大单可达千万
QUANTITY_RANGES = {
    "sample_max": 99,      # 100 件以下算样品单，review 不 block
    "min": 1,
    "max": 50_000_000,     # 5000 万（大型基建项目）
}

# ===== 合理交期区间（天）=====
# 数字产品/样品可当天交付，大型设备定制可达 365 天
LEAD_TIME_RANGE = (0, 365)


class AuditResult:
    """审核结果"""
    def __init__(self, level: str = "pass", score: int = 100, reasons: list = None, details: dict = None):
        self.level = level      # pass / review / block
        self.score = score      # 0-100，100 = 完全可信
        self.reasons = reasons or []
        self.details = details or {}
        self.timestamp = datetime.now().isoformat() + "Z"

    @property
    def passed(self) -> bool:
        return self.level == "pass"

    @property
    def blocked(self) -> bool:
        return self.level == "block"

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "score": self.score,
            "reasons": self.reasons,
            "details": self.details,
            "timestamp": self.timestamp,
        }

    def __repr__(self):
        return f"<AuditResult level={self.level} score={self.score} reasons={self.reasons}>"


# ===== 邮箱验证 =====

_email_re = re.compile(r"^[a-zA-Z0-9._%+-]+@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})$")


def validate_email(email: str, check_mx: bool = True) -> AuditResult:
    """验证邮箱真实性：格式 + 一次性邮箱 + MX 记录"""
    if not email or not isinstance(email, str):
        return AuditResult("block", 0, ["邮箱为空"])

    m = _email_re.match(email.strip())
    if not m:
        return AuditResult("block", 0, [f"邮箱格式无效: {email}"])

    domain = m.group(1).lower()

    # 一次性邮箱
    if domain in DISPOSABLE_EMAIL_DOMAINS:
        return AuditResult("block", 10, [f"一次性邮箱域名: {domain}"])

    # MX 记录查询（DNS）— 失败不降分，只记 info
    # 中国很多小工厂用 QQ/163 邮箱，自有域名没配 MX 是正常的
    if check_mx:
        try:
            import dns.resolver
            answers = dns.resolver.resolve(domain, "MX", lifetime=3)
            if not answers:
                return AuditResult("pass", 90, [f"域名无 MX 记录（可能用第三方邮箱）: {domain}"])
        except ImportError:
            # dnspython 未安装，跳过 MX 检查
            pass
        except Exception:
            # DNS 查询失败（超时/网络问题），不降分
            return AuditResult("pass", 95, [f"MX 查询跳过（网络/DNS）: {domain}"])

    return AuditResult("pass", 100, [])


# ===== 公司名验证 =====

_company_valid_patterns = [
    re.compile(r"有限公司$"),        # 中文
    re.compile(r"有限责任公司$"),
    re.compile(r"股份.*公司$"),
    re.compile(r"(厂|合作社|工作室|经营部|门市部|加工厂|制造厂|制品厂)$"),  # 个体户/小微实体
    re.compile(r"(Ltd|LTD|Limited)\.?$", re.I),  # 英文
    re.compile(r"(Inc|Incorporated)\.?$", re.I),
    re.compile(r"(Co|Company)\.?,?Ltd\.?$", re.I),
    re.compile(r"GmbH$", re.I),       # 德语
    re.compile(r"(S\.A\.|S\.R\.L\.|S\.A\.S\.)$", re.I),  # 法/意/西
    re.compile(r"(Pty|Pvt)\.?\s*Ltd\.?$", re.I),  # 澳/印
    re.compile(r"(Corp|Corporation)\.?$", re.I),
    re.compile(r"(Group|Holding)\.?$", re.I),
]


def validate_company_name(name: str, country: str = "") -> AuditResult:
    """验证公司名格式是否包含合法后缀"""
    if not name or len(name.strip()) < 4:
        return AuditResult("block", 0, ["公司名过短或为空"])

    name = name.strip()

    # 检查是否包含合法公司后缀
    matched = any(p.search(name) for p in _company_valid_patterns)
    if not matched:
        return AuditResult(
            "review", 60,
            [f"公司名缺少合法后缀（有限公司/Ltd/Inc/GmbH 等）: {name}"]
        )

    # 检查是否像测试数据
    test_keywords = ["test", "demo", "example", "sample", "fake", "placeholder", "测试", "示例"]
    name_lower = name.lower()
    for kw in test_keywords:
        if kw in name_lower:
            return AuditResult("review", 40, [f"公司名包含测试关键词 '{kw}': {name}"])

    return AuditResult("pass", 100, [])


# ===== 统一社会信用代码验证（中国工厂）=====

_uscc_re = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")


def validate_uscc(uscc: str) -> AuditResult:
    """验证统一社会信用代码格式（18 位，排除易混淆字符 I/O/S/V/Z）"""
    if not uscc:
        return AuditResult("pass", 100, ["未提供，跳过"])  # 非必填

    uscc = uscc.strip().upper()
    if not _uscc_re.match(uscc):
        return AuditResult("review", 50, [f"统一社会信用代码格式无效（应为18位，排除I/O/S/V/Z）: {uscc}"])

    return AuditResult("pass", 100, [])


# ===== 手机号验证 =====

_phone_cn_re = re.compile(r"^\+?86?\s*1[3-9]\d{9}$")
_phone_intl_re = re.compile(r"^\+\d{6,15}$")


def validate_phone(phone: str, country: str = "") -> AuditResult:
    """验证手机号格式"""
    if not phone:
        return AuditResult("block", 0, ["手机号为空"])

    phone = phone.strip()

    # 中国手机号
    if "CN" in country.upper() or "中国" in country or "+86" in phone:
        if _phone_cn_re.match(phone):
            return AuditResult("pass", 100, [])
        return AuditResult("review", 60, [f"中国手机号格式无效: {phone}"])

    # 国际号码
    if _phone_intl_re.match(phone):
        return AuditResult("pass", 90, [])

    return AuditResult("review", 50, [f"手机号格式无法识别: {phone}"])


# ===== 价格合理性 =====

def validate_price(unit_price_usd: float, category: str, quantity: int = 1) -> AuditResult:
    """验证单价是否在品类合理区间"""
    if unit_price_usd <= 0:
        return AuditResult("block", 0, [f"价格非正数: {unit_price_usd}"])

    cat = (category or "").lower().strip()
    price_range = CATEGORY_PRICE_RANGES.get(cat)

    if not price_range:
        # 未知品类，只做基础检查
        if unit_price_usd > 1_000_000:
            return AuditResult("block", 10, [f"价格异常高: {unit_price_usd}"])
        return AuditResult("pass", 80, [f"未知品类 '{cat}'，跳过区间校验"])

    min_price, max_price, unit = price_range

    # block 阈值极宽：只有明显异常（<1% 或 >10000% 市场价）才拦截
    if unit_price_usd < min_price * 0.01:
        return AuditResult("block", 20, [
            f"价格异常低（低于品类 '{cat}' 市场价 1%）：${unit_price_usd}/{unit}（市场最低 ${min_price}/{unit}）"
        ])

    if unit_price_usd > max_price * 100:
        return AuditResult("block", 20, [
            f"价格异常高（高于品类 '{cat}' 市场价 100 倍）：${unit_price_usd}/{unit}（市场最高 ${max_price}/{unit}）"
        ])

    # review 阈值：偏离 5 倍以内只标记不拦截（B2B 量大优惠/定制加价都正常）
    if unit_price_usd < min_price * 0.2 or unit_price_usd > max_price * 5:
        return AuditResult("review", 70, [
            f"价格偏离品类 '{cat}' 市场区间（${min_price}-${max_price}/{unit}，报价 ${unit_price_usd}）"
        ])

    return AuditResult("pass", 100, [])


# ===== 数量合理性 =====

def validate_quantity(quantity: int) -> AuditResult:
    """验证采购数量是否合理"""
    if quantity <= 0:
        return AuditResult("block", 0, [f"数量非正数: {quantity}"])

    # B2B 样品单 1-99 件完全正常，不标记不拦截
    sample_max = QUANTITY_RANGES.get("sample_max", 99)
    if quantity <= sample_max:
        return AuditResult("pass", 95, [f"样品单（{quantity} 件）"])

    if quantity > QUANTITY_RANGES["max"]:
        return AuditResult("block", 10, [f"数量异常大: {quantity}（超过 {QUANTITY_RANGES['max']:,}）"])

    return AuditResult("pass", 100, [])


# ===== 交期合理性 =====

def validate_lead_time(lead_time_days: int) -> AuditResult:
    """验证交期是否合理"""
    if lead_time_days < 0:
        return AuditResult("block", 0, [f"交期为负数: {lead_time_days} 天"])

    min_d, max_d = LEAD_TIME_RANGE
    # 0 天 = 现货/数字产品，允许
    if lead_time_days == 0:
        return AuditResult("pass", 95, ["现货/即时交付"])

    if lead_time_days > max_d:
        return AuditResult("review", 60, [f"交期较长: {lead_time_days} 天（超过 {max_d} 天）"])

    return AuditResult("pass", 100, [])


# ===== 内容合规审核 =====

def audit_text_content(text: str) -> AuditResult:
    """文本内容合规审核：违禁品 + 钓鱼/垃圾"""
    if not text:
        return AuditResult("pass", 100, ["内容为空，跳过"])

    text_lower = text.lower()
    reasons = []
    score = 100

    # 违禁品检测
    for kw in FORBIDDEN_KEYWORDS:
        if kw.lower() in text_lower:
            return AuditResult("block", 0, [f"检测到违禁关键词: '{kw}'"])

    # 钓鱼/垃圾模式
    for pattern in SPAM_PATTERNS:
        if re.search(pattern, text, re.I):
            score -= 30
            reasons.append(f"检测到垃圾/钓鱼模式: {pattern}")

    # 可疑链接过多
    urls = re.findall(r"https?://\S+", text)
    if len(urls) > 5:
        score -= 20
        reasons.append(f"包含过多链接 ({len(urls)} 个)")

    # 纯大写（喊叫式）
    if len(text) > 50 and text == text.upper():
        score -= 10
        reasons.append("全大写文本（疑似垃圾信息）")

    if score < 60:
        return AuditResult("review", score, reasons)
    elif reasons:
        return AuditResult("pass", score, reasons)
    return AuditResult("pass", 100, [])


# ===== LLM 深度审核（可选，需要 LLM 可用）=====

def audit_text_with_llm(text: str, llm_provider=None) -> AuditResult:
    """用 LLM 做深度内容审核（欺诈/钓鱼/不专业表达）"""
    if not llm_provider or not llm_provider.is_available():
        return AuditResult("pass", 100, ["LLM 不可用，跳过深度审核"])

    try:
        prompt = f"""请审核以下 B2B 询单内容，判断是否存在以下风险：
1. 欺诈/钓鱼（试图骗取钱财或信息）
2. 不专业表达（与真实采购意图不符）
3. 违禁品询价（武器/毒品/制假等）
4. 垃圾信息（广告/无关内容）

询单内容：
{text[:1000]}

请用 JSON 格式返回：
{{"risk_level": "low|medium|high", "reasons": ["原因1", "原因2"]}}"""

        # 复用 LLM provider 的 raw call
        # 注意：ArkProvider 的属性是 BASE_URL（类属性大写）和 flash_model（非 model_flash）
        import requests
        resp = requests.post(
            f"{llm_provider.BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {llm_provider.api_key}"},
            json={
                "model": llm_provider.flash_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 200,
            },
            timeout=10,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        # 解析 JSON
        import json
        # 去除可能的 markdown 代码块
        content = content.strip().strip("`").strip()
        if content.startswith("json"):
            content = content[4:].strip()
        result = json.loads(content)

        risk = result.get("risk_level", "low")
        reasons = result.get("reasons", [])

        if risk == "high":
            return AuditResult("block", 20, [f"LLM 审核高风险: {', '.join(reasons)}"])
        elif risk == "medium":
            return AuditResult("review", 60, [f"LLM 审核中风险: {', '.join(reasons)}"])
        return AuditResult("pass", 100, [])

    except Exception as e:
        logger.warning(f"LLM 审核失败: {e}")
        return AuditResult("pass", 90, [f"LLM 审核异常: {e}"])


# ===== 综合审核：买家询单 =====

def audit_buyer_inquiry(
    email: str,
    raw_message: str,
    quantity: int,
    target_price_usd: float,
    category: str = "",
    llm_provider=None,
) -> AuditResult:
    """买家询单综合审核"""
    reasons = []
    score = 100
    details = {}

    # 1. 邮箱验证
    email_audit = validate_email(email, check_mx=True)
    details["email"] = email_audit.to_dict()
    if email_audit.blocked:
        return email_audit  # 邮箱不合规直接拦截
    if email_audit.level == "review":
        score = min(score, email_audit.score)
        reasons.extend(email_audit.reasons)

    # 2. 内容合规
    content_audit = audit_text_content(raw_message)
    details["content"] = content_audit.to_dict()
    if content_audit.blocked:
        return content_audit  # 违禁品直接拦截
    if content_audit.level == "review":
        score = min(score, content_audit.score)
        reasons.extend(content_audit.reasons)

    # 3. 数量合理性
    qty_audit = validate_quantity(quantity)
    details["quantity"] = qty_audit.to_dict()
    if qty_audit.blocked:
        return qty_audit
    if qty_audit.level == "review":
        score = min(score, qty_audit.score)
        reasons.extend(qty_audit.reasons)

    # 4. 价格合理性
    if target_price_usd > 0:
        price_audit = validate_price(target_price_usd, category, quantity)
        details["price"] = price_audit.to_dict()
        if price_audit.blocked:
            return price_audit
        if price_audit.level == "review":
            score = min(score, price_audit.score)
            reasons.extend(price_audit.reasons)

    # 5. LLM 深度审核（可选）
    if raw_message and llm_provider:
        llm_audit = audit_text_with_llm(raw_message, llm_provider)
        details["llm"] = llm_audit.to_dict()
        if llm_audit.blocked:
            return llm_audit
        if llm_audit.level == "review":
            score = min(score, llm_audit.score)
            reasons.extend(llm_audit.reasons)

    # 综合定级
    if score < 60:
        return AuditResult("review", score, reasons or ["综合评分偏低"], details)
    return AuditResult("pass", score, reasons, details)


# ===== 综合审核：工厂报价 =====

def audit_supplier_quote(
    unit_price_usd: float,
    target_price_usd: float,
    quantity: int,
    lead_time_days: int,
    moq: int,
    category: str,
    supplier_trust_score: int = 100,
) -> AuditResult:
    """工厂报价综合审核"""
    reasons = []
    score = 100
    details = {}

    # 1. 价格合理性（品类区间）
    price_audit = validate_price(unit_price_usd, category, quantity)
    details["price"] = price_audit.to_dict()
    if price_audit.blocked:
        return price_audit
    if price_audit.level == "review":
        score = min(score, price_audit.score)
        reasons.extend(price_audit.reasons)

    # 2. 报价 vs 目标价偏离
    if target_price_usd > 0:
        ratio = unit_price_usd / target_price_usd
        details["price_vs_target"] = {"ratio": round(ratio, 2)}
        if ratio < 0.3:
            return AuditResult("block", 10, [
                f"报价远低于目标价（目标 ${target_price_usd}，报价 ${unit_price_usd}，比值 {ratio:.0%}）— 疑似欺诈"
            ])
        if ratio > 5:
            return AuditResult("block", 10, [
                f"报价远高于目标价（目标 ${target_price_usd}，报价 ${unit_price_usd}，比值 {ratio:.0%}）— 疑似宰客"
            ])
        if ratio < 0.5 or ratio > 2:
            score = min(score, 60)
            reasons.append(f"报价偏离目标价（比值 {ratio:.0%}）")

    # 3. MOQ 校验
    if moq > quantity:
        return AuditResult("block", 20, [
            f"MOQ ({moq}) 大于采购数量 ({quantity})"
        ])

    # 4. 交期合理性
    lt_audit = validate_lead_time(lead_time_days)
    details["lead_time"] = lt_audit.to_dict()
    if lt_audit.blocked:
        return lt_audit
    if lt_audit.level == "review":
        score = min(score, lt_audit.score)
        reasons.extend(lt_audit.reasons)

    # 5. 供应商信誉
    if supplier_trust_score < 30:
        score = min(score, 40)
        reasons.append(f"供应商信誉过低 (trust_score={supplier_trust_score})")

    if score < 60:
        return AuditResult("review", score, reasons, details)
    return AuditResult("pass", score, reasons, details)


# ===== 综合审核：工厂注册 =====

def audit_supplier_registration(
    company_name: str,
    email: str,
    phone: str,
    uscc: str = "",
    country: str = "CN",
    llm_provider=None,
) -> AuditResult:
    """工厂注册综合审核"""
    reasons = []
    score = 100
    details = {}

    # 1. 邮箱验证
    email_audit = validate_email(email, check_mx=True)
    details["email"] = email_audit.to_dict()
    if email_audit.blocked:
        return email_audit
    if email_audit.level == "review":
        score = min(score, email_audit.score)
        reasons.extend(email_audit.reasons)

    # 2. 公司名验证
    name_audit = validate_company_name(company_name, country)
    details["company_name"] = name_audit.to_dict()
    if name_audit.blocked:
        return name_audit
    if name_audit.level == "review":
        score = min(score, name_audit.score)
        reasons.extend(name_audit.reasons)

    # 3. 手机号验证
    phone_audit = validate_phone(phone, country)
    details["phone"] = phone_audit.to_dict()
    if phone_audit.blocked:
        return phone_audit
    if phone_audit.level == "review":
        score = min(score, phone_audit.score)
        reasons.extend(phone_audit.reasons)

    # 4. 统一社会信用代码（中国工厂）
    if country in ("CN", "中国", "") and uscc:
        uscc_audit = validate_uscc(uscc)
        details["uscc"] = uscc_audit.to_dict()
        if uscc_audit.level == "review":
            score = min(score, uscc_audit.score)
            reasons.extend(uscc_audit.reasons)

    if score < 60:
        return AuditResult("review", score, reasons, details)
    return AuditResult("pass", score, reasons, details)
