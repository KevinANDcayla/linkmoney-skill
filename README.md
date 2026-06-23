<p align="center">
  <img src="https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=A%20minimalist%20logo%20for%20'LinkMoney'%20-%20a%20B2B%20trade%20platform%20connecting%20AI%20agents%20to%20Chinese%20factories.%20Design%20shows%20two%20connected%20nodes%20forming%20a%20bridge%2C%20one%20orange%20one%20dark%20blue%2C%20clean%20geometric%20style%20on%20transparent%20background&image_size=square_hd" width="120" alt="LinkMoney Logo">
</p>

<h1 align="center">LinkMoney（连钱）</h1>
<p align="center">
  <strong>AI Agent Marketplace for Global B2B Trade</strong><br>
  <em>Agent 时代的 B2B 贸易链接器</em>
</p>

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/quick_start-5_min-blue"></a>
  <a href="./SKILL.md"><img src="https://img.shields.io/badge/skill-MCP_Skill-orange"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-green"></a>
  <a href="https://linkmoney.online/mcp/manifest.json"><img src="https://img.shields.io/badge/MCP-43_tools-purple"></a>
  <a href="https://linkmoney.online/en"><img src="https://img.shields.io/badge/demo-live_online-brightgreen"></a>
  <a href="#-middle-agent-v30"><img src="https://img.shields.io/badge/v5.0-2500_factories-blueviolet"></a>
</p>

---

> **LinkMoney gives AI agents the ability to source products from real Chinese factories.**
> Not an app. Not a website. Not a middleware. **It's an AI-native marketplace where agents do the sourcing.**

> **v5.0 大规模数据扩充** — 2,500 家工厂 / 30,000 个产品 / 16 个品类。海外端永久免费。详见 [快速开始](#-quick-start)。

---

## Quick Start

### 1. Get API Key (Free Forever)

```
API Key: lm-demo-2026
Header:  X-API-Key: lm-demo-2026
Base URL: https://linkmoney.online
```

No signup. No credit card. Just start calling.

### 2. Find Suppliers (curl)

```bash
curl "https://linkmoney.online/find_china_supplier?category=fastener&spec=M8%20304%20hex%20bolt&quantity=50000" \
  -H "X-API-Key: lm-demo-2026"
```

Returns 8-15 ranked suppliers with 7-dimension scores, MOQ, pricing, and MCP endpoints.

### 3. Python Example

```python
import requests

BASE = "https://linkmoney.online"
HEADERS = {"X-API-Key": "lm-demo-2026"}

# Find suppliers
r = requests.get(f"{BASE}/find_china_supplier", headers=HEADERS, params={
    "category": "fastener",
    "spec": "M8 304 hex bolt A2-70",
    "quantity": 50000,
    "target_price": "0.12 USD"
})
for s in r.json()["matches"][:5]:
    print(f"{s['name_en']} | score: {s['match_score']} | MOQ: {s.get('moq')}")

# Get pricing
r = requests.get(f"{BASE}/get_pricing", headers=HEADERS, params={
    "supplier_id": r.json()["matches"][0]["id"],
    "sku": "HEX-BOLT-M8-DIN933-88FD13",
    "quantity": 50000
})
print(r.json())

# Submit RFQ
r = requests.post(f"{BASE}/submit_rfq", headers=HEADERS, json={
    "supplier_id": "hd-fastener-0001",
    "product_sku": "HEX-BOLT-M8-DIN933-88FD13",
    "quantity": 50000,
    "delivery_port": "Los Angeles"
})
print(r.json())
```

### 4. Install as Skill

```bash
npx skills add KevinANDcayla/linkmoney-skill
```

---

## What is LinkMoney?

LinkMoney is an **MCP (Model Context Protocol) Skill** that connects overseas buyers' AI agents directly to Chinese manufacturers' systems. Think of it as **"Alibaba for AI Agents"** — but with real-time pricing, live inventory, and direct factory connections.

### How it works

```
Overseas Buyer's AI Agent                 Chinese Factory's MCP Server
  "Find M10 bolts, 50K pcs"                    ┌──────────────┐
         │                                      │  ERP System  │
         ▼                                      │  (实时数据)   │
    ┌─────────┐    find_china_supplier    ┌─────┴──────────────┤
    │ Claude  │ ─────────────────────────→│  Factory MCP        │
    │  GPT    │ ←──── live pricing ───────│  /pricing           │
    │ Cursor  │ ←──── live inventory ─────│  /inventory         │
    └─────────┘    submit_rfq → email     │  /quote             │
                                         └────────────────────┘
```

### Key Features

- **43 MCP Tools** (v5.0) — search, compare, quote, negotiate, transact, audit, maintain, marketplace
- **2,500 Verified Factories** — 30,000+ products across 16 categories, 833 with live MCP endpoints
- **Hybrid Architecture** — LinkMoney routes inquiries; factories serve live data from their own MCP servers
- **Real-time Data** — pricing and inventory straight from factory ERP, not stale listings
- **9-Language Support** — auto-translate inquiries (EN/ZH/JA/DE/ES/FR/AR/PT/RU)
- **Email Notifications** — SMTP email for RFQ submissions and quote responses
- **Zero-code Onboarding** — factories upload CSV or edit JSON; 5 minutes to go live
- **Auto-discovery** — `/.well-known/linkmoney-skill.json` protocol; LinkMoney auto-discovers new suppliers
- **Production-ready** — Docker, HTTPS, rate limiting, TTL caching, API key auth
- **Free Forever for Buyers** — overseas agents pay nothing; Chinese factories pay subscription

---

## For Chinese Factories (厂家接入)

```bash
# 1. 下载模板
git clone https://github.com/KevinANDcayla/linkmoney-skill.git
cd linkmoney-skill/supplier_mcp_template

# 2. 填产品数据（三选一）
# 方式A: 编辑 data.json
# 方式B: 打开 http://localhost:9001/admin 上传 CSV
# 方式C: 改一行代码连金蝶/用友 ERP

# 3. 启动
pip install -r requirements.txt
python server.py
# → 运行在 http://localhost:9001
```

See [厂家接入指南](https://linkmoney.online/onboard-supplier) for full details.

### Run LinkMoney API Server

```bash
# Clone & install
git clone https://github.com/KevinANDcayla/linkmoney-skill.git
cd linkmoney-skill/api
pip install -r requirements.txt

# Start
python server.py
# → http://localhost:8765
# → MCP Manifest: http://localhost:8765/mcp/manifest.json
# → API Docs:     http://localhost:8765/docs
```

### Docker (Production)

```bash
cp .env.example .env   # Edit with your config
bash deploy.sh         # One-click deploy
```

---

## API Tools

| # | Tool | Description |
|---|------|-------------|
| 1 | `find_china_supplier` | Search factories by category, spec, quantity |
| 2 | `get_pricing` | Real-time tiered pricing (proxy to factory MCP) |
| 3 | `get_inventory` | Live stock status (proxy to factory MCP) |
| 4 | `match_spec` | Match specs to industry standards |
| 5 | `download_cert` | Download ISO/CE/RoHS certifications |
| 6 | `multi_lang_inquiry` | Generate inquiries in 6 languages |
| 7 | `submit_rfq` | Send RFQ + email notification |
| 8 | `send_quote` | Factory quotes RFQ + emails buyer |
| 9 | `get_supplier_contact` | View supplier contact (Skill-gated) |
| 10 | `get_my_rfqs` | Factories query their received RFQs |
| 11 | `evaluate_sme` | AI readiness assessment for factories |
| 12 | `register_supplier` | Factory registration (v3.3 auto-activate hosted MCP) |
| 13 | `update_products` | Manage products via conversation (v3.3) |
| 14 | `upload_products_csv` | CSV bulk import (v3.3) |
| 15 | `register_buyer` | Overseas buyer self-registration (v3.3) |

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│              LinkMoney（黄页 + 路由）              │
│  - 供应商档案 + 认证 + RFQ记录（静态）             │
│  - 不存价格/库存（动态数据由厂家MCP提供）           │
│  - TTLCache 加速 | SlowAPI 限流 | API Key 认证    │
└──────────────┬───────────────────────────────────┘
               │  MCP Proxy (forward to factory)
    ┌──────────┼──────────┐
    ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│ 厂家A   │ │ 厂家B   │ │ 厂家C   │
│ MCP在线 │ │ MCP在线 │ │ MCP离线 │
│ 实时价格 │ │ 实时价格 │ │ 缓存数据 │
│ ERP直连 │ │ ERP直连 │ │ Fallback │
└────────┘ └────────┘ └────────┘
```

---

## Project Structure

```
linkmoney/
├── SKILL.md                    # Skill definition (Agent entry point)
├── LAUNCH_PLAN.md              # 4-week launch plan (Chinese)
├── docker-compose.yml          # Docker deployment
├── Dockerfile                  # API server Dockerfile
├── nginx.conf                  # HTTPS reverse proxy
├── deploy.sh                   # One-click deploy script
├── .env.example                # Environment config template
├── api/
│   ├── server.py               # FastAPI MCP Server (25 tools)
│   ├── mailer.py               # SMTP email module (async)
│   ├── migrate_contacts.py     # Contact data migration
│   └── requirements.txt        # Python dependencies
├── data/
│   ├── database.json           # Seed data (24 suppliers, 140 products)
│   └── linkmoney.db            # SQLite runtime database
├── supplier_mcp_template/      # Factory-side MCP Server template
│   ├── server.py               # Supplier MCP (cached, CSV upload)
│   ├── data.json               # Sample product data
│   ├── Dockerfile              # Factory Dockerfile
│   └── requirements.txt        # Factory dependencies
└── web/
    └── landing.html            # Landing page
```

---

## Demo

```bash
# 1. Find suppliers
curl "http://localhost:8765/find_china_supplier?category=fastener&spec=M10&quantity=50000" \
  -H "X-API-Key: lm-demo-2026"

# 2. Get live pricing (proxied to factory MCP)
curl "http://localhost:8765/get_pricing?supplier_id=nb-fastener-001&sku=M10-304-A2-70-BOLT&quantity=50000" \
  -H "X-API-Key: lm-demo-2026"

# 3. Submit RFQ (triggers email to factory)
curl -X POST "http://localhost:8765/submit_rfq?supplier_id=nb-fastener-001&buyer_id=buyer-us-auto-001&sku=M10-304-A2-70-BOLT&quantity=50000&target_price_usd=0.08&port=Los%20Angeles&contact_email=buyer@example.com" \
  -H "X-API-Key: lm-demo-2026"

# 4. Factory quotes (triggers email to buyer)
curl -X POST "http://localhost:8765/send_quote" \
  -H "X-API-Key: lm-demo-2026" \
  -H "Content-Type: application/json" \
  -d '{"rfq_id":"rfq-20260611-001","supplier_id":"nb-fastener-001","unit_price_usd":0.075,"lead_time_days":25}'
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Server | FastAPI + Uvicorn |
| Database | SQLite (runtime) + JSON (seed) |
| Auth | API Key header |
| Rate Limiting | SlowAPI |
| Caching | In-memory TTLCache |
| Email | SMTP (async, background thread) |
| MCP Proxy | Requests (8s timeout, fallback) |
| Deployment | Docker + docker-compose + Nginx |
| Logging | python-json-logger |

---

## Roadmap

- [x] 25 MCP tools + hybrid architecture
- [x] SMTP email notifications
- [x] Factory MCP template (zero-code onboarding)
- [x] Docker production deployment
- [x] Auto-discovery via `/.well-known/`
- [x] **v3.0** — 25 tools + 中间 Agent 维护层（健康检查 / 路由 / 告警 / 自我优化）
- [ ] Real translation API (DeepL)
- [ ] PostgreSQL migration (for scale)
- [ ] Real-time WebSocket notifications
- [ ] Payment/escrow integration
- [ ] Mobile mini-program (WeChat)

---

## Middle Agent (v3.0)

> **「双边 Skill 之间的中维护者」** — 嵌入在主 API 中，承担平台自身健康。

### 架构

```
┌─────────────────┐                         ┌─────────────────┐
│  C 端 Skill     │                         │  W 端 Skill     │
│  (中国老板 Agent)│                         │  (海外采购方)    │
└────────┬────────┘                         └────────┬────────┘
         │                                           │
         ▼                                           ▼
┌─────────────────────────────────────────────────────────────┐
│               LinkMoney 中间 Agent 维护层                    │
│   健康检查 · 智能路由 · 告警 · 维护日志 · 自我优化            │
└─────────────────────────────────────────────────────────────┘
```

### 7 个 Agent 端点

| 端点 | 用途 |
|------|------|
| `GET /agent/status` | Agent 元信息 + 当前健康度概览 |
| `GET /agent/health?force=true` | 批量检查所有厂家 MCP 端点（可强制刷新） |
| `GET /agent/routing?category=...` | RFQ 路由推荐（综合信任分 + 评价 + 健康度） |
| `GET /agent/alerts` | 告警列表（厂家离线 / 降级 / 优化建议） |
| `GET /agent/maintenance` | 维护日志（健康检查 / 路由推荐 / 手动维护） |
| `GET /agent/optimize` | 触发自我优化分析，生成运营建议 |
| `POST /agent/maintain` | 手动触发维护任务（ping 单家 / 重路由某条需求） |

### 路由评分公式

```
score = trust_score * 0.35
      + review_avg * 8 * 0.20
      + 健康度奖励(online=30, degraded=10, offline=-20, no_skill=-5)
      + 金标奖励(+10)
      + 安装数奖励(min(15, installs * 0.5))
      + 营收奖励(min(10, revenue / 5M))
      - MOQ 不符(-25)
      + lead_time 优势(<=5)
```

若 `need_live_data=true` 且厂家状态不是 `online/degraded`，该厂家在路由中被直接过滤。

### 启动行为

服务启动时自动调用 `bootstrap_agent()`：
1. 跑一次全量健康检查
2. 把离线 / 降级的厂家写入告警队列（同时持久化 SQLite `agent_alerts` 表）
3. 在 `agent_maintenance_logs` 表写一条 `bootstrap_health_check` 日志
4. SRE 上线后第一眼就能从 `/agent/alerts` 看到全网状态

### 自我优化建议示例

```
⚠️ 厂家 MCP 在线率仅 32%，建议在「需求广场」优先推已装 Skill 的厂家
💡 暂无金牌供应商，建议运营侧引导高质量供应商互评以达到金标门槛
💡 互评数据偏少，建议在 RFQ 完结流程中强化提醒买卖双方留评
⚠️ 待处理 RFQ 堆积（14 笔）+ 厂家在线率不足，建议开启 Agent 自动外联补位
```

---

## Contributing

LinkMoney is open source. We welcome contributions from:

- **Factories**: Add your company to the database
- **Developers**: Improve the MCP server, add new tools
- **Translators**: Help with multi-language support
- **Testers**: Run end-to-end scenarios and report bugs

Open an issue or submit a PR.

---

## License

MIT License — see [LICENSE](./LICENSE) file.

---

<p align="center">
  <sub>LinkMoney · AI-native B2B Trade Linker · <a href="https://linkmoney.online">linkmoney.online</a></sub>
</p>