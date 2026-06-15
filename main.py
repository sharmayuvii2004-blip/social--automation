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

# --- META CREDENTIALS ---
FB_USER_TOKEN = os.environ.get('FB_USER_TOKEN', '')
META_IDS = {
    'billionaire': {
        'page_id': os.environ.get('FB_PAGE_ID_BILLIONAIRE', ''),
        'ig_id': os.environ.get('IG_BUSINESS_ID_BILLIONAIRE', '')
    },
    'ai_sales': {
        'page_id': os.environ.get('FB_PAGE_ID_AI_SALES', ''),
        'ig_id': os.environ.get('IG_BUSINESS_ID_AI_SALES', '')
    }
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

# ==========================================
# NEW: INSTAGRAM REELS UPLOAD FUNCTION
# ==========================================
def post_instagram(ig_id, video_url, caption):
    if not ig_id or not FB_USER_TOKEN:
        return False, "IG Credentials Missing"
    try:
        # Step 1: Create Container
        url = f"https://graph.facebook.com/v25.0/{ig_id}/media"
        res = requests.post(url, data={
            'media_type': 'REELS',
            'video_url': video_url,
            'caption': caption,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' not in res:
            return False, f"IG Container Error: {json.dumps(res.get('error', res))}"
        
        container_id = res['id']
        print(f"DEBUG: Instagram Container created ({container_id}). Waiting 45s for Meta processing...")
        time.sleep(45)
        
        # Step 2: Publish Container
        pub_url = f"https://graph.facebook.com/v25.0/{ig_id}/media_publish"
        pub_res = requests.post(pub_url, data={
            'creation_id': container_id,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' in pub_res:
            return True, f"IG_Live_{pub_res['id']}"
        return False, f"IG Publish Error: {json.dumps(pub_res.get('error', pub_res))}"
    except Exception as e:
        return False, f"IG Exception: {str(e)}"

# ==========================================
# NEW: FACEBOOK REELS UPLOAD FUNCTION
# ==========================================
def post_facebook(page_id, video_path, caption):
    if not page_id or not FB_USER_TOKEN:
        return False, "FB Credentials Missing"
    try:
        # Step 1: Get Page Access Token
        acc_url = f"https://graph.facebook.com/v25.0/me/accounts?access_token={FB_USER_TOKEN}"
        acc_res = requests.get(acc_url).json()
        page_token = next((p['access_token'] for p in acc_res.get('data', []) if str(p['id']) == str(page_id)), FB_USER_TOKEN)
        
        # Read local binary file downloaded via gdown
        with open(video_path, 'rb') as f:
            video_binary = f.read()
            
        # Step 2: Initialize Session
        init_url = f"https://graph.facebook.com/v25.0/{page_id}/video_reels"
        init_res = requests.post(init_url, data={'upload_phase': 'START', 'access_token': page_token}).json()
        
        if 'video_id' not in init_res:
            return False, f"FB Init Error: {json.dumps(init_res.get('error', init_res))}"
            
        video_id = init_res['video_id']
        upload_url = init_res['upload_url']
        
        # Step 3: Upload Binary Pieces
        requests.post(upload_url, headers={'Authorization': f'OAuth {page_token}'}, data=video_binary)
        print("DEBUG: Facebook binary upload completed. Waiting 20s for processing...")
        time.sleep(20)
        
        # Step 4: Finalize Publish
        pub_res = requests.post(init_url, data={
            'upload_phase': 'FINISH',
            'video_id': video_id,
            'video_state': 'PUBLISHED',
            'description': caption,
            'access_token': page_token
        }).json()
        
        if pub_res.get('success') or 'id' in pub_res:
            return True, f"FB_Live_{pub_res.get('id', 'Success')}"
        return False, f"FB Publish Error: {json.dumps(pub_res.get('error', pub_res))}"
    except Exception as e:
        return False, f"FB Exception: {str(e)}"

def post_youtube(row):
    # This function is kept completely identical to your original code
    clean_row = {str(k).lower().strip(): v for k, v in row.items()}
    p_val = str(clean_row.get('platform', '')).lower().strip()
    channel = str(clean_row.get('channel', '')).lower().strip()
    
    if 'youtube' not in p_val and 'yt' not in p_val:
        return True, 'skipped'

    access_token = get_yt_access_token(channel)
    if not access_token: return False, 'YT token missing'

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

# ==========================================
# MODIFIED MASTER MULTI-DISPATCH LOGIC
# ==========================================
def main():
    sheet = get_sheet()
    if not sheet: return
    pending = get_pending(sheet)
    if not pending: return
    
    for row_num, post in pending:
        clean_row = {str(k).lower().strip(): v for k, v in post.items()}
        platforms_list = [p.strip().lower() for p in str(clean_row.get('platform', '')).split(',')]
        channel_name = str(clean_row.get('channel', '')).strip().lower()
        
        # Dynamic ID Fetch based on Channel Account Name Mapping
        meta_info = META_IDS.get(channel_name, {'page_id': '', 'ig_id': ''})
        
        # Download video once globally using your trusted approach
        video_url = post.get('video_url', '')
        if "drive.google.com" in video_url:
            if "/d/" in video_url: f_id = video_url.split('/d/')[1].split('/')[0]
            elif "id=" in video_url: f_id = video_url.split('id=')[1].split('&')[0]
            else: f_id = video_url
            web_download_url = f"https://drive.google.com/uc?export=download&id={f_id}"
        else:
            web_download_url = video_url

        video_path = 'temp_video.mp4'
        if not os.path.exists(video_path):
            try:
                gdown.download(web_download_url, video_path, quiet=True, fuzzy=True)
            except Exception as download_err:
                update_row(sheet, row_num, 'failed', '', f"Global Download Error: {download_err}")
                continue

        success_logs = []
        error_logs = []

        # 1. Dispatch to YouTube Shorts
        if 'youtube' in platforms_list or 'yt' in platforms_list:
            yt_ok, yt_msg = post_youtube(post)
            if yt_ok: success_logs.append(f"YT: {yt_msg}")
            else: error_logs.append(f"YT Fail: {yt_msg}")

        # 2. Dispatch to Instagram Reels (Requires clean absolute url web target)
        if 'instagram' in platforms_list or 'ig' in platforms_list:
            ig_ok, ig_msg = post_instagram(meta_info['ig_id'], web_download_url, post.get('description', ''))
            if ig_ok: success_logs.append(ig_msg)
            else: error_logs.append(ig_msg)

        # 3. Dispatch to Facebook Reels (Processes via local downloaded file binary)
        if 'facebook' in platforms_list or 'fb' in platforms_list:
            fb_ok, fb_msg = post_facebook(meta_info['page_id'], video_path, post.get('description', ''))
            if fb_ok: success_logs.append(fb_msg)
            else: error_logs.append(fb_msg)

        # Cleanup local file after execution loop for safety
        if os.path.exists(video_path):
            try: os.remove(video_path)
            except: pass

        # Row Tracking Updates
        if error_logs:
            err_message = " | ".join(error_logs)
            update_row(sheet, row_num, 'failed', '', err_message)
        else:
            success_message = " | ".join(success_logs)
            update_row(sheet, row_num, 'posted', datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S'), success_message)

if __name__ == '__main__':
    main()
