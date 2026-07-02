# LinkMoney 安全架构

> **本文档面向开发者/运维/合规审计**，不面向 Agent。Agent 请读 [SKILL.md](../SKILL.md)。

## 1. 数据流向告知

**用户需明确知晓以下数据流向，其中标注 🔴 的为高风险操作（数据发送至外部第三方）**：

| 操作 | 数据流向 | 风险等级 | 说明 |
|------|---------|---------|------|
| `find_china_supplier` / `get_pricing` / `get_inventory` 查询 | LinkMoney 中心化缓存 → 用户 | 🟢 低 | 数据不流出 LinkMoney 平台 |
| verified 工厂实时查询（用户明确要求时） | LinkMoney → 厂家 MCP 端点 | 🟡 中 | 仅 verified 工厂支持；用户的产品规格、数量等查询参数发送至对应厂家服务器 |
| `submit_rfq` | 用户 → LinkMoney → 指定供应商 | 🟡 中 | **用户提交 RFQ 前需通过 `confirm_data_sharing=true` 参数明确确认数据将发送给指定供应商**。供应商身份在 RFQ 提交前已明确展示。支持 `anonymize_contact=true` 匿名化联系方式 |
| `register_supplier` | 厂家 → LinkMoney 中央库 | 🟡 中 | 厂家提交的联系方式、产品数据存储在 LinkMoney 中央库，对海外采购方公开（联系方式仅在主动查询时返回） |
| LLM 辅助功能 | 用户文本 → 火山引擎 ARK API (ark.cn-beijing.volces.com) | 🟢 低 | 国内云服务，数据不出境。未配置 `ARK_API_KEY` 时自动降级为规则引擎。详见 [INTERNAL_ARCHITECTURE.md](./INTERNAL_ARCHITECTURE.md) |
| 邮件通知 | LinkMoney → 供应商/采购方邮箱 | 🟡 中 | RFQ 提交和报价时，系统自动发送邮件通知对方，邮件含 RFQ 摘要 |

### 用户控制权
- 用户可在提交 RFQ 前查看完整询价内容，并明确选择目标供应商
- 用户可选择不使用 LLM 功能（不配置 API Key 或设置 `LLM_ENABLED=false`）
- 用户可请求删除自己的 RFQ 记录和供应商档案（联系 support@linkmoney.online）

---

## 2. 二次确认与数据匿名化机制

### submit_rfq 二次确认
- 用户提交 RFQ 时必须传入 `confirm_data_sharing=true` 参数，明确确认询价信息将发送给指定供应商
- 未传入 `confirm_data_sharing=true` 时，API 返回 400 错误，提示用户确认数据共享
- 这确保用户在提交前充分知晓数据流向，防止误操作导致数据外泄

### 联系方式匿名化
- 用户提交 RFQ 时可传入 `anonymize_contact=true` 参数，启用联系方式匿名化
- 启用后，供应商收到的邮件中买家联系方式替换为 LinkMoney 中转邮箱（`relay@linkmoney.online`）
- 供应商回复邮件时，LinkMoney 平台自动将回复转发给买家真实邮箱
- 这保护了买家隐私，供应商无法直接获取买家真实邮箱地址

### 实现位置
- `submit_rfq` 接口增加 `confirm_data_sharing: bool = false` 参数（必传 true 才能提交）
- `submit_rfq` 接口增加 `anonymize_contact: bool = false` 参数（可选，启用匿名化）
- 邮件发送时根据 `anonymize_contact` 参数决定是否替换收件人地址

---

## 3. 架构安全措施

详细架构安全措施（API 接口定义、禁止动态代码执行、证书校验、架构隔离、缓存策略、manifest.json 验证、白名单机制、熔断机制）请见 [INTERNAL_ARCHITECTURE.md](./INTERNAL_ARCHITECTURE.md)。

---

## 4. 厂家 MCP 端点准入审核

详细准入审核机制请见 [INTERNAL_ARCHITECTURE.md](./INTERNAL_ARCHITECTURE.md#4-厂家-mcp-端点准入审核机制)。
