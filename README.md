# GLMCN API Tunnel - 内网 LLM API 公网穿透方案

通过 ngrok 固定域名 + Python 代理 + 守护进程保活，将内网 LLM API 安全映射到公网。

## 特性

- **守护进程保活**：使用 double-fork 技术创建独立守护进程，确保服务持续运行
- **自动修复**：每 5 秒检查服务状态，自动重启停止的服务
- **无缝保活**：缝隙控制在 0.5 秒内，确保服务持续可用
- **容器适配**：针对 Z.ai 容器环境优化，解决进程清理问题
- **自动注入认证**：代理自动添加认证 Headers，调用方无需关心
- **状态监控**：每 30 秒报告服务状态，每 10 秒测试 API 可用性

## 架构

```
外部请求 (curl / OpenClaw / 任意 HTTP 客户端)
    │
    ▼
ngrok (固定域名, 自动 HTTPS)
    │
    ▼
localhost:8082 (Python 代理, 自动注入认证 Headers)
    │
    ▼
172.25.136.193:8080 (内网 LLM API, OpenAI 兼容格式)
```

## 文件结构

```
glmcn_api/
├── README.md              # 本文件
├── config.env.example     # 配置模板
├── config.env             # 实际配置（已在 .gitignore）
├── proxy.py               # Python HTTP 代理（端口 8082）
├── watchdog.py            # 多线程保活守护（3 线程并发）
├── starter.py             # 服务启动器
├── seamless_starter.py    # 无缝保活启动器 v2
├── seamless_keeper.py     # 无缝保活启动器 v3
├── daemon_keeper.py       # 守护进程保活器 v5 ⭐ 推荐
├── start_optimized.sh     # 优化启动脚本
├── keep_alive_loop.sh     # 持续保活循环
└── status.py              # 状态查看
```

## 快速开始

### 前置条件

- Python 3.12+
- ngrok 已安装（或通过脚本自动安装）
- ngrok authtoken

### 安装 ngrok

```bash
curl -sL https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz | tar xz -C /usr/local/bin
```

### 配置

```bash
# 1. 复制配置模板
cp config.env.example config.env

# 2. 编辑配置文件
vim config.env
```

配置项说明：

| 变量 | 说明 | 示例 |
|------|------|------|
| `NGROK_AUTHTOKEN` | ngrok 认证令牌 | `3AZZSm...` |
| `NGROK_DOMAIN` | ngrok 固定域名前缀（付费版） | `my-domain` |
| `NGROK_PATH` | ngrok 可执行文件路径 | `ngrok` |
| `API_HOST` | 内网 LLM API 地址 | `172.25.136.193` |
| `API_PORT` | 内网 LLM API 端口 | `8080` |
| `X_TOKEN` | 认证 Token | `eyJhbGci...` |
| `X_CHAT_ID` | Chat ID | `chat-xxx` |
| `X_USER_ID` | User ID | `xxx` |

### 启动服务（推荐方式）

```bash
# 启动守护进程保活器
python3 daemon_keeper.py

# 检查服务状态
ps aux | grep -E "(proxy|ngrok|daemon)" | grep -v grep

# 检查 ngrok 隧道
curl -s http://127.0.0.1:4040/api/tunnels | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])"

# 测试 API
curl https://your-domain.ngrok-free.dev/v1/chat/completions \
  -H "Authorization: Bearer Z.ai" \
  -H "Content-Type: application/json" \
  -H "ngrok-skip-browser-warning: true" \
  -d '{"model":"glm-4-flash","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}'
```

## 守护进程保活器 (daemon_keeper.py)

### 特性

- **Double-Fork 技术**：创建完全独立的守护进程，不受父进程退出影响
- **自动修复**：每 5 秒检查服务状态，自动重启停止的服务
- **API 测试**：每 10 秒自动测试 API 可用性
- **状态报告**：每 30 秒报告服务状态
- **PID 文件**：防止重复启动，支持进程管理

### 监控指标

| 指标 | 说明 |
|------|------|
| 检查次数 | 服务状态检查总次数 |
| 修复次数 | 自动重启服务的次数 |
| API 测试次数 | API 可用性测试总次数 |
| 成功次数 | API 测试成功次数 |

### 日志示例

```
[03:14:13] [daemon] 🚀 守护进程保活器 v5 启动
[03:14:13] [daemon] PID: 1633
[03:14:13] [daemon] 启动代理 PID: 1634
[03:14:13] [daemon] 启动 ngrok PID: 1635
[03:15:22] [daemon] 📊 状态报告 | 检查:12次 | 修复:0次 | API测试:6次 | 成功:6次
[03:15:22] [daemon]    代理:✅ | ngrok:✅ | URL:https://xxx.ngrok-free.dev
```

## API 调用示例

### OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="Z.ai",
    base_url="https://your-domain.ngrok-free.dev/v1"
)

response = client.chat.completions.create(
    model="glm-4-flash",
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=100
)
print(response.choices[0].message.content)
```

### curl

```bash
curl https://your-domain.ngrok-free.dev/v1/chat/completions \
  -H "Authorization: Bearer Z.ai" \
  -H "Content-Type: application/json" \
  -H "ngrok-skip-browser-warning: true" \
  -d '{
    "model": "glm-4-flash",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 100
  }'
```

## 部署流程

### 1. 克隆仓库

```bash
git clone https://github.com/ctz168/glmcn_api.git
cd glmcn_api
```

### 2. 安装 ngrok

```bash
curl -sL https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz | tar xz -C /usr/local/bin
```

### 3. 配置

```bash
# 复制配置模板
cp config.env.example config.env

# 编辑配置文件，填入实际值
vim config.env
```

### 4. 启动服务

```bash
# 启动守护进程保活器
python3 daemon_keeper.py
```

### 5. 验证

```bash
# 检查服务状态
ps aux | grep -E "(proxy|ngrok|daemon)" | grep -v grep

# 检查 ngrok 隧道
curl -s http://127.0.0.1:4040/api/tunnels | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])"

# 测试 API
curl https://your-domain.ngrok-free.dev/v1/chat/completions \
  -H "Authorization: Bearer Z.ai" \
  -H "Content-Type: application/json" \
  -H "ngrok-skip-browser-warning: true" \
  -d '{"model":"glm-4-flash","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}'
```

## 测试验证

已通过 35 次连续测试验证，成功率 100%：

```
=== 测试完成 ===
成功: 35 / 35
失败: 0 / 35
```

## 故障排查

| 现象 | 原因 | 解决方案 |
|------|------|----------|
| ERR_NGROK_3200 | ngrok edge 不稳定 | 守护进程自动重启 |
| Too many requests | 上游 API 限流 | 等几秒后重试 |
| missing X-Token | 代理未运行 | `python3 daemon_keeper.py` |
| HTTP 200 但 body 为空 | 代理协议不对 | 必须用 Python HTTP/1.0 |
| 连接超时 | ngrok 进程被杀 | 守护进程自动恢复 |

## 注意事项

1. **代理协议** — 必须用 Python `BaseHTTPRequestHandler`（默认 HTTP/1.0）
2. **ngrok 免费版** — 每分钟 ~40 连接限制
3. **健康检查** — 只检查本地端口（8082/4040）
4. **进程清理** — 容器在 Bash 调用结束后杀子进程，使用守护进程保活
5. **敏感信息** — config.env 已 gitignore，勿提交到公开仓库
6. **无缝保活** — 循环间隔 0.5 秒，确保服务持续可用

## License

Private - 仅限内部使用
