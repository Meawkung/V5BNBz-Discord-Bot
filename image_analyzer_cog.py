# image_analyzer_cog.py
import discord
from discord.ext import commands
import google.generativeai as genai
import os
import io         # <<< เพิ่ม import io
import json
from dotenv import load_dotenv
import logging
import re
from PIL import Image # <<< เพิ่ม import Image จาก Pillow

# ตั้งค่า logging (เหมือนเดิม)
log = logging.getLogger(__name__)

# --- โหลด Environment Variables ---
# (เหมือนเดิม)
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    # ... (error handling เหมือนเดิม)
    log.error("ไม่พบ GEMINI_API_KEY ใน .env ไฟล์")
    raise ValueError("ไม่พบ GEMINI_API_KEY ใน .env ไฟล์ สำหรับ Image Analyzer Cog")

# --- ตั้งค่า Gemini ---
# (เหมือนเดิม)
try:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model_name = 'gemini-2.0-flash' # หรือ 'gemini-2.0-flash'
    log.info(f"กำลังพยายามสร้างโมเดล Gemini: {gemini_model_name}")
    gemini_model = genai.GenerativeModel(gemini_model_name)
    log.info(f"Image Analyzer Cog: เชื่อมต่อและสร้างโมเดล Gemini สำเร็จ (ใช้โมเดล: {gemini_model_name})")
    GEMINI_PROMPT = "ขอรายละเอียดค่า stat ตัวละครจากในรูป ที่ไม่ใช่ค่า status เช่น STR AGI VIT INT DEX LUK แล้วแปลงให้เป็น JSON"
except Exception as e:
    # ... (error handling เหมือนเดิม)
    log.exception(f"!!! ข้อผิดพลาดในการตั้งค่า Gemini (Image Analyzer Cog) ด้วยโมเดล {gemini_model_name}: {e}")
    raise ConnectionError(f"ตั้งค่า Gemini ล้มเหลว ({gemini_model_name}): {e}")

class ImageAnalyzerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        log.info("Image Analyzer Cog: โหลดสำเร็จ")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user: return
        if not isinstance(message.channel, discord.DMChannel): return

        log.info(f"ได้รับข้อความ DM จาก: {message.author} (ID: {message.author.id})")

        if message.attachments:
            attachment = message.attachments[0]
            log.info(f"-> มีไฟล์แนบ: {attachment.filename} ({attachment.content_type})")

            if attachment.content_type and attachment.content_type.startswith('image/'):
                processing_msg = None
                original_image_bytes = None # เก็บ bytes ดั้งเดิมไว้เผื่อกรณี error
                try:
                    # อ่านข้อมูลรูปภาพต้นฉบับ
                    original_image_bytes = await attachment.read()
                    log.info(f"อ่านรูปภาพต้นฉบับสำเร็จ ({len(original_image_bytes)} bytes)")

                    # --- ทำ Image Processing: แบ่งครึ่งและเลือกด้านซ้าย ---
                    processed_image_bytes = None
                    try:
                        log.info("กำลังประมวลผลรูปภาพ (แบ่งครึ่งซ้าย)...")
                        # 1. โหลด image bytes เข้า Pillow
                        img = Image.open(io.BytesIO(original_image_bytes))

                        # 2. หาขนาด
                        width, height = img.size
                        log.info(f"ขนาดรูปภาพต้นฉบับ: {width}x{height}")

                        # 3. กำหนดพิกัดครึ่งซ้าย (left, upper, right, lower)
                        # ใช้ integer division // เพื่อให้ได้ค่าจำนวนเต็ม
                        left_half_coords = (0, 0, width // 2, height)
                        log.info(f"พิกัดครึ่งซ้ายที่คำนวณได้: {left_half_coords}")

                        # 4. ตัดรูปภาพ
                        left_half_img = img.crop(left_half_coords)
                        log.info(f"ตัดรูปภาพครึ่งซ้ายสำเร็จ ขนาดใหม่: {left_half_img.width}x{left_half_img.height}")

                        # 5. บันทึกรูปภาพที่ตัดแล้วลงใน BytesIO buffer
                        output_buffer = io.BytesIO()
                        # พยายามบันทึกด้วย format เดิมของรูปภาพ
                        img_format = img.format if img.format else attachment.content_type.split('/')[-1].upper()
                        # จัดการกรณี format ไม่ได้มาตรฐาน (เช่น webp อาจต้องติดตั้ง plugin เพิ่ม)
                        if img_format == 'WEBP' and not Image.registered_extensions().get('.webp'):
                             log.warning("Format WEBP อาจไม่รองรับการบันทึกโดยตรง จะลองบันทึกเป็น PNG แทน")
                             img_format = 'PNG'
                        elif not img_format or img_format.upper() not in ['JPEG', 'PNG', 'GIF', 'BMP', 'TIFF']:
                             log.warning(f"ไม่รู้จัก format '{img_format}', จะลองบันทึกเป็น PNG แทน")
                             img_format = 'PNG' # ใช้ PNG เป็น default ที่ปลอดภัย

                        left_half_img.save(output_buffer, format=img_format)
                        processed_image_bytes = output_buffer.getvalue()
                        log.info(f"บันทึกรูปภาพครึ่งซ้ายเป็น bytes สำเร็จ ({len(processed_image_bytes)} bytes, format: {img_format})")

                    except Exception as img_proc_err:
                        log.exception(f"!!! เกิดข้อผิดพลาดระหว่างการประมวลผลรูปภาพ: {img_proc_err}")
                        # ถ้าประมวลผลไม่ได้ อาจจะแจ้งผู้ใช้ หรือ fallback ไปใช้รูปเดิม
                        # ในที่นี้เราจะแจ้งข้อผิดพลาดและหยุดการทำงานส่วนนี้
                        await message.channel.send("❌ ขออภัย เกิดข้อผิดพลาดขณะประมวลผลรูปภาพ ไม่สามารถแบ่งครึ่งรูปได้")
                        return # ออกจากการทำงานของ listener นี้เลย
                    # --- สิ้นสุด Image Processing ---

                    # ตรวจสอบว่าได้ bytes ของรูปที่ประมวลผลแล้วหรือยัง
                    if not processed_image_bytes:
                         log.error("processed_image_bytes เป็น None หลังจากการประมวลผล (Logic Error?)")
                         await message.channel.send("❌ ขออภัย มีข้อผิดพลาดภายใน ไม่ได้รับข้อมูลรูปภาพหลังประมวลผล")
                         return

                    # ส่งข้อความแจ้งกำลังประมวลผล *หลังจาก* ประมวลผลรูปเสร็จ
                    processing_msg = await message.channel.send(f"ประมวลผลรูปภาพสำเร็จ กำลังส่งข้อมูลครึ่งซ้ายให้ {gemini_model_name}... 🧠⚡")

                    # เตรียมข้อมูลสำหรับ Gemini โดยใช้รูปภาพที่ประมวลผลแล้ว
                    image_part = {
                        # ใช้ content_type เดิม เพราะ Gemini อาจต้องการรู้ประเภทไฟล์ต้นฉบับ
                        # หรือจะเปลี่ยนเป็นประเภทไฟล์ที่เรา save ไปก็ได้ (เช่น 'image/png' ถ้า fallback)
                        "mime_type": attachment.content_type if img_format.upper() != 'PNG' else 'image/png',
                        "data": processed_image_bytes # <<< ใช้ bytes ของรูปครึ่งซ้าย
                    }

                    log.info(f"-> กำลังส่งรูปภาพครึ่งซ้าย ({len(processed_image_bytes)} bytes) และ prompt ไปยัง Gemini ({gemini_model_name})...")
                    try:
                        response = await gemini_model.generate_content_async([GEMINI_PROMPT, image_part])

                        if processing_msg:
                           await processing_msg.delete()
                           processing_msg = None

                        result_text = response.text
                        log.info(f"<- ได้รับผลลัพธ์จาก Gemini ({gemini_model_name}) หลังส่งครึ่งซ้าย:\n{result_text}")

                        # --- ประมวลผล JSON และเลือก 4 รายการสุดท้าย (เหมือนเดิม) ---
                        processed_output = None
                        json_parsed_successfully = False

                        if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                            # ... (จัดการ block เหมือนเดิม)
                             block_reason = response.prompt_feedback.block_reason
                             log.warning(f"Gemini block การตอบสนองเนื่องจาก: {block_reason}")
                             processed_output = f"⚠️ ขออภัย การสร้างเนื้อหาถูกบล็อกโดย Gemini เนื่องจาก: {block_reason}\n(Raw Response: {result_text})"
                        else:
                            try:
                                # ... (Clean และ Parse JSON เหมือนเดิม) ...
                                potential_json = result_text.strip()
                                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", potential_json, re.DOTALL | re.IGNORECASE)
                                if match:
                                    potential_json = match.group(1).strip()
                                else:
                                    start_brace = potential_json.find('{')
                                    end_brace = potential_json.rfind('}')
                                    if start_brace != -1 and end_brace != -1 and start_brace < end_brace:
                                        potential_json = potential_json[start_brace : end_brace + 1]

                                parsed_json = json.loads(potential_json)
                                json_parsed_successfully = True
                                log.info("Parse JSON จาก Gemini สำเร็จ")

                                if isinstance(parsed_json, dict):
                                    all_items = list(parsed_json.items())
                                    last_four_items = all_items[-4:]
                                    last_four_dict = dict(last_four_items)

                                    if last_four_dict:
                                        json_output_string = json.dumps(last_four_dict, indent=2, ensure_ascii=False)
                                        processed_output = f"✅ ค่า Stat 4 รายการสุดท้าย (จากรูปครึ่งซ้าย) โดย Gemini ({gemini_model_name}):\n```json\n{json_output_string}\n```" # เพิ่ม context
                                        log.info("ดึงและจัดรูปแบบ 4 รายการสุดท้ายจาก JSON สำเร็จ")
                                    else:
                                        # ... (จัดการกรณี JSON ว่างเปล่า เหมือนเดิม)
                                        full_parsed_json_string = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                                        processed_output = f"⚠️ ได้รับ JSON (จากรูปครึ่งซ้าย) แต่ไม่พบข้อมูล 4 รายการสุดท้าย:\n```json\n{full_parsed_json_string}\n```"
                                else:
                                    # ... (จัดการกรณีไม่ใช่ Dict เหมือนเดิม)
                                    full_parsed_json_string = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                                    processed_output = f"⚠️ Gemini ตอบกลับเป็น JSON (จากรูปครึ่งซ้าย) แต่รูปแบบไม่ถูกต้อง (ไม่ใช่ Object):\n```json\n{full_parsed_json_string}\n```"

                            except json.JSONDecodeError as json_err:
                                # ... (จัดการ Parse Error เหมือนเดิม)
                                log.warning(f"ไม่สามารถ parse JSON ที่ได้รับจาก Gemini (แม้จะลอง clean แล้ว): {json_err}")
                                processed_output = f"✅ ผลลัพธ์จาก Gemini ({gemini_model_name}) (จากรูปครึ่งซ้าย, ไม่สามารถประมวลผลเป็น JSON ได้):\n```text\n{result_text}\n```"
                            except Exception as e:
                                # ... (จัดการข้อผิดพลาดอื่น เหมือนเดิม)
                                log.exception(f"เกิดข้อผิดพลาดอื่นขณะประมวลผล JSON จาก Gemini: {e}")
                                processed_output = f"❌ เกิดข้อผิดพลาดขณะประมวลผลผลลัพธ์จาก Gemini:\n```text\n{result_text}\n```"
                        # --- สิ้นสุดการประมวลผล JSON ---

                        # --- ส่งผลลัพธ์ ---
                        if processed_output:
                            await message.channel.send(processed_output)
                        else:
                            # ... (Fallback error message เหมือนเดิม)
                            log.error("processed_output เป็น None ไม่สามารถส่งข้อความได้ (Logic Error?)")
                            await message.channel.send("❌ ขออภัย มีข้อผิดพลาดในการเตรียมข้อมูลผลลัพธ์")

                    # --- จัดการข้อผิดพลาด Gemini API ---
                    # (เหมือนเดิม)
                    except genai.types.BlockedPromptException as blocked_err: # ...
                         log.warning(f"Gemini API block prompt: {blocked_err}")
                         if processing_msg: await processing_msg.delete()
                         await message.channel.send(f"⚠️ ขออภัย Prompt หรือรูปภาพ (ครึ่งซ้าย) ถูกบล็อกโดยนโยบายความปลอดภัยของ Gemini.")
                    except genai.types.StopCandidateException as stop_err: # ...
                         log.warning(f"Gemini API stopped generation: {stop_err}")
                         if processing_msg: await processing_msg.delete()
                         await message.channel.send(f"⚠️ Gemini หยุดการสร้างเนื้อหากลางคัน อาจได้ข้อมูลไม่ครบถ้วน.")
                    except Exception as e: # ...
                         log.exception(f"!!! เกิดข้อผิดพลาดในการเรียก Gemini API ({gemini_model_name}): {e}")
                         if processing_msg: await processing_msg.delete()
                         error_message = f"{e}"
                         await message.channel.send(f"❌ ขออภัย เกิดข้อผิดพลาดขณะประมวลผลกับ Gemini ({gemini_model_name}): {error_message}")

                # --- จัดการข้อผิดพลาดอื่นๆ ---
                # (เหมือนเดิม)
                except discord.HTTPException as e: # ...
                    log.exception(f"!!! เกิดข้อผิดพลาดเกี่ยวกับ Discord (HTTP): {e}")
                    if processing_msg:
                         try: await processing_msg.delete()
                         except discord.NotFound: pass
                    await message.channel.send("❌ ขออภัย เกิดข้อผิดพลาดในการอ่านหรือส่งข้อความบน Discord")
                except Exception as e: # ...
                    log.exception(f"!!! เกิดข้อผิดพลาดไม่คาดคิดใน on_message: {e}")
                    if processing_msg:
                         try: await processing_msg.delete()
                         except discord.NotFound: pass
                    await message.channel.send(f"❌ ขออภัย เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ: {e}")

            else: # ไฟล์แนบไม่ใช่รูปภาพ
                log.info("-> ไฟล์แนบไม่ใช่รูปภาพ")
        else: # ไม่มีไฟล์แนบ
            log.info("-> ไม่มีไฟล์แนบ")
            pass

# --- ฟังก์ชัน Setup (เหมือนเดิม) ---
async def setup(bot: commands.Bot):
    """Loads the ImageAnalyzerCog."""
    # (เหมือนเดิม)
    try:
        await bot.add_cog(ImageAnalyzerCog(bot))
        log.info("ฟังก์ชัน setup ของ Image Analyzer Cog ทำงาน: โหลด Cog เรียบร้อย")
    except ConnectionError as e:
         log.error(f"!!! ไม่สามารถโหลด Image Analyzer Cog ได้เนื่องจากปัญหาการเชื่อมต่อ/ตั้งค่า Gemini: {e}")
    except Exception as e:
        log.exception(f"!!! ฟังก์ชัน setup ของ Image Analyzer Cog ล้มเหลวด้วยเหตุผลอื่น: {e}")
        raise e