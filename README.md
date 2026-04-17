# GLMCN API Tunnel - 内网 LLM API 公网穿透方案

通过 ngrok 固定域名 + Python 代理 + 多线程 watchdog，将内网 LLM API 安全映射到公网。

## 特性

- **自动保活**：watchdog 多线程监控，自动修复服务
- **独立进程**：使用 setsid 创建独立进程组，不受父进程退出影响
- **容器适配**：针对 Z.ai 容器环境优化，解决进程清理问题
- **自动注入认证**：代理自动添加认证 Headers，调用方无需关心
- **无缝保活**：缝隙控制在 0.5 秒内，确保服务持续可用

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
| `API_KEY` | API 认证密钥 | `Z.ai` |
| `X_TOKEN` | 自动注入的 JWT Token | `eyJhb...` |
| `X_CHAT_ID` | 自动注入的 Chat ID | `chat-xxx` |
| `X_USER_ID` | 自动注入的 User ID | `xxx` |

### 启动服务

#### 方式一：无缝保活启动器（推荐）

```bash
# 使用无缝保活启动器
python3 seamless_starter.py --timeout 280 --check-interval 5 --report-interval 30

# 参数说明：
# --timeout 280          运行超时时间（秒）
# --check-interval 5     每 5 秒检查服务状态
# --report-interval 30   每 30 秒报告状态
# --keepalive-interval 60 每 60 秒保活调用
```

#### 方式二：标准启动器

```bash
# 使用标准启动器
python3 starter.py --timeout 280
```

#### 方式三：Shell 脚本

```bash
# 一键启动
bash start_optimized.sh start

# 查看状态
bash start_optimized.sh status

# 测试 API
bash start_optimized.sh test

# 停止服务
bash start_optimized.sh stop
```

### 持续保活（容器环境）

在 Z.ai 容器环境中，使用 timeout 控制运行时间：

```bash
# 运行 280 秒（留 20 秒缓冲）
timeout 280 python3 seamless_starter.py
```

## API 调用

### 基本信息

| 项目 | 值 |
|------|-----|
| **Base URL** | `https://<ngrok-domain>.ngrok-free.dev/v1` |
| **API Key** | `Z.ai` |
| **协议** | OpenAI 兼容格式 |
| **必需 Header** | `Authorization: Bearer Z.ai` |
| **ngrok Header** | `ngrok-skip-browser-warning: true` |

### curl 示例

```bash
# 聊天补全
curl https://your-domain.ngrok-free.dev/v1/chat/completions \
  -H "Authorization: Bearer Z.ai" \
  -H "ngrok-skip-browser-warning: true" \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-4-flash","messages":[{"role":"user","content":"Hello"}],"max_tokens":100}'

# 流式响应
curl https://your-domain.ngrok-free.dev/v1/chat/completions \
  -H "Authorization: Bearer Z.ai" \
  -H "ngrok-skip-browser-warning: true" \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-4-flash","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

## 多线程保活机制

### 架构设计

```
watchdog.py（多线程守护进程）
    │
    ├─ proxy_watcher  每 2s 检查代理(8082) → 挂了立即重启
    ├─ ngrok_watcher  每 3s 检查隧道(4040) → 挂了立即重启
    └─ stats_reporter 每 10s 状态报告     → 写入日志
```

### 无缝保活启动器特性

```
seamless_starter.py（无缝保活启动器 v2）
    │
    ├─ 每 5 秒检查服务状态
    ├─ 每 30 秒报告状态
    ├─ 每 60 秒保活调用 API
    ├─ 自动修复停止的服务
    └─ 缝隙控制在 0.5 秒内
```

### 关键特性

| 特性 | 说明 |
|------|------|
| 并发监控 | 代理和 ngrok 独立检查，互不阻塞 |
| 带锁修复 | `threading.Lock()` 防止多线程同时重启 |
| 轻量检查 | 只 ping 本地端口，不打上游 API |
| 快速响应 | 2-3 秒内检测故障并自动重启 |
| 防雪崩退避 | 连续修复失败时指数退避 |
| 无缝保活 | 循环间隔 0.5 秒，确保服务持续可用 |

## 故障排查

| 现象 | 原因 | 解决方案 |
|------|------|----------|
| ERR_NGROK_3200 | ngrok edge 不稳定 | watchdog 3s 内自动重启 |
| Too many requests | 上游 API 限流 | 等几秒后重试 |
| missing X-Token | 代理未运行 | `bash start_optimized.sh start` |
| HTTP 200 但 body 为空 | 代理协议不对 | 必须用 Python HTTP/1.0 |
| 连接超时 | ngrok 进程被杀 | watchdog 会自动恢复 |

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
# 使用无缝保活启动器
python3 seamless_starter.py --timeout 280
```

### 5. 验证

```bash
# 检查服务状态
curl http://127.0.0.1:8082/_ping

# 检查 ngrok 隧道
curl http://127.0.0.1:4040/api/tunnels

# 测试 API
curl https://your-domain.ngrok-free.dev/v1/chat/completions \
  -H "Authorization: Bearer Z.ai" \
  -H "ngrok-skip-browser-warning: true" \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-4-flash","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}'
```

## 注意事项

1. **代理协议** — 必须用 Python `BaseHTTPRequestHandler`（默认 HTTP/1.0）
2. **ngrok 免费版** — 每分钟 ~40 连接限制
3. **健康检查** — 只检查本地端口（8082/4040）
4. **进程清理** — 容器在 Bash 调用结束后杀子进程，使用 setsid 保活
5. **敏感信息** — config.env 已 gitignore，勿提交到公开仓库
6. **无缝保活** — 循环间隔 0.5 秒，确保服务持续可用

## License

Private - 仅限内部使用
