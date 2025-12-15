import sqlite3

def init_db():
    conn = sqlite3.connect('feeder.db')
    c = conn.cursor()
    
    # 建立寵物資料表
    # 欄位：名字、體重、目標食量(體重x2%)、品種ID、品種名稱
    c.execute('DROP TABLE IF EXISTS pets') # 如果有舊的就刪掉重來
    c.execute('''
        CREATE TABLE pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            weight REAL NOT NULL,
            target_feed REAL NOT NULL,
            breed_id INTEGER NOT NULL,
            breed_name TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    print("✅ 資料庫初始化完成！檔案: feeder.db")

if __name__ == '__main__':
    init_db()
