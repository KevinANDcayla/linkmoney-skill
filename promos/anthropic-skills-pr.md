# LinkMoney - Anthropic Skills 官方收录 PR 指南

## Anthropic Skills 是什么
Anthropic 官方的 Claude Skills 目录。通过 GitHub PR 提交，收录后 Claude 用户可直接搜索安装。

## PR 提交地址
https://github.com/anthropics/skills（新建 PR 添加 linkmoney）

## 提交步骤

### Step 1: Fork anthropics/skills 仓库

### Step 2: 创建 skills/linkmoney.md

```markdown
---
name: linkmoney
version: 3.0.1
description: LinkMoney — AI-native B2B marketplace connecting overseas agents with verified Chinese factories. Real-time pricing, inventory, and RFQ via MCP.
author: LinkMoney AI
homepage: https://linkmoney.online
license: MIT
install_command: npx skills add KevinANDcayla/linkmoney-skill
repository: https://github.com/KevinANDcayla/linkmoney-skill
mcp_endpoint: https://linkmoney.online/mcp/manifest.json
tags:
  - b2b
  - china
  - sourcing
  - supply-chain
  - manufacturing
  - procurement
  - agent
  - MCP
---

# LinkMoney（连钱）Skill

> 让钱通过 Agent 流动 / *Link the Money, Link the World*

## Overview

LinkMoney is the first MCP Skill for agent-to-agent B2B trade — connecting overseas procurement agents with verified Chinese factories for live pricing, real-time inventory, and automated RFQ.

## Capabilities

### For Overseas Buyers（W-side, 13 tools）
- `find_china_supplier` — Search 51 verified Chinese suppliers
- `get_pricing` — Live factory pricing with quantity tiers
- `get_inventory` — Real-time stock from factory ERP
- `match_spec` — Spec matching by category + standard
- `download_cert` — ISO/CE/FDA certifications
- `multi_lang_inquiry` — Auto-generate RFQ in 8 languages
- `submit_rfq` — Submit RFQ with automatic email notification
- `get_supplier_contact` — Full supplier contact (Skill-installed only)
- `post_requirement` — Post public sourcing requirement
- `browse_requirements` — Browse open requirements
- `leave_review` — 5-dimension supplier review
- `trust_score` — Supplier/buyer trust rating
- `stats` — Global platform statistics

### For Chinese Factories（C-side, 6 tools）
- `evaluate_sme` — 5-dimension AI export readiness assessment
- `register_supplier` — Factory onboarding
- `get_my_rfqs` — Query received RFQs
- `send_quote` — Quote RFQ with email notification
- `bid_on_requirement` — Bid on open requirements
- `outreach_buyer` — Active outreach to buyers (trust score ≥60)

### Middle Agent Layer（7 tools, internal）
- Health checks, RFQ routing, alerts, maintenance logs, self-optimization

## Architecture

```
LinkMoney（黄页+路由）
    │
    ├── 51 Supplier profiles, certs, RFQ records
    └── Real-time data: 厂商 MCP Server (live) → fallback to cache
```

## Installation

```bash
npx skills add KevinANDcayla/linkmoney-skill
```

## Pricing
- First 3 months: FREE
- Afterwards: 3% success fee on closed deals
- No upfront cost, no subscription

## Example

**User**: "Find M8 304 stainless steel hex bolts, 50K pcs, FOB Ningbo"

**Agent calls**: `find_china_supplier` → returns 3-5 factories with MCP endpoints

**For live data factories**: Agent calls factory MCP directly for pricing + inventory

**Result**: 3-factory comparison with real-time prices, delivered in seconds

## Stats
- 51 verified suppliers
- 140 products across 7 categories
- 7 buyer countries
- Open source: MIT license
```

### Step 3: 创建 PR

PR Title: `feat: add linkmoney — AI-native B2B marketplace for Chinese factory sourcing`

PR Body:
```markdown
## LinkMoney — AI-native B2B Sourcing Skill

LinkMoney is the first MCP Skill that connects overseas procurement agents directly to verified Chinese factories with live pricing, real-time inventory, and automated RFQ.

### Why this belongs in Anthropic Skills

1. **First of its kind** — No other Skill enables agent-to-agent B2B commerce with real Chinese factory ERP integration
2. **Proven scale** — 51 suppliers, 140 products, 7 buyer countries
3. **Real-time data** — Unlike Alibaba (stale listings), LinkMoney pulls live pricing from factory MCP servers
4. **Clear value prop** — Overseas procurement agent installs LinkMoney → searches Chinese factories → submits RFQ → factory responds → deal closes
5. **MIT licensed, open source** — Fully transparent, community auditable

### Installation
```bash
npx skills add KevinANDcayla/linkmoney-skill
```

### Quick Demo
1. Claude calls `find_china_supplier` with category="fastener", quantity=50000
2. Returns 3 verified factories with live pricing endpoints
3. Agent compares pricing → submits RFQ → factory receives email notification
4. Factory quotes → buyer receives email → deal closes

### Stats
- 51 verified suppliers
- 140 products (fastener, electronics, packaging, hardware, injection molding, machinery, textile)
- 13 public MCP tools
- 3% success fee, first 3 months free

### Repository
https://github.com/KevinANDcayla/linkmoney-skill
```

## 审核周期
通常 3-7 天。Anthropic 团队会检查：
- skill 描述是否清晰
- install_command 是否可用
- manifest.json 是否符合 schema
- 是否有真实用途

## 如果被拒
常见原因：
- "Not a skill, it's a service" → 强调 install_command 可用
- "Too niche" → 强调 B2B 采购市场体量（$30T+）
- "Duplicate of existing" → 强调是唯一连接 AI Agent 到中国工厂的 Skill
