import os
import json
import gspread
import requests
import pytz
import time
import mimetypes
import re
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
            if not sched_str:
                continue
                
            sched = datetime.strptime(sched_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=TIMEZONE)
            diff = (now - sched).total_seconds()
            
            # Agar time ho gaya hai (diff > 0) aur 24 ghante purana nahi hai
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
        print(f"❌ YT Error: Missing tokens for channel {channel}")
        return None

    r = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    })

    if r.status_code == 200:
        return r.json().get('access_token')
    
    print(f"❌ YT Auth Failed ({r.status_code}): {r.text}")
    return None

def post_youtube(row):
    # --- IS BLOCK KO DHYAN SE REPLACE KAREIN ---
    # Sabhi columns ke naam ko lowercase aur clean karke map banate hain
    clean_row = {str(k).lower().strip(): v for k, v in row.items()}
    
    # Platform aur Channel ka data nikalte hain
    p_val = str(clean_row.get('platform', '')).lower().strip()
    channel = str(clean_row.get('channel', '')).lower().strip()
    
    print(f"DEBUG: Platform Found -> '{p_val}'")
    print(f"DEBUG: Channel Found -> '{channel}'")

    # Agar 'youtube' word kahin bhi hai, toh skip mat karo
    if 'youtube' not in p_val and 'yt' not in p_val:
        return True, 'skipped'
    # --- BLOCK END ---

    import mimetypes
    import re
    
    # Access token lene ka process
    access_token = get_yt_access_token(channel)
    if not access_token:
        return False, 'YT token missing'

    # 3. Video URL & Download
    video_url = row.get('video_url', '')
    if "drive.google.com" in video_url:
        if "/d/" in video_url:
            file_id = video_url.split('/d/')[1].split('/')[0]
        elif "id=" in video_url:
            file_id = video_url.split('id=')[1].split('&')[0]
        video_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    print(f"DEBUG: Downloading video from Drive...")
    try:
        vid = requests.get(video_url, stream=True, timeout=300, allow_redirects=True)
        content_type = vid.headers.get('Content-Type', '').lower()
        
        if 'text/html' in content_type:
            return False, "Drive error: File might be private or >100MB"
        
        video_data = vid.content
        print(f"DEBUG: File downloaded. Size: {len(video_data) / (1024*1024):.2f} MB")
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

    # Step A: Initialize Resumable Upload
    init = requests.post(
        'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
        headers={**headers, 'Content-Type': 'application/json'},
        json=meta, timeout=30
    )

    if init.status_code != 200:
        return False, f"YT Init Error {init.status_code}: {init.text[:100]}"

    upload_url = init.headers.get('Location', '')

    # Step B: Upload actual file
    mime_type, _ = mimetypes.guess_type(video_url)
    if not mime_type: mime_type = 'video/mp4'

    up = requests.put(
        upload_url,
        data=video_data,
        headers={'Content-Type': mime_type, 'Content-Length': str(len(video_data))},
        timeout=900
    )

    if up.status_code in [200, 201]:
        print("✅ YouTube Upload Success!")
        return True, up.json().get('id', 'success')
    
    return False, f"Upload error {up.status_code}: {up.text[:100]}"

def update_row(sheet, row_num, status, posted_at='', error=''):
    try:
        # Column J=10 (status), K=11 (posted_at), L=12 (error_log)
        sheet.update_cell(row_num, 9, status) # Status column change to I (9) based on your screenshot
        sheet.update_cell(row_num, 10, posted_at) # J (10)
        sheet.update_cell(row_num, 11, error[:200]) # K (11)
    except Exception as e:
        print(f"⚠️ Could not update sheet: {e}")

def main():
    now = datetime.now(TIMEZONE)
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    print(f'🚀 Script Started at {now_str} IST')

    sheet = get_sheet()
    if not sheet: return
    
    pending = get_pending(sheet)

    if not pending:
        print('✅ No posts scheduled for this time.')
        return

    for row_num, post in pending:
        print(f'\n--- Row {row_num} ---')
        
        yt_ok, yt_msg = post_youtube(post)
        
        if yt_msg == 'skipped':
            print("Skipped: Not a YouTube task.")
            continue

        if yt_ok:
            status = 'posted'
            error_log = ''
            print(f"✅ Success: Video ID {yt_msg}")
        else:
            status = 'failed'
            error_log = yt_msg
            print(f"❌ Failed: {yt_msg}")

        update_row(sheet, row_num, status, now_str, error_log)

if __name__ == '__main__':
    main()
    
    


    
