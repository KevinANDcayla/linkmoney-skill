# LinkMoney - MCP.so 收录指南 (v2 — 表单已验证)

## MCP.so 是什么
**mcp.so** — MCP（Model Context Protocol）服务的公共注册表，AI 开发者发现 + 索引 MCP server 的平台。

## 提交 URL（已验证 200 OK）
**https://mcp.so/submit**

## Form 字段（已抓取页面验证）

| 字段 | 类型 | 必填 | 填什么 |
|------|------|------|--------|
| **Type** | radio | ✓ | **MCP Server** |
| **Name** | text | ✓ | `linkmoney` |
| **URL** | text | ✓ | `https://linkmoney.online/mcp/manifest.json` |
| **Server Config** | textarea | ✗ | 见下方 JSON |

## 完整 Server Config（JSON，复制粘贴）

```json
{
  "mcpServers": {
    "linkmoney": {
      "url": "https://linkmoney.online/mcp/manifest.json",
      "transport": "streamable-http"
    }
  }
}
```

## 提交步骤

### Step 1: 打开页面
浏览器访问 https://mcp.so/submit

### Step 2: 填写表单
按上表填 4 个字段。Type 选 "MCP Server"。

### Step 3: 提交
点 "Submit" 按钮。**无需登录** — MCP.so 的 form 是开放的（已确认）。

### Step 4: 等待审核
通常 1-3 个工作日。被收录后会出现在：
- https://mcp.so/servers（按字母排序）
- https://mcp.so/search?q=linkmoney
- 关键词搜索结果

## 收录后的价值

- **SEO 反链**到 linkmoney.online（DAU 高）
- **MCP 开发者**安装 source — install 计数会公开
- **被 Anthropic 内部使用** — mcp.so 已被 Anthropic 在多个文档中引用为 MCP server 的索引源

## 截图准备（建议准备 3 张，但 form 不强制要）

1. https://linkmoney.online/ 全屏
2. https://linkmoney.online/mcp/manifest.json
3. `find_china_supplier` 返回示例（截图或纯文本）
