# LinkMoney 上线行动表与指导书

> 目标：2个月内获得 **100 家中国供应商 Skill 安装** + **50 个海外采购 Agent 活跃用户**

---

## 一、上线前检查清单

### 产品就绪（上线前 1 周完成）
- [x] 25 个 MCP 端点全部可用
- [x] SMTP 邮件通知（RFQ + 报价）
- [x] 混合架构（厂家 MCP 直连 + 缓存 fallback）
- [x] `/。well-known/linkmoney-skill.json` 自动发现
- [x] 厂家 MCP 模板一键部署（supplier_mcp_template/）
- [x] CSV 上传零代码更新产品
- [x] API Key 认证 + Rate Limiting
- [ ] 生产环境服务器部署（建议：阿里云/腾讯云，2C4G 起步）
- [ ] HTTPS 域名配置（建议：https://linkmoney.online）
- [ ] 生产环境 SMTP 配置（建议：企业邮箱，如 support@linkmoney.online）
- [ ] 真实翻译 API 接入（建议：DeepL API Free 起步）
- [ ] 数据备份策略（每日 SQLite 备份到 OSS/COS）
- [ ] 健康监控 + 告警（建议：UptimeRobot 免费方案）

### 内容就绪
- [ ] 中方厂家一页纸说明（中文，带截图，微信可直接转发）
- [ ] 外方采购方 Landing Page（英文，含 Demo 视频）
- [ ] 3 个真实工厂的 Demo 数据（紧固件、电子、包装 — 各 1 家）
- [ ] 1 个完整的端到端录屏（海外 Agent 从询盘到成交全过程）

### 分发渠道就绪
- [ ] Skill 市场发布：ClawHub、skills.sh、MCP.so
- [ ] GitHub 仓库公开 + README 英文
- [ ] 阿里云百炼 MCP 注册
- [ ] 微信社群（至少 1 个外贸厂长群）
- [ ] LinkedIn Company Page 创建

---

## 二、4 周行动表

### 第 1 周：内测 + 种子用户

| 日期 | 行动 | 负责人 | 目标 |
|------|------|--------|------|
| Day 1 | 部署生产服务器 + HTTPS | 技术 | 服务对公网可用 |
| Day 1 | GitHub 仓库公开 + README | 技术 | 可被搜索引擎索引 |
| Day 2 | 录制 3 分钟 Demo 视频 | 产品 | 上传到 B站/YouTube |
| Day 2 | 编写中方厂家一页纸（微信群转发版） | 运营 | 含二维码，可一键加群 |
| Day 3 | 在 ClawHub / skills.sh 提交 LinkMoney Skill | 技术 | 进入 Skill 市场 |
| Day 3 | 在阿里云百炼注册 MCP 服务 | 技术 | 中国企业可直接搜索安装 |
| Day 4-5 | 邀请 5 家关系好的工厂做内测（给补贴） | 商务 | 5 家真实数据上线 |
| Day 5-7 | 修改内测反馈的 bug | 技术 | 修复所有阻塞性问题 |
| Day 7 | 周复盘：统计安装量、RFQ 量、反馈 | 全员 | 决定是否进入第 2 周 |

**本周目标：5 家工厂安装 Skill + 3 个真实 RFQ**

### 第 2 周：中方厂家推广

| 日期 | 行动 | 具体做法 | 渠道 |
|------|------|---------|------|
| Day 8 | 微信行业群群发 | "Agent 帮你做外贸？24小时自动接单的 AI 工具来了" | 50+ 外贸群 |
| Day 8 | 抖音/B站发 Demo 视频 | "我一个螺栓厂老板，装了这个工具，老外Agent半夜都在给我发询盘" | 短视频 |
| Day 9 | 1688/阿里国际站卖家社群 | 在卖家社区发帖 + 私信头部卖家 | 平台私域 |
| Day 10 | 公众号文章 | 《2026年中国工厂的新出路：让 AI Agent 帮你找海外客户》 | 微信公众号 |
| Day 10 | 知乎发布 | "外贸工厂如何用 AI Agent 获客？实操教程" | 知乎 |
| Day 11-12 | 产业带地推 | 宁波紧固件/义乌小商品/深圳电子 → 找协会合作 | 线下 |
| Day 13 | 第 2 批种子用户 | 邀请 20 家工厂，送 3 个月免费 + 优先展示 | 私域 |
| Day 14 | 周复盘 | 统计安装量、询盘量、转化 | 全员 |

**本周目标：20 家工厂 Skill 在线 + 15 个 RFQ**

### 第 3 周：海外采购方推广

| 日期 | 行动 | 具体做法 | 渠道 |
|------|------|---------|------|
| Day 15 | Reddit 发布 | r/supplychain, r/manufacturing, r/smallbusiness | 英文帖 |
| Day 15 | LinkedIn 文章 | "How I automated sourcing from Chinese factories with AI Agent" | LinkedIn |
| Day 16 | Product Hunt 发布 | LinkMoney - AI Agent marketplace for global trade | Product Hunt |
| Day 16 | Hacker News Show HN | 发 Show HN 帖 | Hacker News |
| Day 17 | X(Twitter) 推广 | 找 supply chain / ecommerce KOL 转发 | X |
| Day 17 | Indie Hackers 发布 | 案例分享 | IH |
| Day 18-21 | 邮件触达 | 从 Apollo.io 找 500 个 procurement manager → 冷邮 | Email |
| Day 21 | 周复盘 | 统计海外 Agent 安装量 | 全员 |

**本周目标：50 个海外 Agent 安装**

### 第 4 周：优化 + 留存

| 日期 | 行动 |
|------|------|
| Day 22-24 | 数据驱动优化（哪类产品询盘量最高？哪家工厂响应最快？） |
| Day 25 | 成功案例包装（XX 工厂通过 LinkMoney 成交 $50K 订单） |
| Day 26 | 产品迭代（基于用户反馈的新功能） |
| Day 27-28 | 投付费广告（Google Ads: "source from china ai agent"） |
| Day 28 | 月度复盘 |

**本周目标：75+ 工厂 + 75+ 采购方，累计 100 RFQ**

---

## 三、行动指导书

### A 篇：中方厂家获取指南

#### 目标画像
- 年营收 1000万-5亿 的制造型企业
- 已有出口经验（做过阿里国际站/展会）
- 老板或外贸经理日常使用微信/抖音
- 痛点：获客成本高、询盘质量差、时差沟通低效

#### 触达话术（微信群/朋友圈）

```
【标题】你的工厂，能不能让 AI Agent 帮你接单？

你还在熬夜回老外邮件吗？
你还在阿里国际站烧 P4P 吗？
2026 年了，海外采购方已经用 AI Agent 在找供应商了。

LinkMoney（连钱）—— Agent 时代的 B2B 贸易链接器

老外的 AI Agent 会自动：
✓ 搜索中国供应商
✓ 比价 3-5 家工厂
✓ 查实时库存 + 认证
✓ 提交 RFQ 直接到你面前

你只需要：
① 安装 LinkMoney Skill（5 分钟）
② 上传产品 CSV（从 Excel 导出）
③ 等着收 RFQ 邮件

首批 50 家工厂免费入驻，扫码进群 ↓
[二维码]
```

#### 厂家接入路径（3 选 1）

```
路径 1：零代码（5 分钟）
  → 打开 supplier_mcp_template/data.json
  → 填产品、价格、库存
  → python server.py → 上线

路径 2：CSV 上传（2 分钟）
  → Excel 导出 CSV
  → 打开 http://你的服务器:9001/admin
  → 上传 CSV → 自动生效

路径 3：ERP 对接（半天）
  → data.json 改成连你的金蝶/用友读数据
  → 价格库存实时同步
```

#### 厂家落地页（中文）

添加到 `server.py` 的 `/onboard-supplier` 端点（见第四部分）。

---

### B 篇：海外采购方获取指南

#### 目标画像
- 中小型进口商/贸易公司（年采购额 $50万-$500万）
- 频繁从中国采购（每月至少 1 次）
- 使用 Claude/ChatGPT/Cursor 等 AI 工具
- 痛点：找供应商耗时长、比价困难、时差沟通、质量控制

#### 分发渠道优先级

| 优先级 | 渠道 | 方式 | 预估成本 |
|--------|------|------|---------|
| P0 | ClawHub / skills.sh | 提交 Skill 列表 | 免费 |
| P0 | MCP.so | 注册 MCP 服务 | 免费 |
| P0 | GitHub | 公开仓库 + 英文 README | 免费 |
| P1 | Reddit | r/supplychain, r/manufacturing 发帖 | 免费 |
| P1 | Product Hunt | 产品发布 | 免费 |
| P1 | LinkedIn | 文章 + 私信 procurement manager | 免费 |
| P2 | Hacker News | Show HN | 免费 |
| P2 | Google Ads | "source from china ai agent" | $5-10/day |
| P3 | 行业媒体 | Supply Chain Dive 等投稿 | 免费/付费 |

#### Reddit 帖模板

```
Title: I built an AI Agent that connects overseas buyers directly 
       to Chinese factories — no middlemen, no Alibaba fees

Body:
I run a small importing business. For years, finding reliable 
Chinese suppliers meant:
- Alibaba (fake reviews, middlemen pretending to be factories)
- Trade shows ($10K+ per trip)
- WeChat back-and-forth at 2 AM

So I built LinkMoney — an MCP Skill that lets Claude/GPT 
agents do the sourcing for you.

How it works:
1. Tell your AI agent what you need 
   "I need M8 304 stainless bolts, 50K pcs, 30 days"
2. Agent searches Chinese factories (real manufacturers, not traders)
3. Live pricing + inventory from factory ERP systems
4. Submit RFQ → factory responds with quote → deal

Why this is different:
- No Alibaba middlemen — direct factory connection
- Real-time data from factory systems (not 3 month old listings)
- AI agents do the comparison shopping while you sleep
- Open source, works with any MCP-compatible agent

Try it: https://github.com/linkmoney-ai/linkmoney-skill
```

#### Product Hunt 发布清单

```
Tagline: AI Agent marketplace connecting overseas buyers 
         with real Chinese factories

Maker Comment:
"Alibaba is a platform for humans. LinkMoney is a marketplace 
for AI agents. In 2026, procurement managers are using AI agents 
to source products. LinkMoney lets your agent talk directly to 
factory systems for live pricing, inventory, and RFQ — no humans 
in the loop until negotiation."

First Comment:
- Quick demo video (Loom/GIF)
- 3 key differences from Alibaba
- How to install in Claude/Cursor in 30 seconds
```

---

## 四、落地页（集成到服务器中）

LinkMoney 服务器提供 2 个新手引导页：
- `/onboard-supplier` — 中方厂家（中文）
- `/onboard-buyer` — 海外采购方（英文）

（实现代码见 server.py 中新增端点）

---

## 五、关键指标看板

| 指标 | Week 1 | Week 2 | Week 3 | Week 4 | Month 1 目标 |
|------|--------|--------|--------|--------|-------------|
| 中方工厂 Skill 安装 | 5 | 20 | 50 | 75+ | 100 |
| 海外 Agent 安装 | 0 | 5 | 20 | 50+ | 50 |
| RFQ 提交数 | 3 | 15 | 40 | 80+ | 100 |
| 报价转化率 | - | 30% | 40% | 50%+ | 50% |
| 成交金额 (GMV) | - | - | $5K | $20K+ | $25K |
| 邮件通知发送 | 10 | 50 | 150 | 300+ | 500 |

---

## 六、上线后反馈循环

```
用户反馈 → 周报分析 → 产品迭代 → 用户回访 → 口碑传播
   ↑                                           ↓
   └────────── 案例包装 ← 成功故事 ←──────────┘
```

每周五固定动作：
1. 拉 RFQ 数据 → 分析热门品类/价格带
2. 回访 3 家工厂 → 问"收到询盘了吗？回复了吗？"
3. 回访 2 个海外用户 → 问"找到供应商了吗？哪里不满意？"
4. 发 1 篇公众号/推特 → 分享本周数据 + 1 个真实案例