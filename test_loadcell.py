# test_loadcell.py (最終測試版，強制使用 get_value)
import time
import RPi.GPIO as GPIO
from hx711 import HX711 

# GPIO 腳位 (和你的 app.py 一致)
DT_PIN = 23
SCK_PIN = 24

try:
    GPIO.setmode(GPIO.BCM)
    hx = HX711(DT_PIN, SCK_PIN)
    
    print("=== HX711 原始數據讀取測試 ===")
    
    # 嘗試使用 get_value() 方法
    # 如果這個方法也不存在，你的 hx711 庫版本可能需要重新安裝。
    try:
        raw_reading = hx.get_value() 
    except AttributeError:
        # 如果還是報錯，可能是 get_raw_value()
        raw_reading = hx.get_raw_value()

    if raw_reading is not None and raw_reading is not False:
        print(f"✅ 讀取方法有效。目前的原始數據 (Raw Value): {raw_reading}")
        print("施壓時，這個數字應該會變化。")
    else:
        print("❌ 讀取失敗，可能是接線錯誤。")
        
    print("-" * 30)
    
    for i in range(15):
        try:
            # 持續讀取
            raw = hx.get_value() # 或 hx.get_raw_value()
            
            # 如果 get_value 失敗，嘗試 get_raw_value
            if raw is None or raw is False:
                 raw = hx.get_raw_value()

            print(f"原始數據: {raw}")
        except Exception as e:
            print(f"連續讀取錯誤: {e}")
            break
        
        time.sleep(0.5)

except Exception as e:
    print(f"【嚴重錯誤】: {e}")
finally:
    GPIO.cleanup()