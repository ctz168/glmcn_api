#!/bin/bash
#
# 一键启动脚本 - 自动安装依赖、配置、启动服务
#
# 用法:
#   ./one_click_start.sh              # 交互式配置
#   ./one_click_start.sh --duration 300  # 指定运行时长
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 工作目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 默认运行时长
DURATION=300

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --duration)
            DURATION="$2"
            shift 2
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${GREEN}🚀 GLMCN API 一键启动脚本${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"

# 1. 检查配置文件
echo -e "\n${YELLOW}[1/5] 检查配置文件...${NC}"
if [ ! -f "config.env" ]; then
    echo -e "${YELLOW}配置文件不存在，从模板创建...${NC}"
    if [ -f "config.env.example" ]; then
        cp config.env.example config.env
        echo -e "${GREEN}✅ 已创建 config.env，请编辑后重新运行${NC}"
        echo -e "${YELLOW}需要配置的项目:${NC}"
        echo "  - NGROK_AUTHTOKEN: ngrok 认证令牌"
        echo "  - X_TOKEN: 认证 Token"
        echo "  - X_CHAT_ID: Chat ID"
        echo "  - X_USER_ID: User ID"
        exit 0
    else
        echo -e "${RED}❌ 配置模板不存在，请手动创建 config.env${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✅ 配置文件已存在${NC}"
fi

# 2. 检查并安装 cloudflared
echo -e "\n${YELLOW}[2/5] 检查 cloudflared...${NC}"
if ! command -v cloudflared &> /dev/null; then
    echo -e "${YELLOW}cloudflared 未安装，正在安装...${NC}"
    curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
    echo -e "${GREEN}✅ cloudflared 安装完成${NC}"
else
    echo -e "${GREEN}✅ cloudflared 已安装: $(cloudflared --version)${NC}"
fi

# 3. 检查并安装 ngrok（可选）
echo -e "\n${YELLOW}[3/5] 检查 ngrok（可选）...${NC}"
if ! command -v ngrok &> /dev/null; then
    echo -e "${YELLOW}ngrok 未安装，正在安装...${NC}"
    curl -sL https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz | tar xz -C /usr/local/bin
    echo -e "${GREEN}✅ ngrok 安装完成${NC}"
else
    echo -e "${GREEN}✅ ngrok 已安装: $(ngrok version)${NC}"
fi

# 4. 清理旧进程
echo -e "\n${YELLOW}[4/5] 清理旧进程...${NC}"
pkill -f cloudflared 2>/dev/null || true
pkill -f "proxy.py" 2>/dev/null || true
pkill -f "ultimate_keeper" 2>/dev/null || true
sleep 1
echo -e "${GREEN}✅ 旧进程已清理${NC}"

# 5. 启动服务
echo -e "\n${YELLOW}[5/5] 启动保活服务...${NC}"
echo -e "${BLUE}运行时长: ${DURATION} 秒${NC}"

# 使用 timeout 控制运行时间
timeout $((DURATION + 10)) python3 ultimate_keeper.py --duration "$DURATION"

echo -e "\n${BLUE}════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ 服务已停止${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
