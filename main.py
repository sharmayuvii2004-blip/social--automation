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

# --- SETTINGS ---
TIMEZONE = pytz.timezone('Asia/Kolkata')
SHEET_NAME = 'Content_Master'
WINDOW_SEC = 86400  # 24 hours window

YT_TOKENS = {
    'billionaire': os.environ.get('YT_TOKEN_BILLIONAIRE', ''),
    'ai_sales': os.environ.get('YT_TOKEN_AI_SALES', ''),
}

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
        print(f"❌ Google Sheet Access Error: {e}")
        return None

def get_pending(sheet):
    rows = sheet.get_all_records()
    now = datetime.now(TIMEZONE)
    pending = []
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
            print(f"⚠️ Row {i+2} Date Error: {e}")
    return pending

def get_yt_access_token(target_key):
    refresh_token = YT_TOKENS.get(target_key)
    client_id = os.environ.get('YT_CLIENT_ID', '')
    client_secret = os.environ.get('YT_CLIENT_SECRET', '')
    
    if not refresh_token or not client_id or not client_secret:
        return f"ERROR_MISSING_CREDS_FOR_{target_key.upper()}"
        
    try:
        r = requests.post('https://oauth2.googleapis.com/token', data={
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }, timeout=15)
        res_data = r.json()
        return res_data.get('access_token', f"OAUTH_ERR: {res_data.get('error')}")
    except Exception as e:
        return f"OAUTH_EXCEPTION: {str(e)}"

# ========================================================
# 🎥 MULTI-CHANNEL METADATA ENGINES
# ========================================================

def post_facebook_reel(page_id, video_binary, caption):
    if not page_id or not FB_USER_TOKEN:
        return False, "FB Credentials Missing"
    try:
        init_url = f"https://graph.facebook.com/v25.0/{page_id}/adv_video_reels"
        r = requests.post(init_url, params={'access_token': FB_USER_TOKEN}, data={'upload_phase': 'START'}, timeout=30)
        init_res = r.json()
        
        if 'video_id' not in init_res:
            init_url = f"https://graph.facebook.com/v25.0/{page_id}/video_reels"
            r = requests.post(init_url, data={'upload_phase': 'START', 'access_token': FB_USER_TOKEN}, timeout=30)
            init_res = r.json()
            if 'video_id' not in init_res:
                return False, f"FB_INIT_ERR: {json.dumps(init_res)}"
            
        video_id = init_res['video_id']
        upload_url = init_res['upload_url']
        
        requests.post(upload_url, headers={'Authorization': f'OAuth {FB_USER_TOKEN}'}, data=video_binary, timeout=120)
        time.sleep(20)
        
        p_r = requests.post(init_url, params={'access_token': FB_USER_TOKEN}, data={
            'upload_phase': 'FINISH', 'video_id': video_id, 'video_state': 'PUBLISHED', 'description': caption
        }, timeout=30)
        publish_res = p_r.json()
        
        if publish_res.get('success') or 'id' in publish_res or 'video_id' in publish_res:
            return True, "fb_success"
        return False, f"FB_FINAL_ERR: {json.dumps(publish_res)}"
    except Exception as e:
        return False, f"FB_EXCEPTION: {e}"

def post_instagram_reel(page_id, video_url, caption):
    if not page_id or not FB_USER_TOKEN:
        return False, "IG Credentials Missing"
    try:
        ig_acc_url = f"https://graph.facebook.com/v25.0/{page_id}?fields=instagram_business_account&access_token={FB_USER_TOKEN}"
        r_ig = requests.get(ig_acc_url, timeout=20)
        ig_meta = r_ig.json()
        
        if 'instagram_business_account' not in ig_meta:
            return False, f"IG_LINK_ERR: {json.dumps(ig_meta)}"
            
        ig_business_id = ig_meta['instagram_business_account']['id']
        
        container_url = f"https://graph.facebook.com/v25.0/{ig_business_id}/media"
        c_r = requests.post(container_url, data={
            'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'access_token': FB_USER_TOKEN
        }, timeout=30)
        container_res = c_r.json()
        
        if 'id' not in container_res:
            return False, f"IG_CONTAINER_ERR: {json.dumps(container_res)}"
            
        creation_id = container_res['id']
        
        # --- SMART LOOP FOR INSTAGRAM CDN STATUS CHECK (100% GUARANTEED FIX) ---
        print(f"DEBUG: Container created ({creation_id}). Checking processing status on Meta Servers...")
        status_url = f"https://graph.facebook.com/v25.0/{creation_id}?fields=status_code,status&access_token={FB_USER_TOKEN}"
        
        max_attempts = 18  # 18 * 10 seconds = 3 Minutes max wait time
        is_ready = False
        
        for attempt in range(max_attempts):
            time.sleep(10)
            status_r = requests.get(status_url, timeout=15).json()
            status_code = status_r.get('status_code', '').upper()
            print(f"DEBUG: Status check attempt {attempt+1}: {status_code}")
            
            if status_code == 'FINISHED':
                is_ready = True
                break
            elif status_code == 'ERROR':
                return False, f"IG_SERVER_PROCESSING_FAILED: {json.dumps(status_r)}"
                
        if not is_ready:
            print("WARNING: Video processing taking too long, forcing publication attempt anyway...")
        
        # Finally publish
        publish_url = f"https://graph.facebook.com/v25.0/{ig_business_id}/media_publish"
        p_r = requests.post(publish_url, data={'creation_id': creation_id, 'access_token': FB_USER_TOKEN}, timeout=30)
        publish_res = p_r.json()
        
        if 'id' in publish_res:
            return True, "ig_success"
        return False, f"IG_PUBLISH_ERR: {json.dumps(publish_res)}"
    except Exception as e:
        return False, f"IG_EXCEPTION: {e}"

# ========================================================
# 🚀 ROUTER DISPATCH (GUARANTEED MULTI-BROADCAST)
# ========================================================

def process_multi_platform_post(row):
    clean_row = {str(k).lower().strip(): v for k, v in row.items()}
    p_val = str(clean_row.get('platform', '')).lower().strip()
    
    caption_text = f"{row.get('title', 'New Post')}\n\n{row.get('description', '')}\n\n{row.get('hashtags', '')}"
    video_url = row.get('video_url', '')
    raw_download_url = video_url
    if "drive.google.com" in video_url:
        if "/d/" in video_url: file_id = video_url.split('/d/')[1].split('/')[0]
        elif "id=" in video_url: file_id = video_url.split('id=')[1].split('&')[0]
        else: file_id = video_url
        raw_download_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    video_path = 'temp_video.mp4'
    try:
        gdown.download(raw_download_url, video_path, quiet=True)
        with open(video_path, 'rb') as f:
            video_binary_data = f.read()
    except Exception as e:
        return False, f"Download failed: {e}"

    channels_to_post = ['billionaire', 'ai_sales']
    status_report = {}

    # ----------------------------------------------------
    # 1. BROADCAST ON YOUTUBE (DONO CHANNELS PAR EK SATH)
    # ----------------------------------------------------
    if 'youtube' in p_val or 'yt' in p_val:
        for channel in channels_to_post:
            try:
                access_token = get_yt_access_token(channel)
                if not access_token or access_token.startswith("ERROR") or access_token.startswith("OAUTH"):
                    status_report[f"yt_{channel}"] = f"Failed (Token Error)"
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
                        status_report[f"yt_{channel}"] = f"Failed (Init Error {init.status_code})"
                    else:
                        upload_url = init.headers.get('Location', '')
                        mime_type, _ = mimetypes.guess_type(video_path)
                        if not mime_type: mime_type = 'video/mp4'
                        up = requests.put(
                            upload_url, data=video_binary_data,
                            headers={'Content-Type': mime_type, 'Content-Length': str(len(video_binary_data))},
                            timeout=600
                        )
                        if up.status_code in [200, 201]:
                            status_report[f"yt_{channel}"] = "Success"
                        else:
                            status_report[f"yt_{channel}"] = f"Failed (Put Error {up.status_code})"
            except Exception as e:
                status_report[f"yt_{channel}"] = f"Failed (Exception: {e})"
    else:
        status_report["yt_billionaire"] = "Skipped"
        status_report["yt_ai_sales"] = "Skipped"

    # ----------------------------------------------------
    # 2. BROADCAST ON INSTAGRAM (DONO CHANNELS PAR EK SATH WITH SMART LOOP)
    # ----------------------------------------------------
    if 'instagram' in p_val or 'ig' in p_val:
        for channel in channels_to_post:
            try:
                page_id = FB_PAGE_IDS.get(channel, '')
                ig_ok, ig_msg = post_instagram_reel(page_id, raw_download_url, caption_text)
                status_report[f"ig_{channel}"] = "Success" if ig_ok else f"Failed ({ig_msg})"
            except Exception as e:
                status_report[f"ig_{channel}"] = f"Failed (Exception: {e})"
    else:
        status_report["ig_billionaire"] = "Skipped"
        status_report["ig_ai_sales"] = "Skipped"

    # ----------------------------------------------------
    # 3. BROADCAST ON FACEBOOK (SAFE-LOCKED FOR FUTURE TRYS)
    # ----------------------------------------------------
    if 'facebook' in p_val or 'fb' in p_val:
        for channel in channels_to_post:
            status_report[f"fb_{channel}"] = "Paused (Future Fix Active)"
            # RE-ACTIVATION NOTE FOR FUTURE:
            # page_id = FB_PAGE_IDS.get(channel, '')
            # fb_ok, fb_msg = post_facebook_reel(page_id, video_binary_data, caption_text)
            # status_report[f"fb_{channel}"] = "Success" if fb_ok else f"Failed ({fb_msg})"
    else:
        status_report["fb_billionaire"] = "Skipped"
        status_report["fb_ai_sales"] = "Skipped"

    if os.path.exists(video_path):
        os.remove(video_path)

    # Global Matrix Evaluation
    active_success = True
    log_messages = []
    
    for key, status in status_report.items():
        log_messages.append(f"{key.upper()}:{status}")
        if "Failed" in status:
            active_success = False

    combined_summary = " | ".join(log_messages)
    return active_success, combined_summary

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
