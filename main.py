# main.py
import os
import re
import time
import json
import requests
from io import BytesIO
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
)

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Please set BOT_TOKEN env var in Replit secrets.")

DATA_FILE = "tracked.json"
WATERMARK_TEXT = "The Alpha House"
CARD_WIDTH = 900
CARD_HEIGHT = 520

# Local filenames (upload these to Replit Files)
LOCAL_MEMES = {
    "low": "lowx.png",     # 1-2x
    "mid": "midx.png",     # 2-10x
    "high": "highx.png",   # 10-20x
    "ultra": "ultrax.png", # 20x+
}

# Fallback online meme URLs if local files are absent
FALLBACK_MEMES = {
    "low": ["https://i.imgur.com/7yA0d1Y.png"],
    "mid": ["https://i.imgur.com/8mKXc3T.png"],
    "high": ["https://i.imgur.com/0qK7w9H.png"],
    "ultra": ["https://i.imgur.com/9Yy3GxD.png"]
}

# ---------------- STORAGE ----------------
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(d):
    with open(DATA_FILE, "w") as f:
        json.dump(d, f, indent=2)

# ---------------- HELPERS ----------------
def detect_contract_address(msg: str):
    if not msg:
        return None, None
    evm_pattern = r'\b0x[a-fA-F0-9]{40}\b'
    sol_pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    evm = re.findall(evm_pattern, msg)
    if evm:
        return evm[0].lower(), "EVM"
    sol = re.findall(sol_pattern, msg)
    if sol:
        return sol[0], "SOL"
    return None, None

def get_token_data(ca: str):
    """Query DexScreener for token price & fdv (mcap)"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        r = requests.get(url, timeout=10)
        j = r.json()
        if "pairs" in j and j["pairs"]:
            p = j["pairs"][0]
            price = float(p.get("priceUsd") or 0)
            mcap = float(p.get("fdv") or 0)
            symbol = p.get("baseToken", {}).get("symbol") or p.get("baseToken", {}).get("name") or ca[:8]
            chain = p.get("chainId", "unknown")
            return {"price": price, "mcap": mcap, "symbol": symbol, "chain": chain}
    except Exception as e:
        print("get_token_data error:", e)
    return None

def choose_local_or_fallback(key):
    """Return a BytesIO of meme image either from local file or fallback URL."""
    local_name = LOCAL_MEMES.get(key)
    # prefer local file if exists
    if local_name and os.path.exists(local_name):
        try:
            return Image.open(local_name).convert("RGBA")
        except Exception as e:
            print("Local image open error:", e, local_name)

    # otherwise try fallback URLs
    urls = FALLBACK_MEMES.get(key, [])
    for url in urls:
        try:
            resp = requests.get(url, timeout=10)
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            return img
        except Exception as e:
            print("Fallback fetch error:", e, url)
    return None

def fit_text(draw, text, font_path=None, max_width=420, start_size=64):
    size = start_size
    while size > 10:
        try:
            if font_path:
                f = ImageFont.truetype(font_path, size)
            else:
                f = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=f)
            w = bbox[2] - bbox[0]
            if w <= max_width:
                return f
        except Exception:
            return ImageFont.load_default()
        size -= 2
    return ImageFont.load_default()

def make_card_image(symbol, ca, start_mcap, start_price, now_mcap, now_price, multiplier, chain):
    """Compose a PnL card and return BytesIO PNG."""
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), color=(12, 14, 16))
    draw = ImageDraw.Draw(img)

    # pick meme key by multiplier thresholds
    if multiplier < 1:
        meme_key = "low"
    elif 1 <= multiplier < 2:
        meme_key = "low"
    elif 2 <= multiplier < 10:
        meme_key = "mid"
    elif 10 <= multiplier < 20:
        meme_key = "high"
    else:
        meme_key = "ultra"

    meme_img = choose_local_or_fallback(meme_key)
    if meme_img:
        # Resize meme to fit right ~44% of card
        meme_w = int(CARD_WIDTH * 0.44)
        meme_h = int(CARD_HEIGHT * 0.9)
        meme_img.thumbnail((meme_w, meme_h), Image.LANCZOS)
        meme_x = CARD_WIDTH - meme_img.width - 30
        meme_y = int((CARD_HEIGHT - meme_img.height) / 2)
        img.paste(meme_img, (meme_x, meme_y), mask=meme_img)

    # Fonts
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "arial.ttf"
    ]
    font_bold = None
    for p in font_candidates:
        try:
            font_bold = ImageFont.truetype(p, 48)
            font_path = p
            break
        except Exception:
            font_bold = None
            font_path = None
    if not font_bold:
        font_bold = ImageFont.load_default()
        font_path = None

    # Left block positions
    left_x = 36
    left_w = int(CARD_WIDTH * 0.55) - 60

    # Symbol (title)
    title_font = fit_text(draw, f"${symbol}", font_path=font_path, max_width=left_w, start_size=72)
    draw.text((left_x, 30), f"${symbol}", font=title_font, fill=(255,255,255))

    # Multiplier big with neon green glow effect: draw shadow then bright
    mult_text = f"{multiplier:.2f}×"
    mult_font = fit_text(draw, mult_text, font_path=font_path, max_width=left_w, start_size=96)
    # shadow/glow
    shadow_color = (2, 70, 30)
    for dx, dy in [(-3,-3),(3,3),(-4,0),(0,4)]:
        draw.text((left_x + dx, 110 + dy), mult_text, font=mult_font, fill=shadow_color)
    # main neon
    neon = (0, 255, 140) if multiplier >= 1 else (255, 100, 100)
    draw.text((left_x, 110), mult_text, font=mult_font, fill=neon)

    # Stats lines
    small_font = ImageFont.truetype(font_path, 22) if font_path else ImageFont.load_default()
    y = 230
    draw.text((left_x, y), f"Called Mcap: ${int(start_mcap):,}", font=small_font, fill=(200,200,200))
    y += 32
    draw.text((left_x, y), f"Now Mcap:    ${int(now_mcap):,}", font=small_font, fill=(255,255,255))
    y += 32
    draw.text((left_x, y), f"Start Price: ${start_price:,.8f}", font=small_font, fill=(170,170,170))
    y += 28
    draw.text((left_x, y), f"Now Price:   ${now_price:,.8f}", font=small_font, fill=(255,255,255))

    # bottom left: chain + time
    bottom_font = ImageFont.truetype(font_path, 14) if font_path else ImageFont.load_default()
    bottom_text = f"{chain.upper()}  |  {datetime.now().strftime('%b %d %H:%M')}"
    draw.text((left_x, CARD_HEIGHT - 38), bottom_text, font=bottom_font, fill=(140,140,140))

    # watermark bottom-right
    wm_font = ImageFont.truetype(font_path, 18) if font_path else ImageFont.load_default()
    bbox = draw.textbbox((0,0), WATERMARK_TEXT, font=wm_font)
    w_w = bbox[2] - bbox[0]
    w_h = bbox[3] - bbox[1]
    draw.text((CARD_WIDTH - w_w - 16, CARD_HEIGHT - w_h - 12), WATERMARK_TEXT, font=wm_font, fill=(120,120,120))

    # output bytes
    out = BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out

# ---------------- BOT HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 The Alpha House PnL Bot is active.\nDrop a CA and reply /pnl to its message.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    ca, chain = detect_contract_address(text)
    if not ca:
        return
    data = get_token_data(ca)
    if not data:
        await update.message.reply_text("⚠️ Couldn't fetch token data (may not be indexed yet).")
        return
    stored = load_data()
    if ca not in stored:
        stored[ca] = {
            "price": data["price"],
            "mcap": data["mcap"],
            "symbol": data["symbol"],
            "chain": data["chain"],
            "time": int(time.time()),
            "poster": update.message.from_user.username if update.message.from_user else ""
        }
        save_data(stored)
        await update.message.reply_text(
            f"🪙 Tracking {data['symbol']} ({chain})\nStart Mcap: ${int(data['mcap']):,}\nPrice: ${data['price']:,.8f}"
        )
    else:
        await update.message.reply_text("Already tracking that CA.")

async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = (msg.text or "").strip()
    ca = None

    parts = text.split()
    if len(parts) > 1:
        ca = parts[1].strip()
    elif msg.reply_to_message:
        replied_text = msg.reply_to_message.text or ""
        ca_match, _ = detect_contract_address(replied_text)
        if ca_match:
            ca = ca_match

    if not ca:
        await msg.reply_text("⚠️ Reply to a CA message or include a CA after /pnl.")
        return

    stored = load_data()
    if ca not in stored:
        await msg.reply_text("⚠️ I don’t have this CA yet. Post it so I can track it.")
        return

    start_info = stored[ca]
    start_price = start_info.get("price", 0)
    start_mcap = start_info.get("mcap", 0)
    data = get_token_data(ca)
    if not data:
        await msg.reply_text("⚠️ Couldn't fetch current token data.")
        return

    now_price = data["price"]
    now_mcap = data["mcap"]
    # prefer mcaps if available (more stable for memecoins)
    multiplier = 0
    if start_mcap and now_mcap:
        multiplier = now_mcap / start_mcap if start_mcap else 0
    elif start_price and now_price:
        multiplier = now_price / start_price if start_price else 0

    try:
        card = make_card_image(
            data.get("symbol", "TOKEN"), ca,
            start_mcap or 0, start_price or 0,
            now_mcap or 0, now_price or 0,
            multiplier or 0, data.get("chain", "")
        )
        caption = f"{data.get('symbol','TOKEN')} • {multiplier:.2f}× • {data.get('chain','').upper()}"
        await msg.reply_photo(photo=card, caption=caption)
    except Exception as e:
        print("card error:", e)
        await msg.reply_text(f"Error creating card: {e}")

async def list_tracked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data:
        await update.message.reply_text("📭 No tokens being tracked yet.")
        return
    lines = ["📋 Tracked tokens:"]
    for ca, info in data.items():
        lines.append(f"- {info.get('symbol','?')} ({info.get('chain','?')}): {ca}")
    await update.message.reply_text("\n".join(lines))

async def untrack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("Usage: /untrack <contract_address>")
        return
    ca = parts[1].strip().lower()
    data = load_data()
    if ca in data:
        del data[ca]
        save_data(data)
        await update.message.reply_text(f"🗑️ Untracked {ca}")
    else:
        await update.message.reply_text("⚠️ That CA isn’t being tracked.")

# ---------------- RUN ----------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("list", list_tracked))
    app.add_handler(CommandHandler("untrack", untrack))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()