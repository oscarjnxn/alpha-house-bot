# === CONFIG ===
import os
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Fetch bot token from Render environment
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Please set BOT_TOKEN in Render environment variables.")

# === GLOBALS ===
tracked_tokens = {}  # {token_address: {"name": "TokenName", "symbol": "SYM", "chain": "bnb"}}
MEME_IMAGES = {
    "1x": "https://i.imgur.com/bpPEA0Y.png",   # Slightly happy meme
    "2x": "https://i.imgur.com/XbKhtTo.png",   # Excited meme
    "5x": "https://i.imgur.com/q2q0mEm.png",   # Crazy happy meme
    "10x": "https://i.imgur.com/rI5yA1v.png",  # Overjoyed meme
}
BNB_YELLOW = (243, 186, 47)


# === HELPER FUNCTIONS ===
def generate_pnl_card(name, symbol, x_gain, marketcap, price):
    """Generate an image with meme + PNL text for Telegram."""
    # Pick meme by x_gain range
    if x_gain < 2:
        meme_url = MEME_IMAGES["1x"]
    elif x_gain < 5:
        meme_url = MEME_IMAGES["2x"]
    elif x_gain < 10:
        meme_url = MEME_IMAGES["5x"]
    else:
        meme_url = MEME_IMAGES["10x"]

    # Download meme
    response = requests.get(meme_url)
    meme_img = Image.open(BytesIO(response.content)).convert("RGBA")

    # Prepare canvas
    width, height = meme_img.size
    card = Image.new("RGBA", (width + 400, height), (15, 15, 15, 255))
    card.paste(meme_img, (0, 0))

    # Draw text
    draw = ImageDraw.Draw(card)
    font_large = ImageFont.load_default()
    font_bold = ImageFont.load_default()

    text_x = width + 20
    y_offset = 50

    draw.text((text_x, y_offset), f"{name} (${symbol})", fill=BNB_YELLOW, font=font_bold)
    y_offset += 40
    draw.text((text_x, y_offset), f"Gain: {x_gain:.2f}x", fill=(255, 255, 255), font=font_large)
    y_offset += 30
    draw.text((text_x, y_offset), f"Market Cap: ${marketcap:,}", fill=(200, 200, 200), font=font_large)
    y_offset += 30
    draw.text((text_x, y_offset), f"Price: ${price}", fill=(200, 200, 200), font=font_large)
    y_offset += 40
    draw.text((text_x, y_offset), f"Powered by The Alpha House 🟡", fill=BNB_YELLOW, font=font_large)

    # Save image
    output = BytesIO()
    card.save(output, format="PNG")
    output.seek(0)
    return output


# === COMMAND HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to The Alpha House Bot!\n"
        "Use /pnl <token_address> to view gains.\n"
        "Use /list to view tracked tokens.\n"
        "Use /untrack <token_address> to remove a token."
    )


async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and send PNL card."""
    if len(context.args) == 0:
        await update.message.reply_text("Please provide a token CA, e.g. /pnl 0x123...")
        return

    ca = context.args[0]
    token_data = {
        "name": "SampleCoin",
        "symbol": "SMP",
        "marketcap": 2100000,
        "price": "0.00042",
        "x_gain": 5.6,
    }

    # Generate and send image
    image_file = generate_pnl_card(
        token_data["name"],
        token_data["symbol"],
        token_data["x_gain"],
        token_data["marketcap"],
        token_data["price"],
    )

    await update.message.reply_photo(photo=image_file, caption=f"📊 {token_data['name']} — {token_data['x_gain']}x")


async def list_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not tracked_tokens:
        await update.message.reply_text("No tokens tracked yet.")
        return

    msg = "📋 *Tracked Tokens:*\n"
    for ca, data in tracked_tokens.items():
        msg += f"- {data['name']} (${data['symbol']}) — {ca}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def untrack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Please provide a token address to untrack.")
        return
    ca = context.args[0]
    if ca in tracked_tokens:
        del tracked_tokens[ca]
        await update.message.reply_text(f"❌ Untracked {ca}")
    else:
        await update.message.reply_text("That token isn’t being tracked.")


# === MAIN ===
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("list", list_tokens))
    app.add_handler(CommandHandler("untrack", untrack))
    print("🤖 The Alpha House Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
