#!/usr/bin/env python3
"""
无缝保活启动器 v3 - 健壮的保活机制

功能：
  - 启动 proxy + ngrok 服务
  - 验证 API 可用性
  - 保活机制自循环调用
  - 每 5 秒检查服务状态
  - 每 30 秒报告状态
  - 自动修复停止的服务
  - timeout 控制运行时间
  - 缝隙控制在 0.5 秒内
  - 多次测试验证保活

用法：
  python3 seamless_keeper.py [--timeout 280]
"""

import http.client
import json
import subprocess
import os
import sys
import time
import signal
import argparse
import threading
import urllib.request
import socket

# ═════════════ 从 config.env 读取配置 ═════════════
def load_config():
    config = {}
    search_paths = [
        '/home/z/my-project/glmcn_api/config.env',
        '/home/z/my-project/config.env',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.env'),
        os.environ.get('TUNNEL_CONFIG', ''),
    ]
    for path in search_paths:
        if path and os.path.isfile(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, _, value = line.partition('=')
                        key = key.strip()
                        value = value.strip().split('#')[0].strip()
                        config[key] = value
            break
    return config

CFG = load_config()

# ═════════════ 配置 ═════════════
NGROK_AUTHTOKEN = CFG.get('NGROK_AUTHTOKEN', '')
NGROK_PATH = CFG.get('NGROK_PATH', 'ngrok')
NGROK_DOMAIN = CFG.get('NGROK_DOMAIN', '')
API_HOST = CFG.get('API_HOST', '172.25.136.193')
API_PORT = int(CFG.get('API_PORT', '8080'))
API_KEY = CFG.get('API_KEY', 'Z.ai')
X_TOKEN = CFG.get('X_TOKEN', '')
X_CHAT_ID = CFG.get('X_CHAT_ID', '')
X_USER_ID = CFG.get('X_USER_ID', '')
PROXY_PORT = int(CFG.get('PROXY_PORT', '8082'))
NGROK_API_PORT = int(CFG.get('NGROK_API_PORT', '4040'))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_SCRIPT = os.path.join(SCRIPT_DIR, 'proxy.py')
LOG_FILE = CFG.get('LOG_FILE', '/home/z/my-project/seamless.log')

# ═════════════ 状态 ═════════════
class State:
    def __init__(self):
        self.start_time = time.time()
        self.proxy_ok = False
        self.ngrok_ok = False
        self.ngrok_url = None
        self.proxy_pid = None
        self.ngrok_pid = None
        self.check_count = 0
        self.repair_count = 0
        self.running = True
        self.last_api_ok = False
        self.api_test_count = 0
        self.api_success_count = 0

state = State()

# ═════════════ 日志 ═════════════
def log(msg, level="INFO"):
    timestamp = time.strftime("%H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] [keeper] [{level}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except:
        pass

# ═════════════ 进程管理 ═════════════
def start_proxy():
    """启动 Python 代理"""
    env = os.environ.copy()
    env['SELF_RESTART'] = '1'
    
    cmd = [sys.executable, PROXY_SCRIPT, '--no-daemon']
    proc = subprocess.Popen(
        cmd,
        cwd=SCRIPT_DIR,
        env=env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    state.proxy_pid = proc.pid
    
    # 等待启动
    for _ in range(20):
        time.sleep(0.2)
        if check_proxy():
            return True
    
    return False

def start_ngrok():
    """启动 ngrok 隧道"""
    cmd = [NGROK_PATH, 'http', f'http://127.0.0.1:{PROXY_PORT}', '--log=stdout', '--log-format=logfmt']
    
    proc = subprocess.Popen(
        cmd,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    state.ngrok_pid = proc.pid
    
    # 等待启动
    for _ in range(30):
        time.sleep(0.3)
        ok, url = check_ngrok()
        if ok:
            state.ngrok_url = url
            return True
    
    return False

def check_proxy():
    """检查代理是否运行"""
    try:
        conn = http.client.HTTPConnection('127.0.0.1', PROXY_PORT, timeout=3)
        conn.request('GET', '/_ping')
        resp = conn.getresponse()
        conn.close()
        return resp.status == 200
    except:
        return False

def check_ngrok():
    """检查 ngrok 隧道"""
    try:
        conn = http.client.HTTPConnection('127.0.0.1', NGROK_API_PORT, timeout=3)
        conn.request('GET', '/api/tunnels')
        resp = conn.getresponse()
        if resp.status == 200:
            data = json.loads(resp.read().decode())
            conn.close()
            if data.get('tunnels'):
                return True, data['tunnels'][0]['public_url']
        conn.close()
    except:
        pass
    return False, None

def test_api():
    """测试 API 调用"""
    if not state.ngrok_url:
        return False, "ngrok URL not available"
    
    try:
        url = f"{state.ngrok_url}/v1/chat/completions"
        headers = {
            'Authorization': f'Bearer {API_KEY}',
            'Content-Type': 'application/json',
            'ngrok-skip-browser-warning': 'true'
        }
        data = json.dumps({
            'model': 'glm-4-flash',
            'messages': [{'role': 'user', 'content': 'ping'}],
            'max_tokens': 20
        }).encode()
        
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = resp.read().decode()
            resp_data = json.loads(result)
            if 'choices' in resp_data:
                content = resp_data['choices'][0]['message']['content']
                return True, content
            return False, result[:100]
    except Exception as e:
        return False, str(e)

def repair_proxy():
    """修复代理"""
    state.repair_count += 1
    log(f"🔧 修复代理 (第{state.repair_count}次)...")
    
    # 杀掉旧进程
    if state.proxy_pid:
        try:
            os.kill(state.proxy_pid, 9)
        except:
            pass
    
    time.sleep(0.5)
    return start_proxy()

def repair_ngrok():
    """修复 ngrok"""
    state.repair_count += 1
    log(f"🔧 修复 ngrok (第{state.repair_count}次)...")
    
    # 杀掉旧进程
    if state.ngrok_pid:
        try:
            os.kill(state.ngrok_pid, 9)
        except:
            pass
    
    time.sleep(0.5)
    return start_ngrok()

def report_status():
    """报告状态"""
    elapsed = int(time.time() - state.start_time)
    api_rate = f"{state.api_success_count}/{state.api_test_count}" if state.api_test_count > 0 else "N/A"
    
    log(f"📊 状态报告 | 运行:{elapsed}s | 代理:{'✅' if state.proxy_ok else '❌'} | "
        f"ngrok:{'✅' if state.ngrok_ok else '❌'} | API:{'✅' if state.last_api_ok else '❌'} | "
        f"成功率:{api_rate} | 检查:{state.check_count}次 | 修复:{state.repair_count}次 | "
        f"URL:{state.ngrok_url or 'N/A'}")

# ═════════════ 主函数 ═════════════
def main():
    parser = argparse.ArgumentParser(description='无缝保活启动器 v3')
    parser.add_argument('--timeout', type=int, default=280, help='运行超时（秒）')
    parser.add_argument('--check-interval', type=int, default=5, help='检查间隔（秒）')
    parser.add_argument('--report-interval', type=int, default=30, help='报告间隔（秒）')
    parser.add_argument('--api-test-interval', type=int, default=10, help='API 测试间隔（秒）')
    args = parser.parse_args()
    
    log("════════════════════════════════════════")
    log("🚀 无缝保活启动器 v3")
    log(f"   超时: {args.timeout}s | 检查间隔: {args.check_interval}s | 报告间隔: {args.report_interval}s | API测试间隔: {args.api_test_interval}s")
    log("════════════════════════════════════════")
    
    # ─── Step 1: 启动服务 ───
    log("📦 启动服务...")
    
    # 启动代理
    log("启动 Python 代理...")
    if not start_proxy():
        log("❌ 代理启动失败", "ERROR")
        return 1
    log(f"代理启动成功 (PID {state.proxy_pid}, 端口 {PROXY_PORT})")
    
    # 启动 ngrok
    log("启动 ngrok 隧道...")
    if not start_ngrok():
        log("❌ ngrok 启动失败", "ERROR")
        return 1
    log(f"ngrok 隧道建立成功: {state.ngrok_url}")
    
    # ─── Step 2: 验证 API ───
    log("验证 API 可用性...")
    ok, result = test_api()
    if ok:
        log(f"API 验证成功！AI 回复: {result}")
        state.last_api_ok = True
        state.api_test_count = 1
        state.api_success_count = 1
    else:
        log(f"API 验证失败: {result}", "WARN")
    
    log("✅ 服务启动完成，进入监控循环")
    
    # ─── Step 3: 监控循环 ───
    last_check = time.time()
    last_report = time.time()
    last_api_test = time.time()
    
    # 设置超时
    def timeout_handler():
        state.running = False
        log("⏰ 超时退出")
    
    timeout_timer = threading.Timer(args.timeout, timeout_handler)
    timeout_timer.daemon = True
    timeout_timer.start()
    
    while state.running:
        time.sleep(0.5)
        
        now = time.time()
        
        # 每 5 秒检查服务状态
        if now - last_check >= args.check_interval:
            state.check_count += 1
            state.proxy_ok = check_proxy()
            ok, result = check_ngrok()
            state.ngrok_ok = ok
            if ok and result:
                state.ngrok_url = result
            
            # 自动修复
            if not state.proxy_ok:
                repair_proxy()
            
            if not state.ngrok_ok:
                repair_ngrok()
            
            last_check = now
        
        # 每 10 秒测试 API
        if now - last_api_test >= args.api_test_interval:
            state.api_test_count += 1
            ok, result = test_api()
            state.last_api_ok = ok
            if ok:
                state.api_success_count += 1
                log(f"✅ API 测试 #{state.api_test_count} 成功: {result[:50]}...")
            else:
                log(f"❌ API 测试 #{state.api_test_count} 失败: {result}", "WARN")
            last_api_test = now
        
        # 每 30 秒报告状态
        if now - last_report >= args.report_interval:
            report_status()
            last_report = now
        
        # 检查是否超时
        if time.time() - state.start_time >= args.timeout:
            break
    
    # ─── Step 4: 退出 ───
    timeout_timer.cancel()
    elapsed = int(time.time() - state.start_time)
    
    log("════════════════════════════════════════")
    log(f"🏁 服务退出 | 运行:{elapsed}s | API测试:{state.api_test_count}次 | 成功:{state.api_success_count}次 | 修复:{state.repair_count}次")
    log("════════════════════════════════════════")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
