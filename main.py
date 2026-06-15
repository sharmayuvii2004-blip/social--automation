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
    # Fixed matching logic to handle sub-strings safely
    clean_channel = str(channel).strip().lower()
    key = 'billionaire' if 'billionaire' in clean_channel else 'ai_sales'
    
    refresh_token = YT_TOKENS.get(key, '')
    client_id = os.environ.get('YT_CLIENT_ID', '')
    client_secret = os.environ.get('YT_CLIENT_SECRET', '')
    
    if not refresh_token:
        return None, f"YT Token Secret Missing for key: YT_TOKEN_{key.upper()}"
    if not client_id or not client_secret:
        return None, "YT_CLIENT_ID or SECRET missing in GitHub"
        
    r = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': client_id, 'client_secret': client_secret,
        'refresh_token': refresh_token, 'grant_type': 'refresh_token'
    })
    if r.status_code == 200:
        return r.json().get('access_token'), None
    return None, f"OAuth Refresh Error {r.status_code}: {r.text[:50]}"

def post_instagram(ig_id, video_url, caption):
    if not ig_id:
        return False, "IG ID Missing (Check GitHub Secrets)"
    if not FB_USER_TOKEN:
        return False, "FB_USER_TOKEN Missing"
    try:
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
        print(f"DEBUG: Instagram Container created ({container_id}). Waiting 45s...")
        time.sleep(45)
        
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

def post_facebook(page_id, video_path, caption):
    if not page_id:
        return False, "FB Page ID Missing (Check GitHub Secrets)"
    if not FB_USER_TOKEN:
        return False, "FB_USER_TOKEN Missing"
    try:
        acc_url = f"https://graph.facebook.com/v25.0/me/accounts?access_token={FB_USER_TOKEN}"
        acc_res = requests.get(acc_url).json()
        
        if 'data' not in acc_res:
            return False, f"FB Accounts Fetch Failed: {json.dumps(acc_res.get('error', acc_res))}"
            
        page_token = next((p['access_token'] for p in acc_res.get('data', []) if str(p['id']) == str(page_id)), None)
        if not page_token:
            return False, f"Token doesn't manage Page ID {page_id}. Check permissions."
        
        with open(video_path, 'rb') as f:
            video_binary = f.read()
            
        init_url = f"https://graph.facebook.com/v25.0/{page_id}/video_reels"
        init_res = requests.post(init_url, data={'upload_phase': 'START', 'access_token': page_token}).json()
        
        if 'video_id' not in init_res:
            return False, f"FB Init Error: {json.dumps(init_res.get('error', init_res))}"
            
        video_id = init_res['video_id']
        upload_url = init_res['upload_url']
        
        requests.post(upload_url, headers={'Authorization': f'OAuth {page_token}'}, data=video_binary)
        time.sleep(20)
        
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
    clean_row = {str(k).lower().strip(): v for k, v in row.items()}
    p_val = str(clean_row.get('platform', '')).lower().strip()
    channel = str(clean_row.get('channel', '')).lower().strip()
    
    if 'youtube' not in p_val and 'yt' not in p_val:
        return True, 'skipped'

    access_token, err_msg = get_yt_access_token(channel)
    if not access_token: 
        return False, f"YT Token Error: {err_msg}"

    video_url = row.get('video_url', '')
    if "drive.google.com" in video_url:
        if "/d/" in video_url: file_id = video_url.split('/d/')[1].split('/')[0]
        elif "id=" in video_url: file_id = video_url.split('id=')[1].split('&')[0]
        else: file_id = video_url
        video_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    video_path = 'temp_video.mp4'
    try:
        if not os.path.exists(video_path):
            gdown.download(video_url, video_path, quiet=True, fuzzy=True)
        with open(video_path, 'rb') as f:
            video_data = f.read()
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

def main():
    sheet = get_sheet()
    if not sheet: return
    pending = get_pending(sheet)
    if not pending: return
    
    for row_num, post in pending:
        clean_row = {str(k).lower().strip(): v for k, v in post.items()}
        platforms_list = [p.strip().lower() for p in str(clean_row.get('platform', '')).split(',')]
        channel_name = str(clean_row.get('channel', '')).strip().lower()
        
        # Safely determine correct channel key
        target_key = 'billionaire' if 'billionaire' in channel_name else 'ai_sales'
        meta_info = META_IDS.get(target_key, {'page_id': '', 'ig_id': ''})
        
        video_url = post.get('video_url', '')
        if "drive.google.com" in video_url:
            if "/d/" in video_url: f_id = video_url.split('/d/')[1].split('/')[0]
            elif "id=" in video_url: f_id = video_url.split('id=')[1].split('&')[0]
            else: f_id = video_url
            web_download_url = f"https://drive.google.com/uc?export=download&id={f_id}"
        else:
            web_download_url = video_url

        video_path = 'temp_video.mp4'
        if os.path.exists(video_path):
            try: os.remove(video_path)
            except: pass

        try:
            gdown.download(web_download_url, video_path, quiet=True, fuzzy=True)
        except Exception as download_err:
            update_row(sheet, row_num, 'failed', '', f"Global Download Error: {download_err}")
            continue

        success_logs = []
        error_logs = []

        # 1. YouTube Shorts
        if 'youtube' in platforms_list or 'yt' in platforms_list:
            yt_ok, yt_msg = post_youtube(post)
            if yt_ok: success_logs.append(f"YT: {yt_msg}")
            else: error_logs.append(yt_msg)

        # 2. Instagram Reels
        if 'instagram' in platforms_list or 'ig' in platforms_list:
            ig_ok, ig_msg = post_instagram(meta_info['ig_id'], web_download_url, post.get('description', ''))
            if ig_ok: success_logs.append(ig_msg)
            else: error_logs.append(ig_msg)

        # 3. Facebook Reels
        if 'facebook' in platforms_list or 'fb' in platforms_list:
            fb_ok, fb_msg = post_facebook(meta_info['page_id'], video_path, post.get('description', ''))
            if fb_ok: success_logs.append(fb_msg)
            else: error_logs.append(fb_msg)

        if os.path.exists(video_path):
            try: os.remove(video_path)
            except: pass

        if error_logs:
            err_message = " | ".join(error_logs)
            update_row(sheet, row_num, 'failed', '', err_message)
        else:
            success_message = " | ".join(success_logs)
            update_row(sheet, row_num, 'posted', datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S'), success_message)

if __name__ == '__main__':
    main()
