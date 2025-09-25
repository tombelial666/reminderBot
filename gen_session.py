from telethon import TelegramClient
from telethon.sessions import StringSession
import getpass

api_id = 28371413
api_hash = "9b12da446ceec5c488ab8532491e2e59"
phone = input("Phone (+7...): ").strip()

def ask_code():
    return input("Code (from Telegram): ").strip()

def ask_password():
    return getpass.getpass("2FA password (if enabled, else leave empty): ")

with TelegramClient(StringSession(), api_id, api_hash) as client:
    # Явно передаём phone/code/password коллбеки, чтобы Telethon НЕ спрашивал bot token
    client.start(
        phone=lambda: phone,
        code_callback=ask_code,
        password=ask_password,
        bot_token=None,
    )
    print("AUTHORIZED=", client.loop.run_until_complete(client.is_user_authorized()))
    print("E2E_SESSION=", client.session.save())
