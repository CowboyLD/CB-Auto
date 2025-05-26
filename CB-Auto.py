from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from telegram import Update
from telegram.ext import Application, ContextTypes, CommandHandler
import os
import traceback
import logging
import time
from datetime import datetime
import pytz
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import math
import random
from telegram import BotCommand
from math import radians, sin, cos, sqrt, atan2
from asyncio import Task
import asyncio
from aiohttp import web

def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate distance in meters between two coordinates using Haversine formula
    """
    R = 6373.0  # Earth radius in kilometers

    lat1 = radians(lat1)
    lon1 = radians(lon1)
    lat2 = radians(lat2)
    lon2 = radians(lon2)

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))

    return round(R * c * 1000, 1)  # Convert to meters and round
  
# Configuration
USERNAME = os.getenv('USERNAME')
PASSWORD = os.getenv('PASSWORD')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
AUTHORIZED_USERS = [uid.strip() for uid in os.getenv('AUTHORIZED_USERS', '').split(',') if uid.strip()]
TIMEZONE = pytz.timezone('Asia/Bangkok')
BASE_LATITUDE = float(os.getenv('BASE_LATITUDE', '11.545380'))
BASE_LONGITUDE = float(os.getenv('BASE_LONGITUDE', '104.911449'))
MAX_DEVIATION_METERS = 150

user_scan_tasks = {}
user_drivers = {}

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def generate_random_coordinates():
    """Generate random coordinates within MAX_DEVIATION_METERS of base location"""
    # Convert meters to degrees (approximate)
    radius_deg = MAX_DEVIATION_METERS / 111320  # 1 degree ≈ 111,320 meters
    
    # Random direction (0-360 degrees)
    angle = math.radians(random.uniform(0, 360))
    
    # Random distance (0 to max deviation)
    distance = random.uniform(0, radius_deg)
    
    # Calculate new coordinates
    new_lat = BASE_LATITUDE + (distance * math.cos(angle))
    new_lon = BASE_LONGITUDE + (distance * math.sin(angle))
    
    return new_lat, new_lon

def create_driver():
    options = Options()
    options.binary_location = '/usr/bin/chromium'
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--allow-geolocation')
    options.add_experimental_option("prefs", {
        "profile.default_content_setting_values.geolocation": 1,
    })

    service = Service(executable_path='/usr/bin/chromedriver')
    driver = webdriver.Chrome(service=service, options=options)
    
    # Generate random coordinates
    lat, lon = generate_random_coordinates()
    logger.info(f"Using coordinates: {lat:.6f}, {lon:.6f}")
    
    # Set randomized geolocation
    driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
        "latitude": lat,
        "longitude": lon,
        "accuracy": 100
    })
    
    return driver, (lat, lon)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id

    task = user_scan_tasks.get(user_id)

    if task and not task.done():
        task.cancel()
        await context.bot.send_message(chat_id, "⛔ Cancelling scan-in process...")
    else:
        await context.bot.send_message(chat_id, "ℹ️ No active scan-in process to cancel.")

async def perform_scan_in(bot, chat_id, user_id, cancel_flag):  # Added user_id parameter
    driver, (lat, lon) = create_driver()
    user_drivers[user_id] = driver  # Store under user_id
    screenshot_file = None
    try:
        start_time = datetime.now(TIMEZONE).strftime("%H:%M:%S")
        await bot.send_message(chat_id, f"🕒 Automation started at {start_time} (ICT)")
        
        # Step 1: Login
        await bot.send_message(chat_id, "🚀 Starting browser automation...")
        wait = WebDriverWait(driver, 15)

        await bot.send_message(chat_id, "🌐 Navigating to login page")
        driver.get("https://tinyurl.com/ajrjyvx9")
        
        username_field = wait.until(EC.visibility_of_element_located((By.ID, "txtUserName")))
        username_field.send_keys(USERNAME)
        await bot.send_message(chat_id, "👤 Username entered")

        password_field = driver.find_element(By.ID, "txtPassword")
        password_field.send_keys(PASSWORD)
        await bot.send_message(chat_id, "🔑 Password entered")

        driver.find_element(By.ID, "btnSignIn").click()
        await bot.send_message(chat_id, "🔄 Processing login...")

        wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "small-box")))
        await bot.send_message(chat_id, "✅ Login successful")

        # Step 2: Navigate to Attendance
        await bot.send_message(chat_id, "🔍 Finding attendance card...")
        attendance_xpath = "//div[contains(@class,'small-box bg-aqua')]//h3[text()='Attendance']/ancestor::div[contains(@class,'small-box')]"
        attendance_card = wait.until(EC.presence_of_element_located((By.XPATH, attendance_xpath)))
        
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", attendance_card)
        time.sleep(1)
        more_info_link = attendance_card.find_element(By.XPATH, ".//a[contains(@href, 'ATT/frmclock.aspx')]")
        more_info_link.click()
        await bot.send_message(chat_id, "✅ Clicked 'More info'")

        # Step 3: Clock In
        await bot.send_message(chat_id, "⏳ Waiting for Clock In link...")
        clock_in_xpath = "//a[contains(@href, 'frmclockin.aspx') and contains(., 'Clock In')]"
        clock_in_link = wait.until(EC.element_to_be_clickable((By.XPATH, clock_in_xpath)))
        
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", clock_in_link)
        time.sleep(0.5)
        clock_in_link.click()
        await bot.send_message(chat_id, "✅ Clicked Clock In link")

        # Step 4: Enable Scan In
        await bot.send_message(chat_id, "🔍 Locating Scan In button...")
        scan_in_btn = wait.until(EC.presence_of_element_located((By.ID, "ctl00_maincontent_btnScanIn")))
        
        if scan_in_btn.get_attribute("disabled"):
            driver.execute_script("arguments[0].disabled = false;", scan_in_btn)
            time.sleep(0.5)

        scan_in_btn.click()
        await bot.send_message(chat_id, "🔄 Processing scan-in...")
        
        await bot.send_message(chat_id, "⏳ Verifying scan completion...")
        WebDriverWait(driver, 15).until(
            EC.url_contains("frmclock.aspx")
        )

        # Step 5: Capture attendance table screenshot
        await bot.send_message(chat_id, "📸 Capturing attendance record...")
        
        # Wait for table to load with fresh data
        table_xpath = "//table[@id='ctl00_maincontent_GVList']//tr[contains(., 'Head Office')]"
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, table_xpath))
        )
        # Scroll to table and highlight
        table = driver.find_element(By.ID, "ctl00_maincontent_GVList")
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", table)
        driver.execute_script("arguments[0].style.border='3px solid #00ff00';", table)
        time.sleep(0.5)  # Allow border animation

        # Capture screenshot
        timestamp = datetime.now(TIMEZONE).strftime("%Y%m%d-%H%M%S")
        screenshot_file = f"success_{timestamp}.png"
        table.screenshot(screenshot_file)  # Direct table capture

        # Send confirmation with screenshot
        base_lat = float(os.getenv('BASE_LATITUDE', '11.545380'))
        base_lon = float(os.getenv('BASE_LONGITUDE', '104.911449'))
        distance = calculate_distance(base_lat, base_lon, lat, lon)
        with open(screenshot_file, 'rb') as photo:
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=(
                  f"✅ Successful scan confirmed at {datetime.now(TIMEZONE).strftime('%H:%M:%S')} (ICT)\n"
                  f"📍 *Location:* `{lat:.6f}, {lon:.6f}`\n"
                  f"📏 *Distance from Office:* {distance}m\n"
                  f"🗺 [View on Map](https://maps.google.com/maps?q={lat},{lon})"
                ),
                parse_mode="Markdown"
            )

        return True

    except Exception as e:
        error_time = datetime.now(TIMEZONE).strftime("%H:%M:%S")
        error_text = str(e).strip() or "Unknown error"
        await bot.send_message(chat_id, f"❌ Failed at {error_time} (ICT): {error_text}")
        logger.error(traceback.format_exc())
        
        timestamp = datetime.now(TIMEZONE).strftime("%Y%m%d-%H%M%S")
        driver.save_screenshot(f"error_{timestamp}.png")
        with open(f"page_source_{timestamp}.html", "w") as f:
            f.write(driver.page_source)
            
        with open(f"error_{timestamp}.png", 'rb') as photo:
            await bot.send_photo(chat_id=chat_id, photo=photo, caption="Error screenshot")
        return False
    finally:
        if not cancel_flag.get("cancelled"):
            user_drivers.pop(user_id, None)  # Remove using user_id
            driver.quit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    await update.message.reply_text(
        "🚀 Attendance Bot Ready!\n"
        "Use /scanin to trigger the automation process"
    )

async def scanin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id

    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized to use this bot")
        return

    if user_id in user_scan_tasks and not user_scan_tasks[user_id].done():
        await update.message.reply_text("⚠️ A scan is already in progress. Use /cancel to stop it.")
        return

    # 🆕 New async task wrapper
    async def scan_task():
        try:
            await context.bot.send_message(chat_id, "⏳ Starting scan process...")
            cancel_flag = {"cancelled": False}
            success = await perform_scan_in(context.bot, chat_id, user_id, cancel_flag)  # Pass user_id
    
            if success:
                await context.bot.send_message(chat_id, "✅ Scan-in process completed successfully!")
            else:
                await context.bot.send_message(chat_id, "❌ Scan-in failed.")
        
        except asyncio.CancelledError:
            cancel_flag["cancelled"] = True
            driver = user_drivers.get(user_id)  # Retrieve using user_id
            if driver:
                try:
                    # ... [screenshot capturing code] ...
                finally:
                    driver.quit()
                    user_drivers.pop(user_id, None)
            await context.bot.send_message(chat_id, "🚫 Scan-in was cancelled.")

    # 🚀 Start the background task
    task = asyncio.create_task(scan_task())
    user_scan_tasks[user_id] = task

application = Application.builder().token(TELEGRAM_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("scanin", scanin))
application.add_handler(CommandHandler("cancel", cancel))

# Health check route
async def handle_health_check(request):
    return web.Response(text="OK")

# Telegram webhook route
async def handle_telegram_webhook(request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return web.Response(text="OK")
    
async def handle_root(request):
    return web.Response(text="Bot is running")
    
async def main():
    await application.initialize()
    
    # Create web application
    app = web.Application()
    app.router.add_get("/", handle_root)  # Add this line
    app.router.add_get("/healthz", handle_health_check)
    app.router.add_post("/webhook", handle_telegram_webhook)  # Changed endpoint
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Get port from environment (Render provides this)
    port = int(os.getenv("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    # Set webhook with proper URL
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        raise ValueError("WEBHOOK_URL environment variable not set")
    
    # Verify webhook setup
    await application.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )
    
    # Verify webhook was set
    webhook_info = await application.bot.get_webhook_info()
    logger.info(f"Webhook Info: {webhook_info}")
    
    if webhook_info.url != webhook_url:
        logger.error(f"Webhook URL mismatch: {webhook_info.url} != {webhook_url}")
    else:
        logger.info("✅ Webhook successfully set")
    
    # Keep application running
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
