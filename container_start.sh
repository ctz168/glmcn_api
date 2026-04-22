#!/bin/bash
#
# 容器环境一键启动脚本
#
# 适配 Z.ai 容器环境（30秒进程清理机制）
# 使用 timeout 280 控制运行时间
#
# 用法:
#   ./container_start.sh              # 运行 280 秒
#   ./container_start.sh 300          # 运行 300 秒
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

# 默认运行时长（280秒，约4.7分钟）
DURATION=${1:-280}

echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${GREEN}🚀 GLMCN API 容器环境启动脚本${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"

# 1. 检查配置文件
echo -e "\n${YELLOW}[1/4] 检查配置文件...${NC}"
if [ ! -f "config.env" ]; then
    echo -e "${RED}❌ 配置文件 config.env 不存在${NC}"
    echo -e "${YELLOW}请先创建配置文件:${NC}"
    echo "  cp config.env.example config.env"
    echo "  vim config.env"
    exit 1
fi
echo -e "${GREEN}✅ 配置文件已存在${NC}"

# 2. 检查 cloudflared
echo -e "\n${YELLOW}[2/4] 检查 cloudflared...${NC}"
if ! command -v cloudflared &> /dev/null; then
    echo -e "${YELLOW}cloudflared 未安装，正在安装...${NC}"
    curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
    echo -e "${GREEN}✅ cloudflared 安装完成${NC}"
else
    echo -e "${GREEN}✅ cloudflared 已安装${NC}"
fi

# 3. 清理旧进程
echo -e "\n${YELLOW}[3/4] 清理旧进程...${NC}"
pkill -f cloudflared 2>/dev/null || true
pkill -f "proxy.py" 2>/dev/null || true
pkill -f "container_keeper" 2>/dev/null || true
pkill -f "ultimate_keeper" 2>/dev/null || true
sleep 1
echo -e "${GREEN}✅ 旧进程已清理${NC}"

# 4. 启动服务
echo -e "\n${YELLOW}[4/4] 启动保活服务...${NC}"
echo -e "${BLUE}运行时长: ${DURATION} 秒${NC}"
echo -e "${BLUE}开始时间: $(date '+%H:%M:%S')${NC}"
echo ""

# 使用 timeout 控制运行时间（额外加 10 秒缓冲）
timeout $((DURATION + 10)) python3 container_keeper.py --duration "$DURATION"

echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ 服务已停止${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
