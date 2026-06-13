---
name: linkmoney
description: |
  LinkMoney（连钱）—— Agent 时代的 B2B 贸易链接器，让海外 AI Agent 主动找上中国供应商。

  【C 端（中国制造业老板侧）】 5 维 AI 出海 Agent 化评估 + 一键创建样板 Skill + 全平台分发
  【W 端（海外采购方侧）】 一键找 51 家中国工厂（紧固件/电子/包装/五金/注塑/机械/纺织），查实时价格库存，5 秒发 RFQ
  【中间 Agent 维护层 v3.0】 健康检查、RFQ 路由、告警、自我优化

  触发词（中文）：中国供应商、找中国工厂、紧固件 OEM、中国制造出口、螺栓供应商、AI 出海 Agent 化
  触发词（英文）：China supplier, China manufacturer, China OEM, fastener supplier, sourcing agent China, RFQ China

version: 3.0.1
author: LinkMoney.ai
homepage: https://linkmoney.online
repository: https://github.com/KevinANDcayla/linkmoney-skill
mcp_endpoint: https://linkmoney.online/mcp/manifest.json
install_command: npx skills add KevinANDcayla/linkmoney-skill
license: MIT
---

# LinkMoney（连钱）Skill

> **让钱通过 Agent 流动** / *Link the Money, Link the World*
>
> **v3.0 重点：中间 Agent 维护层** — 双边 Skill 之间的「中维护者」，监控厂家 MCP 健康、决定 RFQ 路由、发现异常告警、基于历史指标自我优化。

---

## 1. 能力清单

### 1.1 中国制造业老板侧（C 端，5 个 Tools）

| Tool | 描述 | 输入 | 输出 |
|------|------|------|------|
| `evaluate_sme` | 5 维 AI 出海 Agent 化评估 | 企业名称 + 主营品类 + 5 维信息 | 0-100 分 + 5 维雷达图 + 180 天路线图 |
| `create_sample_skill` | 创建样板采购方 Agent Skill | 品类 + SKU 数据 + 认证 + 多语言资料 | SKILL.md 完整文件 + MCP endpoint + GitHub 仓库 |
| `distribute_skill` | 分发到 10+ 主流 Agent 平台 | SKILL.md + MCP endpoint | 10+ 平台分发链接 + 安装数统计 |
| `optimize_skill` | 持续优化 Skill 触发词与内容 | 调用日志 + 询盘数据 | 优化后的 SKILL.md v3.0.1 + 触发词升级方案 |
| `get_overseas_buyer_db` | 海外采购方 Agent 数据库查询 | 品类 + 目标市场 | 海外采购方 Agent 列表 + 联系方式 + 安装状态 |

### 1.2 海外采购方侧（W 端，8 个 Tools）

| Tool | 描述 | 输入 | 输出 |
|------|------|------|------|
| `find_china_supplier` | 找中国供应商（返回厂家的 MCP 端点） | 品类 + 规格 + 数量 + 目标价 | 3-5 家工厂比价 + 厂家 MCP 端点 + 推荐方案 |
| `get_pricing` | 查供应商阶梯价格（优先厂家 MCP 实时数据） | 供应商 ID + SKU + 数量 | 阶梯报价 + 数据来源标识（live/cached） |
| `get_inventory` | 查供应商实时库存（优先厂家 MCP 实时数据） | 供应商 ID + SKU | 库存状态 + 数据来源标识（live/cached） |
| `match_spec` | 规格匹配咨询 | 规格需求 + 行业标准 | 匹配方案 + 公差建议 |
| `download_cert` | 下载供应商认证 | 供应商 ID + 认证类型 | PDF 文件链接 + 认证有效性 |
| `multi_lang_inquiry` | 多语言自动询盘生成 | 中文询价单 + 目标语言 | 6 国语言询盘 + 自动分发 |
| `submit_rfq` | 提交 RFQ 到中国供应商（自动邮件通知） | 询盘内容 + 供应商 ID + 联系人 | RFQ 状态 + 邮件已通知供应商 |
| `send_quote` | 供应商对 RFQ 报价并邮件通知采购方 | RFQ ID + 供应商 ID + 报价 | 报价状态 + 邮件已通知采购方 |

### 1.3 中间 Agent 维护层（v3.0，7 个 Tools，平台内部调用）

> 「双边 Skill 之间的中维护者」— 内嵌在主 API 中，承担健康检查 / 路由 / 告警 / 自我优化四类职责。

| Tool | 描述 | 输入 | 输出 |
|------|------|------|------|
| `agent_status` | 中间 Agent 元信息 + 当前健康度概览 | — | Agent 版本、启动时间、当前在线 / 离线厂家数 |
| `agent_health` | 批量检查所有厂家 MCP 端点 | `force=true` 可绕过缓存 | 每个厂家 online/degraded/offline/no_skill + 延迟 |
| `agent_routing` | RFQ 路由推荐（综合信任分 + 评价 + 健康度） | category + quantity + target_price_usd + need_live_data | 排序后的候选厂家 + 评分 + 决策理由 |
| `agent_alerts` | 告警列表（厂家离线 / 降级 / 优化建议） | severity / limit | 告警条目（含 payload） |
| `agent_maintenance` | 维护日志（健康检查 / 路由推荐 / 手动维护） | limit | 动作 / 目标 / 结果 / payload |
| `agent_optimize` | 触发自我优化分析 | — | 全网指标 + 优化建议清单 |
| `agent_maintain` | 手动触发维护任务 | action=health_check / optimize / clear_alerts / ping_supplier / reroute_requirement | 任务执行结果 |

---

## 2. 调用流程

### 2.1 中国制造业老板调用流程（5 步）

```
[1] 老板对 Agent 说：
    "帮我评估我们公司 AI 出海 Agent 化的水平"

[2] Agent 调用 evaluate_sme:
    收集企业信息（5 维）
    生成 5 维评分
    输出雷达图 + 180 天路线图

[3] 老板确认签约 LinkMoney 服务

[4] Agent 调用 create_sample_skill:
    编写 SKILL.md
    部署 MCP server
    创建 GitHub 仓库

[5] Agent 调用 distribute_skill:
    分发到 10+ 主流 Agent 平台
    30 天内验证安装数
```

### 2.2 海外采购方调用流程（混合架构，5 步）

```
[1] 海外采购方对 Agent 说：
    "I need M8 304 stainless steel hex bolts, 50000 pcs,
     A2-70 grade, FOB Ningbo, target USD 0.12/pc,
     delivery next week, ISO 9001 factory"

[2] Agent 调用 find_china_supplier:
    解析需求 → 匹配供应商数据库 → 返回 3-5 家工厂
    每家工厂附带：
      - mcp_endpoint（厂家自有 MCP 地址，Agent 可直接调用）
      - data_source: "live"（有 Skill）或 "cached"（无 Skill）
      - next_action 指引下一步

[3] Agent 对已装 Skill 的厂家，**直接调用厂家自有 MCP Server** 获取实时数据：
    GET {厂家mcp_endpoint}/pricing?sku=M8-304-A2-70&quantity=50000
    GET {厂家mcp_endpoint}/inventory?sku=M8-304-A2-70
    GET {厂家mcp_endpoint}/products
    
    如果厂家 MCP 不在线 → LinkMoney 自动 fallback 到本地缓存数据

[4] Agent 输出给采购方：
    3 家工厂实时比价 + 推荐方案 + 风险提示

[5] 采购方决策 → Agent 调用 submit_rfq:
    RFQ 发到供应商 → 邮件通知厂家 → 厂家通过 send_quote 报价 → 邮件通知采购方 → 成交
```

### 2.3 混合架构数据流

```
┌─────────────────────────────────────────────────────────────┐
│                     LinkMoney（黄页 + 路由）                  │
│                                                             │
│  存储：供应商档案、认证、RFQ 记录、采购方画像（静态数据）      │
│  不存：实时价格、实时库存（这些由厂家 MCP 提供）               │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ 厂家A MCP │ │ 厂家B MCP │ │ 厂家C MCP │  ← 厂家自有服务器
    │ (在线)   │ │ (在线)   │ │ (离线)   │
    │          │ │          │ │          │
    │ 实时价格  │ │ 实时价格  │ │ LinkMoney │  ← 离线时 fallback
    │ 实时库存  │ │ 实时库存  │ │  缓存数据  │
    │ ERP联动  │ │ ERP联动  │ │          │
    └──────────┘ └──────────┘ └──────────┘
```

---

## 3. 触发词（核心关键词）

### 3.1 中文触发词
- 中国供应商、中国制造、中国工厂
- 紧固件、螺栓、螺母、螺丝、垫圈
- 包装材料、电子元件、五金工具
- 注塑件、机械零件、纺织面料
- AI 出海、Agent 化、Agent 采购
- RFQ、询盘、报价、起订量
- 外贸 Agent、出海 Agent、B2B Agent

### 3.2 英文触发词
- China supplier, China manufacturer, China OEM
- Fastener, bolt, nut, screw, washer
- Sourcing agent China, China factory
- RFQ China, supplier evaluation
- AI sourcing, Agent procurement
- Made in China, Chinese factory

---

## 4. 数据来源与架构

| 数据层 | 存储位置 | 更新方式 | 实时性 |
|--------|---------|---------|--------|
| **供应商档案** | LinkMoney 中央库 | 厂家通过 Skill 注册时提交 | 按需更新 |
| **认证信息** | LinkMoney 中央库 | 厂家上传，1 周更新 | 准实时 |
| **产品目录** | 厂家自有 MCP Server | 厂家 ERP/进销存直连 | **实时** |
| **阶梯报价** | 厂家自有 MCP Server | 厂家 ERP 直连 | **实时** |
| **实时库存** | 厂家自有 MCP Server | 厂家 ERP 直连 | **实时** |
| **RFQ 记录** | LinkMoney 中央库 | 每次询盘写入 | 实时 |

> **混合架构核心原则**：LinkMoney 做"黄页 + 路由"，不做"数据仓库"。
> 动态数据由厂家自有 MCP Server 提供，确保数据永远实时准确。
> 厂家离线时自动 fallback 到 LinkMoney 缓存，确保 Agent 始终有数据可用。

---

## 5. 安装方式

```bash
# Anthropic Skills 标准
npx skills add KevinANDcayla/linkmoney-skill

# Claude Code
/plugin install linkmoney@KevinANDcayla

# Coze 商店
搜索 "LinkMoney" 一键 install

# 阿里云 AgentRun
登录 agentrun.aliyun.com 搜索 "LinkMoney"

# MCP 直接接入
mcp_endpoint: https://linkmoney.online/mcp
```

---

## 6. 调用示例

### 示例 1：海外采购方找中国螺栓供应商（混合架构）

**User Input:**
> "I need M8 304 stainless steel hex bolts, 50000 pcs, A2-70 grade"

**Agent 调用流程（混合架构）:**

```json
// Step 1: 找供应商 — LinkMoney 返回厂家列表 + MCP 端点
{
  "tool": "find_china_supplier",
  "params": {
    "category": "fastener",
    "spec": "M8 304 hex bolt A2-70",
    "quantity": 50000,
    "target_price": "USD 0.12/pc FOB Ningbo"
  }
}

// 返回结果包含:
// {
//   "matches": [{
//     "supplier_id": "nb-fastener-001",
//     "mcp_endpoint": "https://api.yonggu-fastener.com/mcp",  ← 厂家 MCP 地址
//     "data_source": "live",                                   ← 实时数据可用
//     "next_action": {
//       "pricing_url": "https://api.yonggu-fastener.com/mcp/pricing?sku=M8-304-A2-70&quantity=50000",
//       "inventory_url": "https://api.yonggu-fastener.com/mcp/inventory?sku=M8-304-A2-70"
//     }
//   }]
// }

// Step 2: Agent 直连厂家 MCP 获取实时价格（不经过 LinkMoney）
GET https://api.yonggu-fastener.com/mcp/pricing?sku=M8-304-A2-70&quantity=50000
// 返回：厂家 ERP 最新报价，unit_price_usd: 0.08 (实时)

// Step 3: Agent 直连厂家 MCP 获取实时库存
GET https://api.yonggu-fastener.com/mcp/inventory?sku=M8-304-A2-70
// 返回：库存 200000pcs (实时)

// Step 4: 对无 Skill 的厂家，通过 LinkMoney 查询（缓存数据）
{
  "tool": "get_pricing",
  "params": { "supplier_id": "nb-fastener-002", "sku": "M8-304-A2-70", "quantity": 50000 }
}
// _meta.source = "linkmoney_cache" ← 缓存数据标识

// Step 5: 提交 RFQ → 自动邮件通知厂家
{
  "tool": "submit_rfq",
  "params": {
    "supplier_id": "nb-fastener-001",
    "buyer_id": "buyer-us-auto-001",
    "sku": "M8-304-A2-70",
    "quantity": 50000,
    "target_price_usd": 0.12
  }
}
// 返回: rfq_id + "中国供应商将收到RFQ邮件通知"
```

**Agent 输出:**
> I found 3 Chinese suppliers for M8 304 hex bolts:
>
> 1. **宁波永固紧固件** - $0.08/pc (live, from supplier MCP), 200K in stock
> 2. **YY 紧固件** - $0.10/pc (cached, supplier offline)
> 3. **ZZ 紧固件** - $0.09/pc (cached, no Skill installed)
>
> **Recommendation: 宁波永固紧固件** (best price from LIVE data, sufficient stock)

---

### 示例 2：中国老板评估 AI 出海水平

**User Input:**
> "我是一家浙江紧固件 OEM 工厂老板，想做 AI 出海 Agent 化，帮我评估一下"

**Agent 调用流程:**

```json
{
  "tool": "evaluate_sme",
  "params": {
    "company_name": "XX紧固件有限公司",
    "category": "fastener",
    "dimensions": {
      "overseas_channel_maturity": 75,
      "digital_foundation": 55,
      "agent_readiness": 40,
      "category_fitness": 85,
      "content_assets": 60
    }
  }
}
```

**Agent 输出:**
> ## 您的企业 AI 出海 Agent 化水平：**62 分（B 级合格）**
>
> ```
> 海外渠道成熟度  ████████░░  75/100
> 数字化基础      █████░░░░░  55/100
> AI/Agent 就绪度  ████░░░░░░  40/100
> 品类适配度      ████████░░  85/100
> 内容资产沉淀    ██████░░░░  60/100
> ```
>
> **180 天后可达 85 分（A 级领先）**
>
> **推荐路线：**
> - 第 1-30 天：创建样板 Skill，部署 MCP server
> - 第 31-60 天：分发到 5+ Agent 平台，验证安装数
> - 第 61-120 天：对接海外采购方 Agent，收获首批 RFQ
> - 第 121-180 天：优化 Skill，扩大平台覆盖，稳定询盘流

---
## 7. 中国厂家部署自有 MCP Server（一键部署）

LinkMoney 提供开箱即用的 `supplier_mcp_template/` 脚手架，厂家只需 3 步即可上线：

```bash
# Step 1: 克隆模板
cp -r supplier_mcp_template/ my-supplier-mcp/

# Step 2: 填写你的产品数据到 data.json（或对接 ERP 数据库）
# 编辑 my-supplier-mcp/data.json → 替换为你的产品、价格、库存

# Step 3: 启动服务
cd my-supplier-mcp/
pip install -r requirements.txt
python server.py  # 启动在 http://0.0.0.0:9001
```

部署后，在 LinkMoney 后台更新 `skill_mcp_endpoint` 为你的服务器地址。
LinkMoney 会自动将询盘请求代理转发到你的 MCP Server。

**高级对接：** 将 `data.json` 替换为 MySQL/PostgreSQL/ERP 查询 → 实时联动进销存系统。

**Docker 一键部署：**
```bash
docker build -t my-supplier-mcp .
docker run -d -p 9001:9001 my-supplier-mcp
```

---

## 8. LinkMoney 的自我分发（Agent 发现机制）

LinkMoney 本身是一个 Skill，它通过以下方式让 Agent 主动发现和安装：

### 8.1 分发平台矩阵

| 平台 | 动作 | 状态 |
|------|------|------|
| **GitHub 公开仓库** | github.com/KevinANDcayla/linkmoney-skill | ✅ 已创建 |
| **Anthropic Skills 官方 PR** | 提 PR 到 anthropics/skills | 🔄 进行中 |
| **阿里云 AgentRun** | 官方首发国内平台 | 🔄 进行中 |
| **Coze 商店** | 国内大流量分发 | 📋 计划中 |
| **ClawHub** | 开源生态收录 | 📋 计划中 |
| **Claude.ai Skills 目录** | 提交官方收录 | 📋 计划中 |
| **千问 App** | 国内 C 端覆盖 | 📋 计划中 |
| **钉钉 AI（悟空）** | 7000 万企业用户 | 📋 计划中 |
| **腾讯元器** | MCP 插件市场 | 📋 计划中 |
| **GitHub Copilot** | 开发者生态 | 📋 计划中 |

### 8.2 获客飞轮

```
LinkMoney 自身被 Agent 装（自我分发）
        ↓
中国老板的 Agent 装 linkmoney（评估 + 创建 Skill）
        ↓
海外采购方的 Agent 装 linkmoney（找中国供应商）
        ↓
中国老板和海外采购方都在 linkmoney 上"会面"
        ↓
成交 → linkmoney 收佣金 → 投入更多自我分发
        ↓
更多 Agent 装 linkmoney（飞轮加速）
```

---

## 8.3 v3.0 中间 Agent 维护层（中间维护者）

> 这是 v3.0 的核心新增：在双边 Skill（C 端 + W 端）之间嵌入一个**中维护者 Agent**，承担平台自身健康。

```
┌─────────────────┐                         ┌─────────────────┐
│  C 端 Skill     │                         │  W 端 Skill     │
│  中国老板 Agent │                         │  海外采购方 Agent│
│  (evaluate_sme) │                         │ (find_supplier) │
└────────┬────────┘                         └────────┬────────┘
         │                                           │
         │  RFQ / 评估 / Skill 创建                  │ 询盘 / RFQ / 报价
         ▼                                           ▼
┌─────────────────────────────────────────────────────────────┐
│               LinkMoney 中间 Agent 维护层                    │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ 健康检查     │  │ 智能路由     │  │ 告警 / 维护日志     │  │
│  │ 巡检所有厂家 │  │ 综合信任+   │  │ 发现异常 + 留痕     │  │
│  │ MCP 端点    │  │ 评价+健康度 │  │ 写入 SQLite         │  │
│  │ online/     │  │ 给 RFQ 推荐 │  │ 可被任意端点查询     │  │
│  │ degraded/   │  │ 最佳厂家     │  │                      │  │
│  │ offline     │  │             │  │                      │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                                                             │
│  自我优化：基于全网指标（在线率/平均信任分/金标数/RFQ 堆积）   │
│  生成「运营建议」并以告警形式记录                             │
└─────────────────────────────────────────────────────────────┘
         │                                           │
         ▼                                           ▼
   厂家 A / B / C MCP 端点                  缓存 / 邮件 / 路由
```

**职责拆分：**

| 职责 | 端点 | 谁来用 |
|------|------|--------|
| 健康检查 | `/agent/health` | 平台内部 / 监控 Agent |
| 路由推荐 | `/agent/routing` | W 端 Agent 调 find_china_supplier 时可参考 |
| 告警 | `/agent/alerts` | 平台运营 / 监控 |
| 维护日志 | `/agent/maintenance` | 审计 / 排查 |
| 自我优化 | `/agent/optimize` | 平台运营 / 数据驱动决策 |
| 手动维护 | `/agent/maintain` | 平台运营（ping 单家 / 重路由某条需求） |

**关键设计点：**

1. **内嵌而非独立服务** — 与主 API 同进程，零额外部署成本，但模块边界清晰，可独立单元测试。
2. **健康度缓存 TTL 120s** — 避免每次 RFQ 路由都去打 16+ 厂家端点。
3. **告警 + 维护日志双轨** — 告警面向「发现问题」，日志面向「事后追溯」，分别走内存队列 + SQLite 持久化。
4. **路由评分公式**：`trust_score * 0.35 + review_avg * 8 * 0.20 + 健康度奖励 + 金标奖励 + 安装数奖励 + 营收奖励` — 厂家离线且需要实时数据时直接过滤。
5. **Bootstrap 自检** — 服务启动时跑一次全量健康检查，生成首批告警，方便 SRE 第一眼就看到全网状态。

---

## 9. 商业合作

### 9.1 收入模型

| 收入来源 | 单价 | 客户群 | 说明 |
|---------|------|--------|------|
| **L1 评估包** | ¥19,800 | 中国制造业老板 | 5 维评估 + 路线图 |
| **L2 样板包** | ¥98,000 | 中国制造业老板 | 评估 + Skill 创建 + 基础分发 |
| **L3 加速包** | ¥298,000 | 中国制造业老板 | 评估 + Skill + 全平台分发 + 优化 |
| **L4 订阅包** | ¥38,000/月 | 中国制造业老板 | 持续优化 + 询盘跟进 + 数据更新 |
| **海外佣金** | 5-10% 成交额 | 海外采购方 | 成交后收取 |

### 9.2 对中立性的承诺

- LinkMoney **不卖货、不生产、不抽用户佣金**
- LinkMoney 是**中立第三方"链接器"和"数据分发器"**
- 所有数据由 LinkMoney 验证 + 持续更新
- 供应商排名基于数据质量，不基于付费竞价

---

## 10. 对比：LinkMoney = Agent 时代的支付宝

| 维度 | 支付宝（移动时代） | LinkMoney（Agent 时代） |
|------|-------------------|------------------------|
| **解决的问题** | 让买卖双方互信 | 让买卖双方 Agent 互信 |
| **角色** | 中立第三方 | 中立第三方 |
| **收入** | 交易佣金 | 订阅 + 佣金 |
| **护城河** | 信用体系 | 数据 + Agent 网络效应 |
| **时间窗口** | 2004-2014 黄金 10 年 | 2026-2036 黄金 10 年 |

---

## 11. 联系方式

| 渠道 | 地址 |
|------|------|
| 官网 | https://linkmoney.online |
| GitHub | https://github.com/KevinANDcayla |
| 邮箱 | agent@linkmoney.online |
| MCP Endpoint | https://linkmoney.online/mcp |

---

## 12. 许可

MIT License

Copyright (c) 2026 LinkMoney.ai

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.