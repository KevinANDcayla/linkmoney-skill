# LinkMoney 火山云部署方案

> 目标：在火山云上线 LinkMoney 中央数据库 + API，通过 DCDN 全球加速实现国内国际双通访问。

---

## 一、架构总览

```
┌──────────────────────────────────────────────────────────┐
│  海外买家 (US/EU/SEA...)                                  │
│      │                                                    │
│      ▼                                                    │
│  DCDN 全球加速 (linkmoney.online)                         │
│      │                                                    │
│      ▼                                                    │
│  国内厂商 (中国境内)                                       │
│      │                                                    │
│      ▼                                                    │
│  DCDN 全球加速 (linkmoney.online)                         │
│      │                                                    │
│      ├── 静态资源 (缓存) ──→ 就近CDN节点返回               │
│      └── API 请求 (回源) ──→ 火山云 ECS (北京/上海)       │
│                                  │                        │
│                           Docker: linkmoney-api           │
│                                  │                        │
│                           SQLite 数据库                    │
│                           (51家供应商, 140个产品)           │
└──────────────────────────────────────────────────────────┘
```

**核心组件：**

| 组件 | 用途 | 配置 |
|------|------|------|
| ECS 云服务器 | 运行 LinkMoney API | 2C4G, CentOS 7.9 / Ubuntu 22.04 |
| DCDN 全站加速 | 全球加速 + DDoS 防护 | 加速域名 linkmoney.online |
| 火山 DNS | 域名解析 | linkmoney.online → DCDN CNAME |
| Docker Compose | 容器化部署 | linkmoney + nginx |
| Certbot/SSL | HTTPS 证书 | Let's Encrypt 免费证书 |

---

## 二、前置准备

### 2.1 火山云账号

1. 注册 [火山引擎](https://www.volcengine.com/) 账号
2. 完成企业实名认证（国际访问需要）
3. 充值（建议首次充值 500 元）

### 2.2 域名

- 域名：`linkmoney.online`（或你已有的域名）
- DNS 托管在火山 DNS 或 Cloudflare

### 2.3 需要开通的服务

| 服务 | 控制台入口 |
|------|-----------|
| ECS 云服务器 | https://console.volcengine.com/ecs |
| DCDN 全站加速 | https://console.volcengine.com/dcdn |
| 火山 DNS（可选） | https://console.volcengine.com/dns |

---

## 三、ECS 服务器部署

### 3.1 创建 ECS 实例

```
地域:     北京（华北2）— 国内用户延迟低，海外通过DCDN回源
          或 上海（华东2）

实例规格:  ecs.g3i.large (2vCPU, 4GB)
          日常够用，后续可按需升配

镜像:     Ubuntu 22.04 LTS 64位

系统盘:   40GB ESSD PL0

网络:     分配公网 IPv4
          带宽按量计费，峰值 100Mbps

安全组:   见 3.2
```

### 3.2 安全组规则

| 方向 | 协议 | 端口 | 来源 | 说明 |
|------|------|------|------|------|
| 入方向 | TCP | 22 | 你的办公IP | SSH 管理 |
| 入方向 | TCP | 80 | 0.0.0.0/0 | HTTP（Let's Encrypt验证） |
| 入方向 | TCP | 443 | 0.0.0.0/0 | HTTPS |
| 入方向 | TCP | 8765 | DCDN回源IP段 | API（仅DCDN回源） |

> DCDN回源IP段获取：DCDN控制台 → 回源配置 → 查看回源IP列表

### 3.3 初始化服务器

SSH 登录后执行：

```bash
# 更新系统
apt update && apt upgrade -y

# 安装 Docker
curl -fsSL https://get.docker.com | bash
systemctl enable docker
systemctl start docker

# 安装 Docker Compose
apt install -y docker-compose-plugin

# 安装 certbot（SSL 证书）
apt install -y certbot

# 创建部署目录
mkdir -p /opt/linkmoney/{data,logs,certs}
```

### 3.4 上传代码

将项目目录中的文件上传到服务器：

```bash
# 本地执行（将 /path/to/linkmoney 替换为实际路径）
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  /Users/tanyina/Documents/markteing/linkmoney/ \
  root@<ECS公网IP>:/opt/linkmoney/
```

需要上传的关键文件：
- `api/server.py` — 主服务
- `api/mailer.py` — 邮件模块
- `api/requirements.txt` — Python 依赖
- `data/database.json` — 数据源（51家供应商）
- `data/linkmoney.db` — SQLite 数据库
- `Dockerfile` — 容器构建
- `docker-compose.yml` — 容器编排
- `nginx.conf` — nginx 配置

### 3.5 配置环境变量

在服务器上创建 `/opt/linkmoney/.env`：

```bash
# API 鉴权 Key（多个用逗号分隔）
LINKMONEY_API_KEYS=lm-prod-2026-key1,lm-prod-2026-key2

# 邮件配置（暂时关闭，后续接入真实SMTP）
LINKMONEY_MAIL_ENABLED=false
LINKMONEY_SMTP_HOST=smtp.qq.com
LINKMONEY_SMTP_PORT=587
LINKMONEY_SMTP_USER=
LINKMONEY_SMTP_PASSWORD=
LINKMONEY_SMTP_FROM=

# 询单邮件覆写（所有通知发到这里）
LINKMONEY_RFQ_OVERRIDE_EMAIL=kevin@coze.email

# MCP 代理开关
LINKMONEY_MCP_PROXY_ENABLED=true

# 缓存 TTL（秒）
LINKMONEY_CACHE_TTL=60
```

### 3.6 获取 SSL 证书

```bash
# 先确保域名 DNS 已解析到 ECS 公网 IP
# 然后申请证书

certbot certonly --standalone \
  -d linkmoney.online \
  --email kevin@coze.email \
  --agree-tos \
  --non-interactive

# 证书路径
# /etc/letsencrypt/live/linkmoney.online/fullchain.pem
# /etc/letsencrypt/live/linkmoney.online/privkey.pem

# 复制证书到部署目录
cp /etc/letsencrypt/live/linkmoney.online/fullchain.pem /opt/linkmoney/certs/
cp /etc/letsencrypt/live/linkmoney.online/privkey.pem /opt/linkmoney/certs/

# 设置自动续期
echo "0 3 * * * root certbot renew --quiet --post-hook 'cp /etc/letsencrypt/live/linkmoney.online/fullchain.pem /opt/linkmoney/certs/ && cp /etc/letsencrypt/live/linkmoney.online/privkey.pem /opt/linkmoney/certs/ && docker restart linkmoney-nginx'" > /etc/cron.d/certbot-renew
```

### 3.7 启动服务

```bash
cd /opt/linkmoney

# 修改 nginx.conf 中的域名（如果是首次部署）
sed -i 's/linkmoney.online/你的实际域名/g' nginx.conf

# 构建并启动
docker compose up -d --build

# 查看运行状态
docker compose ps
docker compose logs -f linkmoney
```

### 3.8 验证服务

```bash
# 健康检查
curl http://localhost:8765/health

# 期望返回: {"status":"ok"}

# API 测试（获取统计）
curl -H "X-API-Key: lm-prod-2026-key1" http://localhost:8765/stats

# 期望返回: {"suppliers":51,"products":140,...}
```

---

## 四、DCDN 全球加速配置

DCDN（Dynamic Content Delivery Network）是火山云的全站加速产品，同时缓存静态内容并加速动态 API 请求。

### 4.1 添加加速域名

1. 进入 [DCDN 控制台](https://console.volcengine.com/dcdn)
2. 点击「添加域名」
3. 配置：

```
加速域名:     linkmoney.online
业务类型:     全站加速
源站类型:     IP 源站
源站地址:     <ECS公网IP>
源站端口:     443 (HTTPS)
回源协议:     HTTPS
```

### 4.2 缓存配置

| 路径 | 缓存时间 | 说明 |
|------|---------|------|
| `/health` | 不缓存 | 健康检查 |
| `/stats` | 60秒 | 统计数据 |
| `/mcp/manifest.json` | 300秒 | MCP manifest |
| `/onboard-*` | 600秒 | 引导页（静态HTML） |
| `/find_china_supplier` | 不缓存 | 动态查询 |
| `/get_pricing` | 不缓存 | 动态价格 |
| `/submit_rfq` | 不缓存 | RFQ 提交 |
| 其他 `/` | 不缓存 | API 端点 |

### 4.3 HTTPS 配置

1. DCDN 控制台 → 域名管理 → HTTPS 配置
2. 上传 SSL 证书（与 ECS 上的一致）
3. 强制 HTTPS 跳转：开启
4. TLS 版本：1.2、1.3

### 4.4 回源配置

```
回源协议:    HTTPS（443端口）
回源Host:    linkmoney.online
回源超时:    30秒
回源重试:    3次
```

### 4.5 IP 访问控制（可选）

```
IP 黑名单:   （暂无，后续可加）
IP 白名单:   （暂不限制）
UA 黑名单:   空
```

### 4.6 性能优化

- **智能压缩**: 开启 Gzip/Brotli
- **HTTP/2**: 开启
- **IPv6**: 开启（海外用户友好）

---

## 五、DNS 解析配置

在域名 DNS 管理后台添加记录：

| 类型 | 主机记录 | 记录值 | TTL |
|------|---------|--------|-----|
| CNAME | api | `<DCDN分配的CNAME>` | 600 |

> DCDN CNAME 地址在添加加速域名后由火山云分配，类似 `linkmoney.online.a.dcdn.volccdn.com`

---

## 六、数据库维护

### 6.1 数据库文件位置

```
ECS 路径:    /opt/linkmoney/data/linkmoney.db
JSON 源:     /opt/linkmoney/data/database.json
```

### 6.2 添加新工厂

编辑 `database.json` 的 `suppliers` 数组，添加新条目，然后重建数据库：

```bash
cd /opt/linkmoney
docker compose exec linkmoney python -c "
from server import init_db
init_db()
"
```

或者本地编辑后重新上传：

```bash
# 本地修改 database.json → 上传 → 重建
rsync data/database.json root@<ECS_IP>:/opt/linkmoney/data/
ssh root@<ECS_IP> 'cd /opt/linkmoney && docker compose restart linkmoney'
```

### 6.3 备份

```bash
# 每日备份脚本（放到 crontab）
#!/bin/bash
BACKUP_DIR="/opt/backups/linkmoney"
mkdir -p $BACKUP_DIR
cp /opt/linkmoney/data/linkmoney.db $BACKUP_DIR/linkmoney-$(date +%Y%m%d).db
# 保留最近 30 天
find $BACKUP_DIR -mtime +30 -delete

# 添加到 crontab
# 0 2 * * * /opt/linkmoney/scripts/backup.sh
```

---

## 七、监控与告警

### 7.1 火山云云监控

在 ECS 控制台开启基础监控：
- CPU 使用率 > 80% 告警
- 内存使用率 > 85% 告警
- 磁盘使用率 > 80% 告警

### 7.2 DCDN 监控

DCDN 控制台提供：
- 带宽/流量趋势
- 请求数 QPS
- 状态码分布
- 回源成功率

### 7.3 应用日志

```bash
# 查看实时日志
docker compose logs -f linkmoney

# 查看 nginx 日志
docker compose logs -f nginx
```

---

## 八、扩容方案（后续）

当前阶段（50家供应商、日均 < 1000 请求）：

```
ECS 2C4G + DCDN → 足够
```

当流量增长到日均 10000+ 请求时：

```
ECS → 升级到 4C8G 或 弹性伸缩组
SQLite → 迁移到火山云 RDS (MySQL/PostgreSQL)
DCDN → 保持
```

---

## 九、国际访问验证

部署完成后，从以下地区验证：

```bash
# 测试延迟
curl -w "\n%{time_total}s\n" -o /dev/null -s https://linkmoney.online/health

# 使用全球测速工具
# https://tools.keycdn.com/performance
# 输入: https://linkmoney.online/health
```

预期结果：
- 中国大陆: < 50ms（DCDN边缘节点）
- 美国西海岸: < 150ms
- 欧洲: < 200ms
- 东南亚: < 80ms

---

## 十、上线 checklist

- [ ] 火山云 ECS 实例创建并初始化
- [ ] Docker + Docker Compose 安装
- [ ] 代码上传到 /opt/linkmoney/
- [ ] .env 环境变量配置（所有邮箱 → kevin@coze.email）
- [ ] SSL 证书申请并配置
- [ ] docker compose up 启动成功
- [ ] /health 健康检查通过
- [ ] DCDN 加速域名添加
- [ ] DNS CNAME 记录指向 DCDN
- [ ] HTTPS 访问正常
- [ ] 国际节点访问测试通过
- [ ] 数据库备份脚本配置
- [ ] 监控告警规则配置

---

## 十一、当前数据库概况

| 指标 | 数量 |
|------|------|
| 供应商 | 51 家 |
| 产品 | 140 个 |
| 海外买家 | 5 个 |
| 品类 | 10 个 |
| 联系邮箱 | 全部 → kevin@coze.email |

**品类分布：**

| 品类 | 供应商数 |
|------|---------|
| 紧固件 (fastener) | 8 |
| 纺织服装 (textile) | 7 |
| 包装印刷 (packaging) | 6 |
| 机械设备 (machinery) | 6 |
| 五金制品 (hardware) | 6 |
| 注塑模具 (injection_molding) | 5 |
| 电子元器件 (electronics) | 5 |
| 电子产品 (electronic) | 3 |
| 汽车零部件 (auto_parts) | 3 |
| 家具家居 (furniture) | 2 |

---

> 部署问题联系: kevin@coze.email