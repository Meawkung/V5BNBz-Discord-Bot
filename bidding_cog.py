# bidding_cog.py
import discord
from discord.ext import commands
from discord.ui import Button, View, Select
import asyncio
import time
import logging
import os # <<< สำหรับอ่านไฟล์
from typing import Dict, List, Optional # เพิ่ม type hinting

# ตั้งค่า logger สำหรับ Cog นี้
log = logging.getLogger(__name__)

# --- ค่าคงที่ ---
# ย้ายรายการการ์ดมาไว้ตรงนี้
BIDDING_CARDS: List[str] = [
    "Deviling Puppet II", "Drake Puppet II", "Eddga Puppet II", "Phreeoni Puppet II",
    "Goblin Leader Puppet II", "Doppelganger Puppet II", "Angeling Puppet II",
    "Moonlight Flower Puppet II", "Golden Thief Bug Puppet II", "Baphomet Puppet II"
]
# ID ของช่องที่จะส่งข้อความเริ่มต้นและข้อความประมูล (สำคัญ: แก้ไขเป็น ID ช่องของคุณ)
BIDDING_CHANNEL_ID = 1288876995836510322 # <<< ใส่ ID ช่องที่ถูกต้อง
GUIDE_FILENAME = "bidding_guide.txt" # <<< ชื่อไฟล์คู่มือ

# --- โครงสร้างข้อมูลสำหรับเก็บการประมูล ---
# card_name -> list of bids
# bid = {'user_id': int, 'user_mention': str, 'user_display_name': str, 'quantity': int, 'timestamp': int, 'done': bool}
BiddingDataType = Dict[str, List[Dict[str, any]]]

# --- คลาส UI Components (Buttons, Select, View) ---

class CardButton(Button):
    def __init__(self, card_label: str, cog_instance): # รับ instance ของ Cog เข้ามา
        # สร้าง custom_id ที่ไม่ซ้ำกันและค่อนข้างคงที่
        safe_label = "".join(c for c in card_label if c.isalnum()) # เอาเฉพาะตัวอักษร/เลข
        super().__init__(label=card_label, style=discord.ButtonStyle.secondary, custom_id=f"bid_card_{safe_label[:50]}") # จำกัดความยาว custom_id
        self.card_label = card_label
        self.cog = cog_instance # เก็บ reference Cog ไว้

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer() # Defer ทันทีเพื่อป้องกัน timeout
        user = interaction.user
        current_timestamp = int(time.time())
        await self.cog.add_or_update_bid(self.card_label, user, current_timestamp)
        # ส่ง View ปัจจุบันไปด้วย
        await self.cog.update_bidding_message(interaction=interaction, view=self.view, is_interaction_edit=True)


class ClearBidsButton(Button):
    def __init__(self, cog_instance):
        super().__init__(label="Clear My Bids", style=discord.ButtonStyle.primary, custom_id="bid_clear_my")
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user = interaction.user
        await self.cog.clear_user_bids(user)
        await self.cog.update_bidding_message(interaction=interaction, view=self.view, is_interaction_edit=True)


class DoneBiddingButton(Button):
    def __init__(self, cog_instance):
        super().__init__(label="Done Bidding", style=discord.ButtonStyle.success, custom_id="bid_done")
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        # หาการ์ดที่ user ประมูลไว้และ *ยังไม่* กด done
        user_bids_cards = self.cog.get_user_active_bid_cards(user)

        if not user_bids_cards:
            await interaction.response.send_message("You don't have any active bids to mark as done.", ephemeral=True)
            return

        # สร้าง Select Menu ใน callback นี้เลย
        options = [discord.SelectOption(label=card, value=card) for card in user_bids_cards]
        # จำกัดจำนวน option ไม่ให้เกิน 25 (ขีดจำกัดของ Discord)
        if len(options) > 25:
             await interaction.response.send_message("You have too many active bids (>25) to display in a selection menu. Please clear some bids first.", ephemeral=True)
             return

        select = Select(
            placeholder="Select card(s) to mark as Done",
            min_values=1,
            max_values=min(len(options), 25), # ไม่เกินจำนวน option ที่มี และไม่เกิน 25
            options=options,
            custom_id="bid_done_select" # custom_id สำหรับ select
        )

        async def select_callback(select_interaction: discord.Interaction):
            # Important: Defer the response to the select interaction
            await select_interaction.response.defer(ephemeral=True) # Defer แบบ ephemeral
            selected_cards = select_interaction.data.get('values', [])
            await self.cog.mark_bids_done(user, selected_cards)

            # Send confirmation via followup for the select interaction
            await select_interaction.followup.send(f"Marked bids for {', '.join(selected_cards)} as done. Please refresh the main message if needed.", ephemeral=True)

            # --- พยายามอัปเดตข้อความหลัก ---
            # หา View หลัก (view ของปุ่ม Done Bidding) จาก interaction เดิมของปุ่ม
            original_view = self.view
            try:
                # พยายาม fetch ข้อความหลักมาแก้ไขโดยตรง (น่าเชื่อถือกว่า interaction เดิม)
                await self.cog.update_bidding_message(view=original_view, is_interaction_edit=False)
            except Exception as e:
                log.warning(f"ไม่สามารถอัปเดตข้อความหลักอัตโนมัติหลัง 'Done': {e}")


        select.callback = select_callback
        view = View(timeout=180) # View สำหรับ Select เท่านั้น
        view.add_item(select)
        # ส่ง Select menu กลับไปหาคนที่กดปุ่ม Done
        await interaction.response.send_message("Choose the card(s) to mark as Done:", view=view, ephemeral=True)


class RestartButton(Button):
    def __init__(self, cog_instance):
        super().__init__(label="Restart Bidding", style=discord.ButtonStyle.danger, custom_id="bid_restart")
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You do not have permission to restart bidding.", ephemeral=True)
            return
        await interaction.response.defer() # Defer ก่อนเคลียร์ข้อมูล
        await self.cog.restart_bidding()
        # ส่ง view ไปด้วย เพราะการ restart ต้องสร้าง view ใหม่ (หรือใช้ view เดิมก็ได้ถ้าปุ่มไม่เปลี่ยน)
        await self.cog.update_bidding_message(interaction=interaction, view=self.view, is_restart=True, is_interaction_edit=True)


class RefreshButton(Button):
    def __init__(self, cog_instance):
        super().__init__(label="🔃", style=discord.ButtonStyle.secondary, custom_id="bid_refresh")
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # แค่อัปเดตข้อความ ไม่ต้องทำอะไรกับข้อมูล
        await self.cog.update_bidding_message(interaction=interaction, view=self.view, is_interaction_edit=True)


class BiddingView(View):
    # ทำให้ View สามารถถูกสร้างใหม่ได้ง่าย และจัดการปุ่มต่างๆ
    def __init__(self, cog_instance, timeout=None): # รับ Cog instance
        super().__init__(timeout=timeout)
        self.cog = cog_instance # เก็บ cog instance ไว้เพื่อให้ button เข้าถึงได้

        # เพิ่มปุ่ม Refresh ก่อน (อาจจะไว้แถวแรก)
        self.add_item(RefreshButton(cog_instance=self.cog))

        # เพิ่มปุ่มการ์ด (อาจจะต้องแบ่งเป็นหลายแถวถ้าเยอะ)
        # ตัวอย่าง: แบ่ง 5 ปุ่มต่อแถว
        row_num = 0
        for i, card in enumerate(BIDDING_CARDS):
             # Discord จำกัด 5 ปุ่มต่อ 1 แถว (Row)
             # การสร้าง Row แบบ Dynamic อาจซับซ้อน, แบบง่ายคือใส่ปุ่มไปเรื่อยๆ View จะจัดให้เอง
             self.add_item(CardButton(card_label=card, cog_instance=self.cog))
             # if i > 0 and i % 5 == 0: # เริ่มแถวใหม่ทุก 5 ปุ่ม (ไม่จำเป็น View จัดการให้ได้)
             #    row_num += 1

        # เพิ่มปุ่มจัดการ (ควรจัดเรียงในแถวใหม่ หรือตามต้องการ)
        # View จะจัดปุ่มเหล่านี้ต่อจากปุ่มการ์ด
        self.add_item(ClearBidsButton(cog_instance=self.cog))
        self.add_item(DoneBiddingButton(cog_instance=self.cog))
        self.add_item(RestartButton(cog_instance=self.cog))

# --- คลาส Cog หลัก ---
class BiddingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # โหลดข้อมูลการประมูลเริ่มต้น (ถ้ามี) หรือสร้างใหม่
        # TODO: Implement loading/saving bid data from a file/database
        self.card_bids: BiddingDataType = {card: [] for card in BIDDING_CARDS}
        self.card_bid_order: List[str] = [] # ลำดับการ์ดที่มีการประมูลครั้งแรก
        # โหลด ID ข้อความล่าสุด (ถ้ามี)
        # TODO: Implement loading/saving bidding_message_id
        self.bidding_message_id: Optional[int] = None
        self.bidding_channel_id: int = BIDDING_CHANNEL_ID
        self.persistent_view_added = False # Flag ป้องกันการ add view ซ้ำซ้อน
        self.message_lock = asyncio.Lock() # Lock สำหรับป้องกัน race condition ตอนอัปเดตข้อความ
        log.info(f"BiddingCog: โหลดสำเร็จ จัดการประมูลสำหรับช่อง ID: {self.bidding_channel_id}")

    # --- Listener สำหรับ View แบบถาวร ---
    @commands.Cog.listener()
    async def on_ready(self):
        # ทำเมื่อบอทเชื่อมต่อสำเร็จ (อาจถูกเรียกหลายครั้ง)
        if not self.persistent_view_added:
             log.info("BiddingCog: on_ready - กำลังตรวจสอบ/เพิ่ม Persistent View...")
             # สร้าง instance ของ View ที่เราต้องการให้ทำงานตลอด
             persistent_view = BiddingView(cog_instance=self, timeout=None)
             # ลงทะเบียน View กับบอท; บอทจะจัดการ callback ของปุ่มที่มี custom_id ใน View นี้
             self.bot.add_view(persistent_view)
             self.persistent_view_added = True
             log.info("BiddingCog: Persistent View ถูกเพิ่ม/ตรวจสอบแล้ว")
             # TODO: โหลด bidding_message_id จากที่บันทึกไว้
             # self.bidding_message_id = load_saved_message_id()
             if self.bidding_message_id:
                  log.info(f"พบ Bidding Message ID ที่บันทึกไว้: {self.bidding_message_id}")
                  # อาจจะ fetch ข้อความมาตรวจสอบสถานะ หรืออัปเดต view ถ้าจำเป็น
             else:
                  log.warning("ไม่พบ Bidding Message ID ที่บันทึกไว้. อาจต้องใช้ !startbidding เพื่อสร้างใหม่")


    # --- Command สำหรับเริ่ม/สร้างข้อความประมูล ---
    @commands.command(name="startbidding")
    @commands.has_permissions(administrator=True) # จำกัดให้ Admin ใช้
    @commands.guild_only() # ใช้ได้เฉพาะใน Server
    async def start_bidding(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """สร้างข้อความเริ่มต้นสำหรับการประมูลในช่องที่ระบุ (Admin เท่านั้น)"""
        target_channel = channel or ctx.guild.get_channel(self.bidding_channel_id) or ctx.channel
        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            await ctx.send("ไม่พบช่องข้อความที่ถูกต้องสำหรับส่งข้อความประมูล", ephemeral=True)
            return

        # --- อ่าน User Guide จากไฟล์ ---
        user_guide = self._get_user_guide() # เรียกใช้เมธอดที่แก้ไขแล้ว
        # -----------------------------
        if "# Error" in user_guide: # ตรวจสอบว่าโหลด guide สำเร็จไหม
             await ctx.send(f"คำเตือน: ไม่สามารถโหลด User Guide ได้\n{user_guide}", ephemeral=True)
             # อาจจะถามยืนยันว่าจะสร้างข้อความประมูลต่อไหม
             # view_confirm = ConfirmView(ctx.author.id)
             # await ctx.send("Proceed without user guide?", view=view_confirm, ephemeral=True)
             # await view_confirm.wait()
             # if not view_confirm.confirmed: return

        try:
            await target_channel.send(user_guide)
        except discord.Forbidden:
             await ctx.send(f"ไม่มีสิทธิ์ส่งข้อความ User Guide ในช่อง {target_channel.mention}", ephemeral=True)
             return
        except discord.HTTPException as e:
            await ctx.send(f"เกิดข้อผิดพลาดในการส่ง User Guide: {e}", ephemeral=True)
            # อาจจะไม่หยุดถ้าส่ง guide ไม่ได้ แต่แจ้งเตือน

        # สร้าง View และส่งข้อความหลัก
        # ต้องสร้าง View instance ใหม่ทุกครั้งที่ส่งข้อความใหม่
        view = BiddingView(cog_instance=self, timeout=None) # View แบบถาวร
        initial_content = "Choose a card to bid on:"
        try:
            msg = await target_channel.send(initial_content, view=view)
            # ลบข้อความเก่า (ถ้ามี ID เดิม) - Optional
            if self.bidding_message_id:
                 try:
                     old_msg = await target_channel.fetch_message(self.bidding_message_id)
                     await old_msg.delete()
                     log.info(f"ลบข้อความประมูลเก่า ID: {self.bidding_message_id}")
                 except discord.NotFound:
                     log.info("ไม่พบข้อความประมูลเก่าที่จะลบ")
                 except discord.Forbidden:
                     log.warning("ไม่มีสิทธิ์ลบข้อความประมูลเก่า")
                 except Exception as e:
                     log.warning(f"เกิดข้อผิดพลาดขณะลบข้อความเก่า: {e}")

            self.bidding_message_id = msg.id # <<< เก็บ ID ของข้อความที่สร้างใหม่
            log.info(f"สร้างข้อความประมูลใหม่ ID: {self.bidding_message_id} ในช่อง {target_channel.id}")
            # TODO: ควรบันทึก bidding_message_id ลงไฟล์/ฐานข้อมูล ณ จุดนี้
            # save_message_id(self.bidding_message_id)
            await ctx.send(f"สร้างข้อความประมูลเรียบร้อยใน {target_channel.mention} (ID: {msg.id})", ephemeral=True)
        except discord.Forbidden:
             await ctx.send(f"ไม่มีสิทธิ์ส่งข้อความพร้อม View ในช่อง {target_channel.mention}", ephemeral=True)
        except discord.HTTPException as e:
            log.exception(f"เกิดข้อผิดพลาด HTTP ในการส่งข้อความประมูลหลัก: {e}")
            await ctx.send(f"เกิดข้อผิดพลาดในการส่งข้อความประมูลหลัก: {e}", ephemeral=True)
        except Exception as e:
            log.exception(f"เกิดข้อผิดพลาดที่ไม่คาดคิดในการส่งข้อความประมูลหลัก: {e}")
            await ctx.send(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", ephemeral=True)


    def _get_user_guide(self) -> str:
        """อ่านเนื้อหา User Guide จากไฟล์ GUIDE_FILENAME"""
        default_error_message = "# Error\nCould not load the user guide."
        try:
            script_dir = os.path.dirname(__file__)
            file_path = os.path.join(script_dir, GUIDE_FILENAME)

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                 log.warning(f"ไฟล์คู่มือ '{file_path}' ว่างเปล่า")
                 return f"# Warning\nUser guide file '{GUIDE_FILENAME}' is empty."
            log.info(f"โหลด User Guide จาก '{file_path}' สำเร็จ")
            return content
        except FileNotFoundError:
            log.error(f"ไม่พบไฟล์คู่มือ '{file_path}' กรุณาสร้างไฟล์นี้")
            return f"# Error\nCould not load user guide: File '{GUIDE_FILENAME}' not found at expected location '{file_path}'."
        except IOError as e:
            log.error(f"เกิดข้อผิดพลาด IO ขณะอ่านไฟล์คู่มือ '{file_path}': {e}")
            return f"# Error\nCould not read user guide file '{GUIDE_FILENAME}': {e}"
        except Exception as e:
             log.exception(f"เกิดข้อผิดพลาดที่ไม่คาดคิดขณะโหลดไฟล์คู่มือ '{file_path}': {e}")
             return default_error_message


    # --- Methods สำหรับจัดการข้อมูลการประมูล ---
    async def add_or_update_bid(self, card_label: str, user: discord.User | discord.Member, timestamp: int):
        """เพิ่มหรืออัปเดตการประมูลของผู้ใช้สำหรับการ์ดที่ระบุ"""
        async with self.message_lock: # ล็อคก่อนแก้ไขข้อมูล bid
            if card_label not in self.card_bids:
                log.warning(f"พยายามประมูลการ์ดที่ไม่รู้จัก: {card_label}")
                return

            bids_for_card = self.card_bids[card_label]
            user_id = user.id
            # พยายามดึง Member object เพื่อเอา Nickname (อาจจะไม่มีถ้า interaction มาจากนอก Guild หรือ Member ออกไปแล้ว)
            display_name = user.display_name # ใช้ display_name ซึ่งจะ fallback ไปเป็น global name ถ้าไม่มี nick

            existing_bid_index = next((i for i, bid in enumerate(bids_for_card) if bid['user_id'] == user_id), -1)

            if existing_bid_index != -1:
                bids_for_card[existing_bid_index]['quantity'] += 1
                bids_for_card[existing_bid_index]['timestamp'] = timestamp
                bids_for_card[existing_bid_index]['done'] = False # การกดปุ่มใหม่ถือว่ายังไม่ done
                log.info(f"อัปเดตการประมูล: {display_name} ({user_id}) สำหรับ {card_label} เป็น {bids_for_card[existing_bid_index]['quantity']}")
            else:
                new_bid = {
                    'user_id': user_id,
                    'user_mention': user.mention,
                    'user_display_name': display_name,
                    'quantity': 1,
                    'timestamp': timestamp,
                    'done': False
                }
                bids_for_card.append(new_bid)
                log.info(f"เพิ่มการประมูลใหม่: {display_name} ({user_id}) สำหรับ {card_label} จำนวน 1")
                if card_label not in self.card_bid_order:
                    self.card_bid_order.append(card_label)
            # TODO: Save bid data after modification
            # self.save_bid_data()

    async def clear_user_bids(self, user: discord.User):
        """ลบการประมูลทั้งหมดของผู้ใช้ที่ระบุ"""
        async with self.message_lock: # ล็อคก่อนแก้ไขข้อมูล
            user_id = user.id
            cleared_count = 0
            cards_to_check = list(self.card_bids.keys())

            for card in cards_to_check:
                initial_len = len(self.card_bids[card])
                self.card_bids[card] = [bid for bid in self.card_bids[card] if bid['user_id'] != user_id]
                cleared_in_card = initial_len - len(self.card_bids[card])
                if cleared_in_card > 0:
                    cleared_count += cleared_in_card
                    log.info(f"ลบ {cleared_in_card} bid ของ {user.display_name} ({user_id}) ออกจาก {card}")
                    if not self.card_bids[card] and card in self.card_bid_order:
                        try:
                            self.card_bid_order.remove(card)
                            log.info(f"นำ {card} ออกจากลำดับการประมูลเนื่องจากไม่มี bid เหลือ")
                        except ValueError: pass

            if cleared_count > 0:
                log.info(f"รวมลบการประมูล {cleared_count} รายการสำหรับผู้ใช้: {user.display_name} ({user_id})")
                # TODO: Save bid data
                # self.save_bid_data()
            else:
                 log.info(f"ผู้ใช้ {user.display_name} ({user_id}) ไม่มี bid ให้ลบ")


    def get_user_active_bid_cards(self, user: discord.User) -> List[str]:
        """คืนค่ารายการการ์ดที่ผู้ใช้มีการประมูลที่ยังไม่ 'done' """
        user_id = user.id
        # ไม่ต้องใช้ lock เพราะแค่ อ่านข้อมูล
        return [card for card, bids in self.card_bids.items() if any(bid['user_id'] == user_id and not bid.get('done', False) for bid in bids)]

    async def mark_bids_done(self, user: discord.User, cards_to_mark: List[str]):
        """ทำเครื่องหมายการประมูลของผู้ใช้สำหรับการ์ดที่ระบุว่าเป็น 'done'"""
        async with self.message_lock: # ล็อคก่อนแก้ไข
            user_id = user.id
            marked_count = 0
            display_name = user.display_name
            for card in cards_to_mark:
                if card in self.card_bids:
                    for bid in self.card_bids[card]:
                        # ทำเครื่องหมายเฉพาะ bid ของ user คนนี้ และยังไม่เป็น done
                        if bid['user_id'] == user_id and not bid.get('done', False):
                            bid['done'] = True
                            marked_count += 1
            if marked_count > 0:
                log.info(f"ทำเครื่องหมาย {marked_count} การประมูลเป็น 'done' สำหรับ {display_name} ({user_id}) ในการ์ด: {', '.join(cards_to_mark)}")
                # TODO: Save bid data
                # self.save_bid_data()
            else:
                 log.info(f"ไม่พบ bid ที่ยังไม่ done ของ {display_name} ({user_id}) ในการ์ดที่เลือก: {', '.join(cards_to_mark)}")


    async def restart_bidding(self):
        """รีเซ็ตข้อมูลการประมูลทั้งหมด"""
        async with self.message_lock: # ล็อคขณะรีเซ็ต
            self.card_bids = {card: [] for card in BIDDING_CARDS}
            self.card_bid_order = []
            # ไม่ต้องลบ bidding_message_id ที่นี่ เพราะเราจะแก้ไขข้อความเดิม
            log.info("--- ระบบการประมูลถูกรีสตาร์ท (ข้อมูลในหน่วยความจำ) ---")
            # TODO: Clear saved bid data
            # self.clear_saved_bid_data()


    # --- Method สำหรับอัปเดตข้อความประมูล ---
    async def update_bidding_message(self, interaction: Optional[discord.Interaction] = None, view: Optional[View] = None, msg_to_edit: Optional[discord.Message] = None, is_restart: bool = False, is_interaction_edit: bool = True):
        """อัปเดตเนื้อหาข้อความประมูลหลัก (Thread-safe)"""
        # ใช้ Lock เพื่อป้องกันการอัปเดตข้อความพร้อมกันหลายครั้ง ซึ่งอาจทำให้ข้อมูลไม่ตรงกัน
        async with self.message_lock:
            log.debug(f"Update message triggered by: {'Interaction' if interaction else 'Direct Call'}{' (Restart)' if is_restart else ''}")
            if is_restart:
                new_content = "Bidding has been restarted. Choose a card to bid on:"
            else:
                # สร้างเนื้อหาจากข้อมูล bid ปัจจุบัน (ที่อยู่ใน lock แล้ว)
                active_bids_data = {card: bids for card, bids in self.card_bids.items() if bids}
                if not active_bids_data:
                    new_content = "No current bids."
                else:
                    # จัดเรียงการ์ด
                    def sort_key(card_name):
                        try: order_index = self.card_bid_order.index(card_name)
                        except ValueError: order_index = float('inf')
                        return (-len(self.card_bids.get(card_name, [])), order_index)

                    sorted_cards = sorted(active_bids_data.keys(), key=sort_key)
                    # สร้างข้อความแสดงผล
                    lines = []
                    for card in sorted_cards:
                        bids = active_bids_data[card]
                        # เรียง bid ภายในตาม timestamp
                        sorted_bids = sorted(bids, key=lambda b: b.get('timestamp', 0))
                        bid_lines = [
                            (f"{idx + 1}. {bid.get('user_mention', 'Unknown User')} "
                             f"({bid.get('user_display_name', '?')}) - {bid.get('quantity', '?')} "
                             f"<t:{bid.get('timestamp', 0)}:R> {'✅' if bid.get('done', False) else ''}").strip()
                            for idx, bid in enumerate(sorted_bids)
                        ]
                        lines.append(f"# **{card}**:\n" + "\n".join(bid_lines))
                    new_content = "\n\n".join(lines)
                    # จำกัดความยาวข้อความไม่ให้เกิน 4000 ตัวอักษร (ขีดจำกัดของ Discord Embed Description หรือใกล้เคียง content)
                    if len(new_content) > 4000:
                         new_content = new_content[:3950] + "\n... (Message too long, truncated)"
                         log.warning("เนื้อหาข้อความประมูลยาวเกินไป ถูกตัดให้สั้นลง")


            # หา view ที่จะใช้ (ถ้าไม่ได้ส่งมา ให้สร้างใหม่ หรือใช้ view จาก interaction/message)
            current_view = view
            if not current_view:
                 if interaction and interaction.message:
                      current_view = View.from_message(interaction.message) # พยายามใช้ View เดิมจากข้อความของ interaction
                 elif msg_to_edit:
                      current_view = View.from_message(msg_to_edit) # พยายามใช้ View เดิมจากข้อความที่ส่งมา
                 else:
                     # ถ้าไม่มีจริงๆ ค่อยสร้างใหม่ (แต่อาจทำให้ปุ่ม state รีเซ็ตถ้าไม่จัดการดีๆ)
                     log.warning("ไม่พบ View เดิม กำลังสร้าง BiddingView ใหม่สำหรับ update_bidding_message")
                     current_view = BiddingView(cog_instance=self, timeout=None)


            # --- เลือกวิธีแก้ไขข้อความ ---
            message_edited = False
            target_message_id = self.bidding_message_id # ใช้ ID ที่เก็บไว้เป็นหลัก
            edit_target = None

            if interaction and is_interaction_edit:
                # ถ้ามี interaction และต้องการแก้ไขผ่าน interaction
                edit_target = interaction
                log.debug(f"พยายามแก้ไขผ่าน Interaction: {interaction.id}")
            elif msg_to_edit:
                 # ถ้าส่ง message object มาให้แก้ไข
                 edit_target = msg_to_edit
                 target_message_id = msg_to_edit.id
                 log.debug(f"พยายามแก้ไขผ่าน Message object: {msg_to_edit.id}")
            elif target_message_id:
                 # ถ้าไม่มี interaction/message แต่มี ID ที่บันทึกไว้
                 log.debug(f"พยายามแก้ไขผ่าน Message ID ที่บันทึกไว้: {target_message_id}")
                 # ไม่ต้องทำอะไรตรงนี้ จะไป fetch ใน try ด้านล่าง
                 pass
            else:
                 log.warning("ไม่สามารถอัปเดตข้อความได้: ไม่มี Interaction, Message หรือ Message ID ที่จะใช้แก้ไข")
                 return # ออกจากฟังก์ชันถ้าไม่มีเป้าหมาย

            # --- ทำการแก้ไข ---
            try:
                if isinstance(edit_target, discord.Interaction):
                    await edit_target.edit_original_response(content=new_content, view=current_view)
                    message_edited = True
                    log.info(f"อัปเดตข้อความประมูลผ่าน Interaction {edit_target.id} สำเร็จ")
                elif isinstance(edit_target, discord.Message):
                    await edit_target.edit(content=new_content, view=current_view)
                    message_edited = True
                    log.info(f"อัปเดตข้อความประมูลผ่าน Message {edit_target.id} สำเร็จ")
                elif target_message_id: # กรณีต้อง fetch
                    channel = self.bot.get_channel(self.bidding_channel_id) or await self.bot.fetch_channel(self.bidding_channel_id)
                    if channel and isinstance(channel, discord.TextChannel):
                        msg = await channel.fetch_message(target_message_id)
                        await msg.edit(content=new_content, view=current_view)
                        message_edited = True
                        log.info(f"อัปเดตข้อความประมูลผ่าน fetch ID {target_message_id} สำเร็จ")
                    elif not channel:
                         log.error(f"ไม่พบช่อง ID {self.bidding_channel_id} สำหรับ fetch message")
                    else:
                         log.error(f"ช่อง ID {self.bidding_channel_id} ไม่ใช่ TextChannel")

            except discord.NotFound:
                log.error(f"ไม่พบ Interaction หรือ Message (ID: {target_message_id}) ที่จะแก้ไข อาจถูกลบไปแล้ว")
                # ถ้าหาข้อความหลักไม่เจอ ควรจะเคลียร์ ID ที่เก็บไว้
                if target_message_id and target_message_id == self.bidding_message_id:
                    self.bidding_message_id = None
                    # TODO: Clear saved message ID
                    # clear_saved_message_id()
                    log.warning("Bidding Message ID ถูกเคลียร์เนื่องจากไม่พบข้อความ")
            except discord.HTTPException as e:
                # บ่อยครั้งคือ Rate Limit หรือข้อความยาวไป (แม้จะเช็คแล้ว) หรือ permission
                log.error(f"เกิดข้อผิดพลาด HTTP ขณะอัปเดตข้อความประมูล (ID: {target_message_id}): {e.status} - {e.text}")
            except Exception as e:
                log.exception(f"เกิดข้อผิดพลาดที่ไม่คาดคิดขณะอัปเดตข้อความประมูล (ID: {target_message_id}): {e}")

            if not message_edited:
                log.warning("การอัปเดตข้อความประมูลล้มเหลว")


# --- ฟังก์ชัน Setup สำหรับ Cog ---
async def setup(bot: commands.Bot):
    """Loads the BiddingCog."""
    try:
        # อาจจะโหลดข้อมูลที่บันทึกไว้ก่อน add cog
        # saved_data = load_bid_data()
        # saved_msg_id = load_saved_message_id()
        cog_instance = BiddingCog(bot)
        # if saved_data: cog_instance.card_bids = saved_data['bids']; cog_instance.card_bid_order = saved_data['order']
        # if saved_msg_id: cog_instance.bidding_message_id = saved_msg_id
        await bot.add_cog(cog_instance)
        log.info("BiddingCog: Setup complete, Cog added to bot.")
    except Exception as e:
        log.exception("BiddingCog: Failed to load Cog.")
        # raise e # อาจจะ raise เพื่อให้ bot หลักรู้ว่าโหลดไม่สำเร็จ

# --- todo: ฟังก์ชันสำหรับ Save/Load Data (ตัวอย่างง่ายๆ กับไฟล์ JSON) ---
# import json
# BID_DATA_FILE = 'bidding_data.json'

# def save_bid_data(self): # ควรเป็น method ใน Cog
#     async with self.message_lock: # ใช้ lock เดียวกัน
#         data_to_save = {
#             'bids': self.card_bids,
#             'order': self.card_bid_order,
#             'message_id': self.bidding_message_id
#         }
#         try:
#             with open(BID_DATA_FILE, 'w', encoding='utf-8') as f:
#                 json.dump(data_to_save, f, ensure_ascii=False, indent=4)
#             log.info(f"บันทึกข้อมูลการประมูลลง {BID_DATA_FILE} สำเร็จ")
#         except IOError as e:
#             log.error(f"ไม่สามารถบันทึกข้อมูลการประมูลลง {BID_DATA_FILE}: {e}")
#         except Exception as e:
#             log.exception(f"เกิดข้อผิดพลาดขณะบันทึกข้อมูล: {e}")

# def load_bid_data(self): # ควรเป็น method ใน Cog หรือเรียกใน __init__ / setup
#     try:
#         if os.path.exists(BID_DATA_FILE):
#             with open(BID_DATA_FILE, 'r', encoding='utf-8') as f:
#                 loaded_data = json.load(f)
#                 self.card_bids = loaded_data.get('bids', {card: [] for card in BIDDING_CARDS})
#                 self.card_bid_order = loaded_data.get('order', [])
#                 self.bidding_message_id = loaded_data.get('message_id', None)
#                 log.info(f"โหลดข้อมูลการประมูลจาก {BID_DATA_FILE} สำเร็จ")
#         else:
#              log.info(f"ไม่พบไฟล์ {BID_DATA_FILE}, เริ่มต้นด้วยข้อมูลว่าง")
#     except json.JSONDecodeError:
#          log.error(f"ไฟล์ {BID_DATA_FILE} มีรูปแบบ JSON ไม่ถูกต้อง, เริ่มต้นด้วยข้อมูลว่าง")
#     except Exception as e:
#          log.exception(f"เกิดข้อผิดพลาดขณะโหลดข้อมูล: {e}")