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

# Meta/Facebook Secrets mapped according to your GitHub repo secrets
FB_USER_TOKEN = os.environ.get('FB_USER_TOKEN', '')
FB_PAGE_IDS = {
    'billionaire': os.environ.get('FB_PAGE_ID_BILLIONAIRE', ''),
    'ai_sales': os.environ.get('FB_PAGE_ID_AI_SALES', ''),
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
    # Flexible key matching to prevent token missing error
    clean_channel = str(channel).strip().lower()
    key = 'billionaire' if 'billionaire' in clean_channel else 'ai_sales'
    
    refresh_token = YT_TOKENS.get(key, '')
    client_id = os.environ.get('YT_CLIENT_ID', '')
    client_secret = os.environ.get('YT_CLIENT_SECRET', '')
    
    if not refresh_token or not client_id:
        return None
        
    r = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': client_id, 'client_secret': client_secret,
        'refresh_token': refresh_token, 'grant_type': 'refresh_token'
    })
    return r.json().get('access_token') if r.status_code == 200 else None

# ========================================================
# 🎥 FIXED META ENGINES (WITH AUTO PAGE TOKEN CONVERSION)
# ========================================================

def post_facebook_reel(page_id, video_binary, caption):
    """Facebook Page par Reel publish karne ke liye (With Dynamic Page Token)"""
    if not page_id or not FB_USER_TOKEN:
        return False, "FB Credentials Missing"
    try:
        print(f"DEBUG: Converting User Token to Page Token for Page ID: {page_id}")
        # Automatically pull specific page token to bypass access permission #200 error
        accounts_url = f"https://graph.facebook.com/v25.0/me/accounts?access_token={FB_USER_TOKEN}"
        accounts_res = requests.get(accounts_url).json()
        
        page_token = FB_USER_TOKEN
        if 'data' in accounts_res:
            for page in accounts_res['data']:
                if str(page['id']) == str(page_id):
                    page_token = page['access_token']
                    print("DEBUG: Successfully generated implicit Page Access Token.")
                    break

        print(f"DEBUG: Initializing Facebook Reel Upload...")
        init_url = f"https://graph.facebook.com/v25.0/{page_id}/video_reels"
        init_res = requests.post(init_url, data={
            'upload_phase': 'START',
            'access_token': page_token
        }).json()
        
        if 'video_id' not in init_res:
            return False, f"FB Init Error: {init_res.get('error', init_res)}"
            
        video_id = init_res['video_id']
        upload_url = init_res['upload_url']
        
        print(f"DEBUG: Uploading Reel Binary to Facebook...")
        requests.post(upload_url, headers={'Authorization': f'OAuth {page_token}'}, data=video_binary)
        
        print("DEBUG: Waiting 15s for processing...")
        time.sleep(15)
        
        print("DEBUG: Finalizing Facebook Reel Publication...")
        publish_res = requests.post(init_url, data={
            'upload_phase': 'FINISH',
            'video_id': video_id,
            'video_state': 'PUBLISHED',
            'description': caption,
            'access_token': page_token
        }).json()
        
        if publish_res.get('success') or 'id' in publish_res:
            return True, "fb_success"
        return False, f"FB Finish Error: {publish_res.get('error', publish_res)}"
    except Exception as e:
        return False, f"FB Exception: {e}"

def post_instagram_reel(page_id, video_url, caption):
    """Instagram Business Profile par Reel publish karne ke liye"""
    if not page_id or not FB_USER_TOKEN:
        return False, "Instagram/FB Credentials Missing"
    try:
        print(f"DEBUG: Fetching Linked Instagram Account ID...")
        ig_acc_url = f"https://graph.facebook.com/v25.0/{page_id}?fields=instagram_business_account&access_token={FB_USER_TOKEN}"
        ig_meta = requests.get(ig_acc_url).json()
        
        if 'instagram_business_account' not in ig_meta:
            return False, "No Instagram Account linked with this Facebook Page"
            
        ig_business_id = ig_meta['instagram_business_account']['id']
        print(f"DEBUG: Instagram Business ID Found: {ig_business_id}")
        
        container_url = f"https://graph.facebook.com/v25.0/{ig_business_id}/media"
        container_res = requests.post(container_url, data={
            'media_type': 'REELS',
            'video_url': video_url,
            'caption': caption,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' not in container_res:
            return False, f"IG Container Error: {container_res.get('error', container_res)}"
            
        creation_id = container_res['id']
        print("DEBUG: Waiting 40 seconds for Instagram to process the video...")
        time.sleep(40)
        
        publish_url = f"https://graph.facebook.com/v25.0/{ig_business_id}/media_publish"
        publish_res = requests.post(publish_url, data={
            'creation_id': creation_id,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' in publish_res:
            return True, "ig_success"
        return False, f"IG Publish Error: {publish_res.get('error', publish_res)}"
    except Exception as e:
        return False, f"Instagram Exception: {e}"

# ========================================================
# 🚀 CORE ROUTER FOR ALL THREE PLATFORMS
# ========================================================

def process_multi_platform_post(row):
    clean_row = {str(k).lower().strip(): v for k, v in row.items()}
    p_val = str(clean_row.get('platform', '')).lower().strip()
    channel = str(clean_row.get('channel', '')).lower().strip()
    
    # Text Payload Formatting
    caption_text = f"{row.get('title', 'New Post')}\n\n{row.get('description', '')}\n\n{row.get('hashtags', '')}"
    
    # Download Video Logic
    video_url = row.get('video_url', '')
    raw_download_url = video_url
    if "drive.google.com" in video_url:
        if "/d/" in video_url: file_id = video_url.split('/d/')[1].split('/')[0]
        elif "id=" in video_url: file_id = video_url.split('id=')[1].split('&')[0]
        else: file_id = video_url
        raw_download_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    print(f"DEBUG: Downloading asset from Drive...")
    video_path = 'temp_video.mp4'
    try:
        gdown.download(raw_download_url, video_path, quiet=True, fuzzy=True)
        with open(video_path, 'rb') as f:
            video_binary_data = f.read()
        print(f"DEBUG: Download successful. Size: {len(video_binary_data) / (1024*1024):.2f} MB")
    except Exception as e:
        return False, f"Download failed: {e}"

    execution_results = {}
    errors_log = []

    # ----------- PLATFORM 1: YOUTUBE SHORTS -----------
    if 'youtube' in p_val or 'yt' in p_val:
        access_token = get_yt_access_token(channel)
        if not access_token:
            execution_results['youtube'] = False
            errors_log.append("YT Token Missing")
        else:
            headers = {'Authorization': f'Bearer {access_token}'}
            meta = {
                'snippet': {
                    'title': row.get('title', 'Short Video')[:100],
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
            if init.status_code != 200:
                execution_results['youtube'] = False
                errors_log.append(f"YT Init: {init.status_code}")
            else:
                upload_url = init.headers.get('Location', '')
                mime_type, _ = mimetypes.guess_type(video_path)
                if not mime_type: mime_type = 'video/mp4'
                up = requests.put(
                    upload_url, data=video_binary_data,
                    headers={'Content-Type': mime_type, 'Content-Length': str(len(video_binary_data))},
                    timeout=900
                )
                if up.status_code in [200, 201]:
                    execution_results['youtube'] = True
                else:
                    execution_results['youtube'] = False
                    errors_log.append(f"YT Upload: {up.status_code}")

    # ----------- PLATFORM 2: FACEBOOK REELS -----------
    if 'facebook' in p_val or 'fb' in p_val:
        target_key = 'billionaire' if 'billionaire' in channel else 'ai_sales'
        page_id = FB_PAGE_IDS.get(target_key, '')
        fb_ok, fb_msg = post_facebook_reel(page_id, video_binary_data, caption_text)
        execution_results['facebook'] = fb_ok
        if not fb_ok: errors_log.append(fb_msg)

    # ----------- PLATFORM 3: INSTAGRAM REELS -----------
    if 'instagram' in p_val or 'ig' in p_val:
        target_key = 'billionaire' if 'billionaire' in channel else 'ai_sales'
        page_id = FB_PAGE_IDS.get(target_key, '')
        ig_ok, ig_msg = post_instagram_reel(page_id, raw_download_url, caption_text)
        execution_results['instagram'] = ig_ok
        if not ig_ok: errors_log.append(ig_msg)

    if os.path.exists(video_path):
        os.remove(video_path)

    if not execution_results:
        return True, 'skipped'
        
    all_success = all(execution_results.values())
    combined_msg = " | ".join([f"{k}:{v}" for k, v in execution_results.items()])
    if errors_log:
        combined_msg += f" (Errors: {', '.join(errors_log)})"

    return all_success, combined_msg

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
        ok, msg = process_multi_platform_post(post)
        if ok: 
            update_row(sheet, row_num, 'posted', datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S'), msg)
        else: 
            update_row(sheet, row_num, 'failed', '', msg)

if __name__ == '__main__':
    main()
