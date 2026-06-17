"""
LinkMoney v3.0+ 部署 — 通过火山引擎 ECS RunCommand SDK 推代码到生产容器

工作流程（5 步）：
  1. 备份容器内 server.py / llm_layer.py / database.db
  2. 从 api.github.com 拉取新代码（ECS 内 raw.githubusercontent.com 被墙，API 可达）
  3. docker cp 到容器 + 验证 import
  4. 写 .env 加 DEEPSEEK_* + docker compose restart
  5. 验证 /multi_lang_inquiry + /submit_rfq

环境要求：
  - VOLC_ACCESSKEY / VOLC_SECRETKEY  环境变量
  - pip install volcengine-python-sdk
  - ECS 在 cn-shanghai 区域，容器名 linkmoney-api

回滚：
  BACKUP_DIR=$(脚本会打印)
  docker cp $BACKUP_DIR/server.py.bak linkmoney-api:/app/server.py
  docker compose -C /opt/linkmoney/linkmoney restart linkmoney
"""
import os
import sys
import time
import base64
import volcenginesdkcore
import volcenginesdkecs
from volcenginesdkcore.rest import ApiException


def main():
    ak = os.environ.get('VOLC_ACCESSKEY')
    sk = os.environ.get('VOLC_SECRETKEY')
    if not ak or not sk:
        print("ERROR: VOLC_ACCESSKEY / VOLC_SECRETKEY not set")
        sys.exit(1)

    REGION = "cn-shanghai"
    configuration = volcenginesdkcore.Configuration()
    configuration.ak = ak
    configuration.sk = sk
    configuration.region = REGION
    volcenginesdkcore.Configuration.set_default(configuration)

    api = volcenginesdkecs.ECSApi()
    req = volcenginesdkecs.DescribeInstancesRequest(max_results=20)
    resp = api.describe_instances(req)
    instances = resp.instances or []
    if not instances:
        print("❌ 没找到 ECS 实例")
        sys.exit(1)
    instance_id = instances[0].instance_id
    print(f"[1/5] ECS 实例: {instance_id} ({instances[0].instance_name})")

    # 1. 备份
    print("\n[2/5] 备份当前容器文件...")
    backup_cmd = r"""
set -e
TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/opt/linkmoney/backups/v3-llm-$TS"
mkdir -p "$BACKUP_DIR"
docker cp linkmoney-api:/app/server.py "$BACKUP_DIR/server.py.bak" 2>/dev/null || echo "  server.py backup skipped"
docker cp linkmoney-api:/app/llm_layer.py "$BACKUP_DIR/llm_layer.py.bak" 2>/dev/null || echo "  llm_layer.py backup skipped"
docker cp linkmoney-api:/app/middle_agent.py "$BACKUP_DIR/middle_agent.py.bak" 2>/dev/null || echo "  middle_agent.py backup skipped"
docker cp linkmoney-api:/app/database.db "$BACKUP_DIR/database.db.bak" 2>/dev/null || echo "  database.db backup skipped"
ls -la "$BACKUP_DIR"
echo "BACKUP_DIR=$BACKUP_DIR"
"""
    r = run_with_retry(api, instance_id, backup_cmd, "backup", 30)
    if not r['success']:
        print(f"❌ 备份失败: {r['output']}")
        sys.exit(1)
    print(r['output'])
    backup_dir = None
    for line in r['output'].split("\n"):
        if line.startswith("BACKUP_DIR="):
            backup_dir = line.split("=", 1)[1].strip()
    print(f"  备份目录: {backup_dir}")

    # 2. 推文件（用 api.github.com 通道）
    print("\n[3/5] 推 llm_layer.py + server.py + middle_agent.py 到容器（api.github.com 通道）...")
    write_cmd = r"""
set -e

download_from_github() {
  local path="$1"
  local out="$2"
  local resp_file="/tmp/_gh_resp.json"
  echo "[ECS] 下载 api/$path (${3} KB)..."
  curl -sSL -m 60 -o "$resp_file" \
    "https://api.github.com/repos/KevinANDcayla/linkmoney-skill/contents/api/${path}?ref=main"
  ls -la "$resp_file"
  python3 - "$resp_file" "$out" <<'PY'
import json, base64, sys
resp_file, out = sys.argv[1], sys.argv[2]
with open(resp_file) as f:
    d = json.load(f)
if 'content' not in d:
    print(f"  ❌ API 返回错误: {d.get('message', d)}")
    sys.exit(1)
raw = base64.b64decode(d['content'])
with open(out, 'wb') as f:
    f.write(raw)
print(f"  ✅ 写入 {out} ({len(raw)} bytes, 期望 {d.get('size')})")
PY
}

download_from_github "llm_layer.py" "/tmp/llm_layer_new.py" "14"
download_from_github "server.py"     "/tmp/server_new.py"     "140"
download_from_github "middle_agent.py" "/tmp/middle_agent_new.py" "25"

echo ""
echo "[ECS] 验证 import (不重启)..."
head -3 /tmp/llm_layer_new.py
head -3 /tmp/server_new.py
head -3 /tmp/middle_agent_new.py

echo ""
echo "[ECS] docker cp 到容器..."
docker cp /tmp/llm_layer_new.py linkmoney-api:/app/llm_layer.py
docker cp /tmp/server_new.py linkmoney-api:/app/server.py
docker cp /tmp/middle_agent_new.py linkmoney-api:/app/middle_agent.py

docker exec linkmoney-api ls -la /app/llm_layer.py /app/server.py /app/middle_agent.py

echo ""
echo "[ECS] 验证 import（容器内）..."
docker exec linkmoney-api python3 -c "import llm_layer; print('  llm_layer OK, has DeepSeekProvider:', hasattr(llm_layer, 'DeepSeekProvider'))"
docker exec linkmoney-api python3 -c "import server; print('  server OK, has _migrate_v21:', hasattr(server, '_migrate_v21'))"
docker exec linkmoney-api python3 -c "import middle_agent; print('  middle_agent OK, has ThreadPoolExecutor:', 'ThreadPoolExecutor' in dir(middle_agent))"

echo "[ECS] ✅ 文件已写入容器"
"""
    r = run_with_retry(api, instance_id, write_cmd, "write-files", 180)
    if not r['success']:
        print(f"❌ 写文件失败: {r['output']}")
        print("回滚命令:")
        print(f"  docker cp {backup_dir}/server.py.bak linkmoney-api:/app/server.py")
        print(f"  docker cp {backup_dir}/llm_layer.py.bak linkmoney-api:/app/llm_layer.py")
        print(f"  docker cp {backup_dir}/middle_agent.py.bak linkmoney-api:/app/middle_agent.py")
        print(f"  docker compose -C /opt/linkmoney/linkmoney restart linkmoney")
        sys.exit(1)
    print(r['output'])

    # 3. 写 .env + 重启
    print("\n[4/5] 写 .env + 重启容器...")
    restart_cmd = r"""
set -e

echo "[ECS] 检查 .env..."
if [ -f /opt/linkmoney/linkmoney/.env ]; then
  if ! grep -q "^DEEPSEEK_API_KEY" /opt/linkmoney/linkmoney/.env; then
    cat >> /opt/linkmoney/linkmoney/.env <<'ENV'

# ===== LLM 配置（v3.0+）=====
DEEPSEEK_API_KEY=
DEEPSEEK_FLASH_MODEL=deepseek-v4-flash
DEEPSEEK_PRO_MODEL=deepseek-v4-pro
ENV
    echo "  ✅ 已添加 DEEPSEEK_* 到 .env"
  else
    echo "  ℹ️  .env 已有 DEEPSEEK_API_KEY（保留原值）"
  fi
else
  echo "  ❌ /opt/linkmoney/linkmoney/.env 不存在！"
  exit 1
fi

echo ""
echo "[ECS] 重启容器..."
cd /opt/linkmoney/linkmoney
docker compose restart linkmoney
echo "  等待启动..."
sleep 12

echo ""
echo "[ECS] 健康检查..."
curl -s -m 5 -o /dev/null -w "  HTTP %{http_code}\n" http://localhost:8765/

echo ""
echo "[ECS] 容器日志最后 20 行..."
docker logs --tail 20 linkmoney-api 2>&1 | tail -20
"""
    r = run_with_retry(api, instance_id, restart_cmd, "restart", 60)
    if not r['success']:
        print(f"❌ 重启失败: {r['output']}")
        sys.exit(1)
    print(r['output'])

    # 4. 验证
    print("\n[5/5] 验证 LLM 集成 + RFQ 端点...")
    verify_cmd = r"""
set -e

echo "[ECS] 测试 /multi_lang_inquiry..."
RESP=$(curl -s -m 30 -X POST http://localhost:8765/multi_lang_inquiry \
  -H "Content-Type: application/json" \
  -H "X-API-Key: lm-prod-2026-key1" \
  -d '{"inquiry_text":"need 50K M8 304 stainless bolts FOB Ningbo","buyer_lang":"en","target_lang":"zh"}' 2>&1)
echo "  raw: $(echo "$RESP" | head -c 200)..."
echo "$RESP" | python3 -c "
import json,sys
try:
    d = json.loads(sys.stdin.read())
    print(f'  mode: {d.get(\"mode\")}')
    print(f'  llm_provider: {d.get(\"llm_provider\")}')
    print(f'  llm_available: {d.get(\"llm_available\")}')
    print(f'  zh: {d.get(\"translations\",{}).get(\"zh\",{}).get(\"inquiry\",\"\")[:100]}')
except Exception as e:
    print(f'  ❌ JSON parse fail: {e}')
"

echo ""
echo "[ECS] 测试 /submit_rfq (raw_message)..."
RFQ_RESP=$(curl -s -m 15 -X POST \
  "http://localhost:8765/submit_rfq?supplier_id=nb-fastener-001&buyer_id=buyer-au-001&sku=M8-DEPLOY-V3&quantity=12345&target_price_usd=0.08&port=Ningbo&incoterms=FOB&raw_message=v3%20deploy%20test%20raw_message" \
  -H "X-API-Key: lm-prod-2026-key1" 2>&1)
echo "  raw: $(echo "$RFQ_RESP" | head -c 300)..."
echo "$RFQ_RESP" | python3 -c "
import json,sys
try:
    d = json.loads(sys.stdin.read())
    print(f'  rfq_id: {d.get(\"rfq_id\")}')
    print(f'  status: {d.get(\"status\")}')
except Exception as e:
    print(f'  ❌ JSON parse fail: {e}')
"

echo ""
echo "[ECS] 容器日志最后 15 行..."
docker logs --tail 15 linkmoney-api 2>&1 | tail -15
"""
    r = run_with_retry(api, instance_id, verify_cmd, "verify", 90)
    if not r['success']:
        print(f"❌ 验证失败: {r['output']}")
        sys.exit(1)
    print(r['output'])

    print()
    print("=" * 60)
    print("✅ 部署完成！")
    print(f"   BACKUP_DIR={backup_dir}")
    print(f"   回滚命令: docker cp {backup_dir}/server.py.bak linkmoney-api:/app/server.py")
    print(f"             docker cp {backup_dir}/middle_agent.py.bak linkmoney-api:/app/middle_agent.py")
    print(f"             docker compose -C /opt/linkmoney/linkmoney restart linkmoney")
    print("=" * 60)
    return 0


def run_with_retry(api, instance_id, command_str, name="step", timeout=60):
    """Run shell command and wait for completion"""
    cmd_b64 = base64.b64encode(command_str.encode("utf-8")).decode("utf-8")
    try:
        req = volcenginesdkecs.RunCommandRequest(
            instance_ids=[instance_id],
            type="Shell",
            command_content=cmd_b64,
            invocation_name=name,
            timeout=timeout,
        )
        resp = api.run_command(req)
        invocation_id = resp.invocation_id
        print(f"  invocation_id = {invocation_id}")

        for i in range(timeout // 5):
            time.sleep(5)
            try:
                desc_req = volcenginesdkecs.DescribeInvocationResultsRequest(invocation_id=invocation_id)
                desc_resp = api.describe_invocation_results(desc_req)
                results = desc_resp.invocation_results or []
                if not results:
                    continue
                for r in results:
                    status = r.invocation_result_status
                    output = r.output or ""
                    if status in ('Success', 'Succeeded', 'Completed'):
                        return {'success': True, 'output': output}
                    elif status in ('Failed', 'Error'):
                        return {'success': False, 'output': output}
                    else:
                        print(f"  [{i+1}/{timeout//5}] 状态: {status}")
            except ApiException as e:
                print(f"  [{i+1}] {e}")
                continue
        return {'success': False, 'output': 'timeout'}
    except ApiException as e:
        return {'success': False, 'output': f'RunCommand ApiException: {e}'}


if __name__ == "__main__":
    sys.exit(main())
