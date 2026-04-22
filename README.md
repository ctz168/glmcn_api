# GLMCN API Tunnel - 内网 LLM API 公网穿透方案

通过 ngrok/cloudflared + Python 代理 + 守护进程保活，将内网 LLM API 安全映射到公网。

## 特性

- **守护进程保活**：使用 double-fork 技术创建独立守护进程，确保服务持续运行
- **自动修复**：每 5 秒检查服务状态，自动重启停止的服务
- **无缝保活**：缝隙控制在 0.5 秒内，确保服务持续可用
- **容器适配**：针对 Z.ai 容器环境优化，解决进程清理问题
- **自动注入认证**：代理自动添加认证 Headers，调用方无需关心
- **状态监控**：每 30 秒报告服务状态，每 10 秒测试 API 可用性
- **双隧道支持**：支持 ngrok 和 cloudflared 两种隧道方案

## 架构

```
外部请求 (curl / OpenClaw / 任意 HTTP 客户端)
    │
    ▼
ngrok/cloudflared (公网隧道, 自动 HTTPS)
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
├── daemon_keeper.py       # 守护进程保活器 v5
├── ultimate_keeper.py     # 无缝保活启动器 v8
├── container_keeper.py    # 容器环境保活启动器 v9 ⭐ 推荐（Z.ai 容器适配）
├── keepalive_test.py      # 保活测试脚本
├── start_optimized.sh     # 优化启动脚本
├── keep_alive_loop.sh     # 持续保活循环
├── one_click_start.sh     # 一键启动脚本
├── container_start.sh     # 容器环境启动脚本 ⭐ 推荐
└── status.py              # 状态查看
```

## 快速开始（一键启动）

### 方式一：Z.ai 容器环境启动（推荐，使用 ngrok）

```bash
# 1. 克隆仓库
git clone https://github.com/ctz168/glmcn_api.git
cd glmcn_api

# 2. 配置（首次运行需要）
cp config.env.example config.env
vim config.env  # 填入实际配置（设置 TUNNEL_TYPE=ngrok）

# 3. 启动服务（运行 280 秒，适配容器 30 秒进程清理机制）
timeout 290 python3 keepalive_test.py

# 或指定运行时长
timeout 320 python3 keepalive_test.py  # 运行 300 秒
```

### 方式二：使用一键启动脚本

```bash
# 1. 克隆仓库
git clone https://github.com/ctz168/glmcn_api.git
cd glmcn_api

# 2. 配置（首次运行需要）
cp config.env.example config.env
vim config.env  # 填入实际配置

# 3. 一键启动（自动安装依赖、启动服务、保活）
chmod +x one_click_start.sh
./one_click_start.sh
```

### 方式二：手动启动

```bash
# 1. 安装 cloudflared（推荐，解决 ngrok 域名占用问题）
curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# 2. 或安装 ngrok
curl -sL https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz | tar xz -C /usr/local/bin
ngrok config add-authtoken YOUR_AUTHTOKEN

# 3. 配置
cp config.env.example config.env
vim config.env

# 4. 启动保活服务
python3 ultimate_keeper.py --duration 300  # 运行 5 分钟
```

## 配置说明

### config.env 配置项

| 变量 | 说明 | 示例 |
|------|------|------|
| `NGROK_AUTHTOKEN` | ngrok 认证令牌 | `3AZZSm...` |
| `NGROK_DOMAIN` | ngrok 固定域名前缀（付费版） | `my-domain` |
| `API_HOST` | 内网 LLM API 地址 | `172.25.136.193` |
| `API_PORT` | 内网 LLM API 端口 | `8080` |
| `X_TOKEN` | 认证 Token | `eyJhbGci...` |
| `X_CHAT_ID` | Chat ID | `chat-xxx` |
| `X_USER_ID` | User ID | `xxx` |

### 获取 Z.ai 配置

在 Z.ai 容器环境中，配置文件位于 `/etc/.z-ai-config`：

```bash
# 读取配置
cat /etc/.z-ai-config
```

## 隧道方案对比

| 特性 | ngrok | cloudflared |
|------|-------|-------------|
| 固定域名 | 付费功能 | 免费支持 |
| 域名占用问题 | 有（需 pooling-enabled） | 无 |
| 连接稳定性 | 较好 | 很好 |
| 免费额度 | 有限制 | 较宽松 |
| 推荐场景 | 有付费账户 | 免费使用 |

### ngrok 域名占用问题

如果遇到 `ERR_NGROK 3200: The endpoint you requested is currently online` 错误：

1. **方案一**：使用 `--pooling-enabled` 参数
   ```bash
   ngrok http 8082 --url https://your-domain.ngrok-free.dev --pooling-enabled
   ```

2. **方案二**：使用 cloudflared（推荐）
   ```bash
   cloudflared tunnel --url http://localhost:8082
   ```

## 无缝保活启动器 (ultimate_keeper.py)

### 特性

- **双隧道支持**：自动选择 cloudflared 或 ngrok
- **5 秒检查**：每 5 秒检查服务状态
- **30 秒报告**：每 30 秒报告运行状态
- **自动修复**：服务停止时自动重启
- **0.5 秒缝隙**：循环间隔 0.5 秒，确保服务持续可用
- **五次验证**：启动时进行五次 API 可用性验证

### 使用方法

```bash
# 运行 5 分钟（默认）
python3 ultimate_keeper.py

# 运行指定时长
python3 ultimate_keeper.py --duration 600  # 运行 10 分钟

# 使用 timeout 控制运行时间
timeout 310 python3 ultimate_keeper.py --duration 300
```

### 监控指标

| 指标 | 说明 |
|------|------|
| 运行时长 | 已运行时间（秒） |
| 检查次数 | 服务状态检查总次数 |
| 修复次数 | 自动重启服务的次数 |
| API 测试次数 | API 可用性测试总次数 |
| 成功次数 | API 测试成功次数 |

### 日志示例

```
[06:23:09] [keeper] 🚀 无缝保活启动器 v8 启动
[06:23:09] [keeper] PID: 1587
[06:23:09] [keeper] 计划运行时长: 300 秒
[06:23:09] [keeper] ✅ 代理已启动 PID: 1589
[06:23:09] [keeper] ✅ cloudflared 已启动 PID: 1592
[06:23:09] [keeper] 🌐 公网 URL: https://xxx.trycloudflare.com
[06:23:50] [keeper] 📊 状态报告 | 运行:45s | 剩余:254s
[06:23:50] [keeper]    检查:6次 | 修复:0次 | API测试:3次 | 成功:3次
[06:23:50] [keeper]    代理:✅ | cloudflared:✅ | URL:https://xxx.trycloudflare.com
```

## API 调用示例

### OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="Z.ai",
    base_url="https://your-domain.trycloudflare.com/v1"
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
curl https://your-domain.trycloudflare.com/v1/chat/completions \
  -H "Authorization: Bearer Z.ai" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4-flash",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 100
  }'
```

## 部署经验总结

### 1. 进程保活关键点

- **使用 timeout 控制运行时间**：避免无限循环导致资源耗尽
- **0.5 秒检查间隔**：确保服务状态及时更新
- **自动修复机制**：服务停止时立即重启
- **PID 文件管理**：防止重复启动

### 2. 隧道选择建议

- **cloudflared**：免费、稳定、无域名占用问题，推荐使用
- **ngrok**：需要付费账户才能使用固定域名，免费版有域名占用问题

### 3. 容器环境注意事项

- 容器可能会杀掉后台进程，需要使用保活机制
- 使用 `preexec_fn=os.setpgrp` 创建独立进程组
- 日志文件记录运行状态，便于排查问题

### 4. 常见问题解决

| 现象 | 原因 | 解决方案 |
|------|------|----------|
| ERR_NGROK_3200 | ngrok 域名已占用 | 使用 cloudflared 或 pooling-enabled |
| Too many requests | 上游 API 限流 | 降低请求频率 |
| 进程被杀 | 容器资源限制 | 使用保活机制 |
| 连接超时 | 隧道进程停止 | 守护进程自动恢复 |

## 测试验证

已通过 5 分钟无缝保活测试验证（使用 ngrok）：

```
════════════════════════════════════════
📈 最终报告
════════════════════════════════════════
运行时长: 300 秒
检查次数: 55
修复次数: 0
API 测试: 27 次
成功次数: 27 次
成功率: 100.0%
════════════════════════════════════════
```

### 容器环境适配测试

在 Z.ai 容器环境中测试结果：
- 服务稳定运行 5 分钟，无需修复
- 代理和 ngrok 进程持续可用
- API 调用成功率 100%
- 公网 URL: `https://noncommemorational-mitzi-glitteringly.ngrok-free.dev`

## 故障排查

| 现象 | 原因 | 解决方案 |
|------|------|----------|
| ERR_NGROK_3200 | ngrok edge 不稳定 | 使用 cloudflared |
| Too many requests | 上游 API 限流 | 等几秒后重试 |
| missing X-Token | 代理未运行 | `python3 ultimate_keeper.py` |
| HTTP 200 但 body 为空 | 代理协议不对 | 必须用 Python HTTP/1.0 |
| 连接超时 | 隧道进程被杀 | 守护进程自动恢复 |

## 注意事项

1. **代理协议** — 必须用 Python `BaseHTTPRequestHandler`（默认 HTTP/1.0）
2. **隧道限制** — 免费版有连接限制，注意使用频率
3. **健康检查** — 只检查本地端口（8082/4040）
4. **进程清理** — 容器在 Bash 调用结束后杀子进程，使用守护进程保活
5. **敏感信息** — config.env 已 gitignore，勿提交到公开仓库
6. **无缝保活** — 循环间隔 0.5 秒，确保服务持续可用

## License

Private - 仅限内部使用
