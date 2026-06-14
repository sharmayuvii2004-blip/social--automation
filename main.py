import os
import json
import gspread
import requests
import pytz
import time
import mimetypes
import gdown
from datetime import datetime
from google.oauth2.service_account import Credentials

# ============================================================
# CONFIGURATION
# ============================================================
TIMEZONE = pytz.timezone('Asia/Kolkata')
SHEET_NAME = 'Content_Master'
WINDOW_SEC = 86400  # 24 hours

# Facebook & Instagram
FB_USER_TOKEN = os.environ.get('FB_USER_TOKEN', '')
FB_PAGE_ID_BILLIONAIRE = os.environ.get('FB_PAGE_ID_BILLIONAIRE', '1133625303164256')
FB_PAGE_ID_AI_SALES = os.environ.get('FB_PAGE_ID_AI_SALES', '1123448560851308')

# YouTube
YT_CLIENT_ID = os.environ.get('YT_CLIENT_ID', '')
YT_CLIENT_SECRET = os.environ.get('YT_CLIENT_SECRET', '')
YT_REFRESH_BILLIONAIRE = os.environ.get('YT_TOKEN_BILLIONAIRE', '')
YT_REFRESH_AI_SALES = os.environ.get('YT_TOKEN_AI_SALES', '')

# ============================================================
# GOOGLE SHEET
# ============================================================
def get_sheet():
    scopes = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    try:
        creds_json = json.loads(os.environ['GOOGLE_CREDS'])
        creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open(SHEET_NAME).sheet1
    except Exception as e:
        print(f"❌ Google Sheet Error: {e}")
        return None

def get_pending(sheet):
    rows = sheet.get_all_records()
    now = datetime.now(TIMEZONE)
    pending = []
    print(f"🕐 Current Time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📋 Total Rows: {len(rows)}")
    for i, row in enumerate(rows):
        status = str(row.get('status', '')).strip().lower()
        if status != 'pending':
            continue
        try:
            sched_str = str(row.get('schedule_datetime', '')).strip()
            if not sched_str:
                continue
            sched = datetime.strptime(sched_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=TIMEZONE)
            diff = (now - sched).total_seconds()
            if 0 <= diff <= WINDOW_SEC:
                pending.append((i + 2, row))
                print(f"✅ Row {i+2} is pending: {row.get('title', '')}")
        except Exception as e:
            print(f"⚠️ Row {i+2} date error: {e}")
    return pending

def update_row(sheet, row_num, status, posted_at='', error_log=''):
    try:
        sheet.update_cell(row_num, 9, status)
        if posted_at:
            sheet.update_cell(row_num, 10, posted_at)
        if error_log:
            sheet.update_cell(row_num, 11, str(error_log)[:500])
    except Exception as e:
        print(f"⚠️ Sheet update error: {e}")

# ============================================================
# VIDEO DOWNLOAD
# ============================================================
def download_video(video_url, filename='temp_video.mp4'):
    try:
        if "drive.google.com" in video_url:
            if "/d/" in video_url:
                file_id = video_url.split('/d/')[1].split('/')[0]
            elif "id=" in video_url:
                file_id = video_url.split('id=')[1].split('&')[0]
            else:
                file_id = video_url
            print(f"📥 Downloading from Google Drive: {file_id}")
            gdown.download(
                f"https://drive.google.com/uc?id={file_id}",
                filename, quiet=False, fuzzy=True
            )
        else:
            print(f"📥 Downloading from URL: {video_url}")
            r = requests.get(video_url, timeout=300, stream=True)
            with open(filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        size = os.path.getsize(filename)
        print(f"✅ Downloaded: {size/(1024*1024):.2f} MB")
        return filename, None
    except Exception as e:
        return None, f"Download failed: {e}"

# ==========================================================
