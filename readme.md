
# Discord Bot: Image Analyzer, Voice Logger & Bidding System

บอท Discord อเนกประสงค์ที่พัฒนาด้วย Python และไลบรารี `discord.py` พร้อมฟีเจอร์หลัก 3 ส่วน:

1.  **Image Analyzer (ทำงานผ่าน DM):** รับรูปภาพจากผู้ใช้ผ่าน Direct Message (DM), ทำการประมวลผลเบื้องต้น (แบ่งครึ่งรูปเลือกฝั่งซ้าย), ส่งรูปที่ประมวลผลแล้วไปยัง Google Gemini API พร้อม prompt เฉพาะเพื่อดึงค่า stat ตัวละคร (ที่ไม่ใช่ค่า status พื้นฐาน) และแปลงเป็น JSON, จากนั้นดึงเฉพาะ 4 รายการสุดท้ายจาก JSON ที่ได้ ส่งกลับให้ผู้ใช้ใน DM
2.  **Voice Channel Logger:** ตรวจสอบการเข้า-ออก หรือย้ายช่องเสียงที่กำหนดไว้ บันทึกกิจกรรมลงไฟล์ `.txt` แยกตามช่องและวัน และส่งข้อความแจ้งเตือนแบบ Embed ไปยังช่องข้อความที่กำหนด
3.  **Bidding System (ปิดใช้งานโดยค่าเริ่มต้น):** ระบบประมูลไอเทม (การ์ด) ผ่านปุ่มกดในข้อความ Discord ผู้ใช้สามารถกดปุ่มเพื่อเพิ่มจำนวน bid, ยกเลิก bid ของตนเอง, หรือทำเครื่องหมายว่าประมูลเสร็จสิ้น มีปุ่มสำหรับ Admin เพื่อรีสตาร์ทระบบ และอ่านคู่มือการใช้งานจากไฟล์ `bidding_guide.txt`

## ✨ Features

*   **Image Analysis (DM):**
    *   รับไฟล์รูปภาพใน DM
    *   **Image Processing:** แบ่งครึ่งรูปภาพและใช้เฉพาะส่วนซ้ายในการวิเคราะห์
    *   เชื่อมต่อ Google Gemini API (`gemini-1.5-flash-latest` หรือ `gemini-2.0-flash`) เพื่อวิเคราะห์รูปภาพด้วย Prompt ที่กำหนด
    *   พยายาม Parse ผลลัพธ์จาก Gemini เป็น JSON
    *   **JSON Filtering:** หากผลลัพธ์เป็น JSON ที่ถูกต้อง จะเลือกเฉพาะ 4 Key-Value Pairs สุดท้าย
    *   ส่งผลลัพธ์ (JSON ที่กรองแล้ว หรือข้อความดิบ/ข้อผิดพลาด) กลับไปยังผู้ใช้ใน DM
*   **Voice Logging:**
    *   ตรวจสอบหลายช่องเสียงพร้อมกัน (กำหนด ID ในโค้ด)
    *   บันทึกเหตุการณ์ Join, Leave, Move ลงไฟล์ `.txt`
        *   สร้างโฟลเดอร์ `logged/<channel_name>/<YYYY-MM-DD>/` โดยอัตโนมัติ
        *   ไฟล์ log แยกตามประเภท (`join`, `leave`) และไฟล์รวม (`combined`)
    *   ส่ง Embed Notification ไปยังช่องข้อความที่กำหนด (กำหนด ID ในโค้ด) พร้อมรายละเอียด:
        *   ชื่อผู้ใช้ (รวม Nickname) และ Avatar
        *   การกระทำ (Joined, Left, Moved)
        *   ช่องเสียงที่เกี่ยวข้อง
        *   Timestamp (GMT+7 สำหรับ log file, UTC สำหรับ Embed)
*   **Bidding System (ต้องเปิดใช้งานใน `bot.py`):**
    *   สร้างข้อความพร้อมปุ่มกดสำหรับการ์ดที่กำหนดไว้
    *   ผู้ใช้กดปุ่มการ์ดเพื่อเพิ่มจำนวน bid (ครั้งละ 1)
    *   แสดงผล bid ปัจจุบัน เรียงตามลำดับการ์ดที่มี bid และจำนวน bid
    *   ปุ่ม "Clear My Bids" สำหรับผู้ใช้ลบ bid ทั้งหมดของตนเอง
    *   ปุ่ม "Done Bidding" ให้ผู้ใช้เลือกการ์ดที่ประมูลเสร็จแล้ว (เพิ่มเครื่องหมาย ✅)
    *   ปุ่ม "Restart Bidding" (สำหรับ Admin) เพื่อล้างข้อมูล bid ทั้งหมด
    *   ปุ่ม Refresh "🔃" เพื่ออัปเดตข้อความแสดงผล
    *   อ่าน User Guide จากไฟล์ `bidding_guide.txt` เมื่อใช้คำสั่ง `!startbidding` (Admin)
    *   ใช้ Persistent Views ทำให้ปุ่มทำงานได้แม้บอทจะรีสตาร์ท (ต้องจัดการ Message ID)

##  prerequisites

*   **Python:** เวอร์ชั่น 3.8 หรือสูงกว่า
*   **Discord Bot Token:** สร้างบอทใน Discord Developer Portal และคัดลอก Token
    *   **สำคัญ:** ต้องเปิดใช้งาน **Privileged Gateway Intents** ทั้ง 3 อันใน Developer Portal:
        *   `Presence Intent`
        *   `Server Members Intent` (จำเป็นสำหรับ Voice Logging และ Bidding)
        *   `Message Content Intent` (จำเป็นสำหรับ Image Analyzer และคำสั่งบางอย่าง)
*   **Google AI (Gemini) API Key:** สร้าง API Key จาก Google AI Studio ([https://aistudio.google.com/](https://aistudio.google.com/))
*   **Discord Account:** สำหรับทดสอบและใช้งานบอท

## 🔧 Setup

1.  **Clone หรือดาวน์โหลดโค้ด:** นำไฟล์ทั้งหมด (`bot.py`, `image_analyzer_cog.py`, `voice_logging_cog.py`, `bidding_cog.py`) มาไว้ในโฟลเดอร์เดียวกัน
2.  **ติดตั้ง Dependencies:** เปิด Terminal หรือ Command Prompt ในโฟลเดอร์โปรเจกต์ แล้วรัน:
    ```bash
    pip install -U discord.py python-dotenv google-generativeai Pillow
    ```
3.  **สร้างไฟล์ `.env`:** ในโฟลเดอร์เดียวกัน สร้างไฟล์ชื่อ `.env` และใส่ข้อมูลลงไป:
    ```dotenv
    DISCORD_BOT_TOKEN=YOUR_DISCORD_BOT_TOKEN_HERE
    GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
    ```
    (แทนที่ `YOUR_..._HERE` ด้วยค่าจริง)
4.  **กำหนดค่า Channel IDs:**
    *   **Voice Logging:** แก้ไข ID ในไฟล์ `voice_logging_cog.py`:
        *   `MONITORED_VOICE_CHANNEL_IDS`: ใส่ ID ของช่องเสียงที่ต้องการตรวจจับ
        *   `NOTIFICATION_TEXT_CHANNEL_IDS`: ใส่ ID ของช่องข้อความที่ต้องการรับการแจ้งเตือน
    *   **Bidding System (ถ้าเปิดใช้งาน):** แก้ไข ID ในไฟล์ `bidding_cog.py`:
        *   `BIDDING_CHANNEL_ID`: ใส่ ID ของช่องข้อความที่ต้องการให้แสดงข้อความประมูล
5.  **สร้างโฟลเดอร์ `logged`:** สร้างโฟลเดอร์ชื่อ `logged` ในระดับเดียวกับ `bot.py` เพื่อให้ Voice Logger สามารถบันทึกไฟล์ได้
6.  **สร้างไฟล์ `bidding_guide.txt` (ถ้าเปิดใช้งาน Bidding):** สร้างไฟล์นี้ในโฟลเดอร์เดียวกัน และใส่เนื้อหาคู่มือการใช้งานระบบประมูลลงไป (บันทึกเป็น UTF-8)
7.  **เชิญบอทเข้าเซิร์ฟเวอร์:** ใช้ URL Generator ใน Discord Developer Portal (แท็บ OAuth2) เลือก scope `bot` และให้ Permissions ที่จำเป็น (เช่น Send Messages, Read Message History, View Channels, Connect, Speak, Use Voice Activity, Attach Files, Manage Messages [ถ้าต้องการลบข้อความเก่า]) แล้วนำ URL ที่ได้ไปเปิดในเบราว์เซอร์เพื่อเชิญบอท
8.  **(Optional) เปิดใช้งาน Bidding System:** หากต้องการใช้ระบบประมูล ให้เปิดไฟล์ `bot.py` และเอาเครื่องหมายคอมเมนต์ (`#`) หน้าบรรทัด `'bidding_cog',` ในลิสต์ `INITIAL_EXTENSIONS` ออก

## 🚀 Running the Bot

เปิด Terminal หรือ Command Prompt ในโฟลเดอร์โปรเจกต์ แล้วรันคำสั่ง:

```bash
python bot.py
```

บอทจะทำการเชื่อมต่อกับ Discord และโหลด Cogs ที่เปิดใช้งานอยู่ (Image Analyzer, Voice Logger และ Bidding ถ้าเปิดไว้)

## 💡 Usage

*   **Image Analyzer:**
    1.  เปิด Direct Message (DM) กับบอท
    2.  ส่งรูปภาพที่คุณต้องการวิเคราะห์ (บอทจะใช้ครึ่งซ้ายของรูป)
    3.  รอสักครู่ บอทจะตอบกลับด้วย JSON ที่มีค่า stat 4 รายการสุดท้ายที่ Gemini หาเจอ หรือข้อความแสดงข้อผิดพลาด/ผลลัพธ์อื่นๆ
*   **Voice Logging:**
    *   ทำงานโดยอัตโนมัติเมื่อมีการเคลื่อนไหวในช่องเสียงที่กำหนดไว้
    *   ไฟล์ Log จะถูกบันทึกในโฟลเดอร์ `logged` บนเครื่องที่รันบอท
    *   ข้อความแจ้งเตือนจะถูกส่งไปยังช่องข้อความที่กำหนดไว้ใน `NOTIFICATION_TEXT_CHANNEL_IDS`
*   **Bidding System (ถ้าเปิดใช้งาน):**
    1.  **Admin:** ใช้คำสั่ง `!startbidding` ในเซิร์ฟเวอร์ (สามารถระบุช่องได้ เช่น `!startbidding #ช่องประมูล`) เพื่อให้บอทส่ง User Guide และข้อความเริ่มต้นพร้อมปุ่มกด
    2.  **Users:**
        *   กดปุ่มการ์ดที่ต้องการเพื่อลง bid (กดซ้ำเพื่อเพิ่มจำนวน)
        *   กด "Clear My Bids" เพื่อยกเลิก bid ทั้งหมดของตนเอง
        *   กด "Done Bidding" แล้วเลือกการ์ดที่ประมูลเสร็จสิ้น
        *   กด "🔃" เพื่อรีเฟรชข้อความแสดงผล
    3.  **Admin:** กด "Restart Bidding" เพื่อล้างข้อมูลประมูลทั้งหมด (ต้องยืนยันถ้ามีการ implement เพิ่ม)

## 📁 File Structure (โดยประมาณ)

```
your_bot_project/
├── bot.py                 # ไฟล์หลักสำหรับรันบอท
├── image_analyzer_cog.py  # Cog สำหรับวิเคราะห์รูปภาพผ่าน Gemini
├── voice_logging_cog.py   # Cog สำหรับบันทึกกิจกรรมช่องเสียง
├── bidding_cog.py         # Cog สำหรับระบบประมูล (อาจถูกคอมเมนต์ใน bot.py)
├── bidding_guide.txt      # ไฟล์ข้อความคู่มือระบบประมูล (ถ้าใช้)
├── .env                   # ไฟล์เก็บ Token และ API Key (สำคัญ: อย่าแชร์ไฟล์นี้)
└── logged/                # โฟลเดอร์สำหรับเก็บไฟล์ log จาก voice_logging_cog (สร้างขึ้นเมื่อใช้งาน)
    └── channel_name/
        └── YYYY-MM-DD/
            ├── join_log_... .txt
            ├── leave_log_... .txt
            └── combined_log_... .txt
```

## ⚙️ Dependencies

*   discord.py (`pip install -U discord.py`)
*   python-dotenv (`pip install -U python-dotenv`)
*   google-generativeai (`pip install -U google-generativeai`)
*   Pillow (`pip install -U Pillow`)
```
อย่าลืมปรับแก้ ID ช่องต่างๆ และข้อมูลในไฟล์ `.env` ให้ถูกต้องตามสภาพแวดล้อมของคุณนะครับ!
