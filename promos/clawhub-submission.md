# LinkMoney - ClawHub 提交指南 (v2 — 修正域名)

## ClawHub 是什么
**clawhub.ai**（不是 .com，.com 是 404）— OpenClaw 官方插件市场。

平台规模（2026-06）：
- **52,700+ tools**
- **180,000+ users**
- **12,000,000+ downloads**
- 499 publishers
- 4.8 平均评分

中国镜像：https://mirror-cn.clawhub.com（火山引擎 × OpenClaw 共建）

## 重要：ClawHub 没有公开 submit 表单

ClawHub 是 OpenClaw 生态的一部分，**没有像 mcp.so 那样的公开 form**。提交需要：

### 路径 A：成为 Publisher（推荐）

1. 注册 OpenClaw 账号：https://openclaw.ai
2. 申请 Publisher 资质（`clawhub.ai/publishers` 页面有 Become a Publisher 入口）
3. 提交 publisher 申请 + 实名 + 关联 GitHub repo `KevinANDcayla/linkmoney-skill`
4. 审核通过后用 `openclaw publish` CLI 发布 skill（命令类似 `npm publish`）

### 路径 B：通过 OpenClaw Agent 自动收录

OpenClaw 0.20.0+ 版本会自动扫描 GitHub 上的 `SKILL.md` 格式仓库，识别为 skill 后出现在 ClawHub。
我们的仓库已经有 `SKILL.md`，**等 24-48 小时 OpenClaw 索引器自动抓**即可。

### 路径 C：通过 npm 包自动分发（最快）

`npx skills add KevinANDcayla/linkmoney-skill` 安装量如果起来，ClawHub 的 indexer 会通过 npm 索引发现。

## 实际发布步骤（采用路径 A）

### Step 1: 注册 OpenClaw Publisher
- 访问 https://clawhub.ai/publishers
- 点击 "Become a Publisher" 或 "Sign in with GitHub"
- 用 `KevinANDcayla` GitHub 账号登录

### Step 2: 关联仓库
在 Publisher Dashboard → Repositories → Add:
- Repo: `https://github.com/KevinANDcayla/linkmoney-skill`
- Branch: `main`
- Auto-publish: enabled
- Visibility: public

### Step 3: 填写 skill metadata
- **Name**: linkmoney
- **Display Name**: LinkMoney（连钱）
- **Tagline**: AI-native B2B marketplace connecting agents with 51 verified Chinese factories
- **Category**: Business / Supply Chain
- **Tags**: b2b, china, sourcing, supply-chain, manufacturing, procurement, agent, MCP
- **Description (EN)**: See below
- **Install Command**: `npx skills add KevinANDcayla/linkmoney-skill`
- **Homepage**: https://linkmoney.online
- **MCP Manifest**: https://linkmoney.online/mcp/manifest.json

### Step 4: 提交审核
OpenClaw 团队审核（通常 1-3 天），审核维度：
- skill 是否真有用途
- install_command 能否跑通
- manifest.json 是否合法
- 仓库许可证（我们 MIT ✓）

## Description (EN)（复制粘贴）

```
LinkMoney is the first MCP Skill that connects AI agents directly to real 
Chinese factory ERP systems — enabling live pricing, real-time inventory, 
and automated RFQ without stale Alibaba listings.

When an overseas procurement agent asks "Find M8 304 stainless steel bolts, 
50K pcs", LinkMoney returns 3-5 verified Chinese factories with LIVE 
pricing from their own MCP servers.

Stats:
- 51 verified Chinese suppliers
- 140 products across 7 categories (fastener, electronics, packaging, 
  hardware, injection molding, machinery, textile)
- 13 public MCP tools covering the full procurement lifecycle
- 7 buyer countries currently active

Pricing: 3% success fee on closed deals. First 3 months FREE.
License: MIT (open source)
```

## 截图位置

1. https://linkmoney.online/ — Landing Page 全屏
2. https://linkmoney.online/mcp/manifest.json — manifest（展示 13 tool）
3. 调用 `find_china_supplier` 的示例输出
4. 调用 `get_pricing` + `get_inventory` 的对比表

## 等待与跟进

- 提交后 1-3 天收到 OpenClaw 审核结果邮件
- 审核通过后立即出现在 https://clawhub.ai/skills
- 链接会被索引到 ClawHub 中国镜像 https://mirror-cn.clawhub.com
- 被搜索/分类/排行
