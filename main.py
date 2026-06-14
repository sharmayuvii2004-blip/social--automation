import os
import requests
import json
import time
import gspread
from datetime import datetime

# ==========================================
# 1. ENVIRONMENT VARIABLES & CREDENTIALS
# ==========================================
FB_USER_TOKEN = os.environ.get('FB_USER_TOKEN')
YT_CLIENT_ID = os.environ.get('YT_CLIENT_ID')
YT_CLIENT_SECRET = os.environ.get('YT_CLIENT_SECRET')
GOOGLE_CREDS_JSON = os.environ.get('GOOGLE_CREDS')

# ==========================================
# 2. INSTAGRAM REELS VALIDATOR
# ==========================================
def post_instagram_reel(instagram_business_id, video_url, caption):
    if not instagram_business_id or not FB_USER_TOKEN:
        return False, "IG Auth Error: ID ya FB User Token missing hai env me."
    try:
        container_url = f"https://graph.facebook.com/v25.0/{instagram_business_id}/media"
        container_res = requests.post(container_url, data={
            'media_type': 'REELS',
            'video_url': video_url,
            'caption': caption,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' not in container_res:
            return False, f"IG Container Failure: {json.dumps(container_res.get('error', container_res))}"
            
        container_id = container_res['id']
        print(f"DEBUG IG: Container created ({container_id}). Waiting 45 seconds for encoding...")
        time.sleep(45) # Policy safe wait time for video processing
        
        publish_url = f"https://graph.facebook.com/v25.0/{instagram_business_id}/media_publish"
        publish_res = requests.post(publish_url, data={
            'creation_id': container_id,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' in publish_res:
            return True, f"IG_Success_ID_{publish_res['id']}"
        return False, f"IG Publish Rejected: {json.dumps(publish_res.get('error', publish_res))}"
    except Exception as e:
        return False, f"IG System Exception: {str(e)}"

# ==========================================
# 3. FACEBOOK REELS VALIDATOR
# ==========================================
def post_facebook_reel(page_id, video_url, caption):
    if not page_id or not FB_USER_TOKEN:
        return False, "FB Auth Error: Page ID ya FB User Token missing hai env."
    try:
        # Auto Page Token extraction to completely bypass (#200) Permission Error
        accounts_url = f"https://graph.facebook.com/v25.0/me/accounts?access_token={FB_USER_TOKEN}"
        accounts_res = requests.get(accounts_url).json()
        
        page_access_token = None
        if 'data' in accounts_res:
            for page in accounts_res['data']:
                if str(page['id']) == str(page_id):
                    page_access_token = page['access_token']
                    break
        
        token_to_use = page_access_token if page_access_token else FB_USER_TOKEN
        
        # Download binary for secure stream upload
        video_binary = requests.get(video_url).content
        
        init_url = f"https://graph.facebook.com/v25.0/{page_id}/video_reels"
        init_res = requests.post(init_url, data={'upload_phase': 'START', 'access_token': token_to_use}).json()
        
        if 'video_id' not in init_res:
            return False, f"FB Init Failure: {json.dumps(init_res.get('error', init_res))}"
            
        video_id = init_res['video_id']
        upload_url = init_res['upload_url']
        
        # Binary upload phase
        requests.post(upload_url, headers={'Authorization': f'OAuth {token_to_use}'}, data=video_binary)
        print("DEBUG FB: Binary uploaded. Waiting 15 seconds for finalize...")
        time.sleep(15)
        
        publish_res = requests.post(init_url, data={
            'upload_phase': 'FINISH',
            'video_id': video_id,
            'video_state': 'PUBLISHED',
            'description': caption,
            'access_token': token_to_use
        }).json()
        
        if publish_res.get('success') or 'id' in publish_res:
            return True, f"FB_Success_ID_{publish_res.get('id', 'confirmed')}"
        return False, f"FB Publish Rejected: {json.dumps(publish_res.get('error', publish_res))}"
    except Exception as e:
        return False, f"FB System Exception: {str(e)}"

# ==========================================
# 4. YOUTUBE SHORTS (STRICT PUBLIC VALIDATOR)
# ==========================================
def get_youtube_refresh_token(channel_name):
    clean_name = str(channel_name).strip().lower()
    if 'billionaire' in clean_name:
        return os.environ.get('YT_TOKEN_BILLIONAIRE')
    return os.environ.get('YT_TOKEN_AI_SALES')

def refresh_youtube_access_token(refresh_token):
    if not refresh_token: return None
    url = "https://oauth2.googleapis.com/token"
    try:
        res = requests.post(url, data={
            "client_id": YT_CLIENT_ID,
            "client_secret": YT_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }).json()
        return res.get("access_token")
    except:
        return None

def post_youtube_shorts(refresh_token, video_url, title):
    access_token = refresh_youtube_access_token(refresh_token)
    if not access_token:
        return False, "YT Auth Error: Refresh token se access token nahi bana. Expiry/Client ID check karein."
    try:
        video_binary = requests.get(video_url).content
        url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # Multi-part metadata mapping to force public publishing
        metadata = {
            "snippet": {
                "title": title[:100],
                "description": "#shorts #automation",
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }
        
        files = {
            'snippet': (None, json.dumps(metadata), 'application/json; charset=UTF-8'),
            'media': ('video.mp4', video_binary, 'video/mp4')
        }
        
        response = requests.post(url, headers=headers, files=files)
        res_json = response.json()
        
        # Strict Response Structure Check
        if 'id' in res_json and 'snippet' in res_json:
            return True, f"YT_Success_ID_{res_json['id']}"
        return False, f"YT API Rejected Payload: {json.dumps(res_json.get('error', res_json))}"
    except Exception as e:
        return False, f"YT System Exception: {str(e)}"

# ==========================================
# 5. CORE CONNECTOR & RUNTIME
# ==========================================
def get_sheet():
    client = gspread.service_account_from_dict(json.loads(GOOGLE_CREDS_JSON))
    return client.open("Content_Master").sheet1

def main():
    print("DEBUG: Production Automation Engine Started.")
    try:
        sheet = get_sheet()
        rows = sheet.get_all_records()
    except Exception as e:
        print(f"Sheet Connectivity Fatal Error: {e}")
        return

    for idx, row in enumerate(rows, start=2):
        status = str(row.get('status', '')).strip().lower()
        if status != 'pending':
            continue
            
        print(f"DEBUG: Processing target Row {idx}...")
        channel_name = str(row.get('channel', '')).strip().lower()
        video_url = row.get('video_url', '')
        caption = row.get('caption', '')
        platforms = [p.strip().lower() for p in str(row.get('platform', '')).split(',')]
        
        # Load environment routing configurations
        fb_page_id = os.environ.get('FB_PAGE_ID_BILLIONAIRE') if 'billionaire' in channel_name else os.environ.get('FB_PAGE_ID_AI_SALES')
        ig_business_id = os.environ.get('IG_BUSINESS_ID_BILLIONAIRE') if 'billionaire' in channel_name else os.environ.get('IG_BUSINESS_ID_AI_SALES')

        platform_errors = []
        success_logs = []

        # INSTAGRAM FIELD RUN
        if 'instagram' in platforms:
            ok, res = post_instagram_reel(ig_business_id, video_url, caption)
            if ok: success_logs.append(res)
            else: platform_errors.append(res)

        # FACEBOOK FIELD RUN
        if 'facebook' in platforms:
            ok, res = post_facebook_reel(fb_page_id, video_url, caption)
            if ok: success_logs.append(res)
            else: platform_errors.append(res)

        # YOUTUBE FIELD RUN
        if 'youtube' in platforms:
            yt_token = get_youtube_refresh_token(channel_name)
            ok, res = post_youtube_shorts(yt_token, video_url, caption)
            if ok: success_logs.append(res)
            else: platform_errors.append(res)

        # Google Sheets Exact Index Mapping
        status_col = list(row.keys()).index('status') + 1
        posted_at_col = list(row.keys()).index('posted_at') + 1
        error_log_col = list(row.keys()).index('error_log') + 1 if 'error_log' in row else None

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Decision validation parsing
        if platform_errors:
            # Agar ek bhi platform fail hua toh sheet failed mark hogi aur log me likhega kya galti hai
            sheet.update_cell(idx, status_col, 'failed')
            error_msg = " | ".join(platform_errors)
            if error_log_col: 
                sheet.update_cell(idx, error_log_col, f"Errors: {error_msg}")
            print(f"ROW {idx} RUN ENCOUNTERED ERRORS -> {error_msg}")
        else:
            # Jab poora clear success hoga tabhi posted mark hoga
            sheet.update_cell(idx, status_col, 'posted')
            sheet.update_cell(idx, posted_at_col, current_time)
            if error_log_col: 
                sheet.update_cell(idx, error_log_col, f"All Success: {' / '.join(success_logs)}")
            print(f"ROW {idx} EXECUTED 100% PERFECTLY.")

if __name__ == "__main__":
    main()
