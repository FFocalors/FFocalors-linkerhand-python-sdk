"""临时代码：集成测试 stream 模式。"""
import subprocess, time, json, urllib.request, sys, os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. 启动 server
server_proc = subprocess.Popen(
    [sys.executable, os.path.join(SCRIPT_DIR, "custom11_server.py"), "--port", "19876"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# 2. 等待 server 就绪（health check 重试）
url_health = "http://127.0.0.1:19876/health"
url_keypoints = "http://127.0.0.1:19876/keypoints"
url_latest = "http://127.0.0.1:19876/latest"

ready = False
for i in range(10):
    time.sleep(0.3)
    try:
        req = urllib.request.Request(url_health, method="GET")
        resp = urllib.request.urlopen(req, timeout=1)
        if resp.getcode() == 200:
            ready = True
            break
    except Exception:
        pass

if not ready:
    print("[test] ERROR: server did not start")
    server_proc.terminate()
    sys.exit(1)
print("[test] server ready on port 19876")

# 3. 加载样例
with open(os.path.join(SCRIPT_DIR, "sample_keypoints_11.json")) as f:
    samples = json.load(f)

# 4. 发送数据
for name in ["paper", "rock", "scissors"]:
    payload = json.dumps({"source": "test", "hand": "left", "keypoints": samples[name]}).encode()
    req = urllib.request.Request(url_keypoints, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=2)
    r = json.loads(resp.read())
    print("[server] POST {}: ok={}, kps={}".format(name, r["ok"], r.get("keypoints_count", 0)))
    time.sleep(0.15)

# 5. 测试 left_hand_teleop stream
print("\n" + "=" * 60)
print("left_hand_teleop --input-mode stream")
print("=" * 60)
result = subprocess.run(
    [sys.executable, os.path.join(SCRIPT_DIR, "left_hand_teleop.py"),
     "--dry-run", "--input-mode", "stream", "--stream-url", url_latest],
    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
out = result.stdout or ""
print(out[-4000:] if len(out) > 4000 else out)
if result.stderr:
    print("STDERR:", result.stderr[-300:])

# 6. 重新发送数据
for name in ["rock", "paper", "scissors"]:
    payload = json.dumps({"source": "test", "hand": "left", "keypoints": samples[name]}).encode()
    req = urllib.request.Request(url_keypoints, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=2)
    time.sleep(0.15)

# 7. 测试 rps_game stream
print("\n" + "=" * 60)
print("rps_game --input-mode stream")
print("=" * 60)
result = subprocess.run(
    [sys.executable, os.path.join(SCRIPT_DIR, "rps_game.py"),
     "--dry-run", "--input-mode", "stream", "--stream-url", url_latest,
     "--rounds", "3", "--seed", "42"],
    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
out = result.stdout or ""
print(out[-4000:] if len(out) > 4000 else out)
if result.stderr:
    print("STDERR:", result.stderr[-300:])

server_proc.terminate()
server_proc.wait(timeout=3)
print("\n[INTEGRATION TEST] Done.")
