import logging
import json
import os
from dotenv import load_dotenv
from web3 import Web3
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from flask import Flask
from threading import Thread

# ========================
# CARGA VARIABLES DE .env
# ========================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

# ========================
# CONFIGURACIÓN FIJA
# ========================
SENDER_ADDRESS = "0x4756A2f0E8094467fE9507d8615243D7Cd876bFe"
CONTRACT_ADDRESS = "0x899F6eB2cF9ffa77fb0aF0F5dC4e13a6302F5c2C"
BSC_RPC = "https://bsc-dataseed1.binance.org"
MAX_REWARDS = 100
TOKEN_DECIMALS = 18
MIN_TOKENS_TO_CLAIM = 700
DATA_FILE = "claim_data.json"

web3 = Web3(Web3.HTTPProvider(BSC_RPC))

# ABI BEP-20
BEP20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]

contract = web3.eth.contract(
    address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=BEP20_ABI)

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        claims = json.load(f)
else:
    claims = {"usuarios": {}, "total": 0}

def guardar_claims():
    with open(DATA_FILE, "w") as f:
        json.dump(claims, f, indent=4)

def get_token_balance(address: str) -> int:
    try:
        balance = contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
        return balance / (10**TOKEN_DECIMALS)
    except:
        return 0

def enviar_tokens(destinatario: str, cantidad: int):
    nonce = web3.eth.get_transaction_count(SENDER_ADDRESS)
    tx = contract.functions.transfer(
        Web3.to_checksum_address(destinatario),
        int(cantidad * (10**TOKEN_DECIMALS))).build_transaction({
            "chainId": 56,
            "gas": 100000,
            "gasPrice": web3.to_wei("5", "gwei"),
            "nonce": nonce
        })
    firmado = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = web3.eth.send_raw_transaction(firmado.rawTransaction)
    return tx_hash.hex()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO)

async def bienvenida(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.effective_user.first_name
    uid = str(update.effective_user.id)
    if claims["total"] >= MAX_REWARDS:
        mensaje = f"👋 ¡Hola {nombre}! Bienvenido a Vyrax. La promoción ha terminado, pero sigue apoyando el proyecto 🐉"
    else:
        mensaje = f'''
👋 ¡Hola {nombre}! Bienvenido a *Vyrax Comunidad* 🐉

🎁 Gana hasta *200 Vyrax*:

✅ Ten al menos 700 Vyrax en tu wallet  
✅ Escribe aquí tu wallet BEP-20  
✅ Escribe también el @ de la persona que invitaste (obligatorio para 200)  

📌 Si no invitas a nadie pero tienes 700 Vyrax → recibirás 50 Vyrax  
📌 Solo se entregan tokens a los primeros 100 participantes  

🚫 No spam | 💬 Solo temas de Vyrax | 🐉 ¡Gracias por apoyar!
'''
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def procesar_reclamo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    username = update.effective_user.username or "sin_username"
    mensaje = update.message.text.strip()
    partes = mensaje.split()

    if claims["total"] >= MAX_REWARDS:
        await update.message.reply_text("🚫 Ya se han entregado todos los premios disponibles.")
        return

    if uid in claims["usuarios"]:
        await update.message.reply_text("⚠️ Ya has reclamado tu recompensa.")
        return

    if len(partes) < 1:
        await update.message.reply_text("⚠️ Por favor escribe tu wallet (y el @ de tu invitado si aplica).")
        return

    wallet = partes[0]
    invitado = partes[1] if len(partes) > 1 else None

    if not wallet.startswith("0x") or len(wallet) != 42:
        await update.message.reply_text("❌ Dirección de wallet no válida.")
        return

    balance = get_token_balance(wallet)
    if balance < MIN_TOKENS_TO_CLAIM:
        await update.message.reply_text(
            f"❌ Tu wallet solo tiene {balance:.2f} Vyrax. Se requieren al menos 700.")
        return

    cantidad = 200 if invitado else 50
    tx_hash = enviar_tokens(wallet, cantidad)

    claims["usuarios"][uid] = {
        "username": username,
        "wallet": wallet,
        "recompensa": cantidad,
        "tx": tx_hash,
        "invito": invitado or "no"
    }
    claims["total"] += 1
    guardar_claims()

    await update.message.reply_text(
        f"✅ {cantidad} Vyrax enviados a {wallet}.\n🧾 TX: https://bscscan.com/tx/{tx_hash}"
    )

    resumen = f"{'🚀' if cantidad == 200 else '🎉'} @{username} acaba de reclamar {cantidad} Vyrax"
    resumen += f" {'(compra + invitación)' if cantidad == 200 else '(solo compra)'}\n📦 Wallet: {wallet}"
    if invitado:
        resumen += f"\n👥 Invitó a: {invitado}"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=resumen)

async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quedan = MAX_REWARDS - claims["total"]
    await update.message.reply_text(f"🎁 Quedan {quedan} recompensas disponibles.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await bienvenida(update, context)

def main():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("estado", estado))
    app_bot.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, bienvenida))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_reclamo))
    print("✅ Bot Vyrax corriendo...")
    app_bot.run_polling()

# ========== FLASK PARA RENDER ==========
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Vyrax bot activo y funcionando 24/7."

def mantener_vivo():
    app.run(host='0.0.0.0', port=8080)

# ========== EJECUCIÓN ==========
if __name__ == "__main__":
    Thread(target=mantener_vivo).start()
    main()
