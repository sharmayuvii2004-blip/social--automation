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

def get_yt_access_token(row_dump_str):
    # CRITICAL DEBUG FOR YOUTUBE
    refresh_token = None
    if 'ai_sales' in row_dump_str.lower():
        refresh_token = YT_TOKENS.get('ai_sales')
        print("DEBUG: Selected AI_SALES Refresh Token.")
    else:
        refresh_token = YT_TOKENS.get('billionaire') or YT_TOKENS.get('ai_sales')
        print("DEBUG: Selected BILLIONAIRE (or fallback) Refresh Token.")
        
    client_id = os.environ.get('YT_CLIENT_ID', '')
    client_secret = os.environ.get('YT_CLIENT_SECRET', '')
    
    if not refresh_token:
        print("❌ DEBUG ERROR: Refresh Token itself is EMPTY in GitHub Secrets!")
        return "ERROR_EMPTY_REFRESH_TOKEN"
    if not client_id or not client_secret:
        print("❌ DEBUG ERROR: YT_CLIENT_ID or YT_CLIENT_SECRET is missing in GitHub Secrets!")
        return "ERROR_MISSING_CLIENT_CREDS"
        
    try:
        print("DEBUG: Sending request to Google OAuth Server...")
        r = requests.post('https://oauth2.googleapis.com/token', data={
            'client_id': client_id,
            'clean_secret': client_secret,
            'client_secret': client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        })
        res_data = r.json()
        print(f"DEBUG: Google OAuth Raw Response Status: {r.status_code}")
        print(f"DEBUG: Google OAuth Raw JSON: {json.dumps(res_data)}")
        
        if 'access_token' in res_data:
            return res_data.get('access_token')
        else:
            return f"GOOGLE_OAUTH_REJECTED: {res_data.get('error_description', res_data.get('error'))}"
    except Exception as e:
        print(f"❌ DEBUG ERROR: Exception during Google OAuth request: {e}")
        return f"OAUTH_EXCEPTION: {str(e)}"

# ========================================================
# 🎥 DIRECT META ENGINES (WITH MAXIMUM LOGGING)
# ========================================================

def post_facebook_reel(page_id, video_binary, caption):
    if not page_id or not FB_USER_TOKEN:
        return False, f"FB Credentials Missing (PageID: {page_id}, TokenExist: {bool(FB_USER_TOKEN)})"
    try:
        # Step 1: Exchange System User Token to Page Access Token
        page_token_url = f"https://graph.facebook.com/v20.0/{page_id}?fields=access_token&access_token={FB_USER_TOKEN}"
        p_res = requests.get(page_token_url).json()
        page_access_token = p_res.get('access_token', FB_USER_TOKEN)

        print(f"DEBUG: Hit Meta API for Facebook Page ID: {page_id}")
        init_url = f"https://graph.facebook.com/v20.0/{page_id}/videos"
        
        r = requests.post(init_url, data={
            'upload_phase': 'start',
            'access_token': page_access_token
        })
        init_res = r.json()
        print(f"DEBUG: FB Init HTTP Status: {r.status_code}")
        print(f"DEBUG: FB Init Raw JSON: {json.dumps(init_res)}")
        
        if 'video_id' not in init_res:
            return False, f"FB_INIT_RAW_ERR: {json.dumps(init_res)}"
            
        video_id = init_res['video_id']
        upload_url = init_res['upload_url']
        
        print("DEBUG: Uploading binary to Meta CDN...")
        up_r = requests.post(upload_url, headers={'Authorization': f'OAuth {page_access_token}'}, data=video_binary)
        print(f"DEBUG: FB Video Upload CDN Status: {up_r.status_code}")
        
        time.sleep(20)
        
        print("DEBUG: Dispatching FINISH Command...")
        p_r = requests.post(init_url, data={
            'upload_phase': 'finish',
            'video_id': video_id,
            'video_state': 'PUBLISHED',
            'description': caption,
            'title': caption[:50],
            'access_token': page_access_token
        })
        publish_res = p_r.json()
        print(f"DEBUG: FB Finish HTTP Status: {p_r.status_code}")
        print(f"DEBUG: FB Finish Raw JSON: {json.dumps(publish_res)}")
        
        if publish_res.get('success') or 'id' in publish_res:
            return True, "fb_success"
        return False, f"FB_FINALIZE_RAW_ERR: {json.dumps(publish_res)}"
    except Exception as e:
        return False, f"FB_SYSTEM_EXCEPTION: {e}"

def post_instagram_reel(page_id, video_url, caption):
    if not page_id or not FB_USER_TOKEN:
        return False, "Instagram Credentials Missing"
    try:
        ig_acc_url = f"https://graph.facebook.com/v25.0/{page_id}?fields=instagram_business_account&access_token={FB_USER_TOKEN}"
        r_ig = requests.get(ig_acc_url)
        ig_meta = r_ig.json()
        print(f"DEBUG: IG Account Fetch JSON: {json.dumps(ig_meta)}")
        
        if 'instagram_business_account' not in ig_meta:
            return False, f"IG_LINK_RAW_ERR: {json.dumps(ig_meta)}"
            
        ig_business_id = ig_meta['instagram_business_account']['id']
        
        container_url = f"https://graph.facebook.com/v25.0/{ig_business_id}/media"
        c_r = requests.post(container_url, data={
            'media_type': 'REELS',
            'video_url': video_url,
            'caption': caption,
            'access_token': FB_USER_TOKEN
        })
        container_res = c_r.json()
        print(f"DEBUG: IG Container HTTP Status: {c_r.status_code}")
        print(f"DEBUG: IG Container JSON: {json.dumps(container_res)}")
        
        if 'id' not in container_res:
            return False, f"IG_CONTAINER_RAW_ERR: {json.dumps(container_res)}"
            
        creation_id = container_res['id']
        time.sleep(40)
        
        publish_url = f"https://graph.facebook.com/v25.0/{ig_business_id}/media_publish"
        p_r = requests.post(publish_url, data={
            'creation_id': creation_id,
            'access_token': FB_USER_TOKEN
        })
        publish_res = p_r.json()
        print(f"DEBUG: IG Publish JSON: {json.dumps(publish_res)}")
        
        if 'id' in publish_res:
            return True, "ig_success"
        return False, f"IG_PUBLISH_RAW_ERR: {json.dumps(publish_res)}"
    except Exception as e:
        return False, f"IG_EXCEPTION: {e}"

# ========================================================
# 🚀 ROUTER DISPATCH
# ========================================================

def process_multi_platform_post(row):
    row_dump_str = json.dumps(row)
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

    execution_results = {}
    errors_log = []

    # 1. YOUTUBE REELS
    if 'youtube' in p_val or 'yt' in p_val:
        access_token = get_yt_access_token(row_dump_str)
        if not access_token or access_token.startswith("ERROR") or access_token.startswith("GOOGLE") or access_token.startswith("OAUTH"):
            execution_results['youtube'] = False
            errors_log.append(f"YT Token Debug Triggered -> {access_token}")
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
            print(f"DEBUG: YT Video Init Response: {init.status_code} | Payload: {init.text}")
            if init.status_code != 200:
                execution_results['youtube'] = False
                errors_log.append(f"YT_INIT_API_ERR_{init.status_code}: {init.text[:100]}")
            else:
                upload_url = init.headers.get('Location', '')
                mime_type, _ = mimetypes.guess_type(video_path)
                if not mime_type: mime_type = 'video/mp4'
                up = requests.put(
                    upload_url, data=video_binary_data,
                    headers={'Content-Type': mime_type, 'Content-Length': str(len(video_binary_data))},
                    timeout=900
                )
                print(f"DEBUG: YT Final Video Binary Put Status: {up.status_code}")
                if up.status_code in [200, 201]:
                    execution_results['youtube'] = True
                else:
                    execution_results['youtube'] = False
                    errors_log.append(f"YT_UPLOAD_API_ERR_{up.status_code}")

    # 2. FACEBOOK REELS
    if 'facebook' in p_val or 'fb' in p_val:
        target_key = 'billionaire' if 'billionaire' in row_dump_str.lower() else 'ai_sales'
        page_id = FB_PAGE_IDS.get(target_key, '')
        fb_ok, fb_msg = post_facebook_reel(page_id, video_binary_data, caption_text)
        execution_results['facebook'] = fb_ok
        if not fb_ok: errors_log.append(fb_msg)

    # 3. INSTAGRAM REELS
    if 'instagram' in p_val or 'ig' in p_val:
        target_key = 'billionaire' if 'billionaire' in row_dump_str.lower() else 'ai_sales'
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
