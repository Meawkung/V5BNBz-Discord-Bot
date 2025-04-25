# Discord Bot: Image Analyzer, Voice Logger, TTS Scheduler & Bidding System

บอท Discord อเนกประสงค์ที่พัฒนาด้วย Python และไลบรารี `discord.py` พร้อมฟีเจอร์หลักหลายส่วน:

1.  **Image Analyzer (ทำงานผ่าน DM):** รับรูปภาพจากผู้ใช้ผ่าน Direct Message (DM), ทำการประมวลผลเบื้องต้น (แบ่งครึ่งรูปเลือกฝั่งซ้าย), ส่งรูปที่ประมวลผลแล้วไปยัง Google Gemini API พร้อม prompt เฉพาะเพื่อดึงค่า stat ตัวละคร (ที่ไม่ใช่ค่า status พื้นฐาน) และแปลงเป็น JSON, จากนั้นดึงเฉพาะ 4 รายการสุดท้ายจาก JSON ที่ได้ ส่งกลับให้ผู้ใช้ใน DM
2.  **Voice Channel Logger:** ตรวจสอบการเข้า-ออก หรือย้ายช่องเสียงที่กำหนดไว้ บันทึกกิจกรรมลงไฟล์ `.txt` แยกตามช่องและวัน และส่งข้อความแจ้งเตือนแบบ Embed ไปยังช่องข้อความที่กำหนด
3.  **TTS Scheduler (Text-to-Speech):** เล่นเสียงพูดตามข้อความที่กำหนดไว้ในช่องเสียงเป้าหมาย ตามตารางเวลาที่ตั้งค่าในไฟล์ `tts_schedule.json` โดยใช้ `APScheduler` และ `gTTS`. มีคำสั่ง `!testtts` สำหรับทดสอบการพูดด้วย
4.  **Bidding System (ปิดใช้งานโดยค่าเริ่มต้น):** ระบบประมูลไอเทม (การ์ด) ผ่านปุ่มกดในข้อความ Discord ผู้ใช้สามารถกดปุ่มเพื่อเพิ่มจำนวน bid, ยกเลิก bid ของตนเอง, หรือทำเครื่องหมายว่าประมูลเสร็จสิ้น มีปุ่มสำหรับ Admin เพื่อรีสตาร์ทระบบ และอ่านคู่มือการใช้งานจากไฟล์ `bidding_guide.txt`

## ✨ Features

*   **Image Analysis (DM):**
    *   รับไฟล์รูปภาพใน DM
    *   **Image Processing:** แบ่งครึ่งรูปภาพและใช้เฉพาะส่วนซ้ายในการวิเคราะห์ (ใช้ Pillow)
    *   เชื่อมต่อ Google Gemini API (`gemini-2.0-flash`) เพื่อวิเคราะห์รูปภาพด้วย Prompt ที่กำหนด
    *   พยายาม Parse ผลลัพธ์จาก Gemini เป็น JSON
    *   **JSON Filtering:** หากผลลัพธ์เป็น JSON ที่ถูกต้อง จะเลือกเฉพาะ 4 Key-Value Pairs สุดท้าย
    *   ส่งผลลัพธ์ (JSON ที่กรองแล้ว หรือข้อความดิบ/ข้อผิดพลาด) กลับไปยังผู้ใช้ใน DM
*   **Voice Logging:**
    *   ตรวจสอบหลายช่องเสียงพร้อมกัน (กำหนด ID ใน `voice_logging_cog.py`)
    *   บันทึกเหตุการณ์ Join, Leave, Move ลงไฟล์ `.txt`
        *   สร้างโฟลเดอร์ `logged/<channel_name>/<YYYY-MM-DD>/` โดยอัตโนมัติ (ใช้เวลา GMT+7)
        *   ไฟล์ log แยกตามประเภท (`join`, `leave`) และไฟล์รวม (`combined`)
    *   ส่ง Embed Notification ไปยังช่องข้อความที่กำหนด (กำหนด ID ใน `voice_logging_cog.py`) พร้อมรายละเอียด:
        *   ชื่อผู้ใช้ (รวม Nickname) และ Avatar
        *   การกระทำ (Joined, Left, Moved)
        *   ช่องเสียงที่เกี่ยวข้อง
        *   Timestamp (GMT+7 สำหรับ log file, UTC สำหรับ Embed)
*   **TTS Scheduler:**
    *   **Scheduling:** ใช้ `APScheduler` อ่านตารางเวลาจาก `tts_schedule.json` (รูปแบบ Cron).
    *   **Timezone Aware:** ตั้งค่า timezone สำหรับ Scheduler (ตัวอย่าง GMT+7).
    *   **Voice Connection:** เชื่อมต่อ/ย้ายไปยังช่องเสียงเป้าหมายที่กำหนด (กำหนด ID ใน `tts_scheduler_cog.py`).
    *   **TTS Generation:** ใช้ `gTTS` สร้างไฟล์เสียง `.mp3` ชั่วคราว (รองรับหลายภาษาตามที่ระบุใน schedule หรือ default 'en').
    *   **Playback:** เล่นไฟล์เสียงในช่องเป้าหมาย (ต้องการ `ffmpeg`).
    *   **Persistent Connection:** บอทจะยังคงอยู่ในช่องเสียงหลังจากพูดจบ (ทั้งจาก schedule และ test command).
    *   **`!testtts [lang] <text>` Command:** สำหรับทดสอบ TTS ในช่องเสียง *ของผู้ใช้* บอทจะเชื่อมต่อ/ย้ายไปและพูดข้อความที่กำหนด (รองรับระบุภาษา) และยังคงอยู่ในช่องเสียงนั้น
    *   **Concurrency Control:** ใช้ Lock ป้องกันการเล่นเสียงซ้อนกันระหว่าง scheduled jobs และ test command.
*   **Bidding System (ต้องเปิดใช้งานใน `bot.py`):**
    *   สร้างข้อความพร้อมปุ่มกดสำหรับการ์ดที่กำหนดไว้ (`BIDDING_CARDS` ใน `bidding_cog.py`)
    *   ผู้ใช้กดปุ่มการ์ดเพื่อเพิ่มจำนวน bid (ครั้งละ 1)
    *   แสดงผล bid ปัจจุบัน เรียงตามลำดับการ์ดที่มี bid และจำนวน bid, พร้อม timestamp และสถานะ "Done" (✅)
    *   ปุ่ม "Clear My Bids" สำหรับผู้ใช้ลบ bid ทั้งหมดของตนเอง
    *   ปุ่ม "Done Bidding" ให้ผู้ใช้เลือกการ์ด (ผ่าน Select Menu) ที่ประมูลเสร็จสิ้น (เพิ่มเครื่องหมาย ✅)
    *   ปุ่ม "Restart Bidding" (สำหรับ Admin) เพื่อล้างข้อมูล bid ทั้งหมด
    *   ปุ่ม Refresh "🔃" เพื่ออัปเดตข้อความแสดงผล
    *   อ่าน User Guide จากไฟล์ `bidding_guide.txt` เมื่อใช้คำสั่ง `!startbidding` (Admin)
    *   ใช้ Persistent Views ทำให้ปุ่มทำงานได้แม้บอทจะรีสตาร์ท (ต้องการการจัดการ Message ID ที่เหมาะสม - มี TODO สำหรับการ save/load)

## ⚙️ Prerequisites

*   **Python:** เวอร์ชั่น 3.8 หรือสูงกว่า
*   **Discord Bot Token:** สร้างบอทใน Discord Developer Portal และคัดลอก Token
    *   **สำคัญ:** ต้องเปิดใช้งาน **Privileged Gateway Intents** ทั้ง 3 อันใน Developer Portal:
        *   `Presence Intent` (อาจไม่จำเป็นตรงๆ แต่เป็น default)
        *   `Server Members Intent` (จำเป็นสำหรับ Voice Logging และ Bidding เพื่อดึง Nickname/Avatar)
        *   `Message Content Intent` (จำเป็นสำหรับ Image Analyzer, คำสั่ง และ TTS Test Command)
*   **Google AI (Gemini) API Key:** สร้าง API Key จาก Google AI Studio ([https://aistudio.google.com/](https://aistudio.google.com/)) สำหรับ Image Analyzer
*   **FFmpeg:** ต้องติดตั้ง FFmpeg บนเครื่องที่รันบอท และให้ Python สามารถเรียกใช้งานได้ (อาจต้องเพิ่มใน PATH หรือกำหนด `FFMPEG_PATH` ใน `.env`) สำหรับ TTS Scheduler
*   **Discord Account:** สำหรับทดสอบและใช้งานบอท

## 🔧 Setup

1.  **Clone หรือดาวน์โหลดโค้ด:** นำไฟล์ทั้งหมด (`bot.py`, `image_analyzer_cog.py`, `voice_logging_cog.py`, `bidding_cog.py`, `tts_scheduler_cog.py`, `bidding_guide.txt`, `tts_schedule.json`) มาไว้ในโฟลเดอร์เดียวกัน
2.  **ติดตั้ง Dependencies:** เปิด Terminal หรือ Command Prompt ในโฟลเดอร์โปรเจกต์ แล้วรัน:
    ```bash
    pip install -U discord.py python-dotenv google-generativeai Pillow gTTS PyNaCl APScheduler
    ```
    *(PyNaCl เป็น dependency ของ voice ใน discord.py)*
3.  **สร้างไฟล์ `.env`:** ในโฟลเดอร์เดียวกัน สร้างไฟล์ชื่อ `.env` และใส่ข้อมูลลงไป:
    ```dotenv
    DISCORD_BOT_TOKEN=YOUR_DISCORD_BOT_TOKEN_HERE
    GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
    # FFMPEG_PATH=C:/path/to/your/ffmpeg/bin/ffmpeg.exe # Optional: Uncomment and set if ffmpeg isn't in system PATH
    ```
    (แทนที่ `YOUR_..._HERE` ด้วยค่าจริง)
4.  **กำหนดค่า IDs และ Settings:** แก้ไขค่าในไฟล์ `.py` ต่างๆ:
    *   **`voice_logging_cog.py`:**
        *   `MONITORED_VOICE_CHANNEL_IDS`: ใส่ ID ของช่องเสียงที่ต้องการตรวจจับ (เป็น list)
        *   `NOTIFICATION_TEXT_CHANNEL_IDS`: ใส่ ID ของช่องข้อความที่ต้องการรับการแจ้งเตือน (เป็น list)
    *   **`tts_scheduler_cog.py`:**
        *   `target_guild_id`: ใส่ ID ของ Server ที่ต้องการให้ TTS ทำงานหลัก
        *   `target_voice_channel_id`: ใส่ ID ของช่องเสียงเป้าหมายสำหรับ Scheduled TTS
        *   *(ตรวจสอบ `default_timezone` หากต้องการ Timezone อื่นนอกจาก GMT+7)*
    *   **`bidding_cog.py` (ถ้าเปิดใช้งาน):**
        *   `BIDDING_CARDS`: แก้ไขรายการไอเทม/การ์ดที่ต้องการประมูล (เป็น list ของ strings)
        *   `BIDDING_CHANNEL_ID`: ใส่ ID ของช่องข้อความที่ต้องการให้แสดงข้อความประมูล
5.  **เตรียมไฟล์ข้อมูล:**
    *   **`tts_schedule.json`:** สร้างไฟล์นี้และใส่ตารางเวลาที่ต้องการในรูปแบบ JSON ตามตัวอย่างในไฟล์ที่ให้มา (ตรวจสอบ `hour`, `minute`, `second`, `days` ให้ถูกต้องตามรูปแบบ CronTrigger และ timezone ที่ตั้งค่า)
    *   **`bidding_guide.txt` (ถ้าเปิดใช้งาน Bidding):** ตรวจสอบเนื้อหาคู่มือให้ถูกต้อง หรือสร้างไฟล์นี้หากยังไม่มี
    *   **สร้างโฟลเดอร์ `logged`:** สร้างโฟลเดอร์ชื่อ `logged` ในระดับเดียวกับ `bot.py` เพื่อให้ Voice Logger สามารถบันทึกไฟล์ได้
    *   **สร้างโฟลเดอร์ `temp_tts`:** สร้างโฟลเดอร์ชื่อ `temp_tts` ในระดับเดียวกับ `bot.py` เพื่อให้ TTS Scheduler เก็บไฟล์เสียงชั่วคราว
6.  **เชิญบอทเข้าเซิร์ฟเวอร์:** ใช้ URL Generator ใน Discord Developer Portal (แท็บ OAuth2) เลือก scope `bot` และให้ Permissions ที่จำเป็น:
    *   `View Channels`
    *   `Send Messages`
    *   `Read Message History` (สำหรับ Bidding)
    *   `Embed Links` (สำหรับ Voice Log)
    *   `Attach Files` (อาจไม่จำเป็น แต่เผื่อไว้)
    *   `Add Reactions` (สำหรับ TTS Test)
    *   `Connect` (สำหรับ TTS)
    *   `Speak` (สำหรับ TTS)
    *   `Use Voice Activity` (สำหรับ TTS)
    *   `(Optional) Manage Messages` (ถ้าต้องการให้ Bidding ลบข้อความเก่า)
    แล้วนำ URL ที่ได้ไปเปิดในเบราว์เซอร์เพื่อเชิญบอท
7.  **(Optional) เปิดใช้งาน Bidding System:** หากต้องการใช้ระบบประมูล ให้เปิดไฟล์ `bot.py` และเอาเครื่องหมายคอมเมนต์ (`#`) หน้าบรรทัด `'bidding_cog',` ในลิสต์ `INITIAL_EXTENSIONS` ออก

## 🚀 Running the Bot

เปิด Terminal หรือ Command Prompt ในโฟลเดอร์โปรเจกต์ แล้วรันคำสั่ง:

```bash
python bot.py
```

บอทจะทำการเชื่อมต่อกับ Discord และโหลด Cogs ที่เปิดใช้งานอยู่ พร้อมเริ่ม APScheduler สำหรับ TTS.

## 💡 Usage

*   **Image Analyzer:**
    1.  เปิด Direct Message (DM) กับบอท
    2.  ส่งรูปภาพที่คุณต้องการวิเคราะห์ (บอทจะใช้ครึ่งซ้ายของรูป)
    3.  รอสักครู่ บอทจะตอบกลับด้วย JSON ที่มีค่า stat 4 รายการสุดท้ายที่ Gemini หาเจอ หรือข้อความแสดงข้อผิดพลาด/ผลลัพธ์อื่นๆ
*   **Voice Logging:**
    *   ทำงานโดยอัตโนมัติเมื่อมีการเคลื่อนไหวในช่องเสียงที่กำหนดไว้
    *   ไฟล์ Log จะถูกบันทึกในโฟลเดอร์ `logged` บนเครื่องที่รันบอท
    *   ข้อความแจ้งเตือนจะถูกส่งไปยังช่องข้อความที่กำหนดไว้ใน `NOTIFICATION_TEXT_CHANNEL_IDS`
*   **TTS Scheduler:**
    *   **Scheduled TTS:** ทำงานอัตโนมัติตามเวลาใน `tts_schedule.json` ในช่อง `target_voice_channel_id` บอทจะเชื่อมต่อและพูด แล้ว **คงอยู่ในช่องเสียงนั้น**
    *   **Test TTS:** ใช้คำสั่ง `!testtts [lang] <text>` ในช่องข้อความ (ต้องอยู่ในช่องเสียงก่อน) บอทจะเชื่อมต่อ/ย้ายไปช่องเสียงของคุณ พูดข้อความ และ **คงอยู่ในช่องเสียงนั้น** (เช่น `!testtts Hello world` หรือ `!testtts th สวัสดีครับ`)
*   **Bidding System (ถ้าเปิดใช้งาน):**
    1.  **Admin:** ใช้คำสั่ง `!startbidding` ในเซิร์ฟเวอร์ (สามารถระบุช่องได้ เช่น `!startbidding #ช่องประมูล`) เพื่อให้บอทส่ง User Guide และข้อความเริ่มต้นพร้อมปุ่มกด
    2.  **Users:**
        *   กดปุ่มการ์ดที่ต้องการเพื่อลง bid (กดซ้ำเพื่อเพิ่มจำนวน)
        *   กด "Clear My Bids" เพื่อยกเลิก bid ทั้งหมดของตนเอง
        *   กด "Done Bidding" แล้วเลือกการ์ด (จาก Select Menu) ที่ประมูลเสร็จสิ้น
        *   กด "🔃" เพื่อรีเฟรชข้อความแสดงผล
    3.  **Admin:** กด "Restart Bidding" เพื่อล้างข้อมูลประมูลทั้งหมด

## 📁 File Structure (โดยประมาณ)

```
your_bot_project/
├── bot.py                 # ไฟล์หลักสำหรับรันบอท
├── image_analyzer_cog.py  # Cog วิเคราะห์รูปภาพผ่าน Gemini
├── voice_logging_cog.py   # Cog บันทึกกิจกรรมช่องเสียง
├── tts_scheduler_cog.py   # Cog จัดการ TTS และ Schedule
├── bidding_cog.py         # Cog ระบบประมูล (อาจถูกคอมเมนต์ใน bot.py)
├── bidding_guide.txt      # คู่มือระบบประมูล (ถ้าใช้)
├── tts_schedule.json      # ตารางเวลาสำหรับ TTS
├── .env                   # ไฟล์เก็บ Token, API Key, (Optional) FFMPEG Path (สำคัญ: อย่าแชร์)
├── logged/                # โฟลเดอร์เก็บไฟล์ log จาก voice_logging_cog (สร้างเมื่อใช้งาน)
│   └── channel_name/
│       └── YYYY-MM-DD/
│           ├── join_log_... .txt
│           ├── leave_log_... .txt
│           └── combined_log_... .txt
└── temp_tts/              # โฟลเดอร์เก็บไฟล์ TTS ชั่วคราว (สร้างเมื่อใช้งาน)
    └── scheduled_tts_... .mp3
    └── test_tts_... .mp3
```

## ⚙️ Dependencies Summary

*   `discord.py`
*   `python-dotenv`
*   `google-generativeai`
*   `Pillow`
*   `gTTS`
*   `PyNaCl` (สำหรับ voice)
*   `APScheduler`

**หมายเหตุ:**

*   ตรวจสอบให้แน่ใจว่าได้ติดตั้ง `ffmpeg` และระบบสามารถเรียกใช้งานได้ หรือกำหนด `FFMPEG_PATH` ใน `.env` ให้ถูกต้อง
*   ไฟล์ `.env`, `logged/`, `temp_tts/` ควรถูกเพิ่มใน `.gitignore` หากคุณใช้ Git เพื่อป้องกันข้อมูลสำคัญรั่วไหลหรือไฟล์ที่ไม่จำเป็นถูก commit.
*   ระบบ Bidding ยังมี TODO สำหรับการบันทึกและโหลดข้อมูลประมูล/Message ID เพื่อให้ทำงานข้ามการรีสตาร์ทได้อย่างสมบูรณ์. หากไม่ทำ ข้อมูลประมูลจะหายไปเมื่อบอทปิด.
