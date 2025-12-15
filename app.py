# -*- coding: utf-8 -*-
import cv2
import numpy as np
import time
import threading
import sqlite3
import RPi.GPIO as GPIO
from flask import Flask, render_template, Response, jsonify, request
from gpiozero import AngularServo
from hx711 import HX711 
from openvino.inference_engine import IECore

# ================= 參數設定區 =================
DT_PIN = 23
SCK_PIN = 24

# ★★★ 校正參數 ★★★
ZERO_OFFSET = 392502           
FINAL_REFERENCE_FACTOR = 438760   
BOX_WEIGHT = 0.01 

REFERENCE_UNIT = 1         
SERVO_PIN = 18
FEED_RATIO = 0.02          # 體重 * 0.02
COOLDOWN_TIME = 60        
FLOW_RATE = 0.05           # ★ 流速：0.05 kg/秒
OFFSET_WEIGHT = 0.02       
SERVO_OPEN = 90
SERVO_CLOSE = 0

# ★ 補料循環間隔 (秒)
FEED_INTERVAL_WAIT = 5.0  

# ================= 全域變數 =================
app = Flask(__name__)
GPIO.setwarnings(False)

global_frame = None
current_weight = 0.0
system_running = False
is_feeding = False       
status_msg = "系統待機中"
STARTUP_TARE = 0.0 

detected_pet_name = "---"
detected_pet_weight = "---"
detected_pet_target = 0.0
detected_breed_info = "---"
lock = threading.Lock()

# ================= 模型載入 =================
labels = {}
try:
    with open("models/imagenet_classes.txt", "r") as f:
        for idx, line in enumerate(f):
            labels[idx] = line.strip()
except: 
    print("⚠️ 警告：找不到 models/imagenet_classes.txt")

print(">>> 初始化 NCS2 模型...")
ie = IECore()
net = ie.read_network(model="models/public/mobilenet-v2/FP16/mobilenet-v2.xml", 
                      weights="models/public/mobilenet-v2/FP16/mobilenet-v2.bin")
input_blob = next(iter(net.input_info))
out_blob = next(iter(net.outputs))

exec_net = None
try:
    exec_net = ie.load_network(network=net, device_name="MYRIAD")
    print("✅ NCS2 載入成功")
except Exception as e:
    print(f"❌ NCS2 載入失敗: {e}")

# ================= HX711 讀取與硬體設定 =================
hx = None
servo = None

# --- HX711 讀取輔助函式 ---
def read_hx711_value(times=1, use_tare=True):
    if hx is None: return 0.0
    raw_val = 0
    try:
        try:
            raw_val = hx.get_value(times) 
        except AttributeError:
            raw_val = hx.get_raw_value(times)
    except Exception:
        return 0.0
    
    abs_weight = 0.0
    if FINAL_REFERENCE_FACTOR > 1:
        abs_weight = (raw_val - ZERO_OFFSET) / FINAL_REFERENCE_FACTOR
    
    if use_tare:
        final_w = abs_weight - STARTUP_TARE - BOX_WEIGHT
        return max(0.0, final_w) 
    
    return abs_weight

# --- 硬體設定 ---
def setup_hardware():
    global hx, servo, STARTUP_TARE
    try:
        GPIO.setmode(GPIO.BCM)
        hx = HX711(DT_PIN, SCK_PIN)
        hx.set_reading_format("MSB", "MSB")
        hx.reset()
        
        servo = AngularServo(SERVO_PIN, min_angle=0, max_angle=180, 
                             min_pulse_width=0.0005, max_pulse_width=0.0025)
        servo.value = None
        
        print(">>> 硬體初始化... 等待 Load Cell 穩定 (2秒)...")
        time.sleep(2) 
        
        if FINAL_REFERENCE_FACTOR > 1:
            current_bias = read_hx711_value(times=30, use_tare=False)
            STARTUP_TARE = current_bias
            print(f"✅ 自動歸零完成 (開機偏差: {STARTUP_TARE:.4f} kg)")
            print(f"✅ 已啟用額外紙盒扣重: {BOX_WEIGHT} kg")
        else:
            print("⚠️ 警告: 校正因子未設定。")
            
    except Exception as e: 
        print(f"❌ 硬體初始化錯誤: {e}")
        GPIO.cleanup()

# ================= AI 預測 =================
def predict_image(image):
    if exec_net is None: return -1, 0, "NCS2未就緒"
    try:
        input_key = next(iter(net.input_info))
        n, c, h, w_in = net.input_info[input_key].input_data.shape
        if image.shape[2] == 4: image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        img_resized = cv2.resize(image, (w_in, h))
        img_input = img_resized.transpose((2, 0, 1)).reshape((n, c, h, w_in))
        res = exec_net.infer(inputs={input_key: img_input})
        probs = res[next(iter(net.outputs))][0]
        cid = np.argmax(probs)
        return cid, probs[cid], "OK"
    except Exception as e: return -1, 0, str(e)

# ================= 餵食邏輯 (完全使用時間公式計算) =================
def smart_feed_thread(target_kg, pet_name):
    global is_feeding, status_msg, current_weight, system_running
    
    if is_feeding: return
    is_feeding = True
    
    def emergency_stop(reason):
        global is_feeding, status_msg, current_weight
        if servo: 
            servo.angle = SERVO_CLOSE
            time.sleep(0.5)
            servo.value = None
        current_weight = read_hx711_value(times=5)
        print(f">>> [餵食終止] {reason}, 最終重量: {current_weight:.3f} kg")
        status_msg = f"餵食終止 ({reason})"
        is_feeding = False
        time.sleep(COOLDOWN_TIME)
        status_msg = "監控中..."

    try:
        status_msg = f"啟動餵食程序: {pet_name}"
        
        while True: 
            if not system_running:
                emergency_stop("手動停止")
                return

            # 1. 讀取重量
            current_weight_local = read_hx711_value(times=3)
            missing_kg = target_kg - current_weight_local
            
            # 2. 判斷是否達標 (誤差 5g 內就停止)
            if missing_kg <= 0.005: 
                print(f">>> [達標] 剩餘缺量 {missing_kg:.3f}kg 極小，結束餵食。")
                break 
            
            # 3. ★★★ 公式計算區 ★★★
            # 第一次進入時，current_weight_local 接近 0，所以 missing_kg ≈ 目標重量 (體重*0.02)
            # 公式： 時間 = (目標 - 目前) / 流速
            feed_duration = missing_kg / FLOW_RATE
            
            # 安全限制：最短 0.1 秒，最長 10 秒 (避免數值錯誤開太久)
            if feed_duration < 0.1: feed_duration = 0.1
            if feed_duration > 10.0: feed_duration = 10.0
            
            print(f">>> [公式計算] 缺 {missing_kg:.3f}kg / 流速 {FLOW_RATE} = 開啟 {feed_duration:.2f} 秒")
            status_msg = f"出料中 ({feed_duration:.1f}s)..."
            
            # 4. 執行出料 (時間控制)
            if servo: servo.angle = SERVO_OPEN
            
            # 等待計算出的時間
            start_t = time.time()
            while time.time() - start_t < feed_duration:
                if not system_running: 
                    emergency_stop("手動停止")
                    return
                time.sleep(0.05) # 小睡一下
            
            # 5. 時間到，立刻關門
            if servo: 
                servo.angle = SERVO_CLOSE
                time.sleep(0.5)
                servo.value = None
            
            # 6. 等待 5 秒讓重量穩定 (使用者需求)
            print(f">>> [暫停] 等待 {FEED_INTERVAL_WAIT} 秒讓重量穩定...")
            status_msg = f"等待穩定 ({FEED_INTERVAL_WAIT}s)..."
            time.sleep(FEED_INTERVAL_WAIT)
            
            # 更新重量，迴圈回到開頭
            # 如果還不夠 (missing_kg > 0.005)，會再算一次新的秒數補料
            current_weight = read_hx711_value(times=5) 
            print(f">>> [循環檢查] 目前重量: {current_weight:.3f} kg")

        status_msg = f"餵食完成 (實餵: {current_weight:.3f}kg)"
        print(f">>> [餵食成功] 最終重量: {current_weight:.3f} kg")
        time.sleep(COOLDOWN_TIME)
        status_msg = "監控中..."
        
    except Exception as e:
        print(f"餵食執行緒錯誤: {e}")
        emergency_stop("程式錯誤")
    finally:
        is_feeding = False
        
# ================= 主迴圈 (保持不變) =================
def main_loop():
    global global_frame, current_weight, status_msg
    global detected_pet_name, detected_breed_info, detected_pet_weight, detected_pet_target
    
    setup_hardware()
    cap = cv2.VideoCapture(0)
    cap.set(3, 640); cap.set(4, 480); cap.set(cv2.CAP_PROP_FPS, 30)

    print(">>> 系統啟動 (多執行緒模式)")
    frame_count = 0

    while True:
        try:
            if frame_count % 3 == 0: 
                current_weight = read_hx711_value(times=1)

            ret, frame = cap.read()
            if not ret:
                cap.release(); time.sleep(1); cap = cv2.VideoCapture(0); continue

            frame = cv2.flip(frame, -1)
            with lock: global_frame = frame.copy()

            if system_running and not is_feeding:
                frame_count += 1
                if frame_count % 5 != 0: time.sleep(0.005); continue

                cid, conf, err = predict_image(frame)
                
                if cid != -1 and 151 <= cid <= 268 and conf > 0.7:
                    conn = sqlite3.connect('feeder.db')
                    c = conn.cursor()
                    c.execute('SELECT name, weight, target_feed FROM pets WHERE breed_id=?', (int(cid),))
                    row = c.fetchone()
                    conn.close()

                    if row:
                        p_name, p_weight, p_target = row
                        detected_pet_name = p_name
                        detected_pet_weight = f"{p_weight} kg"
                        detected_pet_target = p_target
                        detected_breed_info = f"{labels.get(cid, '未知')} ({int(conf*100)}%)"

                        if current_weight < p_target:
                            t = threading.Thread(target=smart_feed_thread, args=(p_target, p_name))
                            t.start()
                            status_msg = f"啟動餵食程序: {p_name}"
                        else:
                            status_msg = f"{p_name} 靠近 (已飽)"
                    else:
                        detected_pet_name = "未註冊"; status_msg = "發現新狗狗"
                else:
                    detected_pet_name = "---"
                    status_msg = "監控中..."

            elif not system_running:
                status_msg = "系統已暫停"; frame_count = 0

        except Exception as e:
            print(f"Loop Error: {e}")
        
        time.sleep(0.001)

# ================= Flask 路由 =================
@app.route('/')
def index(): return render_template('index.html')

@app.route('/status')
def status():
    missing = 0.0
    sec = 0.0
    if system_running and detected_pet_target > 0:
        d = detected_pet_target - current_weight
        if d > 0: 
            missing = d
            sec = d / FLOW_RATE
            
    return jsonify({
        'running': system_running,
        'msg': status_msg,
        'weight': f"{current_weight:.3f}",
        'pet_name': detected_pet_name,
        'pet_weight': detected_pet_weight,
        'breed_info': detected_breed_info,
        'target_feed': f"{detected_pet_target:.3f}",
        'missing_weight': f"{missing:.3f}",
        'supplement_seconds': f"{sec:.1f}"
    })

@app.route('/set_system', methods=['POST'])
def set_system():
    global system_running
    system_running = (request.form.get('action') == 'start')
    return jsonify({'status':'ok', 'running':system_running})

@app.route('/analyze_photo', methods=['POST'])
def analyze_photo():
    try:
        f = request.files['photo']
        if not f: return jsonify({'success': False, 'msg': '無檔'})
        img = cv2.imdecode(np.frombuffer(f.read(), np.uint8), cv2.IMREAD_COLOR)
        cid, conf, err = predict_image(img)
        if cid==-1: return jsonify({'success':False, 'msg':err})
        return jsonify({'success':True, 'breed_id':int(cid), 'breed_name':labels.get(cid,"?"), 'is_dog':bool(151<=cid<=268)})
    except Exception as e: return jsonify({'success':False, 'msg':str(e)})

@app.route('/save_pet', methods=['POST'])
def save_pet():
    try:
        n = request.form['name']
        w = float(request.form['weight'])
        bid = int(request.form['breed_id'])
        bn = request.form['breed_name']
        t = round(w * FEED_RATIO, 3)
        with sqlite3.connect('feeder.db') as conn:
            conn.execute('DELETE FROM pets WHERE breed_id=?',(bid,))
            conn.execute('INSERT INTO pets VALUES (?,?,?,?,?)',(n,w,t,bid,bn))
        return jsonify({'success':True})
    except Exception as e: return jsonify({'success':False, 'msg':str(e)})

def generate():
    while True:
        with lock:
            if global_frame is None: continue
            (flag, enc) = cv2.imencode(".jpg", global_frame)
        if flag: yield(b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(enc) + b'\r\n')
        time.sleep(0.04)

@app.route('/video_feed')
def video_feed():
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    with sqlite3.connect('feeder.db') as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS pets (name TEXT, weight REAL, target_feed REAL, breed_id INTEGER, breed_name TEXT)''')
    t = threading.Thread(target=main_loop)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)