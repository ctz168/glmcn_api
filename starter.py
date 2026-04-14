#!/usr/bin/env python3
"""
API 服务启动器 v1 - 统一启动入口

功能：
  - 启动 proxy + ngrok 服务
  - 验证 API 可用性
  - 保活机制自循环调用
  - 每 5 秒检查服务状态
  - 每 30 秒报告状态
  - 自动修复停止的服务
  - timeout 280 控制运行时间

用法：
  python3 starter.py [--timeout 280] [--no-verify]
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

# ═════════════ 从 config.env 读取配置 ═════════════
def load_config():
    config = {}
    search_paths = [
        '/home/z/my-project/config.env',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.env'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config.env'),
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
PROXY_PORT = 8082
WORK_DIR = CFG.get('WORK_DIR', '/home/z/my-project')
LOG_FILE = CFG.get('LOG_FILE', f'{WORK_DIR}/seamless.log')

# 脚本路径 - 优先使用 glmcn_api 子目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_SCRIPT = os.path.join(SCRIPT_DIR, 'proxy.py') if os.path.exists(os.path.join(SCRIPT_DIR, 'proxy.py')) else os.path.join(WORK_DIR, 'proxy.py')
WATCHDOG_SCRIPT = os.path.join(SCRIPT_DIR, 'watchdog.py') if os.path.exists(os.path.join(SCRIPT_DIR, 'watchdog.py')) else os.path.join(WORK_DIR, 'watchdog.py')

# ═════════════ 全局状态 ═════════════
class State:
    running = True
    proxy_ok = False
    ngrok_ok = False
    ngrok_url = ''
    start_time = 0
    check_count = 0
    repair_count = 0
    api_verified = False

state = State()

# ═════════════ 日志 ═════════════
def ts():
    return time.strftime("%H:%M:%S")

def log(msg, level="INFO"):
    line = f"[{ts()}] [starter] [{level}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

# ═════════════ 服务检查 ═════════════
def check_proxy():
    try:
        conn = http.client.HTTPConnection("127.0.0.1", PROXY_PORT, timeout=2)
        conn.request("GET", "/_ping")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status == 200
    except:
        return False

def check_ngrok():
    try:
        result = subprocess.run(["pgrep", "-x", "ngrok"], capture_output=True, timeout=2)
        if result.returncode != 0:
            return False, "no_process"
        conn = http.client.HTTPConnection("127.0.0.1", 4040, timeout=2)
        conn.request("GET", "/api/tunnels")
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        tunnels = json.loads(body).get('tunnels', [])
        if tunnels:
            return True, tunnels[0].get('public_url', '')
        return False, "no_tunnel"
    except:
        return False, "check_error"

def get_ngrok_url():
    try:
        conn = http.client.HTTPConnection("127.0.0.1", 4040, timeout=2)
        conn.request("GET", "/api/tunnels")
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        tunnels = json.loads(body).get('tunnels', [])
        if tunnels:
            return tunnels[0].get('public_url', '')
    except:
        pass
    return ''

# ═════════════ 服务启动 ═════════════
def start_proxy():
    log("启动 Python 代理...")
    
    # 先杀掉旧进程
    subprocess.run(["pkill", "-9", "-f", f"python3.*{PROXY_SCRIPT}"],
                   capture_output=True, timeout=3)
    time.sleep(0.3)
    
    env = os.environ.copy()
    env['SELF_RESTART'] = '1'
    
    proc = subprocess.Popen(
        [sys.executable, PROXY_SCRIPT, '--no-daemon'],
        stdout=open(LOG_FILE, "a"),
        stderr=open(LOG_FILE, "a"),
        start_new_session=True,
        env=env,
    )
    
    # 等待就绪
    for i in range(25):
        time.sleep(0.2)
        if check_proxy():
            log(f"代理启动成功 (PID {proc.pid}, 端口 {PROXY_PORT})")
            return True
    
    log("代理启动失败", "ERROR")
    return False

def start_ngrok():
    log("启动 ngrok 隧道...")
    
    # 先杀掉旧进程
    subprocess.run(["pkill", "-9", "-f", "ngrok"], capture_output=True, timeout=3)
    time.sleep(0.5)
    
    # 配置 authtoken
    if NGROK_AUTHTOKEN:
        subprocess.run([NGROK_PATH, "config", "add-authtoken", NGROK_AUTHTOKEN],
                     capture_output=True, timeout=5)
    
    # 构建 ngrok 命令
    cmd = [NGROK_PATH, "http", f"http://127.0.0.1:{PROXY_PORT}",
           "--log=stdout", "--log-format=logfmt"]
    
    # 如果有固定域名
    if NGROK_DOMAIN:
        cmd.extend(["--domain", f"{NGROK_DOMAIN}.ngrok-free.dev"])
    
    subprocess.Popen(
        cmd,
        stdout=open(LOG_FILE, "a"),
        stderr=open(LOG_FILE, "a"),
        start_new_session=True,
    )
    
    # 等待就绪
    for i in range(100):
        time.sleep(0.2)
        ok, url = check_ngrok()
        if ok:
            log(f"ngrok 隧道建立成功: {url}")
            return True, url
    
    log("ngrok 隧道建立失败", "ERROR")
    return False, ''

def start_watchdog():
    log("启动 watchdog 守护进程...")
    subprocess.Popen(
        [sys.executable, WATCHDOG_SCRIPT, "--holder", "starter"],
        stdout=open(LOG_FILE, "a"),
        stderr=open(LOG_FILE, "a"),
        start_new_session=True,
    )
    time.sleep(1)
    log("watchdog 已启动")

# ═════════════ 服务修复 ═════════════
def repair_proxy():
    log("修复代理...", "WARN")
    state.repair_count += 1
    return start_proxy()

def repair_ngrok():
    log("修复 ngrok...", "WARN")
    state.repair_count += 1
    ok, url = start_ngrok()
    if ok:
        state.ngrok_url = url
    return ok

# ═════════════ API 验证 ═════════════
def verify_api():
    """验证 API 可用性"""
    if not state.ngrok_url:
        return False
    
    log("验证 API 可用性...")
    try:
        import urllib.request
        url = f"{state.ngrok_url}/v1/chat/completions"
        data = json.dumps({
            "model": "glm-4-flash",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 10,
            "stream": False
        }).encode()
        
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Authorization', f'Bearer {API_KEY}')
        req.add_header('ngrok-skip-browser-warning', 'true')
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            if 'choices' in result:
                content = result['choices'][0]['message']['content']
                log(f"API 验证成功！AI 回复: {content}")
                return True
    except Exception as e:
        log(f"API 验证失败: {e}", "ERROR")
    
    return False

def keepalive_call():
    """保活调用 - 自循环调用 API"""
    if not state.ngrok_url:
        return False
    
    try:
        import urllib.request
        url = f"{state.ngrok_url}/v1/chat/completions"
        data = json.dumps({
            "model": "glm-4-flash",
            "messages": [{"role": "user", "content": "keepalive"}],
            "max_tokens": 5,
            "stream": False
        }).encode()
        
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Authorization', f'Bearer {API_KEY}')
        req.add_header('ngrok-skip-browser-warning', 'true')
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return 'choices' in result
    except:
        return False

# ═════════════ 状态报告 ═════════════
def report_status():
    """报告服务状态"""
    elapsed = int(time.time() - state.start_time)
    p = "✅" if state.proxy_ok else "❌"
    n = "✅" if state.ngrok_ok else "❌"
    v = "✅" if state.api_verified else "❌"
    
    log(f"📊 状态报告 | 运行:{elapsed}s | 代理:{p} | ngrok:{n} | API:{v} | 检查:{state.check_count}次 | 修复:{state.repair_count}次 | URL:{state.ngrok_url}")

# ═════════════ 信号处理 ═════════════
def handle_signal(signum, frame):
    elapsed = int(time.time() - state.start_time)
    log(f"收到退出信号，准备退出 (已运行 {elapsed}s)")
    state.running = False

# ═════════════ 主函数 ═════════════
def main():
    parser = argparse.ArgumentParser(description="API 服务启动器")
    parser.add_argument("--timeout", type=int, default=280, help="运行超时时间（秒）")
    parser.add_argument("--no-verify", action="store_true", help="跳过 API 验证")
    parser.add_argument("--check-interval", type=int, default=5, help="检查间隔（秒）")
    parser.add_argument("--report-interval", type=int, default=30, help="报告间隔（秒）")
    args = parser.parse_args()
    
    state.start_time = time.time()
    
    log("════════════════════════════════════════")
    log("🚀 API 服务启动器 v1")
    log(f"   超时: {args.timeout}s | 检查间隔: {args.check_interval}s | 报告间隔: {args.report_interval}s")
    log("════════════════════════════════════════")
    
    # 注册信号处理
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    # 设置超时
    def timeout_handler():
        log(f"⏰ 达到超时时间 {args.timeout}s，准备退出")
        state.running = False
    
    timeout_timer = threading.Timer(args.timeout, timeout_handler)
    timeout_timer.start()
    
    # ─── Step 1: 启动服务 ───
    log("📦 启动服务...")
    
    # 启动 proxy
    if not check_proxy():
        if not start_proxy():
            log("代理启动失败，退出", "ERROR")
            return 1
    else:
        log("代理已在运行")
    
    # 启动 ngrok
    ok, url = check_ngrok()
    if not ok:
        ok, url = start_ngrok()
        if not ok:
            log("ngrok 启动失败，退出", "ERROR")
            return 1
    else:
        log(f"ngrok 已在运行: {url}")
    
    state.ngrok_url = url
    
    # 启动 watchdog
    if not os.path.exists(WATCHDOG_SCRIPT):
        log(f"watchdog 脚本不存在: {WATCHDOG_SCRIPT}", "WARN")
    else:
        start_watchdog()
    
    # ─── Step 2: 验证 API ───
    if not args.no_verify:
        state.api_verified = verify_api()
        if not state.api_verified:
            log("API 验证失败，但继续运行", "WARN")
    
    # ─── Step 3: 主循环 ───
    log("✅ 服务启动完成，进入监控循环")
    report_status()
    
    last_report = time.time()
    last_keepalive = time.time()
    
    while state.running:
        time.sleep(args.check_interval)
        state.check_count += 1
        
        # 检查服务状态
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
        
        # 每 30 秒报告状态
        now = time.time()
        if now - last_report >= args.report_interval:
            report_status()
            last_report = now
        
        # 每 60 秒保活调用
        if now - last_keepalive >= 60:
            if keepalive_call():
                log("🔄 保活调用成功")
            last_keepalive = now
        
        # 检查是否超时
        if time.time() - state.start_time >= args.timeout:
            break
    
    # ─── Step 4: 退出 ───
    timeout_timer.cancel()
    elapsed = int(time.time() - state.start_time)
    
    log("════════════════════════════════════════")
    log(f"🏁 服务退出 | 运行:{elapsed}s | 检查:{state.check_count}次 | 修复:{state.repair_count}次")
    log("════════════════════════════════════════")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
