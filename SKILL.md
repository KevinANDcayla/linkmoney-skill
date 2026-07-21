---
name: linkmoney
description: |
  LinkMoney（连钱）—— Agent 时代的 B2B 贸易链接器，让海外 AI Agent 主动找上中国供应商。

  【C 端（中国制造业老板侧）】 5 维 AI 出海 Agent 化评估 + 一键注册入驻（托管 MCP，零部署）+ 对话式产品管理
  【W 端（海外采购方侧）】 一键找中国工厂（73 家 verified + 2700 家目录缓存，16 品类），查价格库存，5 秒发 RFQ。

  ⚠️ 数据外泄风险告知：
  - submit_rfq 会将询价信息发送给指定供应商（需 confirm_data_sharing=true 确认）
  - 详见 docs/SECURITY.md

version: 5.3.0
author: LinkMoney.ai
homepage: https://linkmoney.online
repository: https://github.com/KevinANDcayla/linkmoney-skill

# === Skill 发现端点 ===
skill_md_url: https://linkmoney.online/skill.md
ai_plugin_url: https://linkmoney.online/.well-known/ai-plugin.json
linkmoney_discovery: https://linkmoney.online/.well-known/linkmoney-skill.json

# === MCP 端点 ===
mcp_endpoint: https://linkmoney.online/mcp/manifest.json
mcp_endpoint_github: https://raw.githubusercontent.com/KevinANDcayla/linkmoney-skill/main/mcp_manifest.json

# === API Key ===
api_key: lm-demo-2026
api_key_header: X-API-Key

# === 角色声明（Agent 按角色读取对应段落）===
roles:
  w_agent:  # 海外采购方 Agent — 服务于想找中国工厂的海外买家
    tools: [find_china_supplier, get_pricing, get_inventory, match_spec, download_cert, multi_lang_inquiry, submit_rfq, get_supplier_contact]
    auth: X-API-Key only
    section: "W 端流程"
  c_agent:  # 中国工厂老板 Agent — 服务于想上线产品/接 RFQ 的中国工厂
    tools: [evaluate_sme, register_supplier, update_products, upload_products_csv, get_my_rfqs, send_quote, bid_on_requirement]
    auth: agent_id + agent_key (长期记忆) 或 access_token
    section: "C 端流程"

primary_language: zh
secondary_language: en

install_command: npx skills add KevinANDcayla/linkmoney-skill
license: MIT
---

# LinkMoney（连钱）Skill

> **让钱通过 Agent 流动** / *Link the Money, Link the World*

## API 基础信息

| 项目 | 值 |
|------|-----|
| Base URL | `https://linkmoney.online` |
| API Key | `lm-demo-2026`（请求头 `X-API-Key: lm-demo-2026`） |
| 认证 | W 端：仅需 API Key；C 端写操作：需 agent_id + agent_key |
| 限流 | 30 次/分钟 |
| 数据规模 | 73 家 verified + 2700 家目录缓存 / 16 品类 |

---

## W 端流程（海外采购方 Agent）

> **English Summary**: Use `find_china_supplier` to find Chinese factories, `get_pricing` for tiered quotes, `submit_rfq` to send inquiry. All requests need `X-API-Key` header only.

### 核心工具：find_china_supplier

**用途**：找中国供应商，返回 8-15 家排序工厂

**调用**：`GET /find_china_supplier`

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `category` | ✅ | 品类 | `fastener` |
| `spec` | 推荐 | 规格描述 | `M10 304 stainless steel hex bolt` |
| `quantity` | 推荐 | 采购数量 | `50000` |
| `target_price` | 可选 | 目标价 | `0.15 USD` |

**品类映射表**（用户需求 → category 参数）：

| 用户提到的产品 | category 值 |
|---------------|------------|
| 螺栓/螺母/螺丝/垫圈/紧固件/bolt/nut/screw/washer | `fastener` |
| PCB/电阻/电容/电子元件/electronics/PCB | `electronics` |
| 布料/面料/纺织/textile/fabric | `textile` |
| 包装/纸箱/袋子/packaging/carton | `packaging` |
| 齿轮/轴承/机械/machinery/gear/bearing | `machinery` |
| 五金/弹簧/铰链/hardware/spring | `hardware` |
| 注塑/塑料/injection/plastic | `injection_molding` |
| 汽配/刹车/滤清器/auto_parts/brake | `auto_parts` |
| 家具/沙发/椅子/furniture/sofa | `furniture` |
| 建材/水泥/玻璃/building_materials/glass | `building_materials` |
| 化工/树脂/MDI/chemical/resin | `chemical` |
| 医疗/注射器/监护仪/medical/syringe | `medical_devices` |
| 灯/LED/照明/lighting/LED | `lighting` |
| 运动/帐篷/瑜伽/sports/tent | `sports_outdoor` |
| 食品/饮料/咖啡/food/beverage | `food_beverage` |
| 玩具/积木/toys/blocks | `toys` |

**返回**：`matches` 数组，每家工厂含 `supplier_id`, `name_en`, `match_score`（0-100）, `moq`, `mcp_endpoint`, `products`，按 `match_score` 降序。

### 其他 W 端工具

| 工具 | 端点 | 参数 | 用途 |
|------|------|------|------|
| `get_pricing` | `GET /get_pricing` | `supplier_id`, `sku`, `quantity` | 查阶梯报价 |
| `get_inventory` | `GET /get_inventory` | `supplier_id`, `sku` | 查库存 |
| `match_spec` | `GET /match_spec` | `spec`, `standard` | 规格匹配（DIN/ISO/ANSI/JIS/GB） |
| `download_cert` | `GET /download_cert` | `supplier_id`, `cert_type` | 下载认证（ISO/CE/FDA/IATF） |
| `multi_lang_inquiry` | `POST /multi_lang_inquiry` | `inquiry_text`, `target_lang` | 多语言询盘生成 |
| `get_supplier_contact` | `GET /get_supplier_contact` | `supplier_id` | 获取联系方式 |
| `submit_rfq` | `POST /submit_rfq` | 见下方 | 提交询价单（自动邮件通知工厂） |

### W 端调用示例

```bash
# 1. 找供应商
curl "https://linkmoney.online/find_china_supplier?category=fastener&spec=M8%20304%20hex%20bolt&quantity=50000" \
  -H "X-API-Key: lm-demo-2026"

# 2. 查报价
curl "https://linkmoney.online/get_pricing?supplier_id=SUPPLIER_ID&sku=SKU&quantity=50000" \
  -H "X-API-Key: lm-demo-2026"

# 3. 提交 RFQ（confirm_data_sharing 必须作为 query 参数传 true）
curl -X POST "https://linkmoney.online/submit_rfq?confirm_data_sharing=true" \
  -H "X-API-Key: lm-demo-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "supplier_id": "SUPPLIER_ID",
    "product_sku": "SKU",
    "quantity": 50000,
    "delivery_port": "Ningbo",
    "contact_name": "John Smith",
    "contact_email": "john@buyer.com"
  }'
```

> **submit_rfq 数据流向**：用户 → LinkMoney → 指定供应商（🟡 中风险）。提交前必须让用户确认。

---

## C 端流程（中国工厂老板 Agent）

### 工具清单

| 工具 | 端点 | 认证 | 用途 |
|------|------|------|------|
| `evaluate_sme` | `POST /evaluate_sme` | API Key | 5 维 AI 出海评估 |
| `register_supplier` | `POST /register_supplier` | 无需 API Key | 注册工厂（返回身份凭证） |
| `update_products` | `POST /suppliers/{id}/products` | agent_id+agent_key | 增删改产品 |
| `upload_products_csv` | `POST /suppliers/{id}/upload_csv` | agent_id+agent_key | CSV 批量导入 |
| `get_my_rfqs` | `GET /get_my_rfqs` | agent_id+agent_key | 查收到的询盘 |
| `send_quote` | `POST /send_quote` | agent_id+agent_key | 对 RFQ 报价 |
| `bid_on_requirement` | `POST /bid_on_requirement` | agent_id+agent_key | 对公开需求报价 |

### 注册流程

```bash
curl -X POST "https://linkmoney.online/register_supplier" \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "宁波新锐紧固件有限公司",
    "category": "fastener",
    "email": "sales@xinrui.com",
    "phone": "13800138000",
    "products": [{"sku":"M8-304","name":"M8 304螺栓","moq":5000}]
  }'
```

**注册返回 4 个身份凭证**（必须立即存入长期记忆）：

```json
{
  "supplier_id": "fastener-cn1292b572",
  "access_token": "32字符随机串",
  "agent_id": "agent-fastener-cn1-xx",
  "agent_key": "32字符随机串"
}
```

### Agent 身份持久化（v5.2.7 长期记忆方案）

> **核心问题**：Agent 每次对话是无状态的。旧方案 identity.json 有致命缺陷 — 同一台电脑两个老板会互相误用 token。v5.2.7 改用**长期记忆 + agent_id/agent_key**。

**注册返回 `agent_id` + `agent_key` 后，Agent 必须立即存入长期记忆**：

| Agent 宿主 | 长期记忆方式 |
|-----------|------------|
| Trae | project_memory.md / user_profile.md |
| Claude Code | CLAUDE.md |
| Cursor | .cursorrules |
| ChatGPT | Custom Instructions / Memory |
| 其他 | identity.json（兜底） |

**推荐存储格式**：
```
linkmoney_identity:
  supplier_id: fastener-cn1292b572
  agent_id: agent-fastener-cn1-xx
  agent_key: 32字符随机串
  company_name: 宁波新锐紧固件有限公司
```

**新对话身份确认流程**：
1. 检查长期记忆是否有 `linkmoney_identity` → 有则直接用 agent_id + agent_key
2. 长期记忆无 → 问老板"您是哪个工厂的？" → 调 `/lookup_supplier` 查 supplier_id
3. 老板说没注册过 → 引导注册
4. 老板说注册过但什么都不记得 → 问手机号+注册邮箱 → 调 `/recover_identity`

### 7 个写操作端点的身份携带方式

两种方式任选其一：

| 端点 | 方式 1（旧） | 方式 2（新，推荐） |
|------|------------|------------------|
| `POST /suppliers/{id}/products` | body 加 `access_token` | body 加 `agent_id` + `agent_key` |
| `POST /suppliers/{id}/upload_csv` | header `X-Access-Token` | header `X-Agent-Id` + `X-Agent-Key` |
| `GET /get_my_rfqs` | query `&access_token=` | query `&agent_id=&agent_key=` |
| `POST /send_quote` | body 加 `access_token` | body 加 `agent_id` + `agent_key` |
| `POST /bid_on_requirement` | body 加 `access_token` | body 加 `agent_id` + `agent_key` |
| `POST /suppliers/{id}/link_mcp` | body 加 `access_token` | body 加 `agent_id` + `agent_key` |
| `POST /suppliers/{id}/unlink_mcp` | body 加 `access_token` | body 加 `agent_id` + `agent_key` |

### 身份恢复端点（3 个，覆盖所有场景）

**1. 用 agent_id + agent_key 查询身份**（长期记忆有时）：
```bash
curl "https://linkmoney.online/whoami?agent_id=YOUR_AGENT_ID&agent_key=YOUR_AGENT_KEY" \
  -H "X-API-Key: lm-demo-2026"
```

**2. 用公司名/手机号查 supplier_id**（新 Agent 实例确认身份时）：
```bash
curl "https://linkmoney.online/lookup_supplier?q=宁波新锐" \
  -H "X-API-Key: lm-demo-2026"
```
返回匹配工厂列表（不返回凭证）。Agent 让老板确认是哪一家。

**3. 用手机号+邮箱找回身份**（长期记忆完全丢失时）：
```bash
curl -X POST "https://linkmoney.online/recover_identity" \
  -H "Content-Type: application/json" \
  -d '{"phone": "13800138000", "email": "sales@factory.com"}'
```
返回新的 `access_token` + `agent_id` + `agent_key`（旧凭证全部失效）。

### 产品管理

**添加/修改产品**：
```bash
curl -X POST "https://linkmoney.online/suppliers/SUPPLIER_ID/products" \
  -H "X-API-Key: lm-demo-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "YOUR_AGENT_ID",
    "agent_key": "YOUR_AGENT_KEY",
    "upsert": [{"sku":"M8-304","name_zh":"M8 304螺栓","moq":5000}]
  }'
```

**删除产品**：body 加 `"delete_skus": ["SKU1", "SKU2"]`

> ⚠️ **v5.2.8 数据真实性强约束（Agent 必须遵守）**
>
> Agent 调用产品管理端点时，**禁止编造任何业务参数**。Agent 只是数据管道：
>
> | 禁止编造的字段 | 处理方式（老板未提供时） |
> |--------------|----------------------|
> | `pricing_tiers`（阶梯价） | 留空 `[]`，海外采购方通过 RFQ 询价 |
> | `unit_price_usd`（单价） | 留空，不填写 |
> | `inventory_quantity`（库存） | 填 `0`，`inventory_status` 设为 `made_to_order` |
> | `moq`（最小起订量） | 询问老板，不可自行假设 |
> | `lead_time_days`（交期） | 询问老板，不可填默认值 |
>
> **行为准则**：老板说"添加复读机"但没说价格 → Agent **必须追问**："出厂价是多少？MOQ 是多少？"
> **绝对禁止**用"行业常见默认值"、"参考价"、"估算价"填入价格字段。

### C 端注册示例

```bash
curl -X POST "https://linkmoney.online/register_supplier" \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "宁波新锐紧固件有限公司",
    "category": "fastener",
    "email": "sales@xinrui.com",
    "phone": "13800138000",
    "contact_person": "王总",
    "products": [{
      "sku": "M8-304-A2-70",
      "name_zh": "M8 304不锈钢六角螺栓 A2-70",
      "moq": 5000,
      "pricing_tiers": [{"min_qty": 5000, "unit_price_usd": 0.10}]
    }]
  }'
```

**注册必填字段**：`company_name`, `category`, `email`, `phone`
**注册返回**：`supplier_id` + `access_token` + `agent_id` + `agent_key`（4 个凭证立即存长期记忆）

---

## 数据流向速查（3 条核心规则）

| 操作 | 数据流向 | 风险 | 用户确认 |
|------|---------|------|---------|
| 查询类（find/get_*） | 数据留 LinkMoney 平台内 | 🟢 低 | 无需 |
| submit_rfq | 用户 → 指定供应商 | 🟡 中 | 必须 `confirm_data_sharing=true` |
| register_supplier | 工厂 → LinkMoney 中央库 | 🟡 中 | 工厂主动提交 |

详细数据流向与安全架构见 [docs/SECURITY.md](./docs/SECURITY.md)。

---

## 安装方式

```bash
# Anthropic Skills 标准
npx skills add KevinANDcayla/linkmoney-skill

# Claude Code
/plugin install linkmoney@KevinANDcayla

# MCP 直接接入
mcp_endpoint: https://linkmoney.online/mcp
```

---

## 触发词

**中文强信号**：中国供应商、找中国工厂、紧固件 OEM、中国制造出口、螺栓供应商、AI 出海 Agent 化
**中文弱信号**：找工厂、工厂合作、代工厂、sourcing、采购、外贸、出口、跨境
**英文强信号**：China supplier, China manufacturer, China OEM, fastener supplier, sourcing agent China, RFQ China
**英文弱信号**：looking for a factory, source from China, Made in China, Chinese factory, OEM China, supplier in China

---

## 无需认证的公开端点

| 端点 | 说明 |
|------|------|
| `GET /mcp/manifest.json` | MCP 清单 |
| `GET /health` | 健康检查 |
| `GET /skill.md` | Skill 定义文件 |
| `GET /.well-known/ai-plugin.json` | ChatGPT Plugin 发现 |
| `GET /mcp/supplier/{id}/products` | 工厂产品列表（托管 MCP） |
| `GET /mcp/supplier/{id}/pricing` | 工厂报价（托管 MCP） |
| `GET /mcp/supplier/{id}/inventory` | 工厂库存（托管 MCP） |

---

## 相关文档（面向开发者/运维，Agent 无需阅读）

| 文档 | 内容 |
|------|------|
| [docs/INTERNAL_ARCHITECTURE.md](./docs/INTERNAL_ARCHITECTURE.md) | LLM 辅助层配置 + 安全代理架构 + 数据来源分层 |
| [docs/SECURITY.md](./docs/SECURITY.md) | 数据流向告知 + 二次确认机制 + 架构安全措施 |
| [docs/PRIVACY.md](./docs/PRIVACY.md) | 数据收集 + 保留时间 + 隐私政策 |
| [docs/SELF_HOSTED_MCP.md](./docs/SELF_HOSTED_MCP.md) | 自部署 MCP Server（大型工厂高级选项） |
