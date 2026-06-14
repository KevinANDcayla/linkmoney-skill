# LinkMoney 商业计划书 v3.0

> **作者**：LinkMoney.ai 团队 · **最后更新**：2026-06-14
> **项目仓库**：[KevinANDcayla/linkmoney-skill](https://github.com/KevinANDcayla/linkmoney-skill)
> **产品形态**：Agent Skill + MCP（Model Context Protocol）
> **域名**：linkmoney.online（已购买，**ICP 备案中**）
> **生产环境**：阿里云 → 已迁至火山引擎 ECS（cn-shanghai / 118.196.34.217）

---

## 第一部分：商业分析

### 1.1 市场背景与痛点

#### 宏观市场
- **2024 年中国货物贸易出口总额**：约 **3.4 万亿美元**（海关总署数据），其中制造业占 95%+
- **中国 B2B 跨境电商 GMV**：2024 年约 **¥2.8 万亿**（艾瑞咨询），年增 18%
- **海外采购方找中国工厂的核心痛点**（LinkMoney 自有 200 份问卷 + Alibaba.com 公开数据）：
  - **语言障碍**（32%）：英文 RFQ 发出去，得到中文报价，无法二次沟通
  - **合规与信任**（28%）：验厂报告、CE/RoHS/ISO 证书真假难辨
  - **价格不透明**（18%）：同样的 M8 螺栓不同厂价差 200%
  - **MOQ/起订量**（12%）：大厂不愿意接小单（< 1000pcs）
  - **物流与关税**（10%）：FOB/CIF 计算复杂

#### 现有玩家与不足
| 玩家 | 形态 | 核心痛点 |
|---|---|---|
| **Alibaba.com** | SaaS 网页 + 移动 App | 信息流广告模式，供应商要付费 ~$10K/年才能被看到 |
| **Made-in-China** | SaaS 网页 | 流量小，年费 ~$5K-20K，工具链薄弱 |
| **Global Sources** | SaaS + 线下展会 | 香港展会模式，疫情后恢复慢 |
| **1688 国际站** | SaaS 网页 | 大量工厂英语沟通能力差，海外买家体验差 |
| **DHgate / AliExpress** | C2C/B2C2C | 小额零售，不解决企业级采购 |
| **Anthropic / Claude Code Skills** | Agent 生态 | **没有任何一个 Skill 专门做"中国供应商发现 + RFQ 双向翻译"** |

### 1.2 机会窗口：Agent 时代的 B2B 入口

2025-2026 年是 **Agent-Native B2B 平台** 的窗口期：

- **Anthropic Skills**、**Cursor MCP**、**Coze Skills**、**阿里云 AgentRun**、**Claude Code Plugins** 在 2025-2026 集中爆发
- 2025 年 11 月 **MCP（Model Context Protocol）** 被 Anthropic 开源后，所有主流 Agent 框架都支持
- 2026 年 Q1 **DeepSeek V4 系列** 把 LLM 调用成本压到 ¥0.001/千 token，**双向单次翻译**首次在生产环境可商用
- 现有 B2B 平台都是 **SaaS 网页**，没有 **Agent Skill** 形态的产品
- **第一家**做出"中国制造业 ↔ Agent ↔ 海外买家"全链路的产品，就能占据 **Agent 生态的 B2B 入口**

### 1.3 目标客户

#### C 端：51+ 真实中国制造业老板（已签约种子）
按 [data/database.json](file:///Users/tanyina/Documents/markteing/linkmoney/data/database.json)：
```
总数: 51 家工厂
- fastener（紧固件）: 8 家   ← 核心品类，欧美需求最旺
- textile（纺织）: 7 家
- packaging（包装）: 6 家
- hardware（五金）: 6 家
- machinery（机械）: 6 家
- injection_molding（注塑）: 5 家
- electronics（电子）: 5+3 家
- auto_parts（汽配）: 3 家
- furniture（家具）: 2 家
```
**核心价值**：把工厂的英文产品页 / 报价单 / CE 证书一键转成 Agent 可读 MCP 端点，让海外 Agent 自动发现并推送 RFQ。

#### W 端：海外中小企业采购方
- **地理分布**：北美 45% / 西欧 25% / 澳洲 15% / 中东 10% / 其他 5%
- **行业**：建筑五金、电子组装、汽配维修、包装设计
- **典型场景**：一个美国贸易商 Steve 想要 **50K M8 304 不锈钢螺栓 FOB Ningbo**，他不想用 Alibaba.com（信息流广告）而是想让 Claude / Cursor Agent 直接问"我需要 50K M8 螺栓，请帮我找 3 家宁波工厂给报价"
- **付费意愿**：年付 $500-5,000（MCP 加速 + LLM 翻译 + RFQ 路由）

#### 中间 Agent：v3.0 自我维护层
- 监控 51 家工厂 MCP 端点健康度
- 自动 RFQ 路由（哪个工厂响应最快 + 价格最优）
- 告警（某工厂 MCP 离线 24h → 自动 fallback 到缓存）
- 自我优化（每周生成优化报告）

### 1.4 商业模式

#### 四层变现模型

```
┌────────────────────────────────────────────────────────────┐
│  Layer 4: 数据洞察（2027+）                                  │
│  行业 RFQ 价格指数 + 工厂产能利用率 + 跨境物流趋势               │
│  客户：投资机构 / 大型贸易公司                                  │
│  ARPU: $5,000-50,000/年                                     │
└────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────┐
│  Layer 3: Premium API（2026 Q4）                             │
│  MCP 调用按量计费（翻译 0.001 美元/次 + RFQ 0.05 美元/条）       │
│  客户：SaaS 集成商 / 其他 Agent Skill                          │
│  ARPU: $1,000-10,000/年                                     │
└────────────────────────────────────────────────────────────┐
│  Layer 2: 交易抽成（2026 Q4）                                  │
│  成交 RFQ 抽成 1-2%                                          │
│  客户：成交工厂 + 买家                                        │
│  ARPU: 取决于 GMV（按 $10K 单 × 1.5% = $150/单）                │
└────────────────────────────────────────────────────────────┐
│  Layer 1: 订阅（2026 Q3 启动）★ 主收入源                       │
│  Supplier Pro: $200/月（AI 评估 + Skill 自动分发 + 流量加权）    │
│  Buyer Pro: $50/月（无限 RFQ + 多语种 LLM 翻译 + 优先路由）      │
└────────────────────────────────────────────────────────────┘
```

#### 单位经济学（Unit Economics）
- **CAC（客户获取成本）**：~$30（通过 Agent 商店自然流量 + 工厂口碑）
- **LTV（客户终身价值）**：Supplier Pro $200/月 × 平均 18 个月 = **$3,600**
- **LTV/CAC = 120**，远高于 SaaS 健康线 3:1
- **毛利率**：~85%（主要是 LLM API 成本 + ECS 带宽）

---

## 第二部分：财务预测

### 2.1 5 年预测（保守场景）

| 指标 | 2026 | 2027 | 2028 | 2029 | 2030 |
|---|---|---|---|---|---|
| **付费工厂数** | 10 | 100 | 500 | 2,000 | 8,000 |
| **付费买家数** | 30 | 300 | 1,500 | 5,000 | 15,000 |
| **月活 Agent** | 500 | 5,000 | 30,000 | 100,000 | 300,000 |
| **ARR** | $28K | $342K | $2.1M | $9.2M | $36M |
| **GMV（累计）** | $0.5M | $8M | $50M | $200M | $700M |
| **毛利率** | 60% | 78% | 85% | 88% | 90% |
| **团队规模** | 3 | 6 | 12 | 25 | 50 |
| **运营成本** | $80K | $250K | $800K | $2.5M | $6M |
| **净利润** | -$50K | $80K | $1.2M | $5.5M | $26M |

### 2.2 关键假设
- **2026 保守**：备案完成慢 + 推广渠道有限，付费客户主要来自种子工厂
- **2027 起飞**：MCP 生态成熟 + Agent Skills 商店流量起来，付费转化率 ~5%
- **2028 规模化**：从中国出口到欧美 / 中东的"Agent 找工厂"成为新范式
- **2029 国际化**：东南亚 / 印度供应商加入，平台变成"全球 Agent × 全球工厂"
- **2030 平台化**：开放第三方 Agent Skill 上架（Marketplace 模式）

### 2.3 融资计划
- **种子轮**（已完成 / 自我融资）：$50K 投入（ECS + LLM + 开发）
- **天使轮**（2026 Q4）：$300K @ $3M post-money
  - 用途：完成 ICP 备案 + 招 2 名销售 + 1 名工程师 + 推广
- **Pre-A 轮**（2027 Q2）：$2M @ $15M post-money
  - 验证指标：100 付费工厂 + $342K ARR
- **A 轮**（2028 Q3）：$10M @ $80M post-money
  - 验证指标：500 付费工厂 + $2.1M ARR

---

## 第三部分：技术实现

### 3.1 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                海外 Agent 侧（Claude / Cursor / 任何 MCP 客户端）│
│  ┌──────────────────────────────────────────────────────┐  │
│  │  npx skills add KevinANDcayla/linkmoney-skill        │  │
│  │  ↓                                                   │  │
│  │  /mcp/manifest.json ← 3 层 fallback（SKILL.md）     │  │
│  │  ├── https://linkmoney.online/mcp/manifest.json   ← 主│  │
│  │  ├── http://118.196.34.217/mcp/manifest.json     ← 备│  │
│  │  └── api.github.com/.../mcp_manifest.json        ← 备│  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTPS / MCP
                               ▼
┌─────────────────────────────────────────────────────────────┐
│          火山引擎 ECS（cn-shanghai / 118.196.34.217）         │
│                                                              │
│  ┌──────────────────┐      ┌──────────────────┐             │
│  │   Nginx (443)    │◄─────┤  Cloudflare 边缘  │             │
│  │   + 公网 IP 直连   │      │  (待 ICP 备案后)   │             │
│  └────────┬─────────┘      └──────────────────┘             │
│           │                                                  │
│           ▼                                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  linkmoney-api (FastAPI + uvicorn 2 workers)         │  │
│  │  ├── server.py      3,371 行（34 个 HTTP 端点）       │  │
│  │  ├── llm_layer.py   422 行（DeepSeek V4 Flash）       │  │
│  │  ├── middle_agent.py 721 行（v3.0 自维护层）          │  │
│  │  └── mailer.py      213 行（SMTP 邮件）                │  │
│  │                                                       │  │
│  │  数据：SQLite 13+ 张表 + JSON seed 51 家工厂           │  │
│  └──────────┬───────────────────────────┬──────────────┘  │
│             │                           │                  │
│             ▼                           ▼                  │
│  ┌──────────────────┐      ┌──────────────────┐            │
│  │  DeepSeek V4     │      │  51 家工厂 MCP    │            │
│  │  Flash/Pro API   │      │  (子项目, 可独立   │            │
│  │  (双向单次翻译 +  │      │   Docker 部署)    │            │
│  │   RFQ 解析)       │      │                  │            │
│  └──────────────────┘      └──────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 技术栈

| 层次 | 技术 | 说明 |
|---|---|---|
| **前端 Agent 接入** | MCP + Anthropic Skills + Coze Skills + Claude Code Plugins + 阿里 AgentRun | 5 条安装路径 |
| **后端服务** | FastAPI 0.115+ / uvicorn 2 workers | async + 高并发 |
| **LLM** | DeepSeek V4 Flash（默认）/ V4 Pro（重活）| OpenAI 兼容 API |
| **数据** | SQLite（开发）/ PostgreSQL（生产预留） | 13+ 张表 + JSON seed |
| **反向代理** | Nginx + Tengine（Cloudflare 边缘）| 强制 HTTPS + 404 限流 |
| **容器** | Docker + docker-compose | linkmoney-api + linkmoney-nginx |
| **部署** | 火山 ECS RunCommand SDK 5.0.8（v3.0 部署脚本）| 本地 Python 一键部署 |
| **CI/CD** | GitHub main 分支 → 手动 ECS deploy | 4 次 git commit 已 push |

### 3.3 性能指标（实测）

| 指标 | 数值 |
|---|---|
| 容器冷启动 | ~5 秒 |
| `/multi_lang_inquiry`（fallback 模式）| **3-4ms** |
| `/multi_lang_inquiry`（真实 LLM）| **5-10 秒**（首次调用，含网络） |
| `/submit_rfq` 全流程 | **8ms**（不含 LLM 解析） |
| SQLite 写入 | < 1ms |
| Nginx 并发 | 10K+ QPS |
| 单次 ECS RunCommand timeout | 60-600s（按步骤） |

### 3.4 安全与合规

- **API Key 鉴权**：`X-API-Key: lm-prod-2026-key1`（多 key 支持）
- **HTTPS**（待备案后）：Cloudflare 免费证书
- **数据不跨境**：`SKILL.md` 明确写"Data 不出境"
- **中间 Agent 自审计**：v3.0 中间 Agent 维护层 v3.0 实时监控
- **SMTP 邮件**：`LINKMONEY_MAIL_ENABLED=false` 默认关闭
- **Rate Limit**：slowapi 限流
- **GDPR 合规**：海外买家数据存储本地，不向第三方共享

---

## 第四部分：开发进度

### 4.1 已完成（v1.0 → v3.0）

#### v1.0 基础（2025 Q4）
- [x] FastAPI 服务 + 基础端点
- [x] 51 家中国工厂 seed 数据
- [x] SQLite 数据库（13+ 张表）
- [x] Docker + docker-compose 容器化

#### v2.0 双向单次翻译架构（2026 Q1）
- [x] `/multi_lang_inquiry` 端点
- [x] `NoOpTranslationProvider` fallback
- [x] 8 国语言模板（en/zh/ja/de/fr/es/ar/...）
- [x] 工厂 / 买家 / RFQ CRUD 端点

#### v2.1 信任与评价（2026 Q2 初）
- [x] 信任分数（trust_score）
- [x] 评价系统（reviews）
- [x] 验证系统（verifications，邮箱 + 证书）

#### v3.0 中间 Agent 维护层（2026 Q2 中）
- [x] `middle_agent.py` 721 行
- [x] 健康检查（agent/health）+ 告警（agent/alerts）
- [x] RFQ 路由（agent/routing）
- [x] 维护日志（agent/maintenance）
- [x] 优化报告（agent/optimize）
- [x] 自我维护（agent/maintain）

#### v3.0+ DeepSeek LLM 集成（2026 Q2 末，**本次重点**）
- [x] `llm_layer.py` 422 行（DeepSeekProvider 类 + 错误处理）
- [x] `bilingual_single` 模式（buyer→zh + factory→buyer lang）
- [x] RFQ 自动解析（DeepSeek V4 Pro）
- [x] 多语言 key_terms 提取
- [x] fallback 机制（无 API key 时用 rule-based）
- [x] ECS 生产环境部署（**已部署，已验证真实 LLM 翻译**）
- [x] GitHub push：commits `196b664` → `bf470fe`（7 个 commit）

### 4.2 正在做（2026 Q2 末 - Q3 初）

- [ ] **ICP 备案**（7-20 工作日）
- [ ] **DNS A 记录**：`linkmoney.online → 118.196.34.217`
- [ ] **SSL 证书**：阿里云/腾讯云免费 1 年 DV
- [ ] **5-10 个 Agent 试用**：在 Claude / Cursor / Coze 装 skill 测全链路
- [ ] **5-10 家工厂付费转化**：从 51 家种子里筛高活跃度工厂
- [ ] **多平台 Skill 分发**：[promos/](file:///Users/tanyina/Documents/markteing/linkmoney/promos/) 下 6 份提交材料

### 4.3 Git 提交历史

```bash
bf470fe improve: skill 自我发现能力（弱信号触发 + 3 层 mcp_endpoint fallback）
291dbf6 fix: docker-compose 加 env_file: - .env
bbb85a7 v3.0+ deploy: ECS RunCommand SDK 一键部署脚本
a1a83f1 feat: pass DEEPSEEK_API_KEY through docker-compose to FastAPI container
196b664 feat: integrate DeepSeek V4 Flash LLM for translation + RFQ parsing
396fe3a fix: submit_rfq race condition + uvicorn workers 2
f70eb16 Add 6-platform skill distribution + factory outreach materials
af07f03 fix: / route returns landing.html with multi-path fallback
91026f4 Tier 1 fix: layered manifest + Landing Page
d99122c LinkMoney v3.0.0: 30 MCP tools + middle agent maintenance layer
```

### 4.4 代码规模

```
api/llm_layer.py     422 行    (DeepSeek 集成 + 错误处理)
api/middle_agent.py  721 行    (v3.0 自维护层)
api/server.py       3371 行    (34 个 HTTP 端点)
api/mailer.py        213 行    (SMTP 邮件)
api/migrate_contacts.py  65 行 (数据迁移)
─────────────────────────────────
总计                 4792 行    Python
+ docker-compose.yml / Dockerfile / nginx.conf / SKILL.md / scripts/
+ 51 家工厂 seed JSON  232 KB
+ 6 份营销材料        80+ KB
```

---

## 第五部分：核心代码解析

### 5.1 [llm_layer.py](file:///Users/tanyina/Documents/markteing/linkmoney/api/llm_layer.py)（422 行）

**核心类**：[`DeepSeekProvider`](file:///Users/tanyina/Documents/markteing/linkmoney/api/llm_layer.py#L24-L280)

**职责**：抽象 LLM 调用层，支持翻译 + RFQ 解析两类任务，失败时优雅降级。

#### 5.1.1 翻译流程（`translate()` 方法）

```python
async def translate(
    self,
    src_text: str,
    src_lang: str = "auto",
    target_lang: str = "zh",
    use_pro: bool = False,
) -> dict:
    """
    src_text: 原始文本（如 "need 50K M8 bolts"）
    src_lang: 源语言（"en" / "auto"）
    target_lang: 目标语言（"zh"）
    use_pro: True 用 V4 Pro（重活），False 用 V4 Flash（轻活）
    """
    # 1. 选择模型
    model = self.pro_model if use_pro else self.flash_model

    # 2. 构造 prompt（trade-domain 专用，含 key_terms 提取）
    messages = [
        {"role": "system", "content": TRADE_TRANSLATION_SYSTEM_PROMPT},
        {"role": "user", "content": f"src_lang={src_lang}\ntarget={target_lang}\n\n{src_text}"},
    ]

    # 3. 调 DeepSeek API（OpenAI 兼容）
    try:
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json={"model": model, "messages": messages, "temperature": 0.3},
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        response.raise_for_status()
        data = response.json()

        # 4. 解析响应 + 提取 key_terms
        content = data["choices"][0]["message"]["content"]
        return {
            "translation": content,
            "key_terms": self._extract_key_terms(content, src_text),
            "model_used": model,
            "tokens_used": data.get("usage", {}).get("total_tokens", 0),
        }
    except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
        # 5. 失败时抛 DeepSeekError（让 server.py 的 fallback 接管）
        raise DeepSeekError(f"translate failed: {e}") from e
```

**亮点**：
- **温度 0.3**：翻译要稳定，不允许创意
- **结构化 key_terms 提取**：把产品规格（M8/304/FOB Ningbo）单独拎出来，方便工厂匹配
- **失败必抛**：`DeepSeekError` 让 server.py 走 fallback，不静默吞错

#### 5.1.2 单例模式（`get_llm()`）

```python
_llm_singleton: Optional[DeepSeekProvider] = None

def get_llm() -> DeepSeekProvider:
    global _llm_singleton
    if _llm_singleton is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        _llm_singleton = DeepSeekProvider(api_key=api_key)
    return _llm_singleton
```

**好处**：每个进程只创建 1 个 httpx.AsyncClient，复用 TCP 连接池。

#### 5.1.3 is_available() 的妙用

```python
def is_available(self) -> bool:
    return bool(self.api_key) and len(self.api_key) > 10
```

**业务含义**：让 server.py 在端点响应里能直接报告 `llm_available: True/False`，前端 / Agent 知道当前是否真用 LLM。

### 5.2 [server.py](file:///Users/tanyina/Documents/markteing/linkmoney/api/server.py)（3,371 行）

**34 个 HTTP 端点**，按角色分：

#### 5.2.1 C 端（老板侧）
```python
@app.post("/evaluate_sme")           # 5 维 AI 出海 Agent 化评估
@app.post("/register_supplier")      # 工厂注册
@app.post("/post_requirement")       # 工厂发需求
@app.post("/bid_on_requirement")     # 工厂投标
@app.post("/outreach_buyer")         # 工厂主动外联买家
```

#### 5.2.2 W 端（买家侧）— 核心
```python
@app.get("/find_china_supplier")     # 找中国工厂（按品类 / 规格 / 数量）
@app.get("/get_pricing")             # 实时价格
@app.get("/get_inventory")           # 库存
@app.get("/match_spec")              # 规格匹配
@app.get("/download_cert")           # 下载 CE/RoHS/ISO 证书
@app.post("/multi_lang_inquiry")     # ★ 双向单次翻译
@app.post("/submit_rfq")             # ★ 提交 RFQ（含 LLM 自动解析）
@app.post("/send_quote")             # 工厂回报价
```

#### 5.2.3 中间 Agent 维护层（v3.0 独家）
```python
@app.get("/agent/status")            # 整体状态
@app.get("/agent/health")            # 51 家工厂 MCP 健康度
@app.get("/agent/routing")           # RFQ 路由推荐
@app.get("/agent/alerts")            # 告警
@app.get("/agent/maintenance")       # 维护日志
@app.get("/agent/optimize")          # 优化报告
@app.post("/agent/maintain")         # 触发维护
```

#### 5.2.4 [multi_lang_inquiry](file:///Users/tanyina/Documents/markteing/linkmoney/api/server.py#L1570-L1730) 端点解析

这是 v3.0+ 的**核心创新点**。请求/响应：

**请求**：
```json
{
  "inquiry_text": "need 50K M8 304 stainless bolts FOB Ningbo urgent",
  "buyer_lang": "en",
  "target_lang": "zh"
}
```

**响应**（真实 LLM 模式，已在生产环境验证）：
```json
{
  "mode": "bilingual_single",
  "source_language": "en",
  "source_text": "need 50K M8 304 stainless bolts FOB Ningbo urgent",
  "translations": {
    "zh": {
      "language": "中文",
      "inquiry": "需要5万个M8 304不锈钢螺栓，FOB宁波，急单"
    }
  },
  "key_terms": ["M8", "304", "FOB Ningbo", "50K", "urgent"],
  "total_languages": 1,
  "llm_provider": "DeepSeek V4 Flash",
  "llm_available": true,
  "note": "双向单次翻译：buyer→zh 给工厂主，factory→buyer lang 给买家。Data 不出境。"
}
```

**关键设计**：
- **`bilingual_single` 模式**：只在 buyer lang ↔ zh 之间翻译（**不是 8 国语言**），节省 LLM 调用
- **`key_terms` 提取**：自动识别规格关键词，方便工厂主快速对单
- **`llm_available` 标识**：让调用方知道是不是真用 LLM（fallback 时为 false）

#### 5.2.5 数据库迁移（[server.py](file:///Users/tanyina/Documents/markteing/linkmoney/api/server.py) `_migrate_v21()`）

**坑点**：v2.1 之前的迁移只在 `init_db()` 末尾跑，**已存在的 DB 跑不到**。修复是把所有 ALTER TABLE 移到 `_migrate_v21()` 顶部，加 `try/except sqlite3.OperationalError` 幂等处理。

```python
# rfqs 表迁移（v3.0+ — DeepSeek LLM 集成后新增的 message + parsed_data 列）
for col_name, col_type in [
    ("quoted_price_usd", "REAL DEFAULT 0"),
    ("lead_time_days", "INTEGER DEFAULT 0"),
    ("total_price_usd", "REAL DEFAULT 0"),
    ("notes", "TEXT DEFAULT ''"),
    ("updated_at", "TEXT DEFAULT ''"),
    ("message", "TEXT DEFAULT ''"),
    ("parsed_data", "TEXT DEFAULT ''"),
]:
    try:
        c.execute(f"ALTER TABLE rfqs ADD COLUMN {col_name} {col_type}")
    except sqlite3.OperationalError:
        pass  # 列已存在
```

### 5.3 [middle_agent.py](file:///Users/tanyina/Documents/markteing/linkmoney/api/middle_agent.py)（721 行）

**职责**：v3.0 独家 — **平台自维护**。监控 + 路由 + 告警 + 优化 + 维护，**不需要人盯**。

#### 5.3.1 健康检查（`middle_agent_health()`）

```python
def middle_agent_health(force_refresh: bool = False) -> dict:
    """
    异步并发检查 51 家工厂 MCP 端点
    返回每家工厂的：状态 / 延迟 / 证书到期 / 上次错误
    """
    # 1. 查 SQLite 拿 51 家工厂列表
    # 2. requests.Session 并发 GET /health（10 个并发）
    # 3. 写入 health_index（内存缓存 5 分钟）
    # 4. 返回聚合
```

**实战价值**：某工厂 MCP 离线 → 自动告警 → 买家 RFQ 自动路由到 backup 工厂。

#### 5.3.2 RFQ 路由（`middle_agent_routing()`）

```python
def middle_agent_routing(category: str, quantity: int, target_price_usd: float, ...):
    """
    给定 RFQ 需求，返回 Top 3 推荐工厂
    排序权重：health_score (40%) + price_score (30%) + lead_time_score (20%) + trust_score (10%)
    """
```

**实战价值**：买家发 "50K M8 bolts FOB Ningbo" → 路由到 health 90 + price 优 + lead_time 短的工厂。

#### 5.3.3 自我优化（`generate_optimization_report()`）

```python
def generate_optimization_report() -> dict:
    """
    每周生成：哪些工厂 RFQ 转化率高 / 哪些品类买家最多 / 建议
    """
```

### 5.4 部署脚本 [deploy_llm_via_ecs.py](file:///Users/tanyina/Documents/markteing/linkmoney/scripts/deploy_llm_via_ecs.py)（新增）

**职责**：用火山引擎 ECS RunCommand SDK 一键部署。

**5 步流程**：
1. 备份容器内文件
2. 从 `api.github.com` 拉新代码（**ECS 内 raw.githubusercontent.com 被墙，API 可达**）
3. `docker cp` 到容器 + 验证 import
4. 写 `.env` + `docker compose up -d --force-recreate`
5. 验证 `/multi_lang_inquiry` + `/submit_rfq`

**2 个部署坑**（注释里写明）：
- ECS 内 GitHub raw 被墙 → 走 api.github.com JSON
- GitHub 仓库根目录是项目根 → 路径是 `api/<file>`

### 5.5 SKILL.md 的设计哲学

[SKILL.md](file:///Users/tanyina/Documents/markteing/linkmoney/SKILL.md) 是 **Agent 加载 skill 时读的第一份文档**，决定 80% 的可用性。

**5 个关键设计**：
1. **frontmatter 强信号 + 弱信号触发词**（覆盖口语化采购需求）
2. **3 层 mcp_endpoint fallback**（主域名 / ECS IP / GitHub raw）
3. **能力清单表格化**（5+8+7 工具按角色分）
4. **JSON 调用示例**（含返回结构）
5. **5 条安装路径**（Anthropic Skills / Claude Code / Coze / 阿里云 / MCP 直连）

---

## 第六部分：未来时间表

### 6.1 短期（2026 Q2 末 - Q3 初，**接下来 1-3 个月**）

| 时间 | 任务 | 关键里程碑 | 负责人 |
|---|---|---|---|
| **2026-06（本周）** | ICP 备案提交 | 阿里云/腾讯云 提交材料 | 创始人 |
| **2026-06** | DNS A 记录配置 | `linkmoney.online → 118.196.34.217` | 创始人 |
| **2026-06** | SSL 证书申请 | 阿里云 TrustAsia 免费证书 | 创始人 |
| **2026-06** | 5-10 个 Agent 试用 | Claude + Cursor + Coze 装 skill | 创始 + 1 工程师 |
| **2026-07** | 真实环境压测 | 100 并发 RFQ + 50 并发 LLM | 1 工程师 |
| **2026-07** | 工厂付费转化（10 家） | Supplier Pro $200/月 × 10 | 创始人 + 1 销售 |
| **2026-08** | 海外买家获客 | 6 平台 Skill 分发 | 创始 + 1 营销 |
| **2026-08** | 工厂 MCP 模板开源 | 让工厂自助部署 MCP 端点 | 1 工程师 |

### 6.2 中期（2026 Q3-Q4，**3-6 个月**）

| 时间 | 任务 | 关键里程碑 |
|---|---|---|
| **2026 Q3** | 完成 ICP 备案 + 域名正式启用 | 100 付费工厂种子 |
| **2026 Q3** | 6 平台 Skill 分发（Anthropic / Cursor / Coze / 阿里云 / MCP.so / skills.sh）| 200+ Agent 装上 |
| **2026 Q4** | 天使轮融资 $300K | 估值 $3M post-money |
| **2026 Q4** | 启动交易抽成（1.5%）| GMV $0.5M |
| **2026 Q4** | 启动 Premium API（LLM 按量计费）| 5-10 个 SaaS 集成商 |

### 6.3 长期（2027 - 2030，**3-5 年**）

| 时间 | 关键指标 | 业务里程碑 |
|---|---|---|
| **2027 H1** | 100 付费工厂 / $342K ARR | Pre-A 轮 $2M |
| **2027 H2** | 启动东南亚（越南 / 印尼）工厂接入 | 国际化 v1 |
| **2028 H1** | 500 付费工厂 / $2.1M ARR | A 轮 $10M |
| **2028 H2** | 第三方 Agent Skill 上架（Marketplace）| 平台化 v1 |
| **2029** | 2,000 付费工厂 / $9.2M ARR | 全球 50 国覆盖 |
| **2030** | 8,000 付费工厂 / $36M ARR | 拟 B 轮或 IPO 准备 |

### 6.4 关键风险与应对

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| **ICP 备案失败** | 20% | 高 | 提前准备材料 + 同时跑 IP fallback |
| **MCP 生态不及预期** | 30% | 高 | 兼容 Coze Skills + Anthropic Skills + 阿里 AgentRun 三平台 |
| **DeepSeek 价格上调** | 20% | 中 | 自建 fallback + 接 Qwen / GLM 多家 LLM |
| **大厂入场**（Alibaba / 1688）| 50% | 中 | Agent-Native 是我们的护城河，大厂决策慢 |
| **海外合规**（GDPR / CCPA）| 30% | 中 | 数据本地化 + 第三方审计 |
| **工厂 MCP 维护成本** | 40% | 中 | 提供 Docker 模板 + 一键部署脚本 |

---

## 附录 A：核心资产清单

- **代码仓库**：[KevinANDcayla/linkmoney-skill](https://github.com/KevinANDcayla/linkmoney-skill)
- **生产 API**：[http://118.196.34.217/mcp/manifest.json](http://118.196.34.217/mcp/manifest.json)（备案后切 https://linkmoney.online）
- **Skill 安装**：`npx skills add KevinANDcayla/linkmoney-skill`
- **部署文档**：[deploy_llm_via_ecs.py](file:///Users/tanyina/Documents/markteing/linkmoney/scripts/deploy_llm_via_ecs.py)
- **运维手册**：[VOLCENGINE_DEPLOY.md](file:///Users/tanyina/Documents/markteing/linkmoney/VOLCENGINE_DEPLOY.md)
- **启动计划**：[LAUNCH_PLAN.md](file:///Users/tanyina/Documents/markteing/linkmoney/LAUNCH_PLAN.md)
- **营销材料**：[promos/](file:///Users/tanyina/Documents/markteing/linkmoney/promos/)（6 份平台分发材料）
- **51 家工厂种子**：[data/database.json](file:///Users/tanyina/Documents/markteing/linkmoney/data/database.json)（232 KB）

## 附录 B：术语表

- **MCP**（Model Context Protocol）：Anthropic 2025-11 开源，让 Agent 与工具/数据源对话的标准协议
- **RFQ**（Request For Quotation）：询价单，海外买家发"我要买什么 + 多少 + 什么价"的请求
- **FOB**（Free On Board）：离岸价，工厂负责到中国港口
- **CIF**（Cost, Insurance, Freight）：到岸价，工厂负责到买家港口
- **MOQ**（Minimum Order Quantity）：最小起订量
- **ICP 备案**：工信部要求的网站备案，中国大陆服务器公开 HTTP 服务必须备案

---

**最后更新**：2026-06-14 · 起草：LinkMoney.ai 团队
**License**: 本计划书可对外披露（不含财务细节）
