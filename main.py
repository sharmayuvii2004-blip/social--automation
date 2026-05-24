import os
import json
import gspread
import requests
import pytz
import time
import mimetypes
import re
import gdown
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- SETTINGS ---
TIMEZONE = pytz.timezone('Asia/Kolkata')
SHEET_NAME = 'Content_Master'
WINDOW_SEC = 86400  # 24 hours window

YT_TOKENS = {
    'billionaire': os.environ.get('YT_TOKEN_BILLIONAIRE', ''),
    'ai_sales': os.environ.get('YT_TOKEN_AI_SALES', ''),
}

def get_sheet():
    scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds_json = json.loads(os.environ['GOOGLE_CREDS'])
        creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open(SHEET_NAME).sheet1
    except Exception as e:
        print(f"❌ Critical Error: Google Sheet access failed: {e}")
        return None

def get_pending(sheet):
    rows = sheet.get_all_records()
    now = datetime.now(TIMEZONE)
    pending = []
    print(f"DEBUG: Current time = {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"DEBUG: Total rows found in sheet = {len(rows)}")

    for i, row in enumerate(rows):
        status = str(row.get('status', '')).strip().lower()
        if status != 'pending':
            continue
        try:
            sched_str = str(row.get('schedule_datetime', ''))
            if not sched_str: continue
            sched = datetime.strptime(sched_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=TIMEZONE)
            diff = (now - sched).total_seconds()
            if 0 <= diff <= WINDOW_SEC:
                pending.append((i + 2, row))
        except Exception as e:
            print(f"⚠️ Row {i+2} date format error: {e}")
    return pending

def get_yt_access_token(channel):
    refresh_token = YT_TOKENS.get(channel, '')
    client_id = os.environ.get('YT_CLIENT_ID', '')
    client_secret = os.environ.get('YT_CLIENT_SECRET', '')
    if not refresh_token or not client_id:
        return None
    r = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': client_id, 'client_secret': client_secret,
        'refresh_token': refresh_token, 'grant_type': 'refresh_token'
    })
    return r.json().get('access_token') if r.status_code == 200 else None

def post_youtube(row):
    clean_row = {str(k).lower().strip(): v for k, v in row.items()}
    p_val = str(clean_row.get('platform', '')).lower().strip()
    channel = str(clean_row.get('channel', '')).lower().strip()
    
    if 'youtube' not in p_val and 'yt' not in p_val:
        return True, 'skipped'

    access_token = get_yt_access_token(channel)
    if not access_token: return False, 'YT token missing'

    # 3. Video URL & Download
    video_url = row.get('video_url', '')
    if "drive.google.com" in video_url:
        if "/d/" in video_url: file_id = video_url.split('/d/')[1].split('/')[0]
        elif "id=" in video_url: file_id = video_url.split('id=')[1].split('&')[0]
        else: file_id = video_url
        video_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    print(f"DEBUG: Downloading video from Drive using gdown...")
    video_path = 'temp_video.mp4'
    try:
        gdown.download(video_url, video_path, quiet=False, fuzzy=True)
        with open(video_path, 'rb') as f:
            video_data = f.read()
        print(f"DEBUG: File downloaded successfully. Size: {len(video_data) / (1024*1024):.2f} MB")
    except Exception as e:
        return False, f"Download failed: {e}"

    # 4. YouTube Upload
    headers = {'Authorization': f'Bearer {access_token}'}
    meta = {
        'snippet': {
            'title': row.get('title', 'Short Video'),
            'description': f"{row.get('description', '')}\n\n{row.get('hashtags', '')}",
            'tags': row.get('hashtags', '').replace('#', '').split(),
            'categoryId': '22'
        },
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
    }

    init = requests.post(
        'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
        headers={**headers, 'Content-Type': 'application/json'}, json=meta, timeout=30
    )
    if init.status_code != 200: return False, f"YT Init Error {init.status_code}: {init.text[:100]}"

    upload_url = init.headers.get('Location', '')
    mime_type, _ = mimetypes.guess_type(video_path)
    if not mime_type: mime_type = 'video/mp4'

    up = requests.put(
        upload_url, data=video_data,
        headers={'Content-Type': mime_type, 'Content-Length': str(len(video_data))},
        timeout=900
    )

    if up.status_code in [200, 201]:
        return True, up.json().get('id', 'success')
    return False, f"Upload error {up.status_code}: {up.text[:100]}"

def update_row(sheet, row_num, status, posted_at='', error=''):
    try:
        sheet.update_cell(row_num, 9, status)
        sheet.update_cell(row_num, 10, posted_at)
        sheet.update_cell(row_num, 11, error[:200])
    except: pass

def main():
    sheet = get_sheet()
    if not sheet: return
    pending = get_pending(sheet)
    if not pending: return
    for row_num, post in pending:
        ok, msg = post_youtube(post)
        if ok: update_row(sheet, row_num, 'posted', datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S'), '')
        else: update_row(sheet, row_num, 'failed', '', msg)

if __name__ == '__main__':
    main()
