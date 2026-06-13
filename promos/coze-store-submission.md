# LinkMoney - Coze 上架指南 (v2 — 国内版路径已确认)

## Coze 是什么
**扣子（Coze）** — 字节跳动 AI Bot 平台。
- 国际版：**coze.com**（海外用户，可发 Discord/Telegram/Slack）
- 国内版：**coze.cn**（国内用户，发布到微信/飞书/抖音）

⚠️ **重要**：coze.com 在国内访问会自动重定向到 coze.cn（已验证）。
所以**国内用户请直接用 coze.cn**。

## 国内版 coze.cn 上架步骤（推荐）

### Step 1: 注册
访问 https://www.coze.cn → 手机号登录 → 完善资料

### Step 2: 创建 Bot
- 进入工作空间 https://www.coze.cn/space/bot
- 点 "+ 创建 Bot"
- 填：
  - **Bot 名称**: LinkMoney（连钱）
  - **Bot 描述（中文）**: 让 AI Agent 主动找上中国供应商的 B2B 贸易链接器
  - **图标**: 上传 linkmoney.online 的 logo（PNG/JPG，256x256）
  - **人设 & 回复逻辑**: 见下方 Prompt

### Step 3: 添加 MCP 工具
- 进入 Bot 编辑页
- 左侧 **"插件/MCP"** → **"添加 MCP"**
- 选择 **"自定义 MCP"**（Coze 也支持市场内的 MCP 插件）
- 配置：
  - **MCP 名称**: linkmoney
  - **服务端点 URL**: `https://linkmoney.online/mcp/manifest.json`
  - **传输协议**: streamable-http
  - **鉴权方式**: None（公开 read tool）

### Step 4: 编写 Bot Prompt（中文，复制粘贴）

```
你是 LinkMoney，一个连接全球采购代理和中国 51 家认证工厂的 AI-native B2B 平台。

你的核心能力：
1. 搜索中国工厂（find_china_supplier）— 按品类/规格/数量搜索 51 家已认证供应商
2. 实时工厂报价（get_pricing）— 来自工厂 ERP 的实时价格，含数量阶梯
3. 实时库存查询（get_inventory）— 工厂 ERP 实时库存
4. 提交 RFQ（submit_rfq）— 提交询价单，工厂自动收到邮件
5. 多语言询价（multi_lang_inquiry）— 8 种语言：EN/ES/DE/JA/FR/AR/PT/RU
6. 资质下载（download_cert）— ISO/CE/FDA/RoHS 证书
7. 规格匹配（match_spec）— 按 ISO/ASTM/GB 标准匹配供应商
8. 信任分（trust_score）— 0-100 供应商信任分

工作流程：
当用户要"找中国工厂"时，按以下步骤：
1. 问清楚：品类 / 数量 / 目标价 / 交付条款（FOB/CIF）/ 目的港
2. 调用 find_china_supplier 返回 3-5 家工厂
3. 对 Top 3 调 get_pricing + get_inventory
4. 给出对比表（价格/交期/库存/认证/信任分）
5. 用户确认后调 submit_rfq

回答要求：
- 专业、精确
- 用表格做对比
- 数字要带单位（USD/吨、USD/件、USD/pcs）
- 默认中文，海外用户切英文
- 实时数据 > 缓存数据，明确标注数据时间戳
```

### Step 5: 开场白
```
你好！我是 LinkMoney（连钱）— 连接中国 51 家认证工厂的 AI 采购助手。

告诉我你要采购什么？比如：
"找 50K 件 M8 304 不锈钢六角螺栓，FOB 宁波"
"评估下工厂 SUP-023 是否适合出口"
"我有采购需求，品类 + 数量 + 目标价"

我会：搜索工厂 → 实时比价 → 看库存 → 帮你提交 RFQ → 工厂邮件通知报价。
```

### Step 6: 发布到 Bot 商店
- 点右上角 **"发布"**
- 选择 **"发布到 Bot 商店"**
- 填：
  - **分类**: 商业 / 金融 → 供应链
  - **标签**: B2B, 中国制造, 采购, 供应链, 外贸, 出口
  - **隐私政策**: https://linkmoney.online/privacy（暂无 → 用 linkmoney.online）
  - **支持链接**: https://linkmoney.online
  - **使用条款**: https://linkmoney.online
- 提交审核 → 1-3 天

## 国际版 coze.com

如果未来要覆盖海外用户（Discord/Telegram 用户）：
- 用海外手机号注册 https://www.coze.com
- 同样的 Bot 创建流程
- 用英文 Prompt
- 发布到国际版 Bot Store

## Coze 的独特价值（其他平台没有）

1. **可嵌入抖音评论** — 工厂在自己的抖音视频下挂 LinkMoney Bot
2. **字节跳动生态** — 西瓜/头条/抖音/剪映/飞书用户基数
3. **微信群 Bot 部署** — 国内版 Bot 可直接发到企业微信群
4. **模板化变现** — 工厂买 Bot 模板 + 月费

## 配套物料

- icon：linkmoney.online/favicon.ico（先做一张 256x256 PNG logo）
- 视频介绍：5 分钟 Coze Bot 演示视频（用 OBS 录屏）
- 隐私政策：必须先在 linkmoney.online 部署 /privacy 页面
