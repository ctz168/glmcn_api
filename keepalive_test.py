#!/usr/bin/env python3
"""
无缝保活测试脚本
- 每 5 秒检查服务状态
- 每 30 秒报告状态
- 自动修复停止的服务
- 进行 API 测试
- 运行 5 分钟
"""

import os
import sys
import time
import signal
import subprocess
import http.client
import json
import urllib.request
import ssl
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, 'keepalive_test.log')

# 全局状态
running = True
check_count = 0
repair_count = 0
api_test_count = 0
api_success_count = 0
public_url = None
start_time = None
duration = 300  # 5 分钟

def log(msg):
    """记录日志"""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except:
        pass

def signal_handler(signum, frame):
    """信号处理"""
    global running
    log(f"收到信号 {signum}，准备退出...")
    running = False

def check_proxy():
    """检查代理是否运行"""
    try:
        conn = http.client.HTTPConnection('127.0.0.1', 8082, timeout=3)
        conn.request('GET', '/_ping')
        resp = conn.getresponse()
        data = resp.read().decode()
        conn.close()
        return data.strip() == 'pong'
    except:
        return False

def check_ngrok():
    """检查 ngrok 是否运行"""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'ngrok'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return True
        return False
    except:
        return False

def get_ngrok_url():
    """获取 ngrok 公网 URL"""
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

def start_proxy():
    """启动代理"""
    log("启动代理...")
    try:
        subprocess.run(["pkill", "-9", "-f", "proxy.py"], capture_output=True, timeout=3)
        time.sleep(0.3)
        
        proxy_script = os.path.join(SCRIPT_DIR, 'proxy.py')
        env = os.environ.copy()
        env['SELF_RESTART'] = '1'
        
        proc = subprocess.Popen(
            [sys.executable, proxy_script, '--no-daemon'],
            stdout=open(LOG_FILE, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
            cwd=SCRIPT_DIR
        )
        
        for _ in range(25):
            time.sleep(0.2)
            if check_proxy():
                log(f"✅ 代理启动成功 (PID {proc.pid})")
                return proc
        
        log("❌ 代理启动失败")
        return None
    except Exception as e:
        log(f"❌ 代理启动异常: {e}")
        return None

def start_ngrok():
    """启动 ngrok"""
    log("启动 ngrok...")
    try:
        subprocess.run(["pkill", "-9", "-f", "ngrok"], capture_output=True, timeout=3)
        time.sleep(0.5)
        
        # 读取配置
        config_path = os.path.join(SCRIPT_DIR, 'config.env')
        ngrok_authtoken = ''
        if os.path.isfile(config_path):
            with open(config_path) as f:
                for line in f:
                    if line.startswith('NGROK_AUTHTOKEN='):
                        ngrok_authtoken = line.split('=')[1].strip()
                        break
        
        if ngrok_authtoken:
            subprocess.run(["ngrok", "config", "add-authtoken", ngrok_authtoken],
                         capture_output=True, timeout=5)
        
        proc = subprocess.Popen(
            ["ngrok", "http", "http://127.0.0.1:8082", "--log=stdout", "--pooling-enabled"],
            stdout=open(LOG_FILE, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        
        for _ in range(100):
            time.sleep(0.2)
            url = get_ngrok_url()
            if url:
                log(f"✅ ngrok 隧道建立成功 (URL: {url})")
                return proc, url
        
        log("❌ ngrok 隧道建立超时")
        return None, None
    except Exception as e:
        log(f"❌ ngrok 启动异常: {e}")
        return None, None

def test_api(url):
    """测试 API"""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        data = json.dumps({
            "model": "glm-4-flash",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 5
        }).encode('utf-8')
        
        req = urllib.request.Request(
            f"{url}/v1/chat/completions",
            data=data,
            headers={
                'Authorization': 'Bearer Z.ai',
                'Content-Type': 'application/json'
            }
        )
        
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            result = json.loads(resp.read().decode())
            if 'choices' in result:
                content = result['choices'][0]['message']['content']
                return True, content[:50]
            return False, str(result)
    except Exception as e:
        return False, str(e)[:50]

def main():
    global running, check_count, repair_count, api_test_count, api_success_count, public_url, start_time, duration
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    start_time = datetime.now()
    end_time = start_time + timedelta(seconds=duration)
    
    log("════════════════════════════════════════")
    log("🚀 无缝保活测试启动")
    log(f"PID: {os.getpid()}")
    log(f"工作目录: {SCRIPT_DIR}")
    log(f"计划运行时长: {duration} 秒")
    log(f"开始时间: {start_time.strftime('%H:%M:%S')}")
    log(f"预计结束: {end_time.strftime('%H:%M:%S')}")
    log("════════════════════════════════════════")
    
    # 启动代理
    proxy_process = start_proxy()
    if not proxy_process:
        log("❌ 无法启动代理，退出")
        return 1
    
    # 启动 ngrok
    ngrok_process, public_url = start_ngrok()
    if not ngrok_process:
        log("❌ 无法启动 ngrok，退出")
        return 1
    
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
                log(f"❌ 验证 #{i} 失败: {result}")
        else:
            log(f"❌ 验证 #{i} 失败: 无公网 URL")
    
    log("════════════════════════════════════════")
    log(f"验证完成: {verification_success}/5 成功")
    log("════════════════════════════════════════")
    
    # 进入监控循环
    log("进入监控循环...")
    
    last_check_time = time.time()
    last_report_time = time.time()
    last_api_test_time = time.time()
    
    while running:
        now = datetime.now()
        elapsed = (now - start_time).total_seconds()
        
        # 检查是否超时
        if elapsed >= duration:
            log(f"⏰ 运行时长达到 {duration} 秒，准备退出...")
            break
        
        remaining = duration - elapsed
        current_time = time.time()
        
        # 每 5 秒检查服务状态
        if current_time - last_check_time >= 5:
            last_check_time = current_time
            check_count += 1
            
            # 检查代理
            if not check_proxy():
                repair_count += 1
                log(f"⚠️ 代理已停止，重启中... (修复 #{repair_count})")
                proxy_process = start_proxy()
            
            # 检查 ngrok
            if not check_ngrok():
                repair_count += 1
                log(f"⚠️ ngrok 已停止，重启中... (修复 #{repair_count})")
                ngrok_process, public_url = start_ngrok()
            else:
                url = get_ngrok_url()
                if url:
                    public_url = url
            
            # 每 10 秒测试 API
            if current_time - last_api_test_time >= 10 and public_url:
                last_api_test_time = current_time
                api_test_count += 1
                ok, result = test_api(public_url)
                if ok:
                    api_success_count += 1
                    log(f"✅ API 测试 #{api_test_count} 成功: {result}")
                else:
                    log(f"❌ API 测试 #{api_test_count} 失败: {result}")
            
            # 每 30 秒报告状态
            if current_time - last_report_time >= 30:
                last_report_time = current_time
                log(f"📊 状态报告 | 运行:{int(elapsed)}s | 剩余:{int(remaining)}s")
                log(f"   检查:{check_count}次 | 修复:{repair_count}次 | API测试:{api_test_count}次 | 成功:{api_success_count}次")
                log(f"   代理:{'✅' if check_proxy() else '❌'} | ngrok:{'✅' if check_ngrok() else '❌'} | URL:{public_url or 'N/A'}")
        
        # 短暂休眠（0.5 秒缝隙）
        time.sleep(0.5)
    
    # 最终报告
    log("════════════════════════════════════════")
    log("📈 最终报告")
    log("════════════════════════════════════════")
    elapsed = (datetime.now() - start_time).total_seconds()
    log(f"运行时长: {int(elapsed)} 秒")
    log(f"检查次数: {check_count}")
    log(f"修复次数: {repair_count}")
    log(f"API 测试: {api_test_count} 次")
    log(f"成功次数: {api_success_count} 次")
    if api_test_count > 0:
        success_rate = (api_success_count / api_test_count) * 100
        log(f"成功率: {success_rate:.1f}%")
    log("════════════════════════════════════════")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
