# -*- coding: utf-8 -*-
import time
import RPi.GPIO as GPIO
from gpiozero import AngularServo
from hx711 import HX711

# ================= 參數設定 (請修改這裡) =================
DT_PIN = 23
SCK_PIN = 24
SERVO_PIN = 18

# ★ 請填入你校正好的數值，不然測出來的重量不準
REFERENCE_UNIT = 437250 

# 馬達角度設定
SERVO_MIN_PULSE = 0.0005
SERVO_MAX_PULSE = 0.0025

# ================= 硬體初始化 =================
GPIO.setmode(GPIO.BCM)
hx = HX711(DT_PIN, SCK_PIN)
hx.set_reading_format("MSB", "MSB")
hx.set_reference_unit(REFERENCE_UNIT)
hx.reset()
hx.tare()

# 初始化馬達
servo = AngularServo(SERVO_PIN, min_angle=0, max_angle=180, 
                     min_pulse_width=SERVO_MIN_PULSE, 
                     max_pulse_width=SERVO_MAX_PULSE)

def set_servo_angle(angle):
    print(f"馬達轉動至: {angle} 度")
    servo.angle = angle
    time.sleep(0.5)
    servo.value = None # 斷電防止抖動

def test_flow_rate():
    print("\n=== 流量測試模式 ===")
    print("這個測試會打開馬達 1 秒鐘，然後關閉，幫你計算流速。")
    input("請確認出料口有飼料，準備好後按 Enter 開始...")
    
    # 1. 歸零
    print("正在歸零電子秤...")
    hx.tare()
    time.sleep(1)
    
    # 2. 開門 (假設 90 度是全開，0 度是關閉)
    print(">>> 開門！ (1秒)")
    servo.angle = 90
    start_time = time.time()
    
    # 讓它流 1 秒
    time.sleep(1.0)
    
    # 3. 關門
    print(">>> 關門！")
    servo.angle = 0
    time.sleep(0.5)
    servo.value = None
    
    # 4. 等待落料 (關鍵步驟)
    print("等待空中飼料掉落 (2秒)...")
    time.sleep(2.0)
    
    # 5. 讀取重量
    final_weight = max(0, hx.get_weight(15)) # 取15次平均
    print("-" * 30)
    print(f"測試結果：1 秒鐘流出了 {final_weight:.3f} kg 飼料")
    print(f"推算流速：約 {final_weight:.3f} kg/秒")
    print("-" * 30)
    return final_weight

def manual_servo_mode():
    print("\n=== 手動角度調整模式 ===")
    print("輸入 0~180 的數字來測試角度。輸入 q 離開。")
    while True:
        val = input("請輸入角度 (0-180): ")
        if val.lower() == 'q': break
        try:
            angle = float(val)
            if 0 <= angle <= 180:
                set_servo_angle(angle)
            else:
                print("角度超出範圍！")
        except ValueError:
            print("請輸入數字！")

# ================= 主選單 =================
try:
    while True:
        print("\n" + "="*20)
        print("1. 手動調整馬達角度 (找關門點)")
        print("2. 測試出料流速 (1秒測試)")
        print("3. 讀取目前重量")
        print("4. 離開")
        choice = input("請選擇功能 (1-4): ")

        if choice == '1':
            manual_servo_mode()
        elif choice == '2':
            test_flow_rate()
        elif choice == '3':
            w = max(0, hx.get_weight(5))
            print(f"目前重量: {w:.3f} kg")
        elif choice == '4':
            print("程式結束")
            break

except KeyboardInterrupt:
    print("\n強制結束")
finally:
    GPIO.cleanup()