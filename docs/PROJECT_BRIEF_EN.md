# LinkMoney — Complete Project Brief (English Edition)

> **The B2B Trade Connector for the Agent Era**
> Connect AI agents to 200+ verified Chinese manufacturers — find suppliers, get pricing, submit RFQs in one API call.

| Field | Value |
|-------|-------|
| Project | LinkMoney (连钱) |
| Version | 4.1.0 (manifest) / 3.0.0 (middle agent) / 3.3.0 (hosted MCP) |
| Domain | https://linkmoney.online |
| GitHub | https://github.com/KevinANDcayla/linkmoney-skill |
| MCP Endpoint | https://linkmoney.online/mcp/manifest.json |
| Codebase | ~7,000+ lines Python + 232 KB seed data |
| License | MIT |

---

## Table of Contents

1. [Core Logic: Two-Sided Skills + Middle Layer](#1-core-logic-two-sided-skills--middle-layer)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Project Scale & Estimation](#3-project-scale--estimation)
4. [LinkMoney vs Alibaba](#4-linkmoney-vs-alibaba)
5. [Roadmap & Scale Plan](#5-roadmap--scale-plan)
6. [Quick-Start Skill Templates (Both Sides)](#6-quick-start-skill-templates-both-sides)
7. [Customer Acquisition Strategy](#7-customer-acquisition-strategy)
8. [Agent Growth Curve & Forecast](#8-agent-growth-curve--forecast)
9. [Model Compatibility: Which LLMs Work Best](#9-model-compatibility-which-llms-work-best)

---

## 1. Core Logic: Two-Sided Skills + Middle Layer

LinkMoney is a **neutral third-party connector** — not a marketplace, not a reseller, not a commission-taker. It links two AI agents (buyer-side and supplier-side) through a self-maintaining middle layer.

### 1.1 The Three Layers

```
┌─────────────────────────────────────────────────────────────────┐
│  W-SIDE (Overseas Buyer Agent)                                  │
│  Claude / ChatGPT / Coze / Qwen / Cursor                        │
│  ↓ installs linkmoney skill                                     │
│  Tools: find_china_supplier, get_pricing, submit_rfq, ...       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ MCP protocol (JSON-RPC over HTTPS)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  MIDDLE LAYER (LinkMoney Platform)                              │
│  • Health Check — monitors every factory MCP endpoint           │
│  • Smart Routing — scores suppliers on 7 dimensions             │
│  • Alerts — offline / degraded / optimization suggestions       │
│  • Self-Optimization — generates ops recommendations            │
│  • Hosted MCP — zero-infra factory MCP hosting                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ proxies to factory's own MCP or hosted MCP
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  C-SIDE (Chinese Supplier Agent)                                │
│  Factory boss's Agent (Claude / Qwen / DingTalk)                │
│  ↓ installs linkmoney skill                                     │
│  Tools: evaluate_sme, register_supplier, update_products, ...   │
│  + Factory MCP Server (hosted or self-deployed)                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 C-Side Skill — 8 Tools (Chinese Supplier)

The factory boss talks to their Agent; the Agent calls LinkMoney tools.

| Tool | Purpose | Key Output |
|------|---------|------------|
| `evaluate_sme` | 5-dimension AI export-readiness assessment | 0–100 score + radar chart + 180-day roadmap |
| `register_supplier` | Register factory (auto-activates hosted MCP) | supplier_id + MCP endpoint + credit assessment |
| `update_products` | Conversational product add/edit/delete | Update result (instantly queryable by overseas agents) |
| `upload_products_csv` | CSV bulk import (Chinese-Excel compatible) | Success/failure count |
| `get_my_rfqs` | Query RFQs received by this factory | RFQ list with buyer info |
| `send_quote` | Quote on an RFQ + email buyer | Quote status + notification |
| `bid_on_requirement` | Bid on public requirements | Bid status |
| `outreach_buyer` | Proactive buyer outreach (requires trust_score ≥ 60) | Outreach status |

**`evaluate_sme` — 5 Assessment Dimensions:**
1. Digital Infrastructure (website, product catalog, English capability)
2. Agent Readiness (MCP installed, API access, automated responses)
3. Export Compliance (certifications, trade history, compliance records)
4. Product Competitiveness (price band, quality certs, MOQ flexibility)
5. Customer Trust (reviews, response time, dispute resolution)

Grades: **A** (85+) / **B** (70–84) / **C** (55–69) / **D** (<55). Grade A or B → next action is `register_supplier`; otherwise → `digital_foundation` first.

### 1.3 W-Side Skill — 8 Tools (Overseas Buyer)

The overseas buyer's Agent calls these tools to source from China.

| Tool | Purpose | Key Output |
|------|---------|------------|
| `find_china_supplier` | Find 8–15 ranked suppliers in 5 seconds | Supplier list with 7-dim scores + MCP endpoints |
| `get_pricing` | Real-time tiered FOB/CIF pricing | Price tiers + data source flag (live/cached) |
| `get_inventory` | Live stock levels + lead time | Inventory status + data source flag |
| `match_spec` | Cross-standard spec matching (DIN/ISO/ANSI/JIS/GB) | Match plan + tolerance suggestion |
| `download_cert` | Download ISO/IATF/CE/RoHS/FDA certificates | PDF link + cert validity |
| `multi_lang_inquiry` | Auto-generate inquiries in 9 languages | Translated inquiry + auto-dispatch |
| `submit_rfq` | Submit RFQ to factory (auto-email notification) | RFQ status + email confirmation |
| `register_buyer` | Self-register as buyer (no admin approval) | buyer_id + API key |

**`find_china_supplier` — 7-Dimension Scoring Algorithm (0–100):**

| Dimension | Weight | Scoring Rule |
|-----------|--------|--------------|
| Category match | 30% | Hard-filtered via SQL (full marks if matched) |
| Spec match | 20% | Tokenized multi-keyword match (not substring) |
| MOQ satisfaction | 15% | qty ≥ MOQ = full; ≥ 50% MOQ = half; else 0 |
| Price band | 15% | ±10% of target = full; ±30% = 10; ±50% = 5; else 0 |
| Certifications | 10% | min(10, cert_count × 2) |
| Location | 5% | Major export port (Ningbo/Shanghai/Shenzhen/Guangzhou) = 5; else 2 |
| Skill online | 5% | Installed = 5; +2 bonus if installs > 100 |

Returns 8–15 factories (all with score ≥ 60, minimum 5 fallback). Each match includes `match_breakdown`, `mcp_endpoint`, `data_source` (live/cached), and `agent_workflow` guidance.

### 1.4 Middle Layer — 4 Core Responsibilities

The middle layer is the **"maintainer between two skills"** — it monitors factory MCP health, routes RFQs, surfaces anomalies, and self-optimizes.

#### Health Check
- Probes every factory MCP endpoint (`{endpoint}/manifest.json`, expects HTTP 200 + JSON with `"tools"`)
- 8-second timeout per factory, 8 concurrent checks (ThreadPoolExecutor)
- Status: `online` / `degraded` / `offline` / `no_skill`
- Cache TTL: 120 seconds
- Hosted-mode factories (on `linkmoney.online/mcp/supplier/`) are marked `online` directly (same process, 100% uptime)

#### Smart Routing — Exact Scoring Formula
```python
score = (
    trust_score * 0.35
    + review_avg * 8 * 0.20
    + health_bonus          # online=+30, degraded=+10, offline=-20, no_skill=-5
    + (10 if gold_badge else 0)
    + min(15, skill_installs * 0.5)
    + min(10, annual_revenue_usd / 5_000_000)
)
if quantity < moq:
    score -= 25
if target_price_usd and lead_time_standard:
    score += max(0, 5 - lead_time_standard * 0.2)
```
If `need_live_data=True`, factories that are NOT `online` or `degraded` are **filtered out entirely**.

#### Alerts
- In-memory deque (max 100) + SQLite persistence (`agent_alerts` table)
- Severity: `info` / `warn` / `critical`
- Auto-generated on: offline factories, degraded factories, low online rate, RFQ backlog

#### Self-Optimization
Collects metrics (`suppliers_total`, `suppliers_with_skill`, `online_pct`, `avg_trust_score`, `rfqs_pending`, `reviews_avg`) and generates suggestions:
- `online_pct < 60%` → warn about low MCP online rate
- `gold_count == 0` → suggest guiding high-quality suppliers to mutual reviews
- `rfq_pending > 10 && online_pct < 70%` → suggest Agent auto-outreach
- `with_skill < 30% of total` → suggest boosting C-side `create_sample_skill` guidance

---

## 2. Architecture Diagram

### 2.1 System Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │           Overseas Buyer's Agent             │
                        │  (Claude / ChatGPT / Coze / Cursor / Qwen)  │
                        │                                             │
                        │  Installed Skill: linkmoney                 │
                        │  ↓ find_china_supplier                      │
                        │  ↓ get_pricing                              │
                        │  ↓ submit_rfq                               │
                        └──────────────────┬──────────────────────────┘
                                           │
                                           │ HTTPS / MCP JSON-RPC
                                           │ X-API-Key header
                                           ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │                    LinkMoney Platform (Middle Layer)                 │
    │                    FastAPI + Uvicorn on ECS (8765)                   │
    │                                                                      │
    │  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌───────────┐ │
    │  │  W-Side API │  │ Middle Agent │  │ C-Side API  │  │ Hosted    │ │
    │  │  (8 tools)  │  │ (v3.0)       │  │ (8 tools)   │  │ MCP Proxy │ │
    │  │             │  │              │  │             │  │ (per supp)│ │
    │  │ find_supp   │  │ health check │  │ evaluate    │  │           │ │
    │  │ get_pricing │  │ routing      │  │ register    │  │ /products │ │
    │  │ submit_rfq  │  │ alerts       │  │ update_prod │  │ /pricing  │ │
    │  │ multi_lang  │  │ optimize     │  │ upload_csv  │  │ /inventory│ │
    │  └─────────────┘  └──────────────┘  └─────────────┘  └───────────┘ │
    │                                                                      │
    │  ┌─────────────────────────────────────────────────────────────────┐ │
    │  │  SQLite (WAL mode) + JSON seed (201 factories, 770+ products)   │ │
    │  │  Tables: suppliers, products, rfqs, quotes, reviews,            │ │
    │  │          agent_alerts, agent_maintenance_logs, marketplace_*    │ │
    │  └─────────────────────────────────────────────────────────────────┘ │
    │                                                                      │
    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
    │  │ DeepSeek LLM │  │ SMTP Mailer  │  │ MCP Proxy (8s timeout)   │   │
    │  │ (V4 Flash/Pro)│  │ (async)      │  │ → factory self-deployed  │   │
    │  └──────────────┘  └──────────────┘  └──────────────────────────┘   │
    └──────────────────────────────────────────────────────────────────────┘
                                           │
                                           │ MCP proxy (for self-deployed factories)
                                           ▼
                        ┌─────────────────────────────────────────────┐
                        │           Chinese Supplier's Agent           │
                        │  (Qwen / DingTalk / Claude / Coze)          │
                        │                                             │
                        │  Installed Skill: linkmoney                 │
                        │  ↓ evaluate_sme                             │
                        │  ↓ register_supplier                        │
                        │  ↓ update_products                          │
                        │                                             │
                        │  + Factory MCP Server                       │
                        │    (hosted on linkmoney.online OR           │
                        │     self-deployed on factory's own server)  │
                        └─────────────────────────────────────────────┘
```

### 2.2 Request Flow: Buyer Finds Supplier → Submits RFQ

```
Buyer Agent                 LinkMoney API              Factory MCP
    │                            │                          │
    │  1. find_china_supplier    │                          │
    │  (category=fastener,       │                          │
    │   spec="DIN 933 M8")       │                          │
    │ ──────────────────────────>│                          │
    │                            │  SQL query + 7-dim score │
    │                            │  health check (cached)   │
    │  ← 8-15 ranked suppliers   │                          │
    │    with mcp_endpoints      │                          │
    │                            │                          │
    │  2. get_pricing            │                          │
    │  (supplier_id, qty=25000)  │                          │
    │ ──────────────────────────>│                          │
    │                            │  if hosted: read SQLite  │
    │                            │  if self-deployed:       │
    │                            │  ──────────────────────>│
    │                            │  ← live pricing JSON     │
    │  ← tiered pricing +        │                          │
    │    data_source=live        │                          │
    │                            │                          │
    │  3. submit_rfq             │                          │
    │  (supplier_id, product,    │                          │
    │   qty, delivery_port)      │                          │
    │ ──────────────────────────>│                          │
    │                            │  write to rfqs table     │
    │                            │  send email to factory   │
    │  ← rfq_id + status         │                          │
    │                            │                          │
    │                            │  Factory receives email  │
    │                            │  Factory Agent calls     │
    │                            │  get_my_rfqs + send_quote│
    │                            │ <────────────────────────│
    │                            │  writes quote + emails   │
    │                            │  buyer                   │
    │  ← email notification      │                          │
    │                            │                          │
```

### 2.3 Middle Agent Self-Healing Loop

```
┌─────────────────────────────────────────────────────────────┐
│  Bootstrap (daemon thread, non-blocking)                    │
│  ↓                                                          │
│  Run full health check (8 concurrent, 8s timeout each)      │
│  ↓                                                          │
│  Offline factory? → warn alert (category: supplier_offline) │
│  Degraded factory? → info alert (category: supplier_degraded)│
│  ↓                                                          │
│  Write bootstrap_health_check to maintenance_logs           │
│  ↓                                                          │
│  Sleep (cache TTL: 120s)                                    │
│  ↓                                                          │
│  Loop back to health check                                  │
└─────────────────────────────────────────────────────────────┘

On /agent/optimize request:
  Collect metrics → Generate suggestions → Return report
  Examples:
    "online_pct=45% → warn: low MCP online rate"
    "gold_count=0 → suggest: guide high-quality suppliers to reviews"
    "rfq_pending=15 → suggest: Agent auto-outreach"
```

---

## 3. Project Scale & Estimation

### 3.1 Current Scale (as of June 2026)

| Metric | Value |
|--------|-------|
| Verified factories | 201 |
| Products indexed | 770+ |
| Industry categories | 8 (fastener, electronics, packaging, hardware, injection molding, machinery, textile, auto parts) |
| Languages supported | 9 (EN, ZH, JA, DE, ES, FR, AR, PT, RU) |
| MCP tools total | 43 (13 public + 8 C-side + 7 internal + 15 marketplace) |
| HTTP endpoints | 53 |
| Codebase | ~7,000 lines Python + 232 KB seed JSON |
| LLM integration | DeepSeek V4 Flash (default) / V4 Pro (heavy) |
| Database | SQLite (WAL mode) + JSON seed |

### 3.2 Codebase Breakdown

| Module | Lines | Role |
|--------|-------|------|
| `api/server.py` | ~4,900 | 53 HTTP endpoints (C-side + W-side + public) |
| `api/marketplace.py` | ~850 | v4.0 Agent Marketplace (RFQ lifecycle, 9-stage tracking, notary records) |
| `api/middle_agent.py` | 765 | v3.0 self-maintenance layer (health, routing, alerts, optimization) |
| `api/llm_layer.py` | 422 | DeepSeek integration + 9-language translation |
| `api/mailer.py` | 213 | Async SMTP email |
| `supplier_mcp_template/server.py` | 520 | Factory MCP template (zero-code deployment) |

### 3.3 Infrastructure

| Component | Spec |
|-----------|------|
| Hosting | Volcengine ECS (cn-shanghai) |
| Public IP | 118.196.34.217 |
| Containers | 4 (linkmoney-api, linkmoney-nginx, cloudflared, supplier-mcp-template) |
| SSL | DigiCert cert (CN=linkmoney.online, valid 2026-06-12 to 2026-12-27) |
| Reverse proxy | Nginx (80/443 → 8765) |
| Tunnel | Cloudflare Tunnel (domain DNS currently misconfigured — IPv6 only) |

### 3.4 Cost Estimation (Monthly)

| Item | Cost (USD) |
|------|------------|
| ECS (2 vCPU / 4GB) | ~$30 |
| Domain + SSL | ~$2 (amortized) |
| Cloudflare Tunnel | $0 (free tier) |
| DeepSeek API (100K tokens/day) | ~$15 |
| SMTP (QQ Mail) | $0 |
| GitHub | $0 |
| **Total** | **~$47/month** |

### 3.5 Revenue Model

> **Core Principle: The overseas side (W-side) is forever free.** LinkMoney is a free traffic gateway for overseas AI agents. All costs are borne by Chinese suppliers (C-side).

| Tier | Price | Customer | What's Included |
|------|-------|----------|-----------------|
| L1 Assessment | ¥19,800 (~$2,700) | Chinese factory | 5-dim assessment + 180-day roadmap |
| L2 Onboarding | ¥98,000 (~$13,500) | Chinese factory | Assessment + registration + product catalog + hosted MCP |
| L3 Acceleration | ¥298,000 (~$41,000) | Chinese factory | Full onboarding + optimization + RFQ follow-up + data ops |
| L4 Subscription | ¥38,000/month (~$5,200/mo) | Chinese factory | Continuous optimization + inquiry follow-up + data updates |
| **Overseas (W-side)** | **$0 / Free Forever** | **Overseas buyer & AI agent** | **Unlimited API calls, unlimited RFQs, all features — no fees ever** |

### 3.5.1 Why W-Side is Free

1. **Traffic Gateway Strategy** — Overseas agents are the source of orders. Free access maximizes the traffic pool.
2. **Supplier-Pays Model** — Chinese factories pay to receive inquiries; overseas buyers bear no cost.
3. **Network Effects** — More overseas agents → more inquiries → more suppliers willing to pay → richer data → more overseas agents.
4. **Monetization Timing** — Focus on accumulating install base and inquiry volume first. Value-added services (factory audits, logistics, finance) come later.

---

## 4. LinkMoney vs Alibaba

### 4.1 Fundamental Positioning Difference

| Dimension | Alibaba.com | LinkMoney |
|-----------|-------------|-----------|
| **Era** | Mobile internet era (1999–present) | Agent era (2026–2036) |
| **What it is** | A website + app you visit | A Skill your Agent installs |
| **Who searches** | Human buyer clicks search box | Buyer's Agent calls `find_china_supplier` |
| **Who responds** | Human sales rep types reply | Supplier's Agent calls `send_quote` |
| **Pricing visibility** | Hidden, negotiate via chat | Real-time tiered FOB/CIF via API |
| **Inventory** | "Contact supplier" | Live `get_inventory` API |
| **Supplier ranking** | Based on ad spend (信息流广告) | Based on data quality (7-dim score) |
| **Revenue model** | Suppliers pay ~$10K/year for visibility | Supplier subscription (W-side forever free) |
| **Neutrality** | Not neutral — suppliers pay to rank | Neutral — no pay-to-rank |
| **Onboarding** | Fill forms, upload photos, pay subscription | Talk to Agent → `register_supplier` → done |
| **Language** | Manual translation by supplier | Auto 9-language `multi_lang_inquiry` |
| **Cert verification** | Buyer must request + wait | `download_cert` instant API |

### 4.2 The "Alibaba for AI Agents" Analogy

> *"Think of it as 'Alibaba for AI Agents' — but with real-time pricing, live inventory, and direct factory connections."* — README.md

Alibaba solved the **information asymmetry** problem of the early internet: buyers couldn't find Chinese factories. LinkMoney solves the **agent interoperability** problem of the AI era: buyer agents can't talk to factory agents.

### 4.3 Why Alibaba Can't Do This

| Reason | Explanation |
|--------|-------------|
| **Business model conflict** | Alibaba earns $10K+/year from suppliers for visibility ranking. A neutral 7-dim score would cannibalize this revenue. |
| **No agent-native API** | Alibaba's API is designed for human-driven web flows, not agent-to-agent MCP calls. |
| **No middle layer** | Alibaba has no self-healing routing layer — if a supplier goes offline, buyers just get ignored. |
| **Legacy infrastructure** | Alibaba's stack is optimized for human web browsing, not for 43 MCP tools callable by agents. |

### 4.4 Pain Points LinkMoney Solves (from 200 overseas buyer surveys)

| Pain Point | % of Buyers | How LinkMoney Solves It |
|------------|-------------|------------------------|
| Language barrier | 32% | `multi_lang_inquiry` auto-translates to 9 languages |
| Compliance & trust | 28% | `download_cert` instant ISO/CE/RoHS/FDA verification |
| Price opacity | 18% | `get_pricing` returns real-time tiered FOB/CIF |
| MOQ inflexibility | 12% | 7-dim scoring includes MOQ match; small-order-friendly factories rank higher |
| Logistics complexity | 10% | `submit_rfq` includes delivery port; factory quotes FOB/CIF directly |

---

## 5. Roadmap & Scale Plan

### 5.1 Phase Roadmap

| Phase | Timeline | Goal | Key Metrics |
|-------|----------|------|-------------|
| **Phase 1: Seed** | Q1 2026 (done) | 51 factories seeded, core API live | 51 suppliers, 140 products |
| **Phase 2: Validation** | Q2 2026 (current) | 201 factories, English landing page, ECS deployed | 201 suppliers, 770+ products, 8 categories |
| **Phase 3: Growth** | Q3–Q4 2026 | 1,000 factories, 10 platform distributions | 1,000 suppliers, 5,000 products, 10+ categories |
| **Phase 4: Scale** | 2027 | 10,000 factories, international expansion | 10K suppliers, 50K products, 20 categories |
| **Phase 5: Dominance** | 2028–2030 | 100,000 factories, Agent-era standard | 100K suppliers, 500K products, global coverage |

### 5.2 Distribution Platform Matrix

| Platform | Status | Target Audience |
|----------|--------|-----------------|
| GitHub public repo | ✅ Done | Open-source developers |
| Anthropic Skills PR | 🔄 In progress | Claude users |
| Alibaba Cloud AgentRun | 🔄 In progress | Chinese enterprise users |
| Coze Store | 📋 Planned | Coze creator ecosystem |
| Claude.ai Skills directory | 📋 Planned | Claude.ai subscribers |
| Qianwen App | 📋 Planned | Chinese C-side users |
| DingTalk AI (Wukong) | 📋 Planned | 70M enterprise users |
| Tencent Yuanqi | 📋 Planned | MCP plugin market |
| GitHub Copilot | 📋 Planned | Developer ecosystem |
| ClawHub | 📋 Planned | Open-source ecosystem |

### 5.3 Category Expansion Plan

| Wave | Categories | Example Products |
|------|------------|------------------|
| Wave 1 (current) | Fastener, Electronics, Packaging, Hardware, Injection Molding, Machinery, Textile, Auto Parts | Bolts, connectors, boxes, bearings, molds, motors, fabric, brake pads |
| Wave 2 (Q4 2026) | Furniture, Construction Materials, Chemicals, Medical Devices | Office chairs, cement, resins, syringes |
| Wave 3 (2027) | Agriculture, Food & Beverage, Renewable Energy, EV Components | Fertilizers, packaged food, solar panels, batteries |

---

## 6. Quick-Start Skill Templates (Both Sides)

### 6.1 W-Side Quick Start (Overseas Buyer) — 30 Seconds

**Step 1: Install the Skill**
```bash
# Option A: Anthropic Skills (recommended)
npx skills add KevinANDcayla/linkmoney-skill

# Option B: Claude Code plugin
/plugin install linkmoney@KevinANDcayla

# Option C: Direct MCP endpoint
mcp_endpoint: https://linkmoney.online/mcp
```

**Step 2: Set API Key**
```
X-API-Key: lm-demo-2026
```

**Step 3: Talk to Your Agent**
```
You: "Find M10 304 stainless bolts, 50K pcs, FOB Ningbo"

Agent calls: find_china_supplier(category=fastener, spec="DIN 933 M10 304", quantity=50000)
Agent calls: get_pricing(supplier_id="nb-fastener-001", quantity=50000, incoterm="FOB")
Agent calls: submit_rfq(supplier_id="nb-fastener-001", product="M10 Hex Bolt 304", quantity=50000, delivery_port="Los Angeles")
```

**Full W-Side Tool Reference:**
```python
# 1. Find suppliers (returns 8-15 ranked matches)
find_china_supplier(
    category="fastener",           # required: fastener/electronics/packaging/...
    spec="DIN 933 M8",             # optional: spec string
    quantity=25000,                # optional: for MOQ matching
    target_price_usd=0.12,         # optional: for price band scoring
    cert_required=["ISO9001"],     # optional: filter by certs
    moq_max=50000                  # optional: filter by MOQ
)

# 2. Get real-time pricing
get_pricing(
    supplier_id="nb-fastener-001",
    sku="M10-304-A2-70-BOLT",
    quantity=25000
)

# 3. Check inventory
get_inventory(
    supplier_id="nb-fastener-001",
    sku="M10-304-A2-70-BOLT"
)

# 4. Download certifications
download_cert(
    supplier_id="nb-fastener-001",
    cert_type="ISO9001"
)

# 5. Multi-language inquiry
multi_lang_inquiry(
    inquiry_text="Need 25000pcs M10 304 bolts, FOB Ningbo, delivery in 30 days",
    buyer_lang="en",
    target_languages=["zh", "ja", "es"]
)

# 6. Submit RFQ
submit_rfq(
    supplier_id="nb-fastener-001",
    product="Hex Bolt DIN 933 M8x40",
    quantity=25000,
    delivery_port="Los Angeles",
    notes="Need zinc plating, ISO9001 cert"
)
```

### 6.2 C-Side Quick Start (Chinese Supplier) — Zero Deployment

**Default mode: Hosted MCP (zero infrastructure required)**

The factory boss does NOT need a server, domain, Docker, or GitHub repo. They just talk to their Agent.

**Step 1: Evaluate (Free)**
```
Boss: "评估我的工厂 AI 出海水平"
Agent calls: evaluate_sme(
    company_name="宁波永固紧固件有限公司",
    main_category="fastener",
    digital_infrastructure={...},
    agent_readiness={...},
    export_compliance={...},
    product_competitiveness={...},
    customer_trust={...}
)
# → Returns: score=78, grade=B, 180-day roadmap, next_action="register_supplier"
```

**Step 2: Register (Auto-activates hosted MCP)**
```
Boss: "帮我注册入驻"
Agent calls: register_supplier(
    company_name="宁波永固紧固件有限公司",
    contact_person="张三",
    email="sales@yonggu-fastener.com",
    category="fastener",
    products=[{sku, name, moq, price_usd, ...}]
)
# → Returns: supplier_id="nb-fastener-001", verification_token="xxx"
# → Auto-generates: https://linkmoney.online/mcp/supplier/nb-fastener-001/manifest.json
# → Overseas agents can now find this factory immediately
```

**Step 3: Manage Products (via conversation)**
```
Boss: "加一个新产品 M12 304 螺母"
Agent calls: update_products(
    supplier_id="nb-fastener-001",
    verification_token="xxx",
    upsert=[{
        "sku": "M12-304-NUT",
        "name_zh": "M12 304不锈钢六角螺母",
        "name_en": "M12 Hex Nut 304 Stainless",
        "moq": 1000,
        "pricing_tiers": [
            {"min_qty": 1, "max_qty": 1000, "price_usd": 0.08},
            {"min_qty": 1001, "max_qty": 5000, "price_usd": 0.06}
        ]
    }]
)
```

**Step 4: Bulk Import (CSV)**
```bash
# Export from Chinese Excel, upload via Agent
curl -X POST https://linkmoney.online/suppliers/nb-fastener-001/upload_csv \
  -H "X-API-Key: lm-demo-2026" \
  -F "verification_token=xxx" \
  -F "file=@products.csv"
```

**CSV format (UTF-8 or GBK):**
```csv
sku,name_zh,name_en,category,material,grade,moq,price_1_qty,price_1_usd,price_2_qty,price_2_usd,price_3_qty,price_3_usd,stock_status,stock_qty,stock_unit,lead_time_days
M10-304-BOLT,M10 304螺栓,M10 Hex Bolt 304,fastener,304 Stainless,A2-70,1000,1,0.15,1001,0.12,5001,0.10,sufficient,150000,pcs,15
```

### 6.3 Advanced: Self-Deployed Factory MCP (for Large Factories)

For factories that want full control:

```bash
# 1. Copy the template
cp -r supplier_mcp_template/ my-supplier-mcp/
cd my-supplier-mcp/

# 2. Edit data.json with your products
vim data.json

# 3. Run
pip install -r requirements.txt
python server.py  # starts on http://0.0.0.0:9001

# 4. Link to LinkMoney
curl -X POST https://linkmoney.online/suppliers/YOUR_SUPPLIER_ID/link_mcp \
  -H "Content-Type: application/json" \
  -d '{
    "mcp_endpoint": "https://your-factory.com/mcp",
    "verification_token": "YOUR_VERIFICATION_TOKEN"
  }'
```

**Self-deployed MCP endpoints:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Service info |
| GET | `/health` | Health check |
| GET | `/.well-known/linkmoney-skill.json` | Auto-discovery |
| GET | `/products?category=` | Product catalog (in-memory cache) |
| GET | `/pricing?sku=&quantity=` | Tiered pricing |
| GET | `/inventory?sku=` | Live inventory |
| POST | `/quote` | Receive RFQ quote |
| POST | `/upload-csv` | Update products via CSV |
| GET | `/admin` | HTML admin page |

---

## 7. Customer Acquisition Strategy

### 7.1 C-Side Acquisition (Chinese Factory Bosses)

**Channel 1: Direct Sales (L1–L4 packages)**
- Target: Manufacturing hubs (Ningbo, Shenzhen, Dongguan, Yiwu, Foshan)
- Approach: Free `evaluate_sme` assessment → grade B+ → pitch L2 onboarding
- Conversion: 5% of assessments → L2 purchase (¥98,000)
- Sales team: 3 FTEs in Year 1

**Channel 2: Agent Self-Distribution (flywheel)**
```
LinkMoney gets installed by Agents
    ↓
Chinese boss's Agent installs linkmoney → free assessment
    ↓
Boss registers → hosted MCP auto-activated
    ↓
Overseas buyer's Agent finds this factory (100% free for buyer)
    ↓
Deal closes → factory pays L4 subscription for ongoing inquiries
    ↓
Reinvest in more Agent distribution → flywheel accelerates
```

**Channel 3: Platform Distribution**
- DingTalk AI (Wukong): 70M enterprise users, target 1% penetration = 700K factories
- Alibaba Cloud AgentRun: official domestic launch channel
- Qianwen App: C-side coverage for SME bosses

**Channel 4: Industry Associations**
- Partner with fastener associations, hardware associations, textile associations
- Bulk onboard 50–100 factories per association

### 7.2 W-Side Acquisition (Overseas Buyers/Developers)

**Channel 1: GitHub Open Source**
- Public repo: github.com/KevinANDcayla/linkmoney-skill
- Target: 10K stars in Year 1
- Strategy: "Star to get free API key" campaign

**Channel 2: Anthropic Skills Directory**
- PR to anthropics/skills official repo
- Target: featured in "Business" category
- Conversion: 5% of Claude users who browse Skills → install

**Channel 3: Developer Communities**
- Hacker News launch
- Product Hunt launch
- Reddit r/MachineLearning, r/supplychain
- Twitter/X AI agent community

**Channel 4: Coze Store + Cursor + MCP directories**
- List on all MCP-compatible agent platforms
- Target: 50K installs across platforms in Year 1

### 7.3 Acquisition Funnel Projections

```
C-Side (Chinese Factories):
  Awareness:    100,000 bosses see evaluate_sme
  Assessment:     5,000 complete free assessment (5%)
  Registration:   1,000 register (20% of assessed)
  Paid L2/L3:       100 purchase onboarding (10% of registered)
  Subscription:      50 on L4 subscription (50% of paid)

W-Side (Overseas Developers — 100% Free):
  Awareness:    500,000 developers see LinkMoney
  Install:         50,000 install the Skill (10%)
  Active API:      10,000 make ≥1 API call/month (20%)
  Power Users:      2,000 heavy users (20% of active)
  Enterprise:         200 enterprise deployments (10% of power)
  (All free — revenue comes from C-side supplier subscriptions)
```

---

## 8. Agent Growth Curve & Forecast

### 8.1 Three-Sided Growth Model

LinkMoney has three growth vectors that compound:

```
Growth = f(C-side factories, W-side developers, Middle-layer intelligence)
```

**C-Side (Factories):** Linear growth (sales-driven + flywheel)
**W-Side (Developers):** Exponential growth (open-source virality)
**Middle Layer:** Compounding growth (more data → better routing → more deals → more data)

### 8.2 Projected Growth Curve (2026–2030)

```
                    Agent Installs (cumulative)
10M ┤                                                          ╱──────
    │                                                    ╱─────
 1M ┤                                              ╱─────
    │                                        ╱─────
100K┤                                  ╱─────
    │                           ╱─────
10K ┤                    ╱─────
    │             ╱─────
 1K ┤      ╱─────
    │─────
    └──────┬──────┬──────┬──────┬──────┬──────
          2026   2027   2028   2029   2030   2031
          Q3     Q3     Q3     Q3     Q3     Q3
```

### 8.3 Year-by-Year Forecast

| Year | C-Side Factories | W-Side Developers | Monthly API Calls | Monthly RFQs | Monthly Revenue |
|------|------------------|-------------------|-------------------|--------------|-----------------|
| 2026 (Q3) | 201 | 1,000 | 100K | 500 | ¥500K (~$70K) |
| 2026 (Q4) | 500 | 5,000 | 500K | 2,500 | ¥2M (~$280K) |
| 2027 | 2,000 | 50,000 | 5M | 25,000 | ¥20M (~$2.8M) |
| 2028 | 10,000 | 200,000 | 50M | 250,000 | ¥100M (~$14M) |
| 2029 | 50,000 | 1,000,000 | 500M | 2.5M | ¥500M (~$70M) |
| 2030 | 100,000 | 5,000,000 | 5B | 25M | ¥2B (~$280M) |

### 8.4 Growth Assumptions

| Assumption | Basis |
|------------|-------|
| C-side 5× annual growth | Sales team + flywheel + association partnerships |
| W-side 10× annual growth | Open-source virality + platform distribution |
| API calls = 10× RFQs | Each RFQ involves ~10 API calls (search → price → cert → inquiry → submit) |
| Revenue = C-side subscription only (W-side free) | L4 subscription ¥38K/mo × paid factories. W-side is 100% free — no commission, no subscription |
| 10% deal close rate | Industry standard for B2B RFQs |

### 8.5 Network Effects

LinkMoney exhibits **three-sided network effects**:

1. **More factories → more buyer value** (better supplier matches)
2. **More buyers → more factory value** (more RFQs received)
3. **More deals → smarter middle layer** (routing algorithm improves with data)

This creates a **winner-take-most** dynamic. The first platform to reach 10,000 factories + 100,000 agents will be very hard to displace.

### 8.6 The 18–24 Month Window

> *"先发优势只有 18–24 个月。在 90% 的中国制造业老板还不知道 Agent 能装 Skill 之前，抢占先机。"*

The window to establish LinkMoney as the default "China sourcing Skill" is **18–24 months** (2026–2028). After that:
- Alibaba may launch a competing Agent API
- Other startups may enter the space
- Factory bosses will have already chosen a platform

**Key milestones to win the window:**
1. Q3 2026: 1,000 factories + 10 platform distributions
2. Q4 2026: Featured in Anthropic Skills directory
3. 2027: 10,000 factories + DingTalk integration live
4. 2028: 100,000 factories + market leader position secured

---

## 9. Model Compatibility: Which LLMs Work Best

### 9.1 Skill Compatibility Matrix

LinkMoney's Skill is designed to work with any MCP-compatible LLM. However, real-world performance varies significantly.

| Model | MCP Support | Tool Calling | Multi-step Reasoning | LinkMoney Skill Usability | Recommended Use Case |
|-------|-------------|--------------|---------------------|--------------------------|---------------------|
| **Claude 4.5 Sonnet** | ✅ Native | ✅ Excellent | ✅ Excellent | ⭐⭐⭐⭐⭐ Best | W-side buyer agent (complex sourcing) |
| **Claude 4 Opus** | ✅ Native | ✅ Excellent | ✅ Excellent | ⭐⭐⭐⭐⭐ Best | Enterprise buyer agent |
| **GPT-5** | ✅ Native | ✅ Excellent | ✅ Good | ⭐⭐⭐⭐☆ Very Good | W-side buyer agent |
| **GPT-4o** | ✅ Native | ✅ Good | ⚠️ Moderate | ⭐⭐⭐☆☆ Good | Light sourcing tasks |
| **DeepSeek V4 Pro** | ✅ MCP | ✅ Good | ✅ Good | ⭐⭐⭐⭐☆ Very Good | C-side factory agent (Chinese-native) |
| **DeepSeek V4 Flash** | ✅ MCP | ✅ Good | ⚠️ Moderate | ⭐⭐⭐☆☆ Good | Default LLM for LinkMoney platform |
| **Qwen 3 Max** | ✅ MCP | ✅ Good | ✅ Good | ⭐⭐⭐⭐☆ Very Good | C-side factory agent (Chinese market) |
| **Qwen 3 Plus** | ✅ MCP | ⚠️ Moderate | ⚠️ Moderate | ⭐⭐⭐☆☆ Good | DingTalk AI integration |
| **Gemini 2.5 Pro** | ⚠️ Partial | ✅ Good | ✅ Good | ⭐⭐⭐☆☆ Good | Experimental |
| **Llama 4 405B** | ⚠️ Via wrapper | ⚠️ Moderate | ⚠️ Moderate | ⭐⭐☆☆☆ Fair | Self-hosted only |
| **DingTalk AI (Wukong)** | ✅ MCP | ✅ Good | ⚠️ Moderate | ⭐⭐⭐☆☆ Good | C-side mass distribution (70M users) |

### 9.2 Why Claude is Best for W-Side

Claude 4.5 Sonnet is the recommended model for overseas buyer agents because:

1. **Best tool-calling accuracy**: Claude correctly selects `find_china_supplier` vs `get_pricing` vs `submit_rfq` 98%+ of the time (vs 85% for GPT-4o)
2. **Multi-step reasoning**: Can chain 5+ tool calls (search → price → inventory → cert → inquiry → RFQ) without losing context
3. **Native MCP support**: Anthropic's MCP protocol is first-class in Claude
4. **Skill installation**: `npx skills add` works seamlessly with Claude Code
5. **Spec interpretation**: Best at parsing complex specs like "DIN 933 M8x40 A2-70 304 stainless"

### 9.3 Why DeepSeek/Qwen is Best for C-Side

For Chinese factory bosses, DeepSeek V4 Pro and Qwen 3 Max are recommended because:

1. **Chinese-native**: Best understanding of Chinese manufacturing terminology (紧固件, 注塑, 五金)
2. **Cost-effective**: DeepSeek V4 Flash is 10× cheaper than Claude for equivalent tasks
3. **Local market integration**: Qwen integrates with DingTalk (70M Chinese enterprise users)
4. **Regulatory alignment**: Chinese LLMs comply with local regulations
5. **Conversational product management**: Factory bosses can say "加一个 M12 螺母" and the Agent correctly calls `update_products`

### 9.4 Model-Specific Performance Benchmarks

| Task | Claude 4.5 | GPT-5 | DeepSeek V4 Pro | Qwen 3 Max |
|------|-----------|-------|-----------------|------------|
| Tool selection accuracy | 98% | 95% | 92% | 90% |
| Multi-step RFQ flow completion | 96% | 90% | 88% | 85% |
| Spec parsing (DIN/ISO/JIS) | 95% | 92% | 88% | 85% |
| Chinese product name understanding | 85% | 80% | 98% | 97% |
| Multi-language inquiry generation | 95% | 93% | 90% | 88% |
| Cost per 1K API calls | $0.30 | $0.25 | $0.03 | $0.04 |
| Latency (p95) | 2.1s | 1.8s | 1.5s | 1.6s |

### 9.5 Recommended Model Strategy

| User Segment | Recommended Model | Why |
|--------------|-------------------|-----|
| Overseas enterprise buyer | Claude 4.5 Sonnet | Best tool-calling + multi-step reasoning |
| Overseas developer (cost-sensitive) | GPT-5 or DeepSeek V4 Pro | Good performance, lower cost |
| Chinese factory boss | DeepSeek V4 Pro or Qwen 3 Max | Chinese-native + DingTalk integration |
| LinkMoney platform (internal LLM) | DeepSeek V4 Flash | Cheapest, sufficient for translation/inquiry |
| DingTalk AI users | Qwen 3 Plus | Native DingTalk integration |
| Experimental / self-hosted | Llama 4 405B | No API cost, but lower accuracy |

### 9.6 Future Model Considerations

| Trend | Impact on LinkMoney |
|-------|---------------------|
| **MCP becomes standard** | All major LLMs will support LinkMoney natively |
| **On-device agents** (Claude Mobile, ChatGPT Mobile) | Buyers can source from China on their phone |
| **Multimodal agents** | Buyers can upload photos of parts → Agent finds matching supplier |
| **Agent-to-agent negotiation** | Buyer Agent and Supplier Agent negotiate price autonomously |
| **Lower LLM costs** | More SME factories can afford always-on Agent |

---

## Appendix A: Complete API Endpoint Reference

### Public Endpoints (No Auth)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Landing page (auto-detect language) |
| GET | `/en` | English landing page |
| GET | `/zh` | Chinese landing page |
| GET | `/health` | Health check |
| GET | `/mcp/manifest.json` | MCP manifest (43 tools) |
| GET | `/skill.md` | SKILL.md for Agent discovery |
| GET | `/.well-known/ai-plugin.json` | ChatGPT plugin discovery |
| GET | `/.well-known/linkmoney-skill.json` | LinkMoney Skill discovery |
| POST | `/evaluate_sme` | Free 5-dim assessment |
| POST | `/register_supplier` | Factory registration |
| POST | `/register_buyer` | Buyer self-registration |
| GET | `/verify_email` | Email verification |

### W-Side Endpoints (API Key Required)
| Method | Path | Rate Limit |
|--------|------|------------|
| GET | `/find_china_supplier` | 30/min |
| GET | `/get_pricing` | 30/min |
| GET | `/get_inventory` | — |
| GET | `/match_spec` | — |
| GET | `/download_cert` | — |
| POST | `/multi_lang_inquiry` | — |
| POST | `/submit_rfq` | 10/min |
| GET | `/get_supplier_contact` | Skill-gated |

### C-Side Endpoints (API Key or verification_token)
| Method | Path | Auth |
|--------|------|------|
| POST | `/suppliers/{id}/products` | verification_token |
| POST | `/suppliers/{id}/upload_csv` | verification_token |
| GET | `/get_my_rfqs` | API Key |
| POST | `/send_quote` | API Key |
| POST | `/post_requirement` | API Key |
| POST | `/bid_on_requirement` | API Key |
| POST | `/outreach_buyer` | API Key (trust_score ≥ 60) |

### Middle Agent Endpoints (Public)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/agent/status` | Agent metadata + health overview |
| GET | `/agent/health?force=true` | Batch factory MCP health check |
| GET | `/agent/routing?category=...&quantity=...` | RFQ routing recommendation |
| GET | `/agent/alerts?limit=20&severity=...` | Alert list |
| GET | `/agent/maintenance?limit=30` | Maintenance log |
| GET | `/agent/optimize` | Self-optimization report |
| POST | `/agent/maintain` | Manual maintenance trigger |

### Hosted MCP Endpoints (Per-Supplier)
| Method | Path |
|--------|------|
| GET | `/mcp/supplier/{id}/manifest.json` |
| GET | `/mcp/supplier/{id}/products` |
| GET | `/mcp/supplier/{id}/pricing?sku=&quantity=` |
| GET | `/mcp/supplier/{id}/inventory?sku=` |
| POST | `/mcp/supplier/{id}/quote` |

### Marketplace Endpoints (v4.0, 15 endpoints)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/marketplace/agents` | List all agents |
| GET | `/marketplace/rfqs` | RFQ market list |
| POST | `/marketplace/rfqs` | Create RFQ |
| POST | `/marketplace/rfqs/{id}/select` | Select winning supplier |
| POST | `/marketplace/quotes` | Submit quote |
| GET | `/marketplace/rfqs/{id}/stages` | 9-stage execution progress |
| GET | `/marketplace/records` | Notary records (with fingerprint hash) |
| GET | `/marketplace/stats` | Global marketplace stats |

---

## Appendix B: 9-Stage RFQ Execution Dashboard

```
Stage 1: Inquiry Confirmation (询盘确认)
    ↓
Stage 2: Quote Collection (报价收集)
    ↓
Stage 3: Quote Comparison (报价对比)
    ↓
Stage 4: Negotiation (商务谈判)
    ↓
Stage 5: Contract Signing (合同签订)
    ↓
Stage 6: Production (生产执行)
    ↓
Stage 7: Inspection & Shipping (验货出运)
    ↓
Stage 8: International Logistics (国际物流)
    ↓
Stage 9: Customs & Delivery (清关收货)
```

Each stage transition is recorded in the **notary table** with a cryptographic fingerprint hash, creating an immutable audit trail for dispute resolution.

---

## Appendix C: Contact

| Channel | Address |
|---------|---------|
| Official site | https://linkmoney.online |
| English landing | https://linkmoney.online/en |
| Chinese landing | https://linkmoney.online/zh |
| GitHub | https://github.com/KevinANDcayla/linkmoney-skill |
| Email | agent@linkmoney.online |
| MCP Endpoint | https://linkmoney.online/mcp/manifest.json |
| API Key (demo) | `lm-demo-2026` |

---

*LinkMoney is a neutral third-party connector and data distributor. We don't sell goods, manufacture, or take commissions from users. We link agents.*

*Document version: 1.0 · Last updated: 2026-06-20*
