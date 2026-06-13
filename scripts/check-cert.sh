#!/bin/bash
# LinkMoney 证书到期提醒 + 续签 helper
# 当前证书：DigiCert 测试版（2026-06-12 → 2026-12-28，199 天）
# 用途：监测证书剩余天数，<30 天发邮件 / 写告警

set -e

CERT_PATH="${1:-./certs/fullchain.pem}"
DOMAIN="linkmoney.online"
WARN_DAYS="${WARN_DAYS:-30}"

if [ ! -f "$CERT_PATH" ]; then
    echo "❌ 证书文件不存在: $CERT_PATH"
    echo "请把 DigiCert 下发的 fullchain.pem + privkey.pem 放入 $CERT_PATH"
    exit 1
fi

# 解析证书到期时间
END_DATE=$(openssl x509 -enddate -noout -in "$CERT_PATH" | cut -d= -f2)
END_TS=$(date -j -f "%b %d %H:%M:%S %Y" "$END_DATE" +%s 2>/dev/null || date -d "$END_DATE" +%s)
NOW_TS=$(date +%s)
DAYS_LEFT=$(( (END_TS - NOW_TS) / 86400 ))

echo "===== LinkMoney 证书状态 ====="
echo "域名：       $DOMAIN"
echo "证书文件：   $CERT_PATH"
echo "到期时间：   $END_DATE"
echo "剩余天数：   $DAYS_LEFT 天"
echo "警告阈值：   < $WARN_DAYS 天"

if [ "$DAYS_LEFT" -lt 0 ]; then
    echo "🔴 已过期！立即续签"
    exit 2
elif [ "$DAYS_LEFT" -lt "$WARN_DAYS" ]; then
    echo "⚠️ 剩余 < $WARN_DAYS 天，建议尽快续签"
    echo "续签步骤："
    echo "  1. 控制台重新签发证书（保留原 CSR 即可）"
    echo "  2. 下载 fullchain.pem + privkey.pem"
    echo "  3. 替换 $CERT_PATH 与 privkey.pem"
    echo "  4. docker exec -it linkmoney-nginx nginx -s reload"
    exit 1
else
    echo "✅ 状态健康"
    exit 0
fi
