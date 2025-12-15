# -*- coding: utf-8 -*-
import time
import RPi.GPIO as GPIO
from hx711 import HX711 
import numpy as np

# ================= 參數設定區 =================
# 這裡使用你的 GPIO 腳位設定
DT_PIN = 23
SCK_PIN = 24

# 這裡設定你用來校正的標準重量，我們使用 0.2 kg (手機重量) 讓計算更準確
# 如果你手上有 1 kg 的水瓶，請改成 1.0
CALIBRATION_KG = 0.2 
# ============================================

# --- HX711 讀取原始數據輔助函式 ---
def read_hx711_raw_stable(hx_instance, times=10):
    """
    嘗試使用各種可能的方法讀取原始數據，並取平均，避免訊號干擾。
    """
    raw_readings = []
    
    for _ in range(times):
        raw = None
        try:
            # 嘗試方法 A: 讀取未經校正的原始值 (最穩定的庫通常叫這個)
            raw = hx_instance.get_raw_value(1)
        except AttributeError:
            try:
                # 嘗試方法 B: 讀取未經校正的原始值 (舊版庫常見名稱)
                raw = hx_instance.read_raw_value(1)
            except AttributeError:
                # 嘗試方法 C: 如果 Raw 讀取都失敗，就直接讀取它的 "值" (你的問題所在)
                raw = hx_instance.get_value(1) 
        except Exception:
            pass
        
        if raw is not None and isinstance(raw, (int, float)):
            raw_readings.append(raw)
        
        time.sleep(0.05)
        
    if not raw_readings:
        print("!!! 錯誤: 無法讀取任何數值，請檢查接線。")
        return 0
        
    return int(np.median(raw_readings)) # 取中位數更抗干擾

# ================= 校正主程式 =================
hx = None
try:
    GPIO.setmode(GPIO.BCM)
    hx = HX711(DT_PIN, SCK_PIN)
    hx.set_reading_format("MSB", "MSB")
    
    # 不設定 REF_UNIT 也不歸零，直接讀取原始數據
    hx.reset()
    print("✅ Load Cell 初始化成功。")
    print("-" * 50)
    
    # --- 步驟 A: 獲取歸零值 (Zero Offset) ---
    input("請確保秤上完全淨空，並按 Enter 開始歸零取樣...")
    print("正在採集 3 秒的原始數據...")
    
    zero_raw = read_hx711_raw_stable(hx, times=30)
    
    print(f"✔️ 採集完成。空載原始讀數 (ZERO_OFFSET R0): {zero_raw}")
    print("-" * 50)
    
    # --- 步驟 B: 獲取標準重量讀數 ---
    input(f"請將 {CALIBRATION_KG} kg 的標準物體（例如手機）放在秤上，並按 Enter...")
    print("正在採集 3 秒的原始數據...")
    
    cal_raw = read_hx711_raw_stable(hx, times=30)
    
    print(f"✔️ 採集完成。載重原始讀數 (R_cal): {cal_raw}")
    print("-" * 50)
    
    # --- 步驟 C: 計算最終的校正因子 ---
    raw_difference = cal_raw - zero_raw
    
    if raw_difference <= 0:
        print("❌ 錯誤: 讀數差異小於等於 0。請檢查 Load Cell 接線是否反接 (白線/綠線)。")
        final_ref_factor = 1
    else:
        # 計算 1 kg 會造成多少原始讀數的變化
        final_ref_factor = round(raw_difference / CALIBRATION_KG)
    
    # ====================================================
    print("\n\n=============== 最終校正結果 ================")
    print(f"1. ZERO_OFFSET (R0): {zero_raw}")
    print(f"2. FINAL_REFERENCE_FACTOR (每公斤): {final_ref_factor}")
    print("=============================================")
    print("\n請將這兩個數字填入 app.py 頂部的參數設定區！")
    print("現在程式將自動校正並讀取一次...")
    
    # 測試驗證
    hx.set_reference_unit(final_ref_factor)
    hx.tare(zero_raw) # 使用我們計算出的 R0 進行歸零
    
    test_weight = hx.get_weight(5)
    print(f"⭐ 測試重量讀數: {test_weight:.3f} kg (應接近 0 kg)")
    
except Exception as e:
    print(f"\n❌ 程式發生錯誤: {e}")
finally:
    GPIO.cleanup()
