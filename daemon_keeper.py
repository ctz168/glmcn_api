#!/usr/bin/env python3
"""
守护进程保活器 v5 - 真正的独立守护进程

使用 double-fork 技术创建完全独立的守护进程
"""

import os
import sys
import time
import signal
import subprocess
import http.client
import json
import atexit

# 配置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_SCRIPT = os.path.join(SCRIPT_DIR, 'proxy.py')
LOG_FILE = os.path.join(SCRIPT_DIR, 'seamless.log')
PID_FILE = os.path.join(SCRIPT_DIR, 'keeper.pid')

# 从 config.env 读取配置
def load_config():
    config = {}
    config_path = os.path.join(SCRIPT_DIR, 'config.env')
    if os.path.isfile(config_path):
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip()
                    if '#' in value:
                        value = value[:value.index('#')].strip()
                    config[key] = value
    return config

CONFIG = load_config()
NGROK_AUTHTOKEN = CONFIG.get('NGROK_AUTHTOKEN', '')

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] [daemon] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except:
        pass

def daemonize():
    """Double-fork 创建独立守护进程"""
    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent exits
        sys.exit(0)
    
    # Decouple from parent environment
    os.chdir('/')
    os.setsid()
    os.umask(0)
    
    # Second fork
    pid = os.fork()
    if pid > 0:
        # First child exits
        sys.exit(0)
    
    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()
    
    with open('/dev/null', 'r') as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())
    
    with open(LOG_FILE, 'a') as log:
        os.dup2(log.fileno(), sys.stdout.fileno())
        os.dup2(log.fileno(), sys.stderr.fileno())
    
    # Write PID file
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

def check_proxy():
    try:
        conn = http.client.HTTPConnection('127.0.0.1', 8082, timeout=3)
        conn.request('GET', '/_ping')
        resp = conn.getresponse()
        conn.close()
        return resp.status == 200
    except:
        return False

def check_ngrok():
    try:
        conn = http.client.HTTPConnection('127.0.0.1', 4040, timeout=3)
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

def start_proxy():
    env = os.environ.copy()
    env['SELF_RESTART'] = '1'
    proc = subprocess.Popen(
        [sys.executable, PROXY_SCRIPT, '--no-daemon'],
        cwd=SCRIPT_DIR,
        env=env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return proc.pid

def start_ngrok():
    proc = subprocess.Popen(
        ['ngrok', 'http', 'http://127.0.0.1:8082', '--log=stdout', '--log-format=logfmt'],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return proc.pid

def test_api(url):
    try:
        conn = http.client.HTTPSConnection(url.replace('https://', ''), timeout=30)
        body = json.dumps({
            "model": "glm-4-flash",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 20
        })
        conn.request('POST', '/v1/chat/completions', body, {
            'Authorization': 'Bearer Z.ai',
            'Content-Type': 'application/json',
            'ngrok-skip-browser-warning': 'true'
        })
        resp = conn.getresponse()
        if resp.status == 200:
            data = json.loads(resp.read().decode())
            conn.close()
            if 'choices' in data:
                return True, data['choices'][0]['message']['content'][:30]
        conn.close()
    except Exception as e:
        pass
    return False, None

def cleanup():
    """清理 PID 文件"""
    try:
        os.unlink(PID_FILE)
    except:
        pass

def main():
    # 检查是否已经在运行
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            # 检查进程是否存在
            os.kill(pid, 0)
            print(f"守护进程已在运行 (PID: {pid})")
            return
        except:
            # PID 文件存在但进程不存在，删除 PID 文件
            os.unlink(PID_FILE)
    
    # 守护化
    daemonize()
    
    # 注册清理函数
    atexit.register(cleanup)
    
    log("════════════════════════════════════════")
    log("🚀 守护进程保活器 v5 启动")
    log(f"PID: {os.getpid()}")
    log("════════════════════════════════════════")
    
    # 启动服务
    proxy_pid = start_proxy()
    log(f"启动代理 PID: {proxy_pid}")
    
    ngrok_pid = start_ngrok()
    log(f"启动 ngrok PID: {ngrok_pid}")
    
    # 等待启动
    time.sleep(3)
    
    check_count = 0
    repair_count = 0
    api_test_count = 0
    api_success_count = 0
    
    # 监控循环
    while True:
        time.sleep(5)
        check_count += 1
        
        # 检查代理
        if not check_proxy():
            repair_count += 1
            log(f"⚠️ 代理已停止，重启中... (修复 #{repair_count})")
            proxy_pid = start_proxy()
            time.sleep(1)
        
        # 检查 ngrok
        ok, url = check_ngrok()
        if not ok:
            repair_count += 1
            log(f"⚠️ ngrok 已停止，重启中... (修复 #{repair_count})")
            ngrok_pid = start_ngrok()
            time.sleep(2)
            ok, url = check_ngrok()
        
        # 每 10 秒测试 API
        if check_count % 2 == 0 and url:
            api_test_count += 1
            ok, result = test_api(url)
            if ok:
                api_success_count += 1
                log(f"✅ API 测试 #{api_test_count} 成功: {result}")
            else:
                log(f"❌ API 测试 #{api_test_count} 失败")
        
        # 每 30 秒报告状态
        if check_count % 6 == 0:
            ok, url = check_ngrok()
            log(f"📊 状态报告 | 检查:{check_count}次 | 修复:{repair_count}次 | API测试:{api_test_count}次 | 成功:{api_success_count}次")
            log(f"   代理:{'✅' if check_proxy() else '❌'} | ngrok:{'✅' if ok else '❌'} | URL:{url or 'N/A'}")

if __name__ == "__main__":
    main()
