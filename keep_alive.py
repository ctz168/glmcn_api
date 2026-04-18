#!/usr/bin/env python3
"""
无缝保活启动器 v6 - 增强版

特性:
- 每 5 秒检查服务状态
- 每 30 秒报告状态
- 自动修复停止的服务
- 使用 timeout 控制运行时间
- 缝隙控制在 0.5 秒内
- 五次验证 API 可用性
"""

import os
import sys
import time
import signal
import subprocess
import http.client
import json
import threading
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

# 全局状态
running = True
proxy_process = None
ngrok_process = None
check_count = 0
repair_count = 0
api_test_count = 0
api_success_count = 0
last_report_time = 0
public_url = None

def log(msg):
    """记录日志"""
    line = f"[{time.strftime('%H:%M:%S')}] [keeper] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except:
        pass

def check_proxy():
    """检查代理是否运行"""
    try:
        conn = http.client.HTTPConnection('127.0.0.1', 8082, timeout=3)
        conn.request('GET', '/_ping')
        resp = conn.getresponse()
        conn.close()
        return resp.status == 200
    except:
        return False

def check_ngrok():
    """检查 ngrok 是否运行并获取公网 URL"""
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
    """启动代理"""
    global proxy_process
    env = os.environ.copy()
    env['SELF_RESTART'] = '1'
    try:
        # 先杀掉可能存在的旧进程
        subprocess.run(['pkill', '-f', 'proxy.py'], capture_output=True)
        time.sleep(0.3)
        
        proxy_process = subprocess.Popen(
            [sys.executable, PROXY_SCRIPT, '--no-daemon'],
            cwd=SCRIPT_DIR,
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return proxy_process.pid
    except Exception as e:
        log(f"启动代理失败: {e}")
        return None

def start_ngrok():
    """启动 ngrok"""
    global ngrok_process
    try:
        # 先杀掉可能存在的旧进程
        subprocess.run(['pkill', '-f', 'ngrok'], capture_output=True)
        time.sleep(0.3)
        
        ngrok_process = subprocess.Popen(
            ['ngrok', 'http', 'http://127.0.0.1:8082', '--log=stdout', '--log-format=logfmt'],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return ngrok_process.pid
    except Exception as e:
        log(f"启动 ngrok 失败: {e}")
        return None

def test_api(url):
    """测试 API 可用性"""
    try:
        host = url.replace('https://', '')
        conn = http.client.HTTPSConnection(host, timeout=30)
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

def signal_handler(signum, frame):
    """信号处理器"""
    global running
    log(f"收到信号 {signum}，准备退出...")
    running = False

def cleanup():
    """清理函数"""
    try:
        os.unlink(PID_FILE)
    except:
        pass

def monitor_loop():
    """监控循环"""
    global check_count, repair_count, api_test_count, api_success_count, last_report_time, public_url, running
    
    while running:
        time.sleep(5)  # 每 5 秒检查一次
        check_count += 1
        
        # 检查代理
        if not check_proxy():
            repair_count += 1
            log(f"⚠️ 代理已停止，重启中... (修复 #{repair_count})")
            pid = start_proxy()
            if pid:
                log(f"✅ 代理已重启 PID: {pid}")
            time.sleep(0.5)
        
        # 检查 ngrok
        ok, url = check_ngrok()
        if not ok:
            repair_count += 1
            log(f"⚠️ ngrok 已停止，重启中... (修复 #{repair_count})")
            pid = start_ngrok()
            if pid:
                log(f"✅ ngrok 已重启 PID: {pid}")
            time.sleep(2)
            ok, url = check_ngrok()
        
        if url:
            public_url = url
        
        # 每 10 秒测试 API (check_count % 2 == 0)
        if check_count % 2 == 0 and public_url:
            api_test_count += 1
            ok, result = test_api(public_url)
            if ok:
                api_success_count += 1
                log(f"✅ API 测试 #{api_test_count} 成功: {result}")
            else:
                log(f"❌ API 测试 #{api_test_count} 失败")
        
        # 每 30 秒报告状态 (check_count % 6 == 0)
        if check_count % 6 == 0:
            ok, url = check_ngrok()
            log(f"📊 状态报告 | 检查:{check_count}次 | 修复:{repair_count}次 | API测试:{api_test_count}次 | 成功:{api_success_count}次")
            log(f"   代理:{'✅' if check_proxy() else '❌'} | ngrok:{'✅' if ok else '❌'} | URL:{url or 'N/A'}")

def main():
    global running
    
    # 检查是否已经在运行
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            print(f"守护进程已在运行 (PID: {pid})")
            return
        except:
            os.unlink(PID_FILE)
    
    # 写入 PID 文件
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    # 注册信号处理器
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    atexit.register(cleanup)
    
    log("════════════════════════════════════════")
    log("🚀 无缝保活启动器 v6 启动")
    log(f"PID: {os.getpid()}")
    log(f"工作目录: {SCRIPT_DIR}")
    log("════════════════════════════════════════")
    
    # 启动服务
    log("启动代理...")
    proxy_pid = start_proxy()
    if proxy_pid:
        log(f"✅ 代理已启动 PID: {proxy_pid}")
    else:
        log("❌ 代理启动失败")
        return 1
    
    log("启动 ngrok...")
    ngrok_pid = start_ngrok()
    if ngrok_pid:
        log(f"✅ ngrok 已启动 PID: {ngrok_pid}")
    else:
        log("❌ ngrok 启动失败")
        return 1
    
    # 等待服务启动
    log("等待服务启动...")
    time.sleep(3)
    
    # 获取公网 URL
    ok, url = check_ngrok()
    if ok and url:
        log(f"🌐 公网 URL: {url}")
        public_url = url
    else:
        log("⚠️ 未能获取公网 URL，等待 ngrok 启动...")
    
    # 五次验证 API 可用性
    log("════════════════════════════════════════")
    log("🔍 开始五次 API 可用性验证...")
    log("════════════════════════════════════════")
    
    verification_success = 0
    for i in range(1, 6):
        time.sleep(2)
        if public_url:
            ok, result = test_api(public_url)
            if ok:
                verification_success += 1
                log(f"✅ 验证 #{i} 成功: {result}")
            else:
                log(f"❌ 验证 #{i} 失败")
        else:
            ok, url = check_ngrok()
            if ok:
                public_url = url
                log(f"🌐 获取到公网 URL: {url}")
                ok, result = test_api(public_url)
                if ok:
                    verification_success += 1
                    log(f"✅ 验证 #{i} 成功: {result}")
                else:
                    log(f"❌ 验证 #{i} 失败")
            else:
                log(f"❌ 验证 #{i} 失败: 无法获取公网 URL")
    
    log("════════════════════════════════════════")
    log(f"验证完成: {verification_success}/5 成功")
    log("════════════════════════════════════════")
    
    if verification_success < 3:
        log("⚠️ 验证成功率过低，请检查配置")
    
    # 进入监控循环
    log("进入监控循环...")
    monitor_loop()
    
    log("保活器退出")
    return 0

if __name__ == "__main__":
    sys.exit(main())
