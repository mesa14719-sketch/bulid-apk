#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
كاشف دوال الشراء Pro - السيرفر (Render Ready)
pip install flask androguard gunicorn
"""

import os
import sys
import json
import time
import threading
import uuid

try:
    from flask import Flask, request, jsonify, render_template, Response
    from androguard.core.apk import APK
    from androguard.core.dex import DEX
except ImportError:
    print("=" * 50)
    print("📦 تثبيت المكتبات المطلوبة...")
    print("=" * 50)
    os.system(f"{sys.executable} -m pip install flask androguard")
    print("\n🔄 أعد تشغيل الملف الآن.")
    sys.exit(0)

app = Flask(__name__)
# Render المجاني: 512MB RAM. الحد الأقصى الآمن للملف 100MB.
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = '/tmp/billing_uploads'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()

# ================== البصمات الثنائية ==================
BYTE_SIGNATURES = {
    "launchBillingFlow": "6c 61 75 6e 63 68 42 69 6c 6c 69 6e 67 46 6c 6f 77",
    "queryPurchases": "71 75 65 72 79 50 75 72 63 68 61 73 65 73",
    "querySkuDetails": "71 75 65 72 79 53 6b 75 44 65 74 61 69 6c 73",
    "acknowledgePurchase": "61 63 6b 6e 6f 77 6c 65 64 67 65 50 75 72 63 68 61 73 65",
}

BILLING_INDICATORS = {
    "com.android.vending.BILLING": {"weight": 30, "type": "permission", "desc": "صلاحية الفوترة"},
    "com.android.billingclient": {"weight": 25, "type": "package", "desc": "مكتبة Billing Client"},
    "BillingClient": {"weight": 15, "type": "class", "desc": "كلاس BillingClient"},
    "launchBillingFlow": {"weight": 10, "type": "method", "desc": "دالة بدء الشراء"},
    "queryPurchases": {"weight": 10, "type": "method", "desc": "دالة الاستعلام عن المشتريات"},
    "onPurchasesUpdated": {"weight": 5, "type": "method", "desc": "دالة تحديث المشتريات"},
}

METHOD_KEYWORDS = [
    "launchBillingFlow", "queryPurchases", "onPurchasesUpdated",
    "querySkuDetailsAsync", "acknowledgePurchase", "startConnection"
]


def update_job(job_id, stage, message, progress):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["progress"].append({
                "stage": stage, "message": message,
                "progress": progress, "timestamp": time.time()
            })


def check_byte_signature(dex_bytes):
    found = []
    for name, hex_sig in BYTE_SIGNATURES.items():
        sig_bytes = bytes.fromhex(hex_sig.replace(" ", ""))
        if sig_bytes in dex_bytes:
            found.append(name)
    return found


def check_obfuscation(apk):
    try:
        dex_files = apk.get_all_dex()
        short_names = 0
        total_names = 0
        for dex_bytes in dex_files:
            d = DEX(dex_bytes)
            for cls in d.get_classes():
                cls_name = cls.get_name()
                parts = cls_name.split("/")
                if parts:
                    last = parts[-1].replace(";", "")
                    total_names += 1
                    if len(last) <= 2:
                        short_names += 1
        if total_names > 0 and (short_names / total_names) > 0.3:
            return True
    except Exception:
        pass
    return False


def analyze_apk_async(job_id, temp_path, filename):
    result = {
        "filename": filename, "success": False, "error": None,
        "indicators_found": [], "methods_found": [],
        "permissions": [], "probability": 0,
        "level": "unknown", "details": {},
        "byte_signatures": [], "obfuscated": False
    }

    try:
        update_job(job_id, "read", "قراءة ملف APK...", 10)
        time.sleep(0.3)
        apk = APK(temp_path)

        update_job(job_id, "permissions", "فحص الصلاحيات...", 20)
        time.sleep(0.3)
        permissions = apk.get_permissions()
        result["permissions"] = list(permissions)
        has_billing_permission = "com.android.vending.BILLING" in permissions

        update_job(job_id, "obfuscation", "كشف التشفير...", 30)
        time.sleep(0.3)
        is_obfuscated = check_obfuscation(apk)
        result["obfuscated"] = is_obfuscated

        update_job(job_id, "metadata", "قراءة إصدار المكتبة...", 35)
        time.sleep(0.3)
        billing_version = None
        try:
            manifest = apk.get_android_manifest_xml()
            for meta in manifest.iter("meta-data"):
                name = meta.get("{http://schemas.android.com/apk/res/android}name")
                value = meta.get("{http://schemas.android.com/apk/res/android}value")
                if name == "com.google.android.play.billingclient.version":
                    billing_version = value
        except Exception:
            pass
        result["details"]["billing_version"] = billing_version

        update_job(job_id, "dex", "تحليل DEX (بحث ثنائي)...", 45)
        time.sleep(0.3)

        found_indicators = set()
        found_methods = []
        found_byte_sigs = set()
        dex_files = apk.get_all_dex()
        total_dex = max(1, len(dex_files))

        for idx, dex_bytes in enumerate(dex_files):
            sigs = check_byte_signature(dex_bytes)
            found_byte_sigs.update(sigs)

            try:
                d = DEX(dex_bytes)
                for cls in d.get_classes():
                    cls_name = cls.get_name()
                    for indicator, info in BILLING_INDICATORS.items():
                        if info["type"] in ("package", "class") and indicator.lower() in cls_name.lower():
                            found_indicators.add(indicator)

                for method in d.get_methods():
                    method_name = method.get_name()
                    for kw in METHOD_KEYWORDS:
                        if kw.lower() in method_name.lower():
                            found_methods.append(method_name)
                            found_indicators.add(kw)
                            break
            except Exception:
                pass

            dex_progress = 45 + int((idx + 1) / total_dex * 30)
            update_job(job_id, "dex", f"تحليل DEX {idx+1}/{total_dex}...", dex_progress)
            time.sleep(0.1)

        update_job(job_id, "calculate", "حساب الاحتمالية...", 85)
        time.sleep(0.3)

        if has_billing_permission:
            result["indicators_found"].append({
                "name": "com.android.vending.BILLING",
                "desc": "صلاحية الفوترة موجودة",
                "weight": 30
            })

        for indicator in found_indicators:
            if indicator in BILLING_INDICATORS:
                info = BILLING_INDICATORS[indicator]
                result["indicators_found"].append({
                    "name": indicator, "desc": info["desc"], "weight": info["weight"]
                })

        for sig in found_byte_sigs:
            result["indicators_found"].append({
                "name": f"ByteSig: {sig}",
                "desc": "بصمة ثنائية لدالة شراء",
                "weight": 20
            })

        result["byte_signatures"] = list(found_byte_sigs)
        result["methods_found"] = list(set(found_methods))[:20]

        # حساب النسبة
        score = 0
        if has_billing_permission: score += 30
        if billing_version: score += 20
        if found_byte_sigs: score += min(30, len(found_byte_sigs) * 10)
        
        name_score = 0
        if "BillingClient" in found_indicators: name_score += 10
        if "launchBillingFlow" in found_indicators or "queryPurchases" in found_indicators: name_score += 10
        score += min(20, name_score)

        if is_obfuscated and found_byte_sigs: score += 10

        probability = min(100, score)
        result["probability"] = probability
        result["success"] = True

        if probability >= 80:
            result["level"] = "مؤكد (High Confidence - 90%+ دقة)"
        elif probability >= 50:
            result["level"] = "محتمل (Medium Confidence)"
        elif probability >= 20:
            result["level"] = "ضعيف (Low Confidence)"
        else:
            result["level"] = "غير موجود (No Billing)"

        update_job(job_id, "done", "اكتمل التحليل!", 100)

        with jobs_lock:
            jobs[job_id]["result"] = result
            jobs[job_id]["status"] = "done"

    except Exception as e:
        update_job(job_id, "error", f"خطأ: {str(e)}", 100)
        with jobs_lock:
            jobs[job_id]["result"] = result
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)
    finally:
        try: os.remove(temp_path)
        except: pass


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "لم يتم رفع أي ملف"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "اسم الملف فارغ"}), 400
    if not file.filename.lower().endswith(".apk"):
        return jsonify({"success": False, "error": "الملف يجب أن يكون APK"}), 400

    job_id = str(uuid.uuid4())
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}.apk")
    file.save(temp_path)

    with jobs_lock:
        jobs[job_id] = {"progress": [], "result": None, "status": "processing", "error": None}

    thread = threading.Thread(target=analyze_apk_async, args=(job_id, temp_path, file.filename))
    thread.daemon = True
    thread.start()

    return jsonify({"success": True, "job_id": job_id})


@app.route("/api/progress/<job_id>")
def api_progress(job_id):
    def generate():
        last_index = 0
        while True:
            with jobs_lock:
                if job_id not in jobs:
                    yield f"data: {json.dumps({'error': 'job_not_found'})}\n\n"
                    return
                job = jobs[job_id]
                new_items = job["progress"][last_index:]
                for item in new_items:
                    yield f"data: {json.dumps(item)}\n\n"
                    last_index += 1
                if job["status"] == "done":
                    yield f"data: {json.dumps({'stage': 'finished', 'result': job['result']})}\n\n"
                    return
                if job["status"] == "error":
                    yield f"data: {json.dumps({'stage': 'error', 'error': job['error'], 'result': job['result']})}\n\n"
                    return
            time.sleep(0.3)
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ================== تشغيل السيرفر ==================
if __name__ == "__main__":
    # Render يعطيك المنفذ عبر متغير PORT
    port = int(os.environ.get("PORT", 5000))
    
    print("=" * 55)
    print("🔍 كاشف دوال الشراء Pro - Render Ready")
    print("=" * 55)
    print(f"🌐 يعمل على المنفذ: {port}")
    print("=" * 55)
    
    # host="0.0.0.0" ضروري لـ Render
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
