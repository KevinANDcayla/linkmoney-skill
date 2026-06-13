#!/bin/bash
# LinkMoney 一键部署脚本
# 用法: bash deploy.sh

set -e

echo "============================================"
echo "  LinkMoney 一键部署"
echo "============================================"

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "错误: 请先安装 Docker"
    echo "Mac: brew install docker"
    echo "Ubuntu: sudo apt install docker.io docker-compose"
    exit 1
fi

# 环境变量
if [ ! -f .env ]; then
    echo "创建 .env 配置文件..."
    cp .env.example .env
    echo "请编辑 .env 填入你的 SMTP 等配置"
fi

# 证书目录
if [ ! -d certs ]; then
    mkdir -p certs
    echo "证书目录已创建 certs/，请放入 fullchain.pem 和 privkey.pem"
    echo "可使用 Let's Encrypt 免费获取: certbot certonly --standalone -d linkmoney.online"
fi

# 数据目录
mkdir -p data logs

# 启动
echo ""
echo "启动服务..."
docker-compose up -d --build

echo ""
echo "============================================"
echo "  部署完成！"
echo "============================================"
echo "  API:     https://linkmoney.online"
echo "  MCP:     https://linkmoney.online/mcp/manifest.json"
echo "  引导页:  https://linkmoney.online/onboard-supplier"
echo "  健康:    https://linkmoney.online/health"
echo "  中间 Agent（v3.0）:"
echo "    - 状态:   https://linkmoney.online/agent/status"
echo "    - 健康度: https://linkmoney.online/agent/health?force=true"
echo "    - 告警:   https://linkmoney.online/agent/alerts"
echo "    - 优化:   https://linkmoney.online/agent/optimize"
echo "  日志:    docker-compose logs -f linkmoney"
echo "  停止:    docker-compose down"
echo "============================================"