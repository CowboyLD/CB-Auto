from selenium import webdriver from selenium.webdriver.common.by import By from selenium.webdriver.chrome.service import Service from selenium.webdriver.chrome.options import Options from selenium.webdriver.support.ui import WebDriverWait from selenium.webdriver.support import expected_conditions as EC from telegram import Update from telegram.ext import Application, ContextTypes, CommandHandler import os import traceback import logging import time from datetime import datetime import pytz import math import random import asyncio from aiohttp import web

Configuration

USERNAME = os.getenv('USERNAME') PASSWORD = os.getenv('PASSWORD') TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') AUTHORIZED_USERS = [uid.strip() for uid in os.getenv('AUTHORIZED_USERS', '').split(',') if uid.strip()] TIMEZONE = pytz.timezone('Asia/Bangkok') BASE_LATITUDE = float(os.getenv('BASE_LATITUDE', '11.545380')) BASE_LONGITUDE = float(os.getenv('BASE_LONGITUDE', '104.911449')) MAX_DEVIATION_METERS = 150

user_scan_tasks = {} user_drivers = {}

logging.basicConfig( format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO ) logger = logging.getLogger(name)

def calculate_distance(lat1, lon1, lat2, lon2): R = 6373.0 lat1 = math.radians(lat1) lon1 = math.radians(lon1) lat2 = math.radians(lat2) lon2 = math.radians(lon2) dlon = lon2 - lon1 dlat = lat2 - lat1 a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2 c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)) return round(R * c * 1000, 1)

def generate_random_coordinates(): radius_deg = MAX_DEVIATION_METERS / 111320 angle = math.radians(random.uniform(0, 360)) distance = random.uniform(0, radius_deg) new_lat = BASE_LATITUDE + (distance * math.cos(angle)) new_lon = BASE_LONGITUDE + (distance * math.sin(angle)) return new_lat, new_lon

def create_driver(): options = Options() options.binary_location = '/usr/bin/chromium' options.add_argument('--headless=new') options.add_argument('--no-sandbox') options.add_argument('--disable-dev-shm-usage') options.add_argument('--disable-gpu') options.add_argument('--window-size=1920,1080') options.add_argument('--ignore-certificate-errors') options.add_experimental_option("prefs", {"profile.default_content_setting_values.geolocation": 1})

service = Service(executable_path='/usr/bin/chromedriver')
driver = webdriver.Chrome(service=service, options=options)
lat, lon = generate_random_coordinates()
driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {"latitude": lat, "longitude": lon, "accuracy": 100})
return driver, (lat, lon)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = str(update.effective_user.id) chat_id = update.effective_chat.id task = user_scan_tasks.get(user_id)

if task and not task.done():
    await context.bot.send_message(chat_id, "⛔ Cancelling scan-in process...")
    task.cancel()

    driver = user_drivers.get(user_id)
    if driver:
        timestamp = datetime.now(TIMEZONE).strftime("%Y%m%d-%H%M%S")
        screenshot_path = f"cancelled_{timestamp}.png"
        driver.save_screenshot(screenshot_path)
        with open(screenshot_path, "rb") as photo:
            await context.bot.send_photo(chat_id=chat_id, photo=photo,
                caption=f"🚫 Operation cancelled at {datetime.now(TIMEZONE).strftime('%H:%M:%S')} (ICT)")
        driver.quit()
        user_drivers.pop(user_id, None)
    else:
        await context.bot.send_message(chat_id, "⚠️ No active browser session found.")
else:
    await context.bot.send_message(chat_id, "ℹ️ No active scan-in process to cancel.")

async def perform_scan_in(bot, chat_id, user_id): driver = None try: driver, (lat, lon) = create_driver() user_drivers[user_id] = driver start_time = datetime.now(TIMEZONE).strftime("%H:%M:%S") await bot.send_message(chat_id, f"🕒 Automation started at {start_time} (ICT)")

wait = WebDriverWait(driver, 15)
    driver.get("https://tinyurl.com/ajrjyvx9")
    wait.until(EC.visibility_of_element_located((By.ID, "txtUserName"))).send_keys(USERNAME)
    driver.find_element(By.ID, "txtPassword").send_keys(PASSWORD)
    driver.find_element(By.ID, "btnSignIn").click()
    wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "small-box")))

    attendance_card = wait.until(EC.presence_of_element_located((
        By.XPATH, "//div[contains(@class,'small-box bg-aqua')]//h3[text()='Attendance']/ancestor::div")))
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", attendance_card)
    attendance_card.find_element(By.XPATH, ".//a[contains(@href, 'ATT/frmclock.aspx')]").click()

    clock_in_link = wait.until(EC.element_to_be_clickable((
        By.XPATH, "//a[contains(@href, 'frmclockin.aspx') and contains(., 'Clock In')]")))
    clock_in_link.click()

    scan_in_btn = wait.until(EC.presence_of_element_located((By.ID, "ctl00_maincontent_btnScanIn")))
    if scan_in_btn.get_attribute("disabled"):
        driver.execute_script("arguments[0].disabled = false;", scan_in_btn)
    scan_in_btn.click()
    WebDriverWait(driver, 15).until(EC.url_contains("frmclock.aspx"))

    table = driver.find_element(By.ID, "ctl00_maincontent_GVList")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table)
    driver.execute_script("arguments[0].style.border='3px solid #00ff00';", table)
    time.sleep(0.5)

    timestamp = datetime.now(TIMEZONE).strftime("%Y%m%d-%H%M%S")
    screenshot_file = f"success_{timestamp}.png"
    table.screenshot(screenshot_file)

    distance = calculate_distance(BASE_LATITUDE, BASE_LONGITUDE, lat, lon)
    with open(screenshot_file, 'rb') as photo:
        await bot.send_photo(chat_id=chat_id, photo=photo, caption=(
            f"✅ Scan confirmed at {datetime.now(TIMEZONE).strftime('%H:%M:%S')} (ICT)\n"
            f"📍 *Location:* `{lat:.6f}, {lon:.6f}`\n"
            f"📏 *Distance:* {distance}m\n"
            f"🗺 [Map](https://maps.google.com/maps?q={lat},{lon})"), parse_mode="Markdown")
    return True

except Exception as e:
    timestamp = datetime.now(TIMEZONE).strftime("%Y%m%d-%H%M%S")
    error_file = f"error_{timestamp}.png"
    driver.save_screenshot(error_file)
    with open(error_file, 'rb') as photo:
        await bot.send_photo(chat_id=chat_id, photo=photo, caption="❌ Error occurred")
    return False

finally:
    if driver:
        driver.quit()
        user_drivers.pop(user_id, None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("🚀 Attendance Bot Ready! Use /scanin to begin.")

async def scanin(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = str(update.effective_user.id) chat_id = update.effective_chat.id

if user_id not in AUTHORIZED_USERS:
    await update.message.reply_text("❌ Unauthorized")
    return

if user_id in user_scan_tasks and not user_scan_tasks[user_id].done():
    await update.message.reply_text("⚠️ Scan in progress. Use /cancel")
    return

async def scan_task():
    try:
        await context.bot.send_message(chat_id, "⏳ Starting scan...")
        await perform_scan_in(context.bot, chat_id, user_id)
    except asyncio.CancelledError:
        await context.bot.send_message(chat_id, "⛔ Task cancelled by user.")

task = asyncio.create_task(scan_task())
user_scan_tasks[user_id] = task

application = Application.builder().token(TELEGRAM_TOKEN).build() application.add_handler(CommandHandler("start", start)) application.add_handler(CommandHandler("scanin", scanin)) application.add_handler(CommandHandler("cancel", cancel))

async def handle_health_check(request): return web.Response(text="OK")

async def handle_telegram_webhook(request): data = await request.json() update = Update.de_json(data, application.bot) await application.process_update(update) return web.Response(text="OK")

async def handle_root(request): return web.Response(text="Bot is running")

async def main(): await application.initialize() app = web.Application() app.router.add_get("/", handle_root) app.router.add_get("/healthz", handle_health_check) app.router.add_post("/webhook", handle_telegram_webhook) runner = web.AppRunner(app) await runner.setup() port = int(os.getenv("PORT", 8000)) site = web.TCPSite(runner, "0.0.0.0", port) await site.start()

webhook_url = os.getenv("WEBHOOK_URL")
if not webhook_url:
    raise ValueError("WEBHOOK_URL not set")

await application.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
await asyncio.Event().wait()

if name == "main": asyncio.run(main())

