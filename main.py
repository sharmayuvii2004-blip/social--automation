import os
import requests
import json
import time
import gspread
from datetime import datetime, timedelta

# Environment Variables
FB_USER_TOKEN = os.environ.get('FB_USER_TOKEN')
YT_CLIENT_ID = os.environ.get('YT_CLIENT_ID')
YT_CLIENT_SECRET = os.environ.get('YT_CLIENT_SECRET')
GOOGLE_CREDS_JSON = os.environ.get('GOOGLE_CREDS')

# ==========================================
# 1. INSTAGRAM MECHANICS
# ==========================================
def post_instagram_reel(instagram_business_id, video_url, caption):
    print(f"[TRACE] Starting Instagram upload for ID: {instagram_business_id}")
    if not instagram_business_id or not FB_USER_TOKEN:
        return False, "IG_Auth_Keys_Missing"
    try:
        container_url = f"https://graph.facebook.com/v25.0/{instagram_business_id}/media"
        res = requests.post(container_url, data={
            'media_type': 'REELS',
            'video_url': video_url,
            'caption': caption,
            'access_token': FB_USER_TOKEN
        }).json()
        
        print(f"[TRACE] Instagram Container Response: {json.dumps(res)}")
        if 'id' not in res:
            return False, f"IG_Container_Failed: {res.get('error', {}).get('message', json.dumps(res))}"
            
        container_id = res['id']
        print(f"[TRACE] IG Container created successfully: {container_id}. Waiting for processing...")
        time.sleep(45)  # Required wait for Meta server processing
        
        publish_url = f"https://graph.facebook.com/v25.0/{instagram_business_id}/media_publish"
        pub_res = requests.post(publish_url, data={
            'creation_id': container_id,
            'access_token': FB_USER_TOKEN
        }).json()
        
        print(f"[TRACE] Instagram Publish Response: {json.dumps(pub_res)}")
        if 'id' in pub_res:
            return True, f"IG_Live_ID_{pub_res['id']}"
        return False, f"IG_Publish_Rejected: {pub_res.get('error', {}).get('message', json.dumps(pub_res))}"
    except Exception as e:
        return False, f"IG_Exception: {str(e)}"

# ==========================================
# 2. FACEBOOK MECHANICS
# ==========================================
def post_facebook_reel(page_id, video_url, caption):
    print(f"[TRACE] Starting Facebook upload for Page ID: {page_id}")
    if not page_id or not FB_USER_TOKEN:
        return False, "FB_Auth_Keys_Missing"
    try:
        accounts_url = f"https://graph.facebook.com/v25.0/me/accounts?access_token={FB_USER_TOKEN}"
        acc_res = requests.get(accounts_url).json()
        
        page_access_token = None
        if 'data' in acc_res:
            for page in acc_res['data']:
                if str(page['id']) == str(page_id):
                    page_access_token = page['access_token']
                    break
        
        token_to_use = page_access_token if page_access_token else FB_USER_TOKEN
        print(f"[TRACE] Downloading video binary for FB upload...")
        video_binary = requests.get(video_url).content
        
        init_url = f"https://graph.facebook.com/v25.0/{page_id}/video_reels"
        init_res = requests.post(init_url, data={'upload_phase': 'START', 'access_token': token_to_use}).json()
        
        print(f"[TRACE] FB Init Response: {json.dumps(init_res)}")
        if 'video_id' not in init_res:
            return False, f"FB_Init_Failed: {init_res.get('error', {}).get('message', json.dumps(init_res))}"
            
        video_id = init_res['video_id']
        upload_url = init_res['upload_url']
        
        print(f"[TRACE] Pushing binary bytes to Meta Server...")
        requests.post(upload_url, headers={'Authorization': f'OAuth {token_to_use}'}, data=video_binary)
        time.sleep(20)
        
        pub_res = requests.post(init_url, data={
            'upload_phase': 'FINISH',
            'video_id': video_id,
            'video_state': 'PUBLISHED',
            'description': caption,
            'access_token': token_to_use
        }).json()
        
        print(f"[TRACE] FB Finish Response: {json.dumps(pub_res)}")
        if pub_res.get('success') or 'id' in pub_res:
            return True, f"FB_Live_ID_{pub_res.get('id', 'Confirmed')}"
        return False, f"FB_Publish_Failed: {pub_res.get('error', {}).get('message', json.dumps(pub_res))}"
    except Exception as e:
        return False, f"FB_Exception: {str(e)}"

# ==========================================
# 3. YOUTUBE MECHANICS (RESTORED TO STABLE PRODUCTION)
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
    print("[TRACE] Refreshing YouTube OAuth Tokens...")
    access_token = refresh_youtube_access_token(refresh_token)
    if not access_token:
        return False, "YT_OAuth_Refresh_Token_Rejected"
    try:
        print("[TRACE] Fetching video streams for YouTube...")
        video_binary = requests.get(video_url).content
        url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        metadata = {
            "snippet": {
                "title": title[:100],
                "description": "#shorts #shortsfeed #viral",
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
        
        res = requests.post(url, headers=headers, files=files).json()
        print(f"[TRACE] YouTube Response: {json.dumps(res)}")
        if 'id' in res:
            return True, f"YT_Live_ID_{res['id']}"
        return False, f"YT_API_Rejected: {res.get('error', {}).get('message', json.dumps(res))}"
    except Exception as e:
        return False, f"YT_Exception: {str(e)}"

# ==========================================
# 4. MONITOR & DISPATCH
# ==========================================
def main():
    print("[SYSTEM] Connecting to Google Sheets...")
    try:
        client = gspread.service_account_from_dict(json.loads(GOOGLE_CREDS_JSON))
        sheet = client.open("Content_Master").sheet1
        rows = sheet.get_all_records()
        print(f"[SYSTEM] Total spreadsheet records pulled: {len(rows)}")
    except Exception as e:
        print(f"[FATAL] Google Sheets initialization failed: {e}")
        return

    processed_any = False

    for idx, row in enumerate(rows, start=2):
        status = str(row.get('status', '')).strip().lower()
        
        # Check condition safely
        if status != 'pending':
            continue
            
        processed_any = True
        channel_name = str(row.get('channel', '')).strip().lower()
        video_url = row.get('video_url', '')
        caption = row.get('caption', '')
        platforms = [p.strip().lower() for p in str(row.get('platform', '')).split(',')]
        
        print(f"\n[EXECUTION] Processing Row {idx} targeting platforms: {platforms}")
        
        fb_page_id = os.environ.get('FB_PAGE_ID_BILLIONAIRE') if 'billionaire' in channel_name else os.environ.get('FB_PAGE_ID_AI_SALES')
        ig_business_id = os.environ.get('IG_BUSINESS_ID_BILLIONAIRE') if 'billionaire' in channel_name else os.environ.get('IG_BUSINESS_ID_AI_SALES')

        status_logs = []
        has_failed = False

        if 'instagram' in platforms:
            ok, res = post_instagram_reel(ig_business_id, video_url, caption)
            status_logs.append(res)
            if not ok: has_failed = True

        if 'facebook' in platforms:
            ok, res = post_facebook_reel(fb_page_id, video_url, caption)
            status_logs.append(res)
            if not ok: has_failed = True

        if 'youtube' in platforms:
            token = get_youtube_refresh_token(channel_name)
            ok, res = post_youtube_shorts(token, video_url, caption)
            status_logs.append(res)
            if not ok: has_failed = True

        # Mapping Headers dynamically
        headers = [str(h).strip().lower() for h in sheet.row_values(1)]
        status_col = headers.index('status') + 1
        posted_at_col = headers.index('posted_at') + 1
        error_log_col = headers.index('error_log') + 1

        ist_time = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        log_message = " | ".join(status_logs)

        if has_failed:
            print(f"[OUTPUT] Row {idx} Execution Encountered Failures. Logging to sheet...")
            sheet.update_cell(idx, status_col, 'failed')
            sheet.update_cell(idx, error_log_col, f"Runtime Error: {log_message}")
        else:
            print(f"[OUTPUT] Row {idx} Successfully Uploaded to All Channels.")
            sheet.update_cell(idx, status_col, 'posted')
            sheet.update_cell(idx, posted_at_col, ist_time)
            sheet.update_cell(idx, error_log_col, f"All Success: {log_message}")

    if not processed_any:
        print("[SYSTEM] No rows with status 'pending' were found. Execution complete.")

if __name__ == "__main__":
    main()
