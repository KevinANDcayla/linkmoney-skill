"""
LinkMoney 中间 Agent 维护层（v3.0）

定位：作为双边 Skill（C 端 + W 端）之间的「中间维护者」，承担
- 厂家 MCP 健康检查
- 路由策略决策（哪条 RFQ 走哪家工厂）
- 告警与异常发现
- 自我优化（基于历史指标调整权重）
- 维护日志审计

设计为内嵌在主 API server.py 中，独立模块，避免与主业务耦合。
"""
import asyncio
import json
import time
import uuid
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urljoin

import requests


def _db():
    """延迟获取 server.get_db，避开与 server.py 的循环导入。"""
    import server  # 局部 import
    return server.get_db


def _log():
    import server
    return server.logger


# ===== Agent 元数据 =====

AGENT_ID = "linkmoney-middle-agent"
AGENT_VERSION = "3.0.0"
AGENT_NAME_ZH = "LinkMoney 中间 Agent"
AGENT_DESCRIPTION = (
    "双边 Skill 之间的维护者：监控厂家 MCP 健康、决定 RFQ 路由、"
    "发现异常告警、基于历史指标自我优化。"
)


# ===== 健康检查 =====

_HEALTH_TIMEOUT = 5  # 厂家 MCP 健康检查超时（秒）— 更严格限制
_HEALTH_CONCURRENCY = 4  # 并发检查数（降低以减少外部请求压力）
_HEALTH_MAX_RETRIES = 1  # 最大重试次数（失败即标记 degraded，不重试）

# ===== 供应商端点熔断机制 =====

# 熔断状态：endpoint -> {"failures": int, "tripped": bool, "tripped_at": float, "half_open": bool}
_CIRCUIT_BREAKER: dict = {}
_CB_FAILURE_THRESHOLD = 3  # 连续失败 3 次触发熔断
_CB_RECOVERY_SECONDS = 300  # 熔断 5 分钟后进入半开状态
_CB_LOCK = threading.Lock()


def _is_circuit_tripped(endpoint: str) -> bool:
    """检查端点是否被熔断"""
    with _CB_LOCK:
        state = _CIRCUIT_BREAKER.get(endpoint)
        if not state:
            return False
        if not state["tripped"]:
            return False
        # 检查是否已过恢复时间
        import time as _time
        elapsed = _time.time() - state["tripped_at"]
        if elapsed >= _CB_RECOVERY_SECONDS:
            # 进入半开状态，允许一次试探请求
            state["half_open"] = True
            return False
        return True


def _record_circuit_failure(endpoint: str):
    """记录端点验证失败"""
    import time as _time
    with _CB_LOCK:
        state = _CIRCUIT_BREAKER.setdefault(endpoint, {"failures": 0, "tripped": False, "tripped_at": 0, "half_open": False})
        state["failures"] += 1
        if state["failures"] >= _CB_FAILURE_THRESHOLD and not state["tripped"]:
            state["tripped"] = True
            state["tripped_at"] = _time.time()
            logger.warning(f"[CIRCUIT_BREAKER] Endpoint tripped: {endpoint} (failures={state['failures']})")


def _record_circuit_success(endpoint: str):
    """记录端点验证成功（重置熔断状态）"""
    with _CB_LOCK:
        if endpoint in _CIRCUIT_BREAKER:
            del _CIRCUIT_BREAKER[endpoint]

# ===== 供应商端点白名单机制 =====

# 允许的供应商 MCP 端点域名后缀白名单
# 仅 LinkMoney 托管端点和已审核的自部署端点可发起健康检查
_SUPPLIER_ENDPOINT_WHITELIST = [
    "linkmoney.online",       # LinkMoney 官方托管端点
    "linkmoney.online:8765",  # 含端口
    "localhost",              # 本地开发环境
    "127.0.0.1",              # 本地开发环境
]

# 是否启用端点白名单严格模式（true=仅白名单内端点可检查，false=记录警告但仍检查）
_ENDPOINT_STRICT_MODE = True


def _is_endpoint_allowed(endpoint: str) -> bool:
    """
    检查供应商 MCP 端点是否在白名单内。

    安全措施：
    - 仅允许预审核的域名后缀
    - 阻止未知外部域名的健康检查请求
    - 严格模式下拒绝非白名单端点
    """
    if not endpoint:
        return False

    # 提取域名（去掉 https:// 和路径）
    try:
        from urllib.parse import urlparse
        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        port = parsed.port
        # 构造 host:port 形式用于匹配
        host_with_port = f"{host}:{port}" if port else host

        # 检查白名单
        for allowed in _SUPPLIER_ENDPOINT_WHITELIST:
            if host == allowed or host_with_port == allowed:
                return True
            # 支持子域名匹配（如 mcp.supplier.linkmoney.online）
            if host.endswith("." + allowed):
                return True

        if _ENDPOINT_STRICT_MODE:
            logger.warning(f"Endpoint not in whitelist (strict mode): {endpoint}")
            return False
        else:
            logger.warning(f"Endpoint not in whitelist (non-strict, allowing): {endpoint}")
            return True
    except Exception:
        return False


def _log_health_check(supplier_id: str, endpoint: str, status: str, latency: int, note: str = ""):
    """
    审计日志：记录所有对外部供应商端点的健康检查请求。

    用于安全审计追踪，记录：
    - 请求目标（supplier_id + endpoint）
    - 请求结果（status + latency）
    - 异常说明（note）
    """
    logger.info(
        f"[HEALTH_CHECK_AUDIT] supplier={supplier_id} endpoint={endpoint} "
        f"status={status} latency={latency}ms note={note}"
    )


# ===== manifest.json 安全验证 =====

# 允许的字段白名单
_MANIFEST_ALLOWED_FIELDS = {"name", "tools", "version", "description", "homepage", "api_key", "base_url", "endpoints"}
# 单字段值最大长度（字节）
_MANIFEST_MAX_FIELD_SIZE = 10 * 1024  # 10KB
# 整个 manifest 最大长度（字节）
_MANIFEST_MAX_TOTAL_SIZE = 100 * 1024  # 100KB
# 允许的 JSON 值类型
_MANIFEST_ALLOWED_TYPES = (str, int, float, bool, list, dict, type(None))


def _validate_manifest(data: Any, depth: int = 0, max_depth: int = 3) -> bool:
    """
    严格验证从外部供应商 MCP 端点获取的 manifest.json 数据。

    安全措施：
    - 字段白名单：仅允许预定义字段，拒绝未知字段
    - 深度限制：解析深度 ≤ 3 层，防止嵌套注入
    - 长度限制：单字段 ≤ 10KB，总响应 ≤ 100KB
    - 类型白名单：仅允许基本 JSON 类型，拒绝函数字符串
    """
    if depth > max_depth:
        return False

    if not isinstance(data, _MANIFEST_ALLOWED_TYPES):
        return False

    if isinstance(data, str):
        return len(data.encode("utf-8")) <= _MANIFEST_MAX_FIELD_SIZE

    if isinstance(data, dict):
        # 检查字段白名单（仅顶层 dict 检查字段名）
        if depth == 0:
            for key in data:
                if key not in _MANIFEST_ALLOWED_FIELDS:
                    return False
        # 递归检查值
        for key, val in data.items():
            if not _validate_manifest(val, depth + 1, max_depth):
                return False
        return True

    if isinstance(data, list):
        if len(data) > 100:  # 列表长度限制
            return False
        for item in data:
            if not _validate_manifest(item, depth + 1, max_depth):
                return False
        return True

    return True


async def _check_one_supplier(sess: requests.Session, supplier: dict) -> dict:
    """检查单个厂家 MCP 的健康度。"""
    endpoint = supplier.get("skill_mcp_endpoint", "").strip()
    sid = supplier["id"]
    name = supplier.get("name_zh") or supplier.get("name_en") or sid

    if not endpoint:
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": "",
            "status": "no_skill",
            "latency_ms": 0,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "note": "未安装 LinkMoney Skill，无 endpoint",
        }

    # 安全检查：端点白名单验证
    if not _is_endpoint_allowed(endpoint):
        _log_health_check(sid, endpoint, "blocked", 0, "endpoint not in whitelist")
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": endpoint,
            "status": "blocked",
            "latency_ms": 0,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "note": "端点未通过白名单审核，健康检查被阻止",
        }

    # 熔断检查：如果端点已被熔断，跳过健康检查
    if _is_circuit_tripped(endpoint):
        _log_health_check(sid, endpoint, "circuit_open", 0, "circuit breaker tripped")
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": endpoint,
            "status": "circuit_open",
            "latency_ms": 0,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "note": "端点熔断中（连续验证失败），5 分钟内跳过健康检查",
        }

    url = urljoin(endpoint.rstrip("/") + "/", "manifest.json")
    t0 = time.time()
    try:
        r = sess.get(url, timeout=_HEALTH_TIMEOUT)
        latency = int((time.time() - t0) * 1000)
        if r.status_code == 200:
            # 检查响应大小限制
            content_length = len(r.content)
            if content_length > _MANIFEST_MAX_TOTAL_SIZE:
                _log_health_check(sid, endpoint, "degraded", latency, f"manifest too large: {content_length} bytes")
                return {
                    "supplier_id": sid,
                    "name": name,
                    "endpoint": endpoint,
                    "status": "degraded",
                    "latency_ms": latency,
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                    "note": f"manifest.json 超过大小限制 ({content_length} > {_MANIFEST_MAX_TOTAL_SIZE} bytes)",
                }
            # 解析 JSON 并严格验证
            try:
                manifest_data = r.json()
            except Exception:
                _log_health_check(sid, endpoint, "degraded", latency, "JSON parse failed")
                _record_circuit_failure(endpoint)
                return {
                    "supplier_id": sid,
                    "name": name,
                    "endpoint": endpoint,
                    "status": "degraded",
                    "latency_ms": latency,
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                    "note": "manifest.json JSON 解析失败",
                }

            # 安全验证：字段白名单 + 深度限制 + 类型检查
            if not _validate_manifest(manifest_data):
                _log_health_check(sid, endpoint, "degraded", latency, "manifest validation failed")
                _record_circuit_failure(endpoint)
                return {
                    "supplier_id": sid,
                    "name": name,
                    "endpoint": endpoint,
                    "status": "degraded",
                    "latency_ms": latency,
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                    "note": "manifest.json 安全验证失败（字段/深度/类型不合规）",
                }

            if "tools" in manifest_data:
                _log_health_check(sid, endpoint, "online", latency, "OK")
                _record_circuit_success(endpoint)
                return {
                    "supplier_id": sid,
                    "name": name,
                    "endpoint": endpoint,
                    "status": "online",
                    "latency_ms": latency,
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                }
        _log_health_check(sid, endpoint, "degraded", latency, f"HTTP {r.status_code}")
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": endpoint,
            "status": "degraded",
            "latency_ms": latency,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "http_status": r.status_code,
        }
    except requests.exceptions.Timeout:
        _log_health_check(sid, endpoint, "offline", int((time.time() - t0) * 1000), "timeout")
        _record_circuit_failure(endpoint)
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": endpoint,
            "status": "offline",
            "latency_ms": int((time.time() - t0) * 1000),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "note": "timeout",
        }
    except Exception as e:  # noqa: BLE001
        _log_health_check(sid, endpoint, "offline", int((time.time() - t0) * 1000), f"error: {str(e)[:100]}")
        _record_circuit_failure(endpoint)
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": endpoint,
            "status": "offline",
            "latency_ms": int((time.time() - t0) * 1000),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(e)[:200],
        }


def run_health_check() -> dict:
    """
    同步执行：拉取所有装 Skill 的厂家，批量检查健康度。
    v3.3: 托管模式（hosted）工厂 100% 在线（同进程），跳过外部探测。
    返回：
      - summary: 在线/降级/离线/未装 数量
      - results: 每个厂家一项
      - generated_at: 时间戳
    """
    with _db()() as conn:
        rows = conn.execute("""
            SELECT id, name_zh, name_en, skill_mcp_endpoint, data_source_type
            FROM suppliers
            WHERE skill_mcp_endpoint IS NOT NULL AND skill_mcp_endpoint != ''
        """).fetchall()
    suppliers = [dict(r) for r in rows]

    # v3.3: 托管模式工厂直接标记 online，不探测
    hosted_results = []
    self_suppliers = []
    for s in suppliers:
        if s.get("data_source_type") == "hosted" or "linkmoney.online/mcp/supplier/" in (s.get("skill_mcp_endpoint") or ""):
            hosted_results.append({
                "supplier_id": s["id"],
                "name": s.get("name_zh") or s.get("name_en") or s["id"],
                "endpoint": s["skill_mcp_endpoint"],
                "status": "online",
                "latency_ms": 0,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
                "note": "托管模式（hosted），同进程，100% 在线",
            })
        else:
            self_suppliers.append(s)

    # 只对自部署（self）工厂做外部 HTTP 探测
    sess = requests.Session()
    sess.headers.update({"User-Agent": f"LinkMoney-MiddleAgent/{AGENT_VERSION}"})
    with ThreadPoolExecutor(max_workers=_HEALTH_CONCURRENCY) as pool:
        self_results = list(pool.map(lambda s: _check_one_supplier_sync(sess, s), self_suppliers))

    results = hosted_results + self_results
    summary = {
        "online": sum(1 for r in results if r["status"] == "online"),
        "degraded": sum(1 for r in results if r["status"] == "degraded"),
        "offline": sum(1 for r in results if r["status"] == "offline"),
        "no_skill": sum(1 for r in results if r["status"] == "no_skill"),
    }
    return {
        "summary": summary,
        "results": results,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _check_one_supplier_sync(sess: requests.Session, supplier: dict) -> dict:
    """同步版本健康检查（避免 asyncio 引入额外复杂度）。

    v5.2: 补齐白名单 + 熔断 + manifest 校验（之前异步版有但同步版缺失）。
    """
    endpoint = supplier.get("skill_mcp_endpoint", "").strip()
    sid = supplier["id"]
    name = supplier.get("name_zh") or supplier.get("name_en") or sid
    if not endpoint:
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": "",
            "status": "no_skill",
            "latency_ms": 0,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "note": "未安装 LinkMoney Skill，无 endpoint",
        }

    # v5.2: 白名单检查 — 非白名单端点直接标记 blocked
    if not _is_endpoint_allowed(endpoint):
        _log_health_check(sid, endpoint, "blocked", 0, "endpoint not in whitelist")
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": endpoint,
            "status": "blocked",
            "latency_ms": 0,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "note": "端点不在白名单内（严格模式拒绝）",
        }

    # v5.2: 熔断检查 — 已熔断的端点直接返回 offline
    if _is_circuit_tripped(endpoint):
        _log_health_check(sid, endpoint, "offline", 0, "circuit breaker tripped")
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": endpoint,
            "status": "offline",
            "latency_ms": 0,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "note": "熔断中（连续失败 3 次，5 分钟后恢复）",
        }

    url = urljoin(endpoint.rstrip("/") + "/", "manifest.json")
    t0 = time.time()
    try:
        r = sess.get(url, timeout=_HEALTH_TIMEOUT)
        latency = int((time.time() - t0) * 1000)

        # v5.2: 响应大小检查
        if len(r.content) > _MANIFEST_MAX_TOTAL_SIZE:
            _record_circuit_failure(endpoint)
            _log_health_check(sid, endpoint, "degraded", latency, f"response too large: {len(r.content)} bytes")
            return {
                "supplier_id": sid,
                "name": name,
                "endpoint": endpoint,
                "status": "degraded",
                "latency_ms": latency,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
                "note": f"响应过大: {len(r.content)} bytes",
            }

        try:
            payload = r.json()
        except Exception:  # noqa: BLE001
            payload = {}
            _record_circuit_failure(endpoint)
            _log_health_check(sid, endpoint, "degraded", latency, "JSON parse failed")
            return {
                "supplier_id": sid,
                "name": name,
                "endpoint": endpoint,
                "status": "degraded",
                "latency_ms": latency,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
                "http_status": r.status_code,
                "note": "JSON 解析失败",
            }

        # v5.2: manifest 字段白名单 + 深度 + 类型校验
        if r.status_code == 200 and isinstance(payload, dict) and "tools" in payload:
            if not _validate_manifest(payload):
                _record_circuit_failure(endpoint)
                _log_health_check(sid, endpoint, "degraded", latency, "manifest validation failed")
                return {
                    "supplier_id": sid,
                    "name": name,
                    "endpoint": endpoint,
                    "status": "degraded",
                    "latency_ms": latency,
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                    "note": "manifest 安全校验失败（字段/深度/类型不合规）",
                }
            # 成功：重置熔断 + 审计日志
            _record_circuit_success(endpoint)
            _log_health_check(sid, endpoint, "online", latency, "ok")
            return {
                "supplier_id": sid,
                "name": name,
                "endpoint": endpoint,
                "status": "online",
                "latency_ms": latency,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
            }
        _record_circuit_failure(endpoint)
        _log_health_check(sid, endpoint, "degraded", latency, f"http {r.status_code}")
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": endpoint,
            "status": "degraded",
            "latency_ms": latency,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "http_status": r.status_code,
        }
    except requests.exceptions.Timeout:
        _record_circuit_failure(endpoint)
        _log_health_check(sid, endpoint, "offline", int((time.time() - t0) * 1000), "timeout")
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": endpoint,
            "status": "offline",
            "latency_ms": int((time.time() - t0) * 1000),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "note": "timeout",
        }
    except Exception as e:  # noqa: BLE001
        _record_circuit_failure(endpoint)
        _log_health_check(sid, endpoint, "offline", int((time.time() - t0) * 1000), str(e)[:200])
        return {
            "supplier_id": sid,
            "name": name,
            "endpoint": endpoint,
            "status": "offline",
            "latency_ms": int((time.time() - t0) * 1000),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(e)[:200],
        }


# ===== 路由决策 =====

def routing_recommend(
    category: str,
    quantity: int = 0,
    target_price_usd: float = 0.0,
    need_live_data: bool = True,
    limit: int = 5,
) -> list[dict]:
    """
    基于厂家健康度 + 信任分 + 评价 + 实时能力，给出 RFQ 路由推荐。
    """
    with _db()() as conn:
        rows = conn.execute("""
            SELECT id, name_zh, name_en, city, category, subcategories,
                   trust_score, review_avg, review_count, gold_badge,
                   skill_mcp_endpoint, agent_skill_installed, skill_installs,
                   lead_time_standard, lead_time_express, moq, annual_revenue_usd
            FROM suppliers
            WHERE category = ? OR category LIKE ?
        """, (category, f"%{category[:3]}%")).fetchall()
        suppliers = [dict(r) for r in rows]

    if not suppliers:
        return []

    health_index = _load_health_index()
    scored: list[dict] = []
    for s in suppliers:
        sid = s["id"]
        health = health_index.get(sid, {})
        health_status = health.get("status", "no_skill")
        health_bonus = {"online": 30, "degraded": 10, "offline": -20, "no_skill": -5}.get(health_status, -5)

        if need_live_data and health_status not in ("online", "degraded"):
            continue  # 需要实时数据但厂家 MCP 不在线，跳过

        score = (
            (s.get("trust_score") or 0) * 0.35
            + (s.get("review_avg") or 0) * 8 * 0.20
            + health_bonus
            + (10 if s.get("gold_badge") else 0)
            + min(15, (s.get("skill_installs") or 0) * 0.5)
            + min(10, (s.get("annual_revenue_usd") or 0) / 5_000_000)
        )

        if quantity and s.get("moq") and quantity < s["moq"]:
            score -= 25
        if target_price_usd and s.get("lead_time_standard"):
            score += max(0, 5 - s["lead_time_standard"] * 0.2)

        scored.append({
            "supplier_id": sid,
            "name_zh": s.get("name_zh"),
            "name_en": s.get("name_en"),
            "city": s.get("city"),
            "category": s.get("category"),
            "trust_score": s.get("trust_score"),
            "review_avg": s.get("review_avg"),
            "review_count": s.get("review_count"),
            "gold_badge": bool(s.get("gold_badge")),
            "skill_endpoint": s.get("skill_mcp_endpoint"),
            "health_status": health_status,
            "routing_score": round(score, 2),
            "routing_reason": _explain_route(s, health_status, health_bonus),
        })

    scored.sort(key=lambda x: x["routing_score"], reverse=True)
    return scored[:limit]


def _explain_route(s: dict, health_status: str, health_bonus: int) -> str:
    parts = []
    if s.get("gold_badge"):
        parts.append("🏅 金牌供应商")
    if (s.get("trust_score") or 0) >= 80:
        parts.append(f"信任分{s['trust_score']:.0f}")
    if (s.get("review_avg") or 0) >= 4.5 and (s.get("review_count") or 0) >= 3:
        parts.append(f"评价{s['review_avg']:.1f}★")
    if health_status == "online":
        parts.append("MCP 实时在线")
    elif health_status == "degraded":
        parts.append("MCP 降级")
    elif health_status == "offline":
        parts.append("MCP 离线（回退缓存）")
    if not parts:
        parts.append("基础候选")
    return " · ".join(parts)


# ===== 告警系统 =====

class AlertStore:
    """
    进程内告警队列 + 持久化（落 SQLite alerts 表）。
    告警分级：info / warn / critical
    """
    def __init__(self, max_recent: int = 100):
        self._recent: deque[dict] = deque(maxlen=max_recent)
        self._lock = threading.Lock()

    def add(self, severity: str, category: str, message: str, source: str = "middle_agent", payload: Optional[dict] = None):
        alert = {
            "id": f"alert-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}",
            "severity": severity,
            "category": category,
            "message": message,
            "source": source,
            "payload": payload or {},
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            self._recent.appendleft(alert)
        self._persist(alert)
        _log().info(f"[AGENT-ALERT] {severity} | {category} | {message}")
        return alert

    def _persist(self, alert: dict):
        try:
            with _db()() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_alerts (
                        id TEXT PRIMARY KEY,
                        severity TEXT NOT NULL,
                        category TEXT NOT NULL,
                        message TEXT NOT NULL,
                        source TEXT DEFAULT '',
                        payload TEXT DEFAULT '{}',
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    INSERT INTO agent_alerts(id, severity, category, message, source, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    alert["id"], alert["severity"], alert["category"], alert["message"],
                    alert["source"], json.dumps(alert["payload"], ensure_ascii=False), alert["created_at"],
                ))
                conn.commit()
        except Exception as e:  # noqa: BLE001
            _log().warning(f"告警持久化失败: {e}")

    def list_recent(self, limit: int = 20, severity: Optional[str] = None) -> list[dict]:
        with self._lock:
            items = list(self._recent)
        if severity:
            items = [a for a in items if a["severity"] == severity]
        return items[:limit]


ALERTS = AlertStore()


# ===== 健康度缓存（路由查询用） =====

_health_cache: dict[str, dict] = {}
_health_cache_at: float = 0.0
_HEALTH_CACHE_TTL = 120  # 2 分钟


def _load_health_index() -> dict[str, dict]:
    global _health_cache, _health_cache_at
    now = time.time()
    if now - _health_cache_at < _HEALTH_CACHE_TTL and _health_cache:
        return _health_cache
    try:
        report = run_health_check()
        _health_cache = {r["supplier_id"]: r for r in report["results"]}
        _health_cache_at = now
    except Exception as e:  # noqa: BLE001
        _log().warning(f"健康度缓存刷新失败: {e}")
    return _health_cache


# ===== 维护日志 =====

class MaintenanceLog:
    """Agent 维护动作的内存 + 持久化日志。"""
    def __init__(self, max_recent: int = 200):
        self._recent: deque[dict] = deque(maxlen=max_recent)
        self._lock = threading.Lock()

    def record(self, action: str, target: str = "", result: str = "ok", payload: Optional[dict] = None):
        entry = {
            "id": f"mlog-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}",
            "action": action,
            "target": target,
            "result": result,
            "payload": payload or {},
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            self._recent.appendleft(entry)
        try:
            with _db()() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_maintenance_logs (
                        id TEXT PRIMARY KEY,
                        action TEXT NOT NULL,
                        target TEXT DEFAULT '',
                        result TEXT DEFAULT 'ok',
                        payload TEXT DEFAULT '{}',
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    INSERT INTO agent_maintenance_logs(id, action, target, result, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    entry["id"], entry["action"], entry["target"], entry["result"],
                    json.dumps(entry["payload"], ensure_ascii=False), entry["created_at"],
                ))
                conn.commit()
        except Exception as e:  # noqa: BLE001
            _log().warning(f"维护日志持久化失败: {e}")
        return entry

    def list_recent(self, limit: int = 30) -> list[dict]:
        with self._lock:
            return list(self._recent)[:limit]


MAINT_LOG = MaintenanceLog()


# ===== 自我优化建议 =====

def generate_optimization_report() -> dict:
    """
    基于历史指标生成自我优化建议：
    - 健康度趋势
    - 路由集中度
    - 高频问题
    - 信任分分布
    """
    with _db()() as conn:
        supplier_count = conn.execute("SELECT COUNT(*) as n FROM suppliers").fetchone()["n"]
        with_skill = conn.execute("SELECT COUNT(*) as n FROM suppliers WHERE agent_skill_installed = 1").fetchone()["n"]
        # 用 COALESCE 把 NULL 聚合值转成 0；并查"已评分"数量用于判定数据是否已初始化
        avg_trust_row = conn.execute(
            "SELECT AVG(trust_score) as v, COUNT(trust_score) as n FROM suppliers WHERE trust_score IS NOT NULL"
        ).fetchone()
        avg_trust = avg_trust_row["v"] or 0
        trust_scored = avg_trust_row["n"] or 0
        gold_count = conn.execute("SELECT COUNT(*) as n FROM suppliers WHERE gold_badge = 1").fetchone()["n"]
        rfq_total = conn.execute("SELECT COUNT(*) as n FROM rfqs").fetchone()["n"]
        rfq_pending = conn.execute("SELECT COUNT(*) as n FROM rfqs WHERE status = 'pending'").fetchone()["n"]
        review_total = conn.execute("SELECT COUNT(*) as n FROM reviews").fetchone()["n"]
        review_avg = conn.execute("SELECT AVG(rating) as v FROM reviews").fetchone()["v"] or 0

    health = run_health_check()
    online_pct = (
        health["summary"]["online"] / max(1, health["summary"]["online"] + health["summary"]["offline"] + health["summary"]["degraded"])
    ) * 100 if (health["summary"]["online"] + health["summary"]["offline"] + health["summary"]["degraded"]) > 0 else 0

    suggestions: list[str] = []
    if online_pct < 60:
        suggestions.append(f"⚠️ 厂家 MCP 在线率仅 {online_pct:.0f}%，建议在「需求广场」优先推已装 Skill 的厂家")
    if gold_count == 0 and review_total > 0:
        suggestions.append("💡 暂无金牌供应商，建议运营侧引导高质量供应商互评以达到金标门槛")
    if review_total < 5 and supplier_count > 5:
        suggestions.append("💡 互评数据偏少，建议在 RFQ 完结流程中强化提醒买卖双方留评")
    if rfq_pending > 10 and online_pct < 70:
        suggestions.append(f"⚠️ 待处理 RFQ 堆积（{rfq_pending} 笔）+ 厂家在线率不足，建议开启 Agent 自动外联补位")
    if trust_scored == 0 and supplier_count > 0:
        suggestions.append("💡 全网尚无信任分数据（trust_score 全为 NULL），请用 /trust_score 端点初始化或导入种子数据")
    elif 0 < avg_trust < 60:
        suggestions.append(f"💡 全网平均信任分仅 {avg_trust:.1f}，建议强化「邮箱/执照/电话」三方验证激励")
    if with_skill < supplier_count * 0.3:
        suggestions.append(f"💡 仅 {with_skill}/{supplier_count} 厂家装 Skill，建议加大 C 端 evaluate_sme 后的 create_sample_skill 引导")

    return {
        "agent": {"id": AGENT_ID, "version": AGENT_VERSION, "name": AGENT_NAME_ZH},
        "metrics": {
            "suppliers_total": supplier_count,
            "suppliers_with_skill": with_skill,
            "suppliers_online_pct": round(online_pct, 1),
            "suppliers_gold": gold_count,
            "avg_trust_score": round(avg_trust, 2),
            "avg_trust_known": trust_scored > 0,
            "trust_scored_count": trust_scored,
            "rfqs_total": rfq_total,
            "rfqs_pending": rfq_pending,
            "reviews_total": review_total,
            "reviews_avg": round(review_avg, 2),
        },
        "suggestions": suggestions,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ===== 启动时自动巡检 =====

def bootstrap_agent() -> None:
    """
    服务启动时跑一次基线巡检。
    关键：异步线程跑，不阻塞 uvicorn 启动（每个 supplier 8s HTTP timeout，
    同步跑会卡住 uvicorn bind 端口，curl 会拿到 ConnectionRefused）。
    """
    def _run_bootstrap():
        try:
            report = run_health_check()
            offline = [r for r in report["results"] if r["status"] == "offline"]
            degraded = [r for r in report["results"] if r["status"] == "degraded"]
            for r in offline:
                ALERTS.add(
                    severity="warn",
                    category="supplier_offline",
                    message=f"厂家 {r['name']} MCP 离线",
                    payload={"supplier_id": r["supplier_id"], "endpoint": r["endpoint"]},
                )
            for r in degraded:
                ALERTS.add(
                    severity="info",
                    category="supplier_degraded",
                    message=f"厂家 {r['name']} MCP 降级（HTTP 异常）",
                    payload={"supplier_id": r["supplier_id"], "endpoint": r["endpoint"], "http_status": r.get("http_status")},
                )
            MAINT_LOG.record(
                action="bootstrap_health_check",
                target="all",
                result="ok",
                payload={
                    "online": report["summary"]["online"],
                    "offline": report["summary"]["offline"],
                    "degraded": report["summary"]["degraded"],
                    "no_skill": report["summary"]["no_skill"],
                },
            )
            _log().info(f"[middle-agent] bootstrap 完成: {report['summary']}")
        except Exception as e:  # noqa: BLE001
            _log().warning(f"中间 Agent 启动巡检失败: {e}")

    t = threading.Thread(target=_run_bootstrap, name="middle-agent-bootstrap", daemon=True)
    t.start()
    _log().info("[middle-agent] bootstrap 已在后台线程启动（不阻塞 uvicorn）")


# ===== 对外 API 封装（供 server.py 路由调用） =====

def report_ts_alert(severity: str, audit_type: str, reasons: list, details: dict) -> dict:
    """供 server.py 调用：记录 Trust & Safety 审核告警到中间层告警系统

    severity: "info" / "warn" / "critical"
    audit_type: "buyer_inquiry" / "supplier_quote" / "supplier_registration"
    reasons: 审核原因列表
    details: 审核详情
    """
    try:
        alert = ALERTS.add(
            severity=severity,
            category=f"trust_safety_{audit_type}",
            message=f"T&S {audit_type} {severity}: {', '.join(reasons[:3])}",
            source="trust_safety",
            payload={"reasons": reasons, "details": details},
        )
        return alert
    except Exception as e:
        _log().warning(f"report_ts_alert failed: {e}")
        return {}


def middle_agent_status() -> dict:
    """Agent 自身状态 + 当前健康度概览。"""
    report = _load_health_index()
    online = sum(1 for r in report.values() if r.get("status") == "online")
    offline = sum(1 for r in report.values() if r.get("status") == "offline")
    degraded = sum(1 for r in report.values() if r.get("status") == "degraded")
    return {
        "agent": {
            "id": AGENT_ID,
            "name": AGENT_NAME_ZH,
            "version": AGENT_VERSION,
            "description": AGENT_DESCRIPTION,
            "started_at": _STARTED_AT,
            "uptime_seconds": int(time.time() - _STARTED_TS),
        },
        "health_summary": {
            "online": online,
            "offline": offline,
            "degraded": degraded,
            "total_tracked": len(report),
            "cache_ttl_seconds": _HEALTH_CACHE_TTL,
        },
        "endpoints": {
            "status": "/agent/status",
            "health": "/agent/health",
            "routing": "/agent/routing",
            "alerts": "/agent/alerts",
            "maintenance": "/agent/maintenance",
            "optimize": "/agent/optimize",
            "maintain": "/agent/maintain",
        },
    }


def middle_agent_health(force_refresh: bool = False) -> dict:
    """完整健康检查报告。force_refresh=True 时绕过缓存。"""
    if force_refresh:
        global _health_cache, _health_cache_at
        _health_cache = {}
        _health_cache_at = 0.0
        _load_health_index()
    report = run_health_check()
    report["agent_id"] = AGENT_ID
    MAINT_LOG.record("health_check_force" if force_refresh else "health_check", "all", "ok",
                     {"summary": report["summary"]})
    return report


def middle_agent_routing(category: str, quantity: int = 0, target_price_usd: float = 0.0,
                        need_live_data: bool = True, limit: int = 5) -> dict:
    """路由推荐。"""
    recs = routing_recommend(category, quantity, target_price_usd, need_live_data, limit)
    MAINT_LOG.record("routing_recommend", category, "ok", {
        "quantity": quantity, "target_price_usd": target_price_usd,
        "need_live_data": need_live_data, "result_count": len(recs),
    })
    return {
        "agent_id": AGENT_ID,
        "category": category,
        "quantity": quantity,
        "need_live_data": need_live_data,
        "recommendations": recs,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def middle_agent_alerts(limit: int = 20, severity: Optional[str] = None) -> dict:
    """告警列表。"""
    items = ALERTS.list_recent(limit=limit, severity=severity)
    return {
        "agent_id": AGENT_ID,
        "total": len(items),
        "alerts": items,
    }


def middle_agent_maintenance(limit: int = 30) -> dict:
    """维护日志。"""
    items = MAINT_LOG.list_recent(limit=limit)
    return {
        "agent_id": AGENT_ID,
        "total": len(items),
        "logs": items,
    }


def middle_agent_optimize() -> dict:
    """触发一次自我优化分析。"""
    report = generate_optimization_report()
    MAINT_LOG.record("optimize_report", "global", "ok", {
        "metrics": report["metrics"],
        "suggestion_count": len(report["suggestions"]),
    })
    if report["suggestions"]:
        ALERTS.add(
            severity="info",
            category="optimization",
            message=f"生成 {len(report['suggestions'])} 条自我优化建议",
            payload={"suggestions": report["suggestions"][:3]},
        )
    return report


def middle_agent_maintain(action: str, target: str = "", notes: str = "") -> dict:
    """手动触发一次维护任务。"""
    action = (action or "").strip()
    valid_actions = {
        "health_check", "optimize", "clear_alerts",
        "ping_supplier", "reroute_requirement",
    }
    if action not in valid_actions:
        raise ValueError(f"action 必须为: {', '.join(valid_actions)}")

    result = {"action": action, "target": target, "notes": notes}

    if action == "health_check":
        rep = run_health_check()
        result["health_summary"] = rep["summary"]
        MAINT_LOG.record("manual_health_check", target or "all", "ok", rep["summary"])
        ALERTS.add(
            severity="info",
            category="manual_health_check",
            message=f"手动巡检完成：在线 {rep['summary']['online']} / 离线 {rep['summary']['offline']}",
            payload=rep["summary"],
        )
    elif action == "optimize":
        result["optimize_report"] = generate_optimization_report()
        MAINT_LOG.record("manual_optimize", target or "global", "ok")
    elif action == "clear_alerts":
        # 仅清内存中告警，保留持久化记录
        ALERTS._recent.clear()
        result["cleared"] = True
        MAINT_LOG.record("clear_alerts", "memory", "ok")
    elif action == "ping_supplier":
        if not target:
            raise ValueError("ping_supplier 必须指定 target=supplier_id")
        with _db()() as conn:
            row = conn.execute(
                "SELECT id, name_zh, skill_mcp_endpoint FROM suppliers WHERE id = ?",
                (target,),
            ).fetchone()
        if not row:
            result["result"] = "not_found"
        else:
            supplier = dict(row)
            sess = requests.Session()
            r = _check_one_supplier_sync(sess, supplier)
            result["ping_result"] = r
            MAINT_LOG.record("ping_supplier", target, "ok" if r["status"] == "online" else "fail", r)
    elif action == "reroute_requirement":
        if not target:
            raise ValueError("reroute_requirement 必须指定 target=requirement_id")
        with _db()() as conn:
            r_row = conn.execute("SELECT * FROM requirements WHERE id = ?", (target,)).fetchone()
        if not r_row:
            result["result"] = "requirement_not_found"
        else:
            req = dict(r_row)
            recs = routing_recommend(req["category"], req.get("quantity", 0), req.get("target_price_usd", 0), True, 3)
            result["recommendations"] = recs
            MAINT_LOG.record("reroute_requirement", target, "ok", {"count": len(recs)})

    return {"agent_id": AGENT_ID, "result": result, "ts": datetime.now().isoformat(timespec="seconds")}


# ===== 启动时间戳 =====

_STARTED_AT = datetime.now().isoformat(timespec="seconds")
_STARTED_TS = time.time()
