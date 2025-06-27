import logging
import json
import os
from dotenv import load_dotenv
from web3 import Web3
from telegram import Update, ChatMember
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
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
GRUPO_ID = -1002117642734  # reemplaza esto con el ID real de tu grupo

web3 = Web3(Web3.HTTPProvider(BSC_RPC))

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

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

async def bienvenida(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.effective_user.first_name
    if claims["total"] >= MAX_REWARDS:
        mensaje = f"👋 ¡Hola {nombre}! Bienvenido a Vyrax. La promoción terminó, pero lee las reglas y apoya el proyecto 🐉"
    else:
        mensaje = f'''
👋 ¡Hola {nombre}! Bienvenido a *Vyrax Comunidad* 🐉

🎁 Gana hasta *200 Vyrax*:

✅ Ten al menos 700 Vyrax en tu wallet  
✅ Escribe aquí tu wallet BEP-20  
✅ Escribe también el @ de la persona que te invitó  

📌 Si no invitas a nadie pero tienes 700 Vyrax → recibes 50 Vyrax  
📌 Solo se entregan tokens a los primeros 100 participantes  

🚫 No spam | 💬 Solo temas de Vyrax
'''
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def procesar_reclamo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    username = update.effective_user.username or "sin_username"
    mensaje = update.message.text.strip()
    partes = mensaje.split()

    if claims["total"] >= MAX_REWARDS:
        return

    if uid in claims["usuarios"]:
        return await update.message.reply_text("⚠️ Ya reclamaste tu recompensa.")

    if len(partes) < 1 or not partes[0].startswith("0x") or len(partes[0]) != 42:
        return  # Ignorar mensajes que no contienen una wallet válida

    wallet = partes[0]
    invitado = partes[1] if len(partes) > 1 else None

    if invitado == f"@{username}":
        return await update.message.reply_text("❌ No puedes invitarte a ti mismo.")

    if invitado:
        for datos in claims["usuarios"].values():
            if datos["invito"] == invitado:
                return await update.message.reply_text("❌ Ese usuario ya fue usado como invitado.")

    balance = get_token_balance(wallet)
    if balance < MIN_TOKENS_TO_CLAIM:
        return await update.message.reply_text(
            f"❌ Tu wallet solo tiene {balance:.2f} Vyrax. Necesitas al menos 700.")

    try:
        miembro_reclamante = await context.bot.get_chat_member(GRUPO_ID, update.effective_user.id)
        if miembro_reclamante.status not in ("member", "administrator", "creator"):
            return await update.message.reply_text("❌ Debes estar en el grupo para reclamar.")

        if invitado:
            invitado_data = await context.bot.get_chat_member(GRUPO_ID, invitado.replace("@", ""))
            if invitado_data.status not in ("member", "administrator", "creator"):
                return await update.message.reply_text("❌ Tu invitado no está en el grupo.")
    except:
        return await update.message.reply_text("❌ No se pudo verificar la membresía del grupo.")

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
        f"✅ {cantidad} Vyrax enviados a {wallet}.\n🧾 TX: https://bscscan.com/tx/{tx_hash}")

    resumen = f"{'🚀' if cantidad == 200 else '🎉'} @{username} reclamó {cantidad} Vyrax"
    resumen += f" {'(compra + invitación)' if cantidad == 200 else '(solo compra)'}\n📦 Wallet: {wallet}"
    if invitado:
        resumen += f"\n👥 Invitó a: {invitado}"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=resumen)

async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quedan = MAX_REWARDS - claims["total"]
    await update.message.reply_text(f"🎁 Quedan {quedan} recompensas disponibles.")

async def borrar_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text:
        texto = update.message.text.lower()
        if "http" in texto or "t.me/" in texto or "@" in texto and not texto.startswith("0x"):
            await update.message.delete()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await bienvenida(update, context)

def main():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("estado", estado))
    app_bot.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, bienvenida))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_reclamo))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, borrar_spam))
    print("✅ Bot Vyrax corriendo...")
    app_bot.run_polling()

# ========== FLASK PARA RENDER ==========

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Vyrax bot activo y funcionando 24/7."

def mantener_vivo():
    app.run(host='0.0.0.0', port=8080)

if __name__ == "__main__":
    Thread(target=mantener_vivo).start()
    main()
