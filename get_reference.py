import RPi.GPIO as GPIO
from hx711 import HX711
import time

# 設定飼料秤腳位
DT_PIN = 23
SCK_PIN = 24

GPIO.setmode(GPIO.BCM)
hx = HX711(DT_PIN, SCK_PIN)

# 歸零
print("正在歸零...請確保秤上是空的")
hx.set_reading_format("MSB", "MSB")
hx.set_reference_unit(1)
hx.reset()
hx.tare()
print("歸零完成！請放上已知重量物品 (例如手機)...")

try:
    while True:
        val = hx.get_weight(5)
        print(f"原始讀數: {val}")
        hx.power_down()
        hx.power_up()
        time.sleep(0.5)
except:
    GPIO.cleanup()
