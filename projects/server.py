import os
import uuid
import shutil
import subprocess
import time
import threading
from flask import Flask, request, jsonify, send_file, send_from_directory, after_this_request
from werkzeug.utils import secure_filename
from flask_cors import CORS

app = Flask(__name__, static_folder=".")
CORS(app)

# ============================================================
# Config
# ============================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
JAR_PATH = os.path.join(CURRENT_DIR, "APKPatcher.jar")
WORK_DIR = os.path.join(CURRENT_DIR, "work")

os.makedirs(WORK_DIR, exist_ok=True)

MAX_SIZE = 200 * 1024 * 1024  # 200 MB
MAX_AGE = 3600  # ساعة لكل جلسة

# تتبع الجلسات
sessions = {}

# تتبع تقدم التعديل
progress = {}

ALLOWED_FLAGS = [
    "-ssl", "-fix", "-rmss", "-v", "-rmusb", "-rmads",
    "-id", "-paid", "-pine", "-pine2", "-pkg", "-a", "-tg"
]

# ============================================================
# Helper — تنظيف الجلسات القديمة
# ============================================================
def cleanup_old_sessions():
    while True:
        time.sleep(300)  # كل 5 دقائق
        now = time.time()
        for sid in list(sessions.keys()):
            if now - sessions[sid]["created"] > MAX_AGE:
                try:
                    shutil.rmtree(sessions[sid]["dir"], ignore_errors=True)
                    sessions.pop(sid, None)
                    progress.pop(sid, None)
                except Exception:
                    pass

threading.Thread(target=cleanup_old_sessions, daemon=True).start()

# ============================================================
# Routes
# ============================================================
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/upload", methods=["POST"])
def upload():
    """استقبال APK"""
    if "file" not in request.files:
        return jsonify({"error": "لا يوجد ملف"}), 400
    
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "اسم الملف فارغ"}), 400
    
    fname = secure_filename(file.filename)
    ext = os.path.splitext(fname)[1].lower()
    
    if ext not in [".apk", ".apks", ".apkm", ".xapk"]:
        return jsonify({"error": "صيغة غير مدعومة"}), 400
    
    # حجم
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    
    if size > MAX_SIZE:
        return jsonify({"error": f"الحد الأقصى {MAX_SIZE//1024//1024}MB"}), 400
    
    # جلسة جديدة
    session_id = str(uuid.uuid4())
    session_dir = os.path.join(WORK_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    input_path = os.path.join(session_dir, fname)
    file.save(input_path)
    
    sessions[session_id] = {
        "dir": session_dir,
        "input": input_path,
        "filename": fname,
        "size": size,
        "created": time.time(),
        "status": "uploaded",
    }
    progress[session_id] = {"percent": 0, "status": "uploaded", "message": ""}
    
    return jsonify({
        "session_id": session_id,
        "filename": fname,
        "size": size,
    })

@app.route("/api/patch", methods=["POST"])
def patch():
    """بدء التعديل"""
    data = request.json
    session_id = data.get("session_id")
    flags = data.get("flags", [])
    
    if session_id not in sessions:
        return jsonify({"error": "جلسة غير موجودة"}), 404
    
    # فلترة flags
    valid_flags = [f for f in flags if f in ALLOWED_FLAGS]
    
    session = sessions[session_id]
    if session["status"] == "processing":
        return jsonify({"error": "قيد المعالجة"}), 400
    
    session["status"] = "processing"
    progress[session_id] = {"percent": 5, "status": "processing", "message": "بدء التعديل..."}
    
    # شغل في thread
    thread = threading.Thread(
        target=run_patcher,
        args=(session_id, valid_flags),
        daemon=True,
    )
    thread.start()
    
    return jsonify({"status": "started"})

def run_patcher(session_id, flags):
    """تشغيل APKPatcher.jar"""
    session = sessions.get(session_id)
    if not session:
        return
    
    session_dir = session["dir"]
    input_path = session["input"]
    filename = session["filename"]
    
    is_split = filename.endswith((".apks", ".apkm", ".xapk"))
    mode_flag = "-m" if is_split else "-i"
    
    cmd = ["java", "-jar", JAR_PATH, mode_flag, input_path] + flags
    
    try:
        progress[session_id] = {"percent": 10, "status": "processing", "message": "معالجة APK..."}
        
        proc = subprocess.Popen(
            cmd,
            cwd=session_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        # تحديث progress كل ثانية
        start = time.time()
        while proc.poll() is None:
            elapsed = time.time() - start
            # تقدير: 30-120 ثانية
            pct = min(90, 10 + int(elapsed * 1.5))
            progress[session_id] = {
                "percent": pct,
                "status": "processing",
                "message": f"معالجة... ({int(elapsed)}s)"
            }
            time.sleep(1)
        
        stdout, stderr = proc.communicate()
        
        if proc.returncode != 0:
            err = stderr.decode() or stdout.decode()
            progress[session_id] = {
                "percent": 100,
                "status": "error",
                "message": err[:500]
            }
            session["status"] = "error"
            return
        
        # البحث عن الملف الناتج
        generated = find_output(session_dir, input_path)
        
        if not generated:
            progress[session_id] = {
                "percent": 100,
                "status": "error",
                "message": "لم يتم إنتاج ملف"
            }
            session["status"] = "error"
            return
        
        session["output"] = generated
        session["status"] = "done"
        progress[session_id] = {
            "percent": 100,
            "status": "done",
            "message": "اكتمل ✅"
        }
    
    except Exception as e:
        progress[session_id] = {
            "percent": 100,
            "status": "error",
            "message": str(e)[:500]
        }
        session["status"] = "error"

def find_output(session_dir, input_path):
    """البحث عن الملف الناتج"""
    candidates = []
    for root, dirs, files in os.walk(session_dir):
        for f in files:
            full = os.path.join(root, f)
            if full == input_path:
                continue
            if f.endswith((".apk", ".apks", ".apkm", ".xapk")):
                candidates.append(full)
    
    if not candidates:
        return None
    
    # الأحدث
    return max(candidates, key=os.path.getmtime)

@app.route("/api/status/<session_id>")
def status(session_id):
    """حالة التعديل"""
    if session_id not in sessions:
        return jsonify({"error": "جلسة غير موجودة"}), 404
    
    p = progress.get(session_id, {})
    s = sessions[session_id]
    
    return jsonify({
        "percent": p.get("percent", 0),
        "status": p.get("status", "unknown"),
        "message": p.get("message", ""),
        "session_status": s["status"],
    })

@app.route("/api/download/<session_id>")
def download(session_id):
    """تحميل الملف المعدّل"""
    if session_id not in sessions:
        return jsonify({"error": "جلسة غير موجودة"}), 404
    
    session = sessions[session_id]
    if session["status"] != "done":
        return jsonify({"error": "التعديل لم يكتمل"}), 400
    
    output = session.get("output")
    if not output or not os.path.exists(output):
        return jsonify({"error": "الملف غير موجود"}), 404
    
    filename = "patched_" + session["filename"]
    
    @after_this_request
    def cleanup(response):
        # تنظيف بعد 60 ثانية
        def remove_later():
            time.sleep(60)
            try:
                shutil.rmtree(session["dir"], ignore_errors=True)
                sessions.pop(session_id, None)
                progress.pop(session_id, None)
            except Exception:
                pass
        threading.Thread(target=remove_later, daemon=True).start()
        return response
    
    return send_file(output, as_attachment=True, download_name=filename)

@app.route("/api/flags")
def get_flags():
    """قائمة الفلاجات"""
    FLAGS = {
        "-ssl": "تجاوز فحص شهادات SSL",
        "-fix": "إصلاح مشاكل التثبيت",
        "-rmss": "تجاوز منع لقطات الشاشة",
        "-v": "تجاوز كشف VPN",
        "-rmusb": "تجاوز كشف تصحيح USB",
        "-rmads": "إزالة الإعلانات",
        "-id": "تجاوز تسجيل الدخول لجهاز واحد",
        "-paid": "فتح المحتوى المدفوع (معاينة)",
        "-pine": "حقن Pine Hook (Abhi)",
        "-pine2": "حقن Pine Hook (My)",
        "-pkg": "تجاوز كشف اسم الحزمة",
        "-a": "حقن Logs",
        "-tg": "باتش Telegram",
    }
    return jsonify(FLAGS)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
