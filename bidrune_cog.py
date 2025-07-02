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
# ย้ายรายการรูนมาไว้ตรงนี้
BIDDING_RUNES: List[str] = [
    "Netherforce"
]
MAX_BIDS_PER_ITEM = 3 # <<< จำนวนสูงสุดของการประมูลต่อรูน
# ID ของช่องที่จะส่งข้อความเริ่มต้นและข้อความประมูล (สำคัญ: แก้ไขเป็น ID ช่องของคุณ)
BIDDING_CHANNEL_ID = 1387457247105515621 # <<< ใส่ ID ช่องที่ถูกต้อง
GUIDE_FILENAME = "bidding_guide.txt" # <<< ชื่อไฟล์คู่มือ

# --- โครงสร้างข้อมูลสำหรับเก็บการประมูล ---
# rune_name -> list of bids
# bid = {'user_id': int, 'user_mention': str, 'user_display_name': str, 'quantity': int, 'timestamp': int, 'done': bool}
BiddingDataType = Dict[str, List[Dict[str, any]]]

# --- คลาส UI Components (Buttons, Select, View) ---

class RuneButton(Button):
    def __init__(self, rune_label: str, cog_instance, *, disabled: bool = False):
        safe_label = "".join(c for c in rune_label if c.isalnum())
        super().__init__(label=rune_label, style=discord.ButtonStyle.secondary, custom_id=f"bid_rune_{safe_label[:50]}", disabled=disabled)
        self.rune_label = rune_label
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        if self.cog.is_paused:
            await interaction.response.send_message("Bidding is currently paused. // ระบบประมูลกำลังหยุดชั่วคราว", ephemeral=True)
            return

        # Defer the response so we have time to process
        await interaction.response.defer()
        
        user = interaction.user
        current_timestamp = int(time.time())

        # Call the updated function and check the return value
        success = await self.cog.add_or_update_bid(self.rune_label, user, current_timestamp)

        if success:
            # If the bid was successful, update the main message
            await self.cog.update_bidding_message(interaction=interaction, is_interaction_edit=True)
        else:
            # If the bid failed (limit reached), send a private message to the user
            # We use followup because we already deferred the interaction
            await interaction.followup.send(
                f"You have reached the maximum of {MAX_BIDS_PER_ITEM} bids for this item. // คุณได้ประมูลไอเทมนี้ครบจำนวนสูงสุด {MAX_BIDS_PER_ITEM} ครั้งแล้ว", 
                ephemeral=True
            )


class ClearBidsButton(Button):
    def __init__(self, cog_instance, *, disabled: bool = False):
        super().__init__(label="Clear My Bids", style=discord.ButtonStyle.primary, custom_id="bid_clear_my", disabled=disabled)
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        if self.cog.is_paused:
            await interaction.response.send_message("Bidding is currently paused. // ระบบประมูลกำลังหยุดชั่วคราว", ephemeral=True)
            return

        await interaction.response.defer()
        user = interaction.user
        await self.cog.clear_user_bids(user)
        # <<< [แก้ไข] เอา `view=self.view` ออกจากการเรียกฟังก์ชัน
        await self.cog.update_bidding_message(interaction=interaction, is_interaction_edit=True)


class DoneBiddingButton(Button):
    def __init__(self, cog_instance, *, disabled: bool = False):
        super().__init__(label="Done Bidding", style=discord.ButtonStyle.success, custom_id="bid_done", disabled=disabled)
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        ## <<< [เพิ่ม] ตรวจสอบสถานะ pause ก่อนทำงาน
        if self.cog.is_paused:
            await interaction.response.send_message("Bidding is currently paused. // ระบบประมูลกำลังหยุดชั่วคราว", ephemeral=True)
            return

        user = interaction.user
        # หารูนที่ user ประมูลไว้และ *ยังไม่* กด done
        user_bids_runes = self.cog.get_user_active_bid_runes(user)

        if not user_bids_runes:
            await interaction.response.send_message("You don't have any active bids to mark as done.", ephemeral=True)
            return

        # สร้าง Select Menu ใน callback นี้เลย
        options = [discord.SelectOption(label=rune, value=rune) for rune in user_bids_runes]
        # จำกัดจำนวน option ไม่ให้เกิน 25 (ขีดจำกัดของ Discord)
        if len(options) > 25:
             await interaction.response.send_message("You have too many active bids (>25) to display in a selection menu. Please clear some bids first.", ephemeral=True)
             return

        select = Select(
            placeholder="Select rune(s) to mark as Done",
            min_values=1,
            max_values=min(len(options), 25), # ไม่เกินจำนวน option ที่มี และไม่เกิน 25
            options=options,
            custom_id="bid_done_select" # custom_id สำหรับ select
        )

        async def select_callback(select_interaction: discord.Interaction):
            # Important: Defer the response to the select interaction
            await select_interaction.response.defer(ephemeral=True) # Defer แบบ ephemeral
            selected_runes = select_interaction.data.get('values', [])
            await self.cog.mark_bids_done(user, selected_runes)

            # Send confirmation via followup for the select interaction
            await select_interaction.followup.send(f"Marked bids for {', '.join(selected_runes)} as done. Please refresh the main message if needed. // ทำการตั้งค่าการประมูล {', '.join(selected_runes)} เป็นเสร็จสิ้นเรียบร้อย กรุณากดปุ่มรีเฟรชที่ข้อความหลักหากจำเป็น ขอบคุณครับ❤️", ephemeral=True)

            # --- พยายามอัปเดตข้อความหลัก ---
            # หา View หลัก (view ของปุ่ม Done Bidding) จาก interaction เดิมของปุ่ม
            original_view = self.view
            try:
                # พยายาม fetch ข้อความหลักมาแก้ไขโดยตรง (น่าเชื่อถือกว่า interaction เดิม)
                await self.cog.update_bidding_message(is_interaction_edit=False)
            except Exception as e:
                log.warning(f"ไม่สามารถอัปเดตข้อความหลักอัตโนมัติหลัง 'Done': {e}")


        select.callback = select_callback
        view = View(timeout=180) # View สำหรับ Select เท่านั้น
        view.add_item(select)
        # ส่ง Select menu กลับไปหาคนที่กดปุ่ม Done
        await interaction.response.send_message("Choose the rune(s) to mark as Done:", view=view, ephemeral=True)


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
        await self.cog.update_bidding_message(interaction=interaction, is_restart=True, is_interaction_edit=True)


class RefreshButton(Button):
    def __init__(self, cog_instance):
        super().__init__(label="🔃", style=discord.ButtonStyle.secondary, custom_id="bid_refresh")
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # <<< [แก้ไข] เอา `view=self.view` ออกจากการเรียกฟังก์ชัน
        await self.cog.update_bidding_message(interaction=interaction, is_interaction_edit=True)


class BiddingView(View):
    # ทำให้ View สามารถถูกสร้างใหม่ได้ง่าย และจัดการปุ่มต่างๆ
    ## <<< [แก้ไข] รับ is_paused เพื่อกำหนดสถานะปุ่ม
    def __init__(self, cog_instance, *, is_paused: bool = False, timeout=None):
        super().__init__(timeout=timeout)
        self.cog = cog_instance

        # ปุ่มที่ทุกคนใช้ได้ แต่จะถูก disable ตอน pause
        is_action_disabled = is_paused

        # เพิ่มปุ่ม Refresh ก่อน (ปุ่มนี้ไม่ควร disable)
        self.add_item(RefreshButton(cog_instance=self.cog))

        # เพิ่มปุ่มรูน
        for rune in BIDDING_RUNES:
             self.add_item(RuneButton(rune, self.cog, disabled=is_action_disabled))

        # เพิ่มปุ่มจัดการ (บางปุ่มจะ disable ตอน pause)
        self.add_item(ClearBidsButton(self.cog, disabled=is_action_disabled))
        self.add_item(DoneBiddingButton(self.cog, disabled=is_action_disabled))
        # ปุ่ม Restart สำหรับ Admin ไม่ต้อง disable
        self.add_item(RestartButton(self.cog))

# --- คลาส Cog หลัก ---
class BiddingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rune_bids: BiddingDataType = {rune: [] for rune in BIDDING_RUNES}
        self.rune_bid_order: List[str] = []
        self.bidding_message_id: Optional[int] = None
        self.bidding_channel_id: int = BIDDING_CHANNEL_ID
        self.persistent_view_added = False
        self.message_lock = asyncio.Lock()
        self.is_paused: bool = False ## <<< [เพิ่ม] สถานะสำหรับ Pause/Resume
        log.info(f"BiddingCog: โหลดสำเร็จ จัดการประมูลสำหรับช่อง ID: {self.bidding_channel_id}")

    # --- Listener สำหรับ View แบบถาวร ---
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.persistent_view_added:
             log.info("BiddingCog: on_ready - กำลังตรวจสอบ/เพิ่ม Persistent View...")
             ## <<< [แก้ไข] ส่งสถานะ is_paused ปัจจุบัน (ซึ่งคือ False ตอนเริ่ม)
             persistent_view = BiddingView(cog_instance=self, is_paused=self.is_paused, timeout=None)
             self.bot.add_view(persistent_view)
             self.persistent_view_added = True
             log.info("BiddingCog: Persistent View ถูกเพิ่ม/ตรวจสอบแล้ว")
             if self.bidding_message_id:
                  log.info(f"พบ Bidding Message ID ที่บันทึกไว้: {self.bidding_message_id}")
             else:
                  log.warning("ไม่พบ Bidding Message ID ที่บันทึกไว้. อาจต้องใช้ !startbiddingrune เพื่อสร้างใหม่")


    ## <<< [เพิ่ม] คำสั่ง !pause
    @commands.command(name="pause")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def pause_bidding(self, ctx: commands.Context):
        """Pauses the bidding. Disables bidding buttons. (Admin only)"""
        if self.is_paused:
            await ctx.send("Bidding is already paused.", ephemeral=True)
            return

        self.is_paused = True
        log.info(f"--- Bidding PAUSED by {ctx.author.name} ---")
        await ctx.send("Bidding has been paused. Buttons will be disabled.", ephemeral=True)
        # อัปเดตข้อความหลักเพื่อแสดงสถานะและปิดปุ่ม
        await self.update_bidding_message()

    ## <<< [เพิ่ม] คำสั่ง !resume
    @commands.command(name="resume")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def resume_bidding(self, ctx: commands.Context):
        """Resumes the bidding. Re-enables bidding buttons. (Admin only)"""
        if not self.is_paused:
            await ctx.send("Bidding is not currently paused.", ephemeral=True)
            return

        self.is_paused = False
        log.info(f"--- Bidding RESUMED by {ctx.author.name} ---")
        await ctx.send("Bidding has been resumed. Buttons will be re-enabled.", ephemeral=True)
        # อัปเดตข้อความหลักเพื่อเอาสถานะออกและเปิดปุ่ม
        await self.update_bidding_message()

    @commands.command(name="manualbid", aliases=["mbid", "manual"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def manual_bid(self, ctx: commands.Context, item_name: str, user: discord.Member, quantity: int, timestamp: Optional[int] = None):
        """
        Manually set a bid for a user. (Admin only)
        
        Usage: !manualbid "<Item Name>" @User <TotalQuantity> [OptionalUnixTimestamp]
        Example: !manualbid "Netherforce" @SomeUser 3
        Example with timestamp: !manualbid "Netherforce" @SomeUser 3 1672531200
        Note: The timestamp must be a number, not the <t:...:R> format.
        """
        # --- Input Validation ---
        if quantity <= 0:
            await ctx.send("❌ Quantity must be a positive number.", ephemeral=True)
            return

        # Sanitize item_name and check if it's a valid bidding item
        clean_item_name = item_name.strip()
        if clean_item_name not in BIDDING_RUNES:
            await ctx.send(
                f"❌ Invalid item name: `{clean_item_name}`.\n"
                f"Valid items are: `{'`, `'.join(BIDDING_RUNES)}`", 
                ephemeral=True
            )
            return

        # Use the provided timestamp or default to the current time
        final_timestamp = timestamp or int(time.time())

        # --- Execution ---
        await self.manual_add_or_update_bid(
            admin=ctx.author,
            target_user=user,
            rune_label=clean_item_name,
            quantity=quantity,
            timestamp=final_timestamp
        )

        # --- Feedback ---
        await ctx.send(f"✅ Manually set bid for **{user.display_name}** on **{clean_item_name}** to **{quantity}**.", ephemeral=True)
        
        # Update the main bidding message to show the change
        await self.update_bidding_message()


    # --- Command สำหรับเริ่ม/สร้างข้อความประมูล ---
    @commands.command(name="startbiddingrune")
    @commands.has_permissions(administrator=True) # จำกัดให้ Admin ใช้
    @commands.guild_only() # ใช้ได้เฉพาะใน Server
    async def start_bidding(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """สร้างข้อความเริ่มต้นสำหรับการประมูลในช่องที่ระบุ (Admin เท่านั้น)"""
        target_channel = channel or ctx.guild.get_channel(self.bidding_channel_id) or ctx.channel
        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            await ctx.send("ไม่พบช่องข้อความที่ถูกต้องสำหรับส่งข้อความประมูล", ephemeral=True)
            return

        user_guide = self._get_user_guide()
        if "# Error" in user_guide:
             await ctx.send(f"คำเตือน: ไม่สามารถโหลด User Guide ได้\n{user_guide}", ephemeral=True)

        try:
            await target_channel.send(user_guide)
        except discord.Forbidden:
             await ctx.send(f"ไม่มีสิทธิ์ส่งข้อความ User Guide ในช่อง {target_channel.mention}", ephemeral=True)
             return
        except discord.HTTPException as e:
            await ctx.send(f"เกิดข้อผิดพลาดในการส่ง User Guide: {e}", ephemeral=True)

        # สร้าง View และส่งข้อความหลัก
        ## <<< [แก้ไข] ส่งสถานะ is_paused ไปยัง View ตอนสร้าง
        view = BiddingView(cog_instance=self, is_paused=self.is_paused, timeout=None)
        initial_content = "Choose a rune to bid on:"
        try:
            msg = await target_channel.send(initial_content, view=view)
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

            self.bidding_message_id = msg.id
            log.info(f"สร้างข้อความประมูลใหม่ ID: {self.bidding_message_id} ในช่อง {target_channel.id}")
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
    async def add_or_update_bid(self, rune_label: str, user: discord.User | discord.Member, timestamp: int) -> bool:
        """
        Adds a new bid entry for the user. Each call represents one bid.
        Returns:
            bool: True if the bid was added, False if the user reached their bid limit.
        """
        async with self.message_lock:  # Lock before modifying bid data
            if rune_label not in self.rune_bids:
                log.warning(f"Attempted bid on unknown rune: {rune_label}")
                return False

            bids_for_rune = self.rune_bids[rune_label]
            user_id = user.id
            display_name = user.display_name
            user_global_name = user.global_name or user.name

            # --- [NEW LOGIC] ---
            # Count the number of existing entries for this user on this rune
            user_bid_count = sum(1 for bid in bids_for_rune if bid['user_id'] == user_id)

            # Check if they have reached the maximum
            if user_bid_count >= MAX_BIDS_PER_ITEM:
                log.info(f"Bid attempt rejected for {display_name} on {rune_label}. Limit of {MAX_BIDS_PER_ITEM} reached.")
                return False  # Return False to indicate failure

            # Always add a new bid entry, as each click is a separate bid.
            new_bid = {
                'user_id': user_id,
                'user_mention': user.mention,
                'user_display_name': user_global_name,
                'quantity': 1,  # Quantity is always 1 per entry
                'timestamp': timestamp,
                'done': False
            }
            bids_for_rune.append(new_bid)
            log.info(f"Added new bid for {display_name} ({user_id}) on {rune_label}. They now have {user_bid_count + 1} bids.")
            
            if rune_label not in self.rune_bid_order:
                self.rune_bid_order.append(rune_label)
            
            return True # Return True to indicate success

    async def clear_user_bids(self, user: discord.User):
        """ลบการประมูลทั้งหมดของผู้ใช้ที่ระบุ"""
        async with self.message_lock: # ล็อคก่อนแก้ไขข้อมูล
            user_id = user.id
            cleared_count = 0
            runes_to_check = list(self.rune_bids.keys())

            for rune in runes_to_check:
                initial_len = len(self.rune_bids[rune])
                self.rune_bids[rune] = [bid for bid in self.rune_bids[rune] if bid['user_id'] != user_id]
                cleared_in_rune = initial_len - len(self.rune_bids[rune])
                if cleared_in_rune > 0:
                    cleared_count += cleared_in_rune
                    log.info(f"ลบ {cleared_in_rune} bid ของ {user.display_name} ({user_id}) ออกจาก {rune}")
                    if not self.rune_bids[rune] and rune in self.rune_bid_order:
                        try:
                            self.rune_bid_order.remove(rune)
                            log.info(f"นำ {rune} ออกจากลำดับการประมูลเนื่องจากไม่มี bid เหลือ")
                        except ValueError: pass

            if cleared_count > 0:
                log.info(f"รวมลบการประมูล {cleared_count} รายการสำหรับผู้ใช้: {user.display_name} ({user_id})")
            else:
                 log.info(f"ผู้ใช้ {user.display_name} ({user_id}) ไม่มี bid ให้ลบ")


    def get_user_active_bid_runes(self, user: discord.User) -> List[str]:
        """คืนค่ารายการรูนที่ผู้ใช้มีการประมูลที่ยังไม่ 'done' """
        user_id = user.id
        return [rune for rune, bids in self.rune_bids.items() if any(bid['user_id'] == user_id and not bid.get('done', False) for bid in bids)]

    async def mark_bids_done(self, user: discord.User, runes_to_mark: List[str]):
        """ทำเครื่องหมายการประมูลของผู้ใช้สำหรับรูนที่ระบุว่าเป็น 'done'"""
        async with self.message_lock: # ล็อคก่อนแก้ไข
            user_id = user.id
            marked_count = 0
            display_name = user.display_name
            for rune in runes_to_mark:
                if rune in self.rune_bids:
                    for bid in self.rune_bids[rune]:
                        if bid['user_id'] == user_id and not bid.get('done', False):
                            bid['done'] = True
                            marked_count += 1
            if marked_count > 0:
                log.info(f"ทำเครื่องหมาย {marked_count} การประมูลเป็น 'done' สำหรับ {display_name} ({user_id}) ในรูน: {', '.join(runes_to_mark)}")
            else:
                 log.info(f"ไม่พบ bid ที่ยังไม่ done ของ {display_name} ({user_id}) ในรูนที่เลือก: {', '.join(runes_to_mark)}")


    async def restart_bidding(self):
        """รีเซ็ตข้อมูลการประมูลทั้งหมด"""
        async with self.message_lock: # ล็อคขณะรีเซ็ต
            self.rune_bids = {rune: [] for rune in BIDDING_RUNES}
            self.rune_bid_order = []
            log.info("--- ระบบการประมูลถูกรีสตาร์ท (ข้อมูลในหน่วยความจำ) ---")


    # --- Method สำหรับอัปเดตข้อความประมูล ---
    ## <<< [แก้ไข] ไม่ต้องรับ view, สร้างใหม่เสมอตามสถานะ is_paused
    async def update_bidding_message(self, interaction: Optional[discord.Interaction] = None, msg_to_edit: Optional[discord.Message] = None, is_restart: bool = False, is_interaction_edit: bool = True):
        """อัปเดตเนื้อหาข้อความประมูลหลัก (Thread-safe)"""
        async with self.message_lock:
            log.debug(f"Update message triggered by: {'Interaction' if interaction else 'Direct Call'}{' (Restart)' if is_restart else ''}")

            ## <<< [เพิ่ม] สร้าง Prefix ตามสถานะ Pause
            status_prefix = ""
            if self.is_paused:
                status_prefix = "## ⏸️ BIDDING IS CURRENTLY PAUSED ⏸️\n\n"

            if is_restart:
                new_content = status_prefix + "Bidding has been restarted. Choose a rune to bid on:"
            else:
                active_bids_data = {rune: bids for rune, bids in self.rune_bids.items() if bids}
                if not active_bids_data:
                    new_content = status_prefix + "No current bids."
                else:
                    def sort_key(rune_name):
                        try: order_index = self.rune_bid_order.index(rune_name)
                        except ValueError: order_index = float('inf')
                        return (-len(self.rune_bids.get(rune_name, [])), order_index)

                    sorted_runes = sorted(active_bids_data.keys(), key=sort_key)
                    lines = []
                    for rune in sorted_runes:
                        bids = active_bids_data[rune]
                        sorted_bids = sorted(bids, key=lambda b: b.get('timestamp', 0))
                        
                        # --- [MODIFIED LINE] ---
                        # Remove the 'quantity' part from the display string
                        bid_lines = [
                            (f"{idx + 1}. {bid.get('user_mention', 'Unknown User')} "
                             f"({bid.get('user_display_name', '?')}) " # <-- Removed the quantity part here
                             f"<t:{bid.get('timestamp', 0)}:R> {'✅' if bid.get('done', False) else ''}").strip()
                            for idx, bid in enumerate(sorted_bids)
                        ]
                        # --- [END MODIFIED LINE] ---
                        
                        lines.append(f"# **{rune}**:\n" + "\n".join(bid_lines))
                    bid_content = "\n\n".join(lines)
                    new_content = status_prefix + bid_content
                    if len(new_content) > 4000:
                         new_content = new_content[:3950] + "\n... (Message too long, truncated)"
                         log.warning("เนื้อหาข้อความประมูลยาวเกินไป ถูกตัดให้สั้นลง")


            ## <<< [แก้ไข] สร้าง View ใหม่เสมอเพื่อให้สถานะปุ่ม (disabled/enabled) ถูกต้อง
            current_view = BiddingView(cog_instance=self, is_paused=self.is_paused, timeout=None)

            # --- ส่วนที่เหลือของฟังก์ชันเหมือนเดิม ---
            message_edited = False
            target_message_id = self.bidding_message_id
            edit_target = None

            if interaction and is_interaction_edit:
                edit_target = interaction
                log.debug(f"พยายามแก้ไขผ่าน Interaction: {interaction.id}")
            elif msg_to_edit:
                 edit_target = msg_to_edit
                 target_message_id = msg_to_edit.id
                 log.debug(f"พยายามแก้ไขผ่าน Message object: {msg_to_edit.id}")
            elif target_message_id:
                 log.debug(f"พยายามแก้ไขผ่าน Message ID ที่บันทึกไว้: {target_message_id}")
                 pass
            else:
                 log.warning("ไม่สามารถอัปเดตข้อความได้: ไม่มี Interaction, Message หรือ Message ID ที่จะใช้แก้ไข")
                 return

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
                if target_message_id and target_message_id == self.bidding_message_id:
                    self.bidding_message_id = None
                    log.warning("Bidding Message ID ถูกเคลียร์เนื่องจากไม่พบข้อความ")
            except discord.HTTPException as e:
                log.error(f"เกิดข้อผิดพลาด HTTP ขณะอัปเดตข้อความประมูล (ID: {target_message_id}): {e.status} - {e.text}")
            except Exception as e:
                log.exception(f"เกิดข้อผิดพลาดที่ไม่คาดคิดขณะอัปเดตข้อความประมูล (ID: {target_message_id}): {e}")

            if not message_edited:
                log.warning("การอัปเดตข้อความประมูลล้มเหลว")

    async def manual_add_or_update_bid(self, admin: discord.User, target_user: discord.Member, rune_label: str, quantity: int, timestamp: int):
        """
        Manually sets a user's total bid count by removing their old bids
        and adding a specific number of new, individual bids.
        """
        async with self.message_lock: # Lock before modifying bid data
            if rune_label not in self.rune_bids:
                log.warning(f"Manual bid by {admin.name} for {target_user.name} failed: Unknown rune {rune_label}")
                return

            user_id = target_user.id
            user_global_name = target_user.global_name or target_user.name

            # --- [NEW LOGIC] ---
            # 1. Remove all existing bids for this user on this specific rune.
            self.rune_bids[rune_label] = [
                bid for bid in self.rune_bids[rune_label] if bid['user_id'] != user_id
            ]
            log.info(f"Manual bid: Cleared previous bids for {target_user.display_name} on {rune_label}.")

            # 2. Add 'quantity' number of new, individual bids.
            for i in range(quantity):
                new_bid = {
                    'user_id': user_id,
                    'user_mention': target_user.mention,
                    'user_display_name': user_global_name,
                    'quantity': 1, # Each entry has a quantity of 1
                    'timestamp': timestamp + i, # Add a tiny offset to maintain order if needed
                    'done': False
                }
                self.rune_bids[rune_label].append(new_bid)

            log.info(f"Manual bid by {admin.name}: Set {target_user.display_name}'s total bids for {rune_label} to {quantity}")
            
            # Ensure the rune is in the display order if it wasn't already
            if quantity > 0 and rune_label not in self.rune_bid_order:
                self.rune_bid_order.append(rune_label)
            # Remove from order if bids are set to 0 and no one else is bidding
            elif quantity == 0 and not self.rune_bids[rune_label]:
                 if rune_label in self.rune_bid_order:
                     self.rune_bid_order.remove(rune_label)


# --- ฟังก์ชัน Setup สำหรับ Cog ---
async def setup(bot: commands.Bot):
    """Loads the BiddingCog."""
    try:
        cog_instance = BiddingCog(bot)
        await bot.add_cog(cog_instance)
        log.info("BiddingCog: Setup complete, Cog added to bot.")
    except Exception as e:
        log.exception("BiddingCog: Failed to load Cog.")