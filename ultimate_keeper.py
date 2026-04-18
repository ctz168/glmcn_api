#!/usr/bin/env python3
"""
无缝保活启动器 v8 - 终极版

特性:
- 使用 cloudflared 替代 ngrok（解决域名占用问题）
- 每 5 秒检查服务状态
- 每 30 秒报告状态
- 自动修复停止的服务
- 缝隙控制在 0.5 秒内
- 五次验证 API 可用性
- 使用 timeout 控制运行时间
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
import re
from datetime import datetime, timedelta

# 配置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_SCRIPT = os.path.join(SCRIPT_DIR, 'proxy.py')
LOG_FILE = os.path.join(SCRIPT_DIR, 'seamless.log')
PID_FILE = os.path.join(SCRIPT_DIR, 'keeper.pid')
PROXY_LOG = os.path.join(SCRIPT_DIR, 'proxy.log')
CLOUDFLARED_LOG = os.path.join(SCRIPT_DIR, 'cloudflared.log')

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

# 全局状态
running = True
proxy_process = None
cloudflared_process = None
check_count = 0
repair_count = 0
api_test_count = 0
api_success_count = 0
public_url = None
start_time = None
duration = 300  # 默认 5 分钟

def log(msg):
    """记录日志"""
    line = f"[{time.strftime('%H:%M:%S')}] [keeper] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except:
        pass

def cleanup():
    """清理进程"""
    global proxy_process, cloudflared_process
    log("清理进程...")
    
    if proxy_process:
        try:
            proxy_process.terminate()
            proxy_process.wait(timeout=2)
        except:
            try:
                proxy_process.kill()
            except:
                pass
    
    if cloudflared_process:
        try:
            cloudflared_process.terminate()
            cloudflared_process.wait(timeout=2)
        except:
            try:
                cloudflared_process.kill()
            except:
                pass
    
    # 清理 PID 文件
    try:
        os.remove(PID_FILE)
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

def get_cloudflared_url():
    """从日志获取 cloudflared 公网 URL"""
    try:
        if os.path.exists(CLOUDFLARED_LOG):
            with open(CLOUDFLARED_LOG, 'r') as f:
                content = f.read()
                # 匹配 trycloudflare.com URL
                match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', content)
                if match:
                    return match.group(0)
    except:
        pass
    return None

def check_cloudflared():
    """检查 cloudflared 是否运行"""
    try:
        # 检查进程
        result = subprocess.run(
            ['pgrep', '-f', 'cloudflared'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            # 检查是否有公网 URL
            url = get_cloudflared_url()
            return True, url
        return False, None
    except:
        return False, None

def start_proxy():
    """启动代理"""
    log("启动代理...")
    try:
        # 清理旧进程
        subprocess.run(['pkill', '-f', 'proxy.py'], capture_output=True)
        time.sleep(0.5)
        
        # 启动新进程
        with open(PROXY_LOG, 'w') as f:
            process = subprocess.Popen(
                [sys.executable, PROXY_SCRIPT],
                stdout=f,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setpgrp,
                cwd=SCRIPT_DIR
            )
        
        # 等待启动
        for _ in range(10):
            time.sleep(0.5)
            if check_proxy():
                log(f"✅ 代理已启动 PID: {process.pid}")
                return process
        
        log("❌ 代理启动失败")
        return None
    except Exception as e:
        log(f"❌ 代理启动异常: {e}")
        return None

def start_cloudflared():
    """启动 cloudflared"""
    log("启动 cloudflared...")
    try:
        # 清理旧进程
        subprocess.run(['pkill', '-f', 'cloudflared'], capture_output=True)
        time.sleep(0.5)
        
        # 清空日志
        with open(CLOUDFLARED_LOG, 'w') as f:
            f.write('')
        
        # 启动新进程
        with open(CLOUDFLARED_LOG, 'a') as f:
            process = subprocess.Popen(
                ['cloudflared', 'tunnel', '--url', 'http://localhost:8082'],
                stdout=f,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setpgrp
            )
        
        # 等待获取公网 URL
        for _ in range(20):
            time.sleep(0.5)
            url = get_cloudflared_url()
            if url:
                log(f"✅ cloudflared 已启动 PID: {process.pid}")
                log(f"🌐 公网 URL: {url}")
                return process, url
        
        log("❌ cloudflared 启动失败：未获取到公网 URL")
        return None, None
    except Exception as e:
        log(f"❌ cloudflared 启动异常: {e}")
        return None, None

def test_api(url):
    """测试 API"""
    try:
        import urllib.request
        import ssl
        
        # 创建 SSL 上下文（忽略证书验证）
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
    global running, proxy_process, cloudflared_process, check_count, repair_count
    global api_test_count, api_success_count, public_url, start_time, duration
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=300, help='运行时长（秒）')
    args = parser.parse_args()
    duration = args.duration
    
    # 设置信号处理
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # 注册清理函数
    atexit.register(cleanup)
    
    start_time = datetime.now()
    end_time = start_time + timedelta(seconds=duration)
    
    log("════════════════════════════════════════")
    log("🚀 无缝保活启动器 v8 启动")
    log(f"PID: {os.getpid()}")
    log(f"工作目录: {SCRIPT_DIR}")
    log(f"计划运行时长: {duration} 秒")
    log(f"开始时间: {start_time.strftime('%H:%M:%S')}")
    log(f"预计结束: {end_time.strftime('%H:%M:%S')}")
    log("════════════════════════════════════════")
    
    # 写入 PID 文件
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    # 启动代理
    proxy_process = start_proxy()
    if not proxy_process:
        log("❌ 无法启动代理，退出")
        return 1
    
    # 启动 cloudflared
    cloudflared_process, public_url = start_cloudflared()
    if not cloudflared_process:
        log("❌ 无法启动 cloudflared，退出")
        cleanup()
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
    
    while running:
        now = datetime.now()
        elapsed = (now - start_time).total_seconds()
        
        # 检查是否超时
        if elapsed >= duration:
            log(f"⏰ 运行时长达到 {duration} 秒，准备退出...")
            break
        
        # 计算剩余时间
        remaining = duration - elapsed
        
        # 每 5 秒检查服务状态
        current_time = time.time()
        if current_time - last_check_time >= 5:
            last_check_time = current_time
            check_count += 1
            
            # 检查代理
            if not check_proxy():
                repair_count += 1
                log(f"⚠️ 代理已停止，重启中... (修复 #{repair_count})")
                proxy_process = start_proxy()
            
            # 检查 cloudflared
            ok, url = check_cloudflared()
            if not ok:
                repair_count += 1
                log(f"⚠️ cloudflared 已停止，重启中... (修复 #{repair_count})")
                cloudflared_process, public_url = start_cloudflared()
            elif url:
                public_url = url
            
            # 每 10 秒测试 API
            if check_count % 2 == 0 and public_url:
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
                ok, url = check_cloudflared()
                log(f"📊 状态报告 | 运行:{int(elapsed)}s | 剩余:{int(remaining)}s")
                log(f"   检查:{check_count}次 | 修复:{repair_count}次 | API测试:{api_test_count}次 | 成功:{api_success_count}次")
                log(f"   代理:{'✅' if check_proxy() else '❌'} | cloudflared:{'✅' if ok else '❌'} | URL:{url or 'N/A'}")
        
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
    
    cleanup()
    return 0

if __name__ == "__main__":
    sys.exit(main())
