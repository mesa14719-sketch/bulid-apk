import os
import sys
import re
import time
import math
import shutil
import asyncio
import gc
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

# ============================================================
# 🔐 Config مباشر
# ============================================================
API_ID = 33651304
API_HASH = "39dd5566cfe202b84f7e6591d3789668"
BOT_TOKEN = "8882497343:AAG-ho19gEPPUZiSfuPy26uZpN4cUp4vs_I"

# ============================================================
# 📁 Paths
# ============================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
JAR_PATH = os.path.join(CURRENT_DIR, "APKPatcher.jar")

BASE_WORK_DIR = os.path.join(CURRENT_DIR, "sessions")
CUSTOM_FILES_DIR = os.path.join(CURRENT_DIR, "custom_files")

os.makedirs(BASE_WORK_DIR, exist_ok=True)
os.makedirs(CUSTOM_FILES_DIR, exist_ok=True)

# ============================================================
# ☕ كشف Java تلقائياً
# ============================================================
def find_java():
    java_path = shutil.which("java")
    if java_path:
        return java_path
    common = [
        "/usr/bin/java",
        "/usr/local/bin/java",
        "/usr/lib/jvm/default-java/bin/java",
        "/opt/java/openjdk/bin/java",
        "/opt/java/bin/java",
    ]
    for p in common:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    if os.environ.get("JAVA_HOME"):
        j = os.path.join(os.environ["JAVA_HOME"], "bin", "java")
        if os.path.exists(j):
            return j
    if os.path.isdir("/usr/lib/jvm"):
        for d in os.listdir("/usr/lib/jvm"):
            j = os.path.join("/usr/lib/jvm", d, "bin", "java")
            if os.path.exists(j):
                return j
    return None

JAVA_BIN = find_java() or "java"

# ============================================================
# 🌐 Health Server — لـ Render Port Scan
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - APKPatcher Bot Running")
    
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    
    def log_message(self, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"✅ Health Server على المنفذ :{port}")
        return server
    except Exception as e:
        print(f"⚠️ Health Server failed: {e}")
        return None

# ============================================================
# 🚀 Client
# ============================================================
app = Client("apkpatcher_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ============================================================
# 📋 Flags
# ============================================================
ALL_FLAGS = {
    "-ssl": "تجاوز فحص شهادات SSL",
    "-fix": "إصلاح مشاكل التثبيت",
    "-rmss": "تجاوز منع لقطات الشاشة",
    "-v": "تجاوز كشف الـ VPN",
    "-rmusb": "تجاوز كشف تصحيح USB",
    "-rmads": "إزالة وإلغاء الإعلانات",
    "-id": "تجاوز تسجيل الدخول لجهاز واحد",
    "-paid": "فتح المحتوى المدفوع (معاينة)",
    "-pine": "حقن Pine Hook (Abhi Loader)",
    "-pine2": "حقن Pine Hook (My Loader)",
    "-pkg": "تجاوز كشف اسم الحزمة",
    "-a": "حقن سجلات الخوارزميات (Logs)",
    "-u": "الحفاظ على الملف بدون توقيع",
    "-tg": "باتش Telegram / Plus"
}

user_flags = {}
user_paths = {}
user_waiting_input = {}
last_edit_times = {}

# ============================================================
# 🔧 Helpers
# ============================================================
def humanbytes(size):
    if not size:
        return "0 B"
    dict_power = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    n = 0
    while size > 1024 and n < 4:
        size /= 1024
        n += 1
    return f"{round(size, 2)} {dict_power[n]}"

def time_formatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((f"{days}d, " if days else "") +
           (f"{hours}h, " if hours else "") +
           (f"{minutes}m, " if minutes else "") +
           (f"{seconds}s, " if seconds else ""))
    return tmp[:-2] if tmp else "0s"

async def progress_bar(current, total, ud_type, message: Message, start_time):
    now = time.time()
    diff = now - start_time
    msg_id = message.id
    
    if msg_id in last_edit_times and (now - last_edit_times[msg_id] < 2.0) and current != total:
        return
    
    percentage = (current * 100 / total) if total > 0 else 0
    speed = current / diff if diff > 0 else 0
    time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0

    filled_length = math.floor(percentage / 10)
    bar = "▰" * filled_length + "▱" * (10 - filled_length)

    tmp = f"<b>{ud_type}</b>\n\n"
    tmp += f"<code>[{bar}] {round(percentage, 1)}%</code>\n\n"
    tmp += f"📊 <b>تم نقل:</b> <code>{humanbytes(current)} / {humanbytes(total)}</code>\n"
    tmp += f"🚀 <b>السرعة:</b> <code>{humanbytes(speed)}/s</code>\n"
    tmp += f"⏳ <b>الوقت المتبقي:</b> <code>{time_formatter(time_to_completion)}</code>"

    try:
        await message.edit_text(tmp)
        last_edit_times[msg_id] = now
    except Exception:
        pass

def build_flags_keyboard(user_id):
    if user_id not in user_flags:
        user_flags[user_id] = {"-ssl": True, "-fix": True}
    
    active = user_flags[user_id]
    paths = user_paths.get(user_id, {})
    buttons = []
    
    for flag_key, flag_desc in ALL_FLAGS.items():
        icon = "✅" if active.get(flag_key, False) else "❌"
        button_text = f"{icon} {flag_desc} [{flag_key}]"
        buttons.append([InlineKeyboardButton(button_text, callback_data=f"toggle_{flag_key}")])
        
    c_status = "📌" if "-c" in paths else "➕"
    l_status = "📌" if "-l" in paths else "➕"
    
    buttons.append([
        InlineKeyboardButton(f"{c_status} شهادة خاصة (-c)", callback_data="input_-c"),
        InlineKeyboardButton(f"{l_status} مسار الموديول (-l)", callback_data="input_-l")
    ])
    
    buttons.append([
        InlineKeyboardButton("🧹 إعادة ضبط الخيارات", callback_data="reset_flags"),
        InlineKeyboardButton("📋 عرض الأمر النهائى", callback_data="show_cmd")
    ])
    
    return InlineKeyboardMarkup(buttons)

# ============================================================
# 🎯 Handlers
# ============================================================
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_flags:
        user_flags[user_id] = {"-ssl": True, "-fix": True}
        
    text = (
        "<b>🛠️ لوحة تحكم أداة APKPatcher المحترفة</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "قم بتحديد الفلاجات والباتشات المطلوبة من القائمة أدناه.\n"
        "الأزرار مجهزة بحالة التفعيل (✅/❌).\n\n"
        "📦 <b>الصيغ المدعومة:</b> <code>.apk</code> | <code>.apks</code> | <code>.apkm</code> | <code>.xapk</code>\n"
        "⚡ بعد ضبط الخيارات، أرسل التطبيق فوراً للبدء في المعالجة."
    )
    await message.reply_text(text, reply_markup=build_flags_keyboard(user_id))

@app.on_message(filters.command("flags") & filters.private)
async def flags_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    await message.reply_text("<b>🎛️ قائمة الفلاجات والباتشات المتاحة:</b>", reply_markup=build_flags_keyboard(user_id))

@app.on_callback_query()
async def handle_callbacks(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data
    
    if user_id not in user_flags:
        user_flags[user_id] = {"-ssl": True, "-fix": True}
        
    if data.startswith("toggle_"):
        flag = data.replace("toggle_", "")
        user_flags[user_id][flag] = not user_flags[user_id].get(flag, False)
        await callback.message.edit_reply_markup(reply_markup=build_flags_keyboard(user_id))
        status_str = "تم تفعيل" if user_flags[user_id][flag] else "تم إيقاف"
        await callback.answer(f"{status_str} {flag}")
        
    elif data == "reset_flags":
        user_flags[user_id] = {"-ssl": True, "-fix": True}
        user_paths[user_id] = {}
        await callback.message.edit_reply_markup(reply_markup=build_flags_keyboard(user_id))
        await callback.answer("تمت إعادة ضبط جميع الخيارات")
        
    elif data == "input_-c":
        user_waiting_input[user_id] = "-c"
        await callback.answer()
        await callback.message.reply_text("<b>📥 قم بإرسال ملف الشهادة الآن (.cert/.crt/.pem/.0) أو أرسل مسار الشهادة كرسالة نصية:</b>")
        
    elif data == "input_-l":
        user_waiting_input[user_id] = "-l"
        await callback.answer()
        await callback.message.reply_text("<b>📥 قم بإرسال مسار موديول Xposed / LSP Module كرسالة نصية:</b>")
        
    elif data == "show_cmd":
        active_flags = [flag for flag, active in user_flags[user_id].items() if active]
        paths = user_paths.get(user_id, {})
        for k, v in paths.items():
            active_flags.extend([k, v])
        cmd_str = f"java -jar APKPatcher.jar -i <app_name> {' '.join(active_flags)}"
        await callback.answer(f"الأمر المطبق حالياً:\n{cmd_str}", show_alert=True)

@app.on_message(filters.text & filters.private & ~filters.command(["start", "flags"]))
async def handle_text_inputs(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in user_waiting_input:
        target_flag = user_waiting_input.pop(user_id)
        if user_id not in user_paths:
            user_paths[user_id] = {}
        user_paths[user_id][target_flag] = message.text.strip()
        await message.reply_text(f"✅ تم تعيين مسار <code>{target_flag}</code> بنجاح:\n<code>{message.text.strip()}</code>", reply_markup=build_flags_keyboard(user_id))

@app.on_message(filters.document & filters.private)
async def process_document(client: Client, message: Message):
    user_id = message.from_user.id
    doc = message.document
    filename = doc.file_name.lower() if doc.file_name else "file"
    
    if not os.path.exists(JAR_PATH):
        await message.reply_text(
            f"❌ <b>خطأ رئيسي:</b>\n"
            f"ملف الأداة غير موجود في هذا المسار:\n<code>{JAR_PATH}</code>\n\n"
            f"⚠️ يرجى نقل ملف <code>APKPatcher.jar</code> ليكون بجانب ملف البوت الرئيسي مباشرة."
        )
        return

    if user_id in user_waiting_input and user_waiting_input[user_id] == "-c":
        if filename.endswith(('.cert', '.crt', '.pem', '.0')):
            user_waiting_input.pop(user_id)
            cert_path = os.path.join(CUSTOM_FILES_DIR, f"{user_id}_{doc.file_name}")
            await client.download_media(message, file_name=cert_path)
            if user_id not in user_paths:
                user_paths[user_id] = {}
            user_paths[user_id]["-c"] = cert_path
            await message.reply_text(f"✅ تم حفظ الشهادة وحقنها مع الفلاج <code>-c</code> بنجاح!", reply_markup=build_flags_keyboard(user_id))
            return

    if not filename.endswith(('.apk', '.apks', '.apkm', '.xapk')):
        await message.reply_text("❌ <b>عذراً! صيغة الملف غير مدعومة.</b>\nيرجى إرسال ملف بأحد الامتدادات: (<code>.apk</code>, <code>.apks</code>, <code>.apkm</code>, <code>.xapk</code>)")
        return

    status_msg = await message.reply_text("📥 <b>جاري التحضير للتنزيل...</b>")
    session_dir = os.path.join(BASE_WORK_DIR, f"session_{user_id}_{int(time.time())}")
    os.makedirs(session_dir, exist_ok=True)
    
    input_path = os.path.join(session_dir, doc.file_name)
    start_time = time.time()
    
    try:
        await client.download_media(
            message=message,
            file_name=input_path,
            progress=progress_bar,
            progress_args=("⬇️ <b>جاري تنزيل التطبيق من تيليجرام</b>", status_msg, start_time)
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>حدث خطأ أثناء التنزيل:</b>\n<code>{e}</code>")
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    await status_msg.edit_text("⚙️ <b>جاري معالجة الملف وتطبيق الفلاجات عبر APKPatcher.jar...</b>")
    
    active_flags = user_flags.get(user_id, {"-ssl": True, "-fix": True})
    cmd_flags = [flag for flag, enabled in active_flags.items() if enabled]
    
    paths = user_paths.get(user_id, {})
    for k, v in paths.items():
        cmd_flags.extend([k, v])

    is_split = filename.endswith(('.apks', '.apkm', '.xapk'))
    mode_flag = "-m" if is_split else "-i"
    
    cmd = [JAVA_BIN, "-jar", JAR_PATH, mode_flag, input_path] + cmd_flags
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=session_dir
        )
        stdout, stderr = await process.communicate()
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>فشل تشغيل الأداة:</b>\n<code>{e}</code>")
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    if process.returncode != 0:
        err_log = stderr.decode().strip() or stdout.decode().strip()
        await status_msg.edit_text(f"❌ <b>حدث خطأ أثناء معالجة التطبيق:</b>\n<code>{err_log[:1000]}</code>")
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    generated_file = None
    for root, dirs, files in os.walk(session_dir):
        for f in files:
            if f != doc.file_name and f.endswith(('.apk', '.apks', '.apkm', '.xapk')):
                generated_file = os.path.join(root, f)
                break

    if not generated_file or not os.path.exists(generated_file):
        await status_msg.edit_text("❌ <b>لم يتم العثور على الملف الناتج بعد المعالجة.</b>")
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    upload_start = time.time()
    await status_msg.edit_text("⬆️ <b>جاري بدء رفع الملف المعدل...</b>")
    
    used_cmd = " ".join(cmd_flags) if cmd_flags else "Default"
    out_name = f"Patched_{doc.file_name}"

    try:
        await client.send_document(
            chat_id=message.chat.id,
            document=generated_file,
            file_name=out_name,
            caption=(
                "✅ <b>تم تعديل وتطبيق الباتشات بنجاح!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🛠️ <b>الفلاجات المطبقة:</b> <code>{used_cmd}</code>"
            ),
            progress=progress_bar,
            progress_args=("⬆️ <b>جاري رفع التطبيق المعدل</b>", status_msg, upload_start)
        )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>حدث خطأ أثناء رفع الملف:</b>\n<code>{e}</code>")
    finally:
        if os.path.exists(session_dir):
            shutil.rmtree(session_dir, ignore_errors=True)
        last_edit_times.pop(status_msg.id, None)
        gc.collect()

# ============================================================
# 🚀 Main
# ============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 APKPatcher Bot")
    print("=" * 50)
    print(f"☕ Java: {JAVA_BIN}")
    print(f"📦 JAR: {'✅' if os.path.exists(JAR_PATH) else '❌'}")
    print("=" * 50)
    
    # تشغيل Health Server (لـ Render)
    start_health_server()
    
    # تشغيل البوت
    print("🚀 البوت يعمل...")
    app.run()
