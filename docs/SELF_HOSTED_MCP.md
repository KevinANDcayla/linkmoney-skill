# LinkMoney 自部署 MCP Server（高级选项）

> **本文档面向大型工厂的技术团队**，中小工厂请使用默认托管模式（注册即自动获得 MCP endpoint，无需读本文档）。

## 适用场景

大型工厂如需自主控制数据（直连 ERP、数据不出企业），可自部署 MCP Server。**自部署端点必须通过 LinkMoney 安全审核后才能接入**。

## 准入要求（必须全部满足）

- ✅ HTTPS 强制 + TLS 1.2+ 证书有效
- ✅ API Key 身份认证
- ✅ 响应符合 LinkMoney JSON Schema 定义
- ✅ 企业资质已验证（营业执照 + ISO 认证）

## 部署步骤

```bash
# Step 1: 克隆模板
cp -r supplier_mcp_template/ my-supplier-mcp/

# Step 2: 填写产品数据到 data.json（或对接 ERP 数据库）

# Step 3: 启动服务（必须配置 HTTPS + 有效证书）
cd my-supplier-mcp/
pip install -r requirements.txt
python server.py  # 启动在 https://0.0.0.0:9001
```

## 接入 LinkMoney

部署并通过审核后，调用 LinkMoney API 注册端点：

```bash
curl -X POST http://118.196.34.217:8765/suppliers/YOUR_SUPPLIER_ID/link_mcp \
  -H "Content-Type: application/json" \
  -d '{
    "mcp_endpoint": "https://your-factory.com/mcp",
    "verification_token": "YOUR_VERIFICATION_TOKEN"
  }'
```

## 安全说明

- LinkMoney 后端代理调用厂家 MCP，Agent 不直接访问外部端点
- 所有外部响应经强类型验证和清洗后才返回给 Agent
- 端点每 90 天复审，不合规将被下线
- 厂家 MCP 离线时，LinkMoney 自动 fallback 到缓存数据

## 托管 MCP endpoint 格式（默认方式，注册即获得）

```
http://118.196.34.217:8765/mcp/supplier/{supplier_id}/products
http://118.196.34.217:8765/mcp/supplier/{supplier_id}/pricing?sku=xxx&quantity=1000
http://118.196.34.217:8765/mcp/supplier/{supplier_id}/inventory?sku=xxx
http://118.196.34.217:8765/mcp/supplier/{supplier_id}/manifest.json
```

工厂不需要：服务器、域名、Docker、GitHub 仓库、curl 命令。
