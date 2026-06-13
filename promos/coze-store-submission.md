# LinkMoney - Coze 商店上架指南

## Coze 是什么
Coze（扣子，coze.com）— 字节跳动 AI Bot 平台，支持 Bot Store 分发。国内用户量最大的 AI Agent 平台之一。

## 上架地址
https://coze.com/store（或国内版 https://coze.cn）

## Coze Bot Store vs Coze 国际版

**Coze 国际版（coze.com）**：
- 面向全球用户，Bot 可发布到 Discord/Telegram/Slack/Web
- 提交后在商店可见，全球用户可添加

**Coze 国内版（coze.cn）**：
- 面向国内用户，Bot 发布到微信/飞书/钉钉
- 适合国内工厂主使用

## 上架步骤（国际版）

### Step 1: 创建 Coze Bot

1. 登录 https://coze.com
2. 点击 "Create Bot" → 填写：
   - **Bot Name**: LinkMoney
   - **Description**: AI-native B2B marketplace connecting overseas agents with Chinese factories
   - **Icon**: 上传 linkmoney.online 的 logo
   - **Model**: GPT-4o 或 Claude 3.5

### Step 2: 配置 MCP 工具

在 Bot 的 "Tools" 部分，添加 MCP tool：
- **Tool Server**: Custom
- **Endpoint**: https://linkmoney.online/mcp
- **Auth Type**: API Key
- **API Key**: 申请一个 LinkMoney API Key（联系 agent@linkmoney.online）

### Step 3: 编写 Bot Instructions（英文 Prompt）

```
You are LinkMoney, an AI-native B2B marketplace connecting overseas 
procurement agents with verified Chinese factories.

Your capabilities:
- Search Chinese suppliers by category, spec, quantity
- Get real-time factory pricing (live from MCP, not cached)
- Check real-time inventory from factory ERP systems
- Match product specifications
- Download factory certifications (ISO, CE, FDA)
- Generate multi-language inquiry forms
- Submit RFQ with automatic email notification

When a user asks about sourcing from China:
1. Ask for: category, quantity, target price, delivery terms
2. Call find_china_supplier to get matches
3. For factories with live MCP: call get_pricing and get_inventory
4. Summarize comparisons
5. If user confirms: call submit_rfq

Always be professional, precise, and focus on helping the user 
source the best quality at the best price.
```

### Step 4: 配置开场白

**Opening Message (EN)**:
```
Hi! I'm LinkMoney. Tell me what you need to source from China — 
I'll find verified factories with real-time pricing and help you submit an RFQ.

Example: "Find M8 304 stainless steel hex bolts, 50K pcs, FOB Ningbo"
```

### Step 5: 发布到商店

点击 "Publish" → 选择发布到 "Bot Store" → 填写：
- **Category**: Business & Finance / Supply Chain
- **Tags**: B2B, China, Sourcing, Procurement, AI, Manufacturing
- **Privacy Policy URL**: https://linkmoney.online/privacy
- **Support URL**: https://linkmoney.online

等待审核（通常 1-3 天）

## 上架步骤（国内版 coze.cn）

国内版需要企业认证。上架流程类似，但：
- 使用中文 Bot 名称：连钱 / LinkMoney
- 使用中文 Prompt
- Bot 可发布到微信公众号/飞书

## Coze 商店的价值

- **字节跳动生态**：抖音/头条/西瓜视频用户基数
- **Bot 可嵌入抖音评论**：工厂可在自己的抖音视频下嵌入 LinkMoney Bot
- **出海商家覆盖**：Coze 国际版覆盖出海电商商家（亚马逊/Shopify 卖家）

## 联系方式
agent@linkmoney.online
