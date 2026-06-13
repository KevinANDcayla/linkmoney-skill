# LinkMoney - 阿里云百炼 MCP 注册指南

## 阿里云百炼是什么
阿里云百炼（bailian.cn）— 阿里云 LLM 应用平台，支持 MCP 工具注册。国内企业可直接在百炼平台搜索安装 LinkMoney。

## 注册地址
https://bailian.cn（百炼控制台 → MCP 工具市场）

## 步骤

### Step 1: 登录阿里云百炼
1. 使用阿里云账号登录 https://bailian.cn
2. 完成企业实名认证（如未认证）

### Step 2: 注册 MCP 工具

在"我的应用"或"MCP 工具"页面，点击"添加自定义 MCP"：

**工具名称**: linkmoney（连钱）
**描述（中文）**: 
让 AI Agent 主动找上中国供应商的 B2B 贸易链接器。支持实时价格查询、库存查询、RFQ 提交，覆盖紧固件/电子/包装/五金/注塑/机械/纺织等 7 大品类。

**描述（English）**: 
LinkMoney — AI-native B2B marketplace connecting AI agents with verified Chinese factories for live pricing, inventory, and automated RFQ.

**MCP 端点（Server URL）**: 
https://linkmoney.online/mcp

**Manifest URL**: 
https://linkmoney.online/mcp/manifest.json

**工具类型**: 商业/采购/供应链

**标签**: B2B, 中国制造, 采购, 供应链, AI, Agent, 外贸, 出口

**Icon/Logo**: 
https://linkmoney.online/favicon.ico

### Step 3: 验证 MCP 服务

百炼会验证 manifest.json 是否可访问：
- 确保 https://linkmoney.online/mcp/manifest.json 返回 200
- 确保包含有效的 tools 数组

### Step 4: 提交审核

填写完信息后提交审核。通常 1-3 个工作日。

## 审核通过后

用户可在百炼平台：
1. 搜索"LinkMoney"或"连钱"
2. 一键添加到自己的 AI Agent
3. 调用 find_china_supplier 等 tool

## 国内用户价值

**痛点对齐**：
- 国内中小企业主用通义千问/钉钉 AI/微信 AI → 通过百炼接入 LinkMoney
- 直接在中文 AI 助手中调用"找中国供应商"
- 无需翻墙，直接访问国内节点

**LinkMoney 对百炼的价值**：
- 丰富百炼的工具生态（供应链/采购类）
- 吸引有外贸需求的企业用户
- 体现平台开放性（接入外部 B2B 服务）

## 联系方式
agent@linkmoney.online
