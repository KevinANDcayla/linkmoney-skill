"""
LinkMoney LLM 层 — 火山引擎豆包（Ark API）
==========================================

设计原则：
  - 使用火山引擎豆包模型（国内云服务，数据不出境，安全合规）
  - 翻译/RFQ解析走 deepseek-v4-flash-260425（够用 + 便宜 + 中文强）
  - 工厂图片提取走 doubao-seed-1-6-vision-250815（多模态）
  - 所有调用 1:1 输入输出比例，按需使用 response_format=json_object
  - 火山引擎 ARK API 兼容 OpenAI 格式，调用方式一致

安全与隐私：
  - 使用火山引擎（字节跳动国内云服务），数据不出境，符合国内合规要求
  - 火山引擎域名 ark.cn-beijing.volces.com 在国内可信范围内
  - 可通过环境变量 LLM_ENABLED=false 完全禁用所有 LLM 调用
  - 未配置 API Key 时自动降级为规则引擎，不影响核心功能
  - 对返回的 JSON 数据实施严格验证（深度限制+键名白名单+大小限制）

成本估算（51 工厂 + 日 100 RFQ）：
  - 双向单次翻译：月 2M tok × ¥0.8/M = ¥1.6
  - RFQ 解析：月 0.1M tok × ¥0.8/M = ¥0.08
  - 工厂图片提取（doubao-seed-1-6-vision）：51 张 × 4K tok = ¥0.5
  - 报价草稿：月 0.05M tok = ¥0.04
  - 合计：¥2.2 / $0.3 / 月
"""

import os
import json
import logging
import time
import hashlib
import requests
from typing import Optional, Dict, Any, List
from threading import Lock
from functools import lru_cache

logger = logging.getLogger("linkmoney.llm")


class LLMError(Exception):
    """LLM API 错误"""
    pass


# 向后兼容别名（server.py 仍引用 DeepSeekError）
DeepSeekError = LLMError


def is_llm_enabled() -> bool:
    """
    检查 LLM 功能是否启用。

    启用条件（全部满足）：
    1. 环境变量 LLM_ENABLED 不为 "false"（默认启用）
    2. 环境变量 ARK_API_KEY 已配置（火山引擎 API Key）

    禁用方式：
    - 设置 LLM_ENABLED=false 完全禁用
    - 不设置 ARK_API_KEY（自动降级为规则引擎）

    安全说明：
    - 使用火山引擎豆包模型（国内云服务，数据不出境）
    - 火山引擎域名 ark.cn-beijing.volces.com 在国内可信范围内
    - 未启用时所有 LLM 调用自动降级为规则引擎，不发送任何数据到外部
    - 启用后对返回的 JSON 数据实施严格验证（深度限制+键名白名单+大小限制）
    """
    if os.getenv("LLM_ENABLED", "true").lower() == "false":
        return False
    return bool(os.getenv("ARK_API_KEY", ""))


# ===== LLM 返回数据安全验证 =====

# 允许的 JSON 键名白名单（ARK API 返回结构，兼容 deepseek + doubao）
_LLM_RESPONSE_ALLOWED_KEYS = {"id", "object", "created", "model", "choices", "usage", "system_fingerprint", "service_tier"}
# 允许的 choices 内部键名
_LLM_CHOICE_KEYS = {"index", "message", "finish_reason", "logprobs"}
# 允许的 message 内部键名（deepseek-v4 返回 reasoning_content 思考过程）
_LLM_MESSAGE_KEYS = {"role", "content", "reasoning_content"}
# 最大解析深度
_LLM_MAX_DEPTH = 5
# 最大响应大小（字节）
_LLM_MAX_RESPONSE_SIZE = 64 * 1024  # 64KB


def _validate_llm_response(data: Any, depth: int = 0, parent_key: str = "") -> bool:
    """
    严格验证 ARK API 返回的 JSON 数据。

    安全措施：
    - 键名白名单：仅对 choices/message 路径检查预定义字段
    - 深度限制：解析深度 ≤ 5 层
    - 类型检查：仅允许基本 JSON 类型
    - 长度限制：单字段值 ≤ 32KB
    """
    if depth > _LLM_MAX_DEPTH:
        return False

    if not isinstance(data, (str, int, float, bool, list, dict, type(None))):
        return False

    if isinstance(data, str):
        return len(data.encode("utf-8")) <= 32 * 1024

    if isinstance(data, dict):
        # 仅对特定路径检查键名白名单（避免误杀 usage 等正常字段）
        if depth == 0:
            for key in data:
                if key not in _LLM_RESPONSE_ALLOWED_KEYS:
                    return False
        elif parent_key == "choices":
            for key in data:
                if key not in _LLM_CHOICE_KEYS:
                    return False
        elif parent_key == "message":
            for key in data:
                if key not in _LLM_MESSAGE_KEYS:
                    return False
        for key, val in data.items():
            if not _validate_llm_response(val, depth + 1, parent_key=key):
                return False
        return True

    if isinstance(data, list):
        if len(data) > 10:
            return False
        for item in data:
            if not _validate_llm_response(item, depth + 1, parent_key=parent_key):
                return False
        return True

    return True


class ArkProvider:
    """
    火山引擎豆包 LLM 封装（ARK API，兼容 OpenAI 格式）。

    - deepseek-v4-flash-260425：翻译、RFQ 解析、报价草稿（够用 + 便宜 + 中文强）
    - doubao-seed-1-6-vision-250815：工厂图片提取（多模态）

    安全控制：
    - 使用火山引擎国内云服务，数据不出境
    - 可通过 LLM_ENABLED=false 禁用
    - 未配置 API Key 时自动降级为规则引擎
    - 对返回 JSON 实施严格验证
    """

    BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"  # 火山引擎 ARK API（国内）
    DEFAULT_TIMEOUT = 30  # 秒

    # 简单内存缓存：相同 input 1 小时内不重复调 LLM
    _cache: Dict[str, tuple] = {}  # key -> (timestamp, value)
    _cache_lock = Lock()
    CACHE_TTL = 3600  # 1 小时

    def __init__(self, api_key: Optional[str] = None):
        # LLM 默认启用（火山引擎国内云服务，数据不出境）
        self._llm_disabled = os.getenv("LLM_ENABLED", "true").lower() == "false"
        if self._llm_disabled:
            logger.info("LLM 功能已通过 LLM_ENABLED=false 禁用，所有调用将降级为规则引擎")
            self.api_key = ""
        else:
            self.api_key = api_key or os.getenv("ARK_API_KEY", "")
            if not self.api_key:
                logger.warning(
                    "ARK_API_KEY not set — LLM features will fallback to rule-based"
                )

        # 火山引擎豆包模型（可通过环境变量覆盖）
        # v5.1.1 — 默认模型更新为 deepseek-v4-flash + doubao-seed-1-6-vision
        self.flash_model = os.getenv("ARK_TEXT_MODEL", "deepseek-v4-flash-260425")
        self.pro_model = os.getenv("ARK_VISION_MODEL", "doubao-seed-1-6-vision-250815")

    def is_available(self) -> bool:
        """是否配置了 API key 且 LLM 未被禁用（没有就 fallback）"""
        if self._llm_disabled:
            return False
        return bool(self.api_key)

    def _cache_key(self, model: str, messages: list, **kwargs) -> str:
        """生成缓存 key"""
        h = hashlib.sha256()
        h.update(model.encode())
        h.update(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode())
        h.update(json.dumps(kwargs, sort_keys=True).encode())
        return h.hexdigest()

    def _cache_get(self, key: str):
        with self._cache_lock:
            if key in self._cache:
                ts, val = self._cache[key]
                if time.time() - ts < self.CACHE_TTL:
                    return val
                del self._cache[key]
        return None

    def _cache_set(self, key: str, val):
        with self._cache_lock:
            self._cache[key] = (time.time(), val)

    def _call(
        self,
        model: str,
        messages: list,
        max_tokens: int = 2000,
        temperature: float = 0.3,
        use_cache: bool = True,
        **kwargs,
    ) -> str:
        """
        调火山引擎 ARK Chat Completion API。

        - 自动 1 小时缓存
        - response_format=json_object 仅对支持的模型启用（deepseek 系列不支持）
        - 失败抛 LLMError
        """
        if not self.is_available():
            raise LLMError("ARK_API_KEY not configured")

        # 缓存检查（只缓存纯文本场景，图片场景不缓存）
        if use_cache and all(isinstance(m.get("content"), str) for m in messages):
            cache_key = self._cache_key(model, messages, max_tokens=max_tokens, temperature=temperature, **kwargs)
            cached = self._cache_get(cache_key)
            if cached is not None:
                logger.debug(f"LLM cache hit: {cache_key[:8]}")
                return cached

        url = f"{self.BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # v5.1.1 — deepseek 系列模型不支持 response_format=json_object，自动跳过
        supports_json_mode = not model.startswith("deepseek-")
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }
        if supports_json_mode:
            body["response_format"] = {"type": "json_object"}

        try:
            r = requests.post(url, headers=headers, json=body, timeout=self.DEFAULT_TIMEOUT)
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Ark API call failed: {e}")
            raise LLMError(f"Ark API error: {e}") from e

        # 安全验证：检查响应大小限制
        if len(r.content) > _LLM_MAX_RESPONSE_SIZE:
            logger.error(f"Ark response exceeds size limit: {len(r.content)} > {_LLM_MAX_RESPONSE_SIZE}")
            raise LLMError(f"Ark response too large: {len(r.content)} bytes")

        # 安全验证：解析 JSON 并严格验证返回数据结构
        try:
            data = r.json()
        except Exception as e:
            logger.error(f"Ark response JSON parse failed: {e}")
            raise LLMError(f"Ark response JSON parse error") from e

        # 严格验证返回数据（键名白名单 + 深度限制 + 类型检查）
        if not _validate_llm_response(data):
            logger.error(f"Ark response validation failed: unexpected structure")
            raise LLMError("Ark response validation failed: unexpected structure")

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            logger.error(f"Ark response malformed: {data}")
            raise LLMError(f"Ark response malformed: {data}") from e

        if use_cache:
            self._cache_set(cache_key, content)

        return content

    # ===== 1. 双向单次翻译 =====

    # 支持的语言（避免 8 国语言过度设计）
    SUPPORTED_LANGS = {
        "en": "English",
        "zh": "中文",
        "ja": "日本語",
        "de": "Deutsch",
        "es": "Español",
        "fr": "Français",
        "ar": "العربية",
        "pt": "Português",
        "ru": "Русский",
    }

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        """
        双向单次翻译。

        场景：
        - 买家 RFQ (en) → 翻译成中文 → 工厂主看
        - 工厂主报价 (zh) → 翻译成买家语言 → 买家看
        """
        if not text or not text.strip():
            return text

        if src_lang == tgt_lang:
            return text

        src_name = self.SUPPORTED_LANGS.get(src_lang, src_lang)
        tgt_name = self.SUPPORTED_LANGS.get(tgt_lang, tgt_lang)

        result = self._call(
            self.flash_model,
            [{
                "role": "user",
                "content": f"""Translate this B2B RFQ / quote from {src_name} to {tgt_name}.

Rules:
- Keep technical terms unchanged: FOB, CIF, EXW, MOQ, DIN, ISO, ASTM, GB, JIS, incoterm
- Keep company names, ports, SKU codes unchanged
- Use formal business tone
- Preserve numbers, units, dimensions exactly

Return JSON: {{"translation": "<translated text>", "key_terms": ["term1", "term2"]}}

Input text ({src_name}):
{text}"""
            }],
        )
        try:
            parsed = json.loads(result)
            return parsed.get("translation", result)
        except json.JSONDecodeError:
            return result

    # ===== 2. RFQ 智能解析 =====

    def parse_rfq(self, raw_text: str, lang: str = "auto") -> dict:
        """
        从买家自然语言 RFQ 提取结构化字段。

        返回:
        {
            "category": "fastener|electronics|packaging|hardware|injection_molding|machinery|textile",
            "spec": "M8 304 stainless hex bolt",
            "quantity": 50000,
            "target_price_usd": null or float,
            "urgency": "low|normal|high",
            "destination_port": "Los Angeles" or null,
            "deadline": "2026-08" or null,
            "language": "en|zh|ja|...",
            "buyer_intent_summary": "..."
        }
        """
        if not raw_text or not raw_text.strip():
            return {"error": "empty input"}

        result = self._call(
            self.flash_model,
            [{
                "role": "user",
                "content": f"""Extract structured fields from this B2B RFQ (Request for Quotation).
The RFQ is in {lang} language (auto-detect if "auto").

Return ONLY valid JSON with these fields:
{{
  "category": "one of: fastener, electronics, packaging, hardware, injection_molding, machinery, textile, other",
  "spec": "concise product spec (material, size, standard)",
  "quantity": integer or null,
  "target_price_usd": float or null,
  "urgency": "low | normal | high",
  "destination_port": "city name or null",
  "deadline": "YYYY-MM or null",
  "language": "ISO 639-1 code (en/zh/ja/de/es/fr/ar/pt/ru)",
  "buyer_intent_summary": "1-sentence English summary of what buyer wants"
}}

RFQ text:
\"\"\"{raw_text}\"\"\""""
            }],
        )
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            logger.error(f"parse_rfq JSON parse failed: {result[:200]}")
            return {
                "category": "other",
                "spec": raw_text[:100],
                "quantity": None,
                "urgency": "normal",
                "language": lang if lang != "auto" else "en",
                "_raw": result[:500],
            }

    # ===== 3. 工厂数据提取（V4 Pro 多模态）=====

    def extract_factory_profile(
        self,
        image_urls: List[str],
        audio_text: str = "",
        location: str = "",
    ) -> dict:
        """
        BD 现场采集的非结构化数据 → 结构化入库。

        输入：
        - image_urls: BD 拍的车间/设备/产品照片 URL 列表
        - audio_text: BD 录的产品介绍文字转写
        - location: 工厂地址（可选）

        返回：
        {
            "year_established": 2003,
            "employees": 280,
            "annual_capacity": "80M pcs/year",
            "certifications": ["ISO 9001", "CE"],
            "main_products": ["M8 stainless bolt", "..."],
            "moq": 5000,
            "main_export_markets": ["EU", "Southeast Asia"],
            "trust_signals": ["automated cold heading", "3 shifts"],
            "red_flags": [],
            "suggested_category": "fastener",
            "confidence": 0.85
        }
        """
        if not self.is_available():
            raise LLMError("ARK_API_KEY not configured")

        # V4 Pro 支持多模态
        content = []
        for url in image_urls[:10]:  # 限制最多 10 张图
            content.append({"type": "image_url", "image_url": {"url": url}})

        prompt = f"""Analyze these factory photos and audio transcript from a Chinese factory site visit.
Extract structured supplier information.

Factory location: {location or "unknown"}
Audio transcript (BD recorded): {audio_text or "none"}

Return ONLY valid JSON:
{{
  "year_established": integer or null,
  "employees": integer or null,
  "annual_capacity": "human-readable string",
  "certifications": ["list of certs seen or mentioned"],
  "main_products": ["list of main products"],
  "moq": integer or null,
  "main_export_markets": ["countries/regions"],
  "trust_signals": ["things that increase trust: automation, scale, certs visible, etc."],
  "red_flags": ["things that decrease trust: outdated equipment, dirty facility, etc."],
  "suggested_category": "fastener|electronics|packaging|hardware|injection_molding|machinery|textile|other",
  "confidence": float 0-1 indicating how confident you are
}}"""

        content.append({"type": "text", "text": prompt})

        result = self._call(
            self.pro_model,
            [{"role": "user", "content": content}],
            max_tokens=2500,
            use_cache=False,  # 图片场景不缓存
        )

        try:
            return json.loads(result)
        except json.JSONDecodeError:
            logger.error(f"extract_factory_profile JSON parse failed")
            return {"_raw": result[:1000], "_error": "JSON parse failed"}

    # ===== 4. 报价邮件草拟 =====

    def draft_quote_email(
        self,
        rfq: dict,
        supplier: dict,
        quote_price_usd: float,
        lead_time_days: int,
        buyer_lang: str = "en",
    ) -> dict:
        """
        工厂主口述"3000 USD/吨，30 天交期" → 帮写专业英文报价邮件。

        返回：{"subject": "...", "body": "..."}
        """
        result = self._call(
            self.flash_model,
            [{
                "role": "user",
                "content": f"""Draft a professional quote email in {self.SUPPORTED_LANGS.get(buyer_lang, 'English')}.

Buyer's RFQ (parsed):
- Category: {rfq.get('category')}
- Spec: {rfq.get('spec')}
- Quantity: {rfq.get('quantity')}
- Destination: {rfq.get('destination_port', 'unspecified')}
- Deadline: {rfq.get('deadline', 'unspecified')}

Supplier:
- Company: {supplier.get('name', 'Chinese supplier')}
- City: {supplier.get('city', 'China')}

Quote:
- Price: USD {quote_price_usd} per unit/MT
- Lead time: {lead_time_days} days
- Incoterm: FOB (default)

Return JSON: {{"subject": "<email subject>", "body": "<email body with greeting/spec/price/lead time/next steps/signature>"}}"""
            }],
        )
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"subject": f"Quote for {rfq.get('spec', 'your RFQ')}", "body": result}

    # ===== 5. 关键术语提取（独立工具）=====

    def extract_key_terms(self, text: str, lang: str = "auto") -> List[str]:
        """从 RFQ/Quote 文本提取关键术语（型号、标准、港口等），避免翻译丢失。"""
        if not text or not text.strip():
            return []

        result = self._call(
            self.flash_model,
            [{
                "role": "user",
                "content": f"""Extract key technical/business terms from this B2B text ({lang}).
Include: SKU codes, material grades, standards (ISO/ASTM/GB/DIN/JIS), ports, incoterms, certifications, dimensions.
Return JSON: {{"key_terms": ["M8", "304 SS", "DIN 912", "FOB Ningbo", ...]}}

Text:
{text}"""
            }],
        )
        try:
            parsed = json.loads(result)
            return parsed.get("key_terms", [])
        except json.JSONDecodeError:
            return []


# ===== 单例 =====

_llm_instance: Optional[ArkProvider] = None
_llm_lock = Lock()


def get_llm() -> ArkProvider:
    """获取 LLM 单例（线程安全）"""
    global _llm_instance
    if _llm_instance is None:
        with _llm_lock:
            if _llm_instance is None:
                _llm_instance = ArkProvider()
    return _llm_instance


# 向后兼容别名（旧代码可能引用 DeepSeekProvider）
DeepSeekProvider = ArkProvider
