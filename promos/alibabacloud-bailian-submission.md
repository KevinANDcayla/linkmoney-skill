# LinkMoney - 阿里云百炼 MCP 注册指南 (v2 — 路径已验证)

## 阿里云百炼是什么
**bailian.console.aliyun.com** — 阿里云 LLM 应用平台 + MCP 工具市场。

2026-04 阿里云百炼上线**业界首个 MCP 全生命周期服务**（注册 → 云托管 → Agent 调用 → 流程组合）。
截至 2026-06 已集成 50+ 工具，**支持在线注册托管 MCP 服务**。

## 实际登录路径

浏览器直接打开：
```
https://bailian.console.aliyun.com/?tab=mcp
```
会自动跳转到 `cn-beijing` 或 `cn-shanghai` 区，然后看到：
- 左侧导航 → **MCP 管理** → **MCP 广场**
- 或者顶栏 **MCP 服务** → **创建 MCP**

## 提交步骤

### Step 1: 登录 + 企业认证
1. 用阿里云主账号登录（不能用 RAM 子账号）
2. 完成**企业实名认证**（个人开发者无法发布 MCP 服务到百炼广场）

### Step 2: 进入 MCP 广场
左侧菜单 → **应用** → **MCP 服务** → 顶部 tab **MCP 广场**

### Step 3: 点击 "创建 MCP"
右上角"创建 MCP"按钮，进入创建表单：

| 字段 | 填什么 |
|------|--------|
| **服务名称** | `linkmoney`（连钱） |
| **服务描述（中文）** | 见下方 |
| **服务描述（English）** | 见下方 |
| **服务类型** | 远程 MCP |
| **服务地址** | `https://linkmoney.online/mcp` |
| **Manifest URL** | `https://linkmoney.online/mcp/manifest.json` |
| **标签** | B2B, 中国制造, 采购, 供应链, AI, Agent, 外贸, 出口 |
| **Icon** | `https://linkmoney.online/favicon.ico` |
| **分类** | 商业 / 采购 / 供应链 |
| **协议** | streamable-http |
| **认证方式** | 无 / API Key（可选） |

### Step 4: 验证服务可达
百炼会**主动 GET** `https://linkmoney.online/mcp/manifest.json`，
返回 200 + 合法 manifest 才能通过。

我们的 manifest 已部署，验证：
```bash
curl -I https://linkmoney.online/mcp/manifest.json
# HTTP/1.1 200 OK
# content-type: application/json
```

### Step 5: 提交审核
通常 1-3 个工作日。通过后会出现在百炼的"通义千问"+"钉钉 AI"+"飞书 AI"的工具市场。

## 中文描述（复制粘贴）

```
LinkMoney（连钱）— 让 AI Agent 主动找上中国供应商的 B2B 贸易链接器。

核心能力：
• 51 家经 ISO/CE/FDA 认证的中国工厂
• 7 大品类：紧固件 / 电子 / 包装 / 五金 / 注塑 / 机械 / 纺织
• 13 个 MCP 工具：搜索 / 实时价格 / 实时库存 / RFQ / 多语言询价
• 覆盖采购全流程：找厂 → 比价 → 看库存 → 提交 RFQ → 收报价 → 成交

价格：成交 3% 佣金（首 3 个月免费），无订阅费、无前期成本。
```

## English description

```
LinkMoney — AI-native B2B marketplace connecting agents with 51 verified 
Chinese factories for live pricing, real-time inventory, and automated RFQ.
MCP endpoint: https://linkmoney.online/mcp/manifest.json
First 3 months free, 3% success fee after.
```

## 国内用户价值

**这是最关键的市场**：
- 通义千问 / 钉钉 AI / 飞书 AI 都跑在百炼
- 中国工厂主/外贸公司用这些工具 → 一键装 LinkMoney
- **国内 CDN** + **无需翻墙**
- 14 亿人口市场
- 已有 50+ MCP 工具在百炼 — 我们是**第一个供应链/B2B 类**

## 审核通过后的推广动作

1. 在百炼广场置顶位置"Featured"展示
2. 钉钉/飞书 AI 助手默认工具推荐
3. 阿里云市场首页导流
4. 阿里云销售对接采购方企业
