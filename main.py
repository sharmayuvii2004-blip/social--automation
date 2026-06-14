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
# 2. INSTAGRAM AUTOMATION LOGIC
# ==========================================
def post_instagram_reel(instagram_business_id, video_url, caption):
    if not instagram_business_id or not FB_USER_TOKEN:
        return False, "IG Credentials Missing"
    try:
        container_url = f"https://graph.facebook.com/v25.0/{instagram_business_id}/media"
        container_res = requests.post(container_url, data={
            'media_type': 'REELS',
            'video_url': video_url,
            'caption': caption,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' not in container_res:
            return False, f"IG Container Error: {container_res.get('error', container_res)}"
            
        container_id = container_res['id']
        time.sleep(30) # Wait for IG processing
        
        publish_url = f"https://graph.facebook.com/v25.0/{instagram_business_id}/media_publish"
        publish_res = requests.post(publish_url, data={
            'creation_id': container_id,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' in publish_res:
            return True, publish_res['id']
        return False, f"IG Publish Error: {publish_res.get('error', publish_res)}"
    except Exception as e:
        return False, f"IG Exception: {e}"

# ==========================================
# 3. FACEBOOK REEL AUTOMATION LOGIC
# ==========================================
def post_facebook_reel(page_id, video_url, caption):
    if not page_id or not FB_USER_TOKEN:
        return False, "FB Credentials Missing"
    try:
        accounts_url = f"https://graph.facebook.com/v25.0/me/accounts?access_token={FB_USER_TOKEN}"
        accounts_res = requests.get(accounts_url).json()
        
        page_access_token = None
        if 'data' in accounts_res:
            for page in accounts_res['data']:
                if str(page['id']) == str(page_id):
                    page_access_token = page['access_token']
                    break
        
        token_to_use = page_access_token if page_access_token else FB_USER_TOKEN
        video_binary = requests.get(video_url).content
        
        init_url = f"https://graph.facebook.com/v25.0/{page_id}/video_reels"
        init_res = requests.post(init_url, data={'upload_phase': 'START', 'access_token': token_to_use}).json()
        
        if 'video_id' not in init_res:
            return False, f"FB Init Error: {init_res.get('error', init_res)}"
            
        video_id = init_res['video_id']
        upload_url = init_res['upload_url']
        
        requests.post(upload_url, headers={'Authorization': f'OAuth {token_to_use}'}, data=video_binary)
        
        publish_res = requests.post(init_url, data={
            'upload_phase': 'FINISH',
            'video_id': video_id,
            'video_state': 'PUBLISHED',
            'description': caption,
            'access_token': token_to_use
        }).json()
        
        if publish_res.get('success') or 'id' in publish_res:
            return True, publish_res.get('id', 'fb_success')
        return False, f"FB Finish Error: {publish_res.get('error', publish_res)}"
    except Exception as e:
        return False, f"FB Exception: {e}"

# ==========================================
# 4. YOUTUBE AUTOMATION LOGIC (RESTORED)
# ==========================================
def get_youtube_refresh_token(channel_name):
    clean_name = str(channel_name).strip().lower()
    if 'billionaire' in clean_name:
        return os.environ.get('YT_TOKEN_BILLIONAIRE')
    elif 'sales' in clean_name or 'ai_sales' in clean_name:
        return os.environ.get('YT_TOKEN_AI_SALES')
    return os.environ.get('YT_TOKEN_BILLIONAIRE') or os.environ.get('YT_TOKEN_AI_SALES')

def refresh_youtube_access_token(refresh_token):
    if not refresh_token or not YT_CLIENT_ID or not YT_CLIENT_SECRET:
        return None
    url = "https://oauth2.googleapis.com/token"
    try:
        res = requests.post(url, data={
            "client_id": YT_CLIENT_ID,
            "client_secret": YT_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }).json()
        return res.get("access_token")
    except Exception as e:
        return None

def post_youtube_shorts(refresh_token, video_url, title, description=""):
    access_token = refresh_youtube_access_token(refresh_token)
    if not access_token:
        return False, "YT Access Token Refresh Failed"
    try:
        video_binary = requests.get(video_url).content
        url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        metadata = {
            "snippet": {"title": title[:100], "description": description},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
        }
        
        files = {
            'snippet': (None, json.dumps(metadata), 'application/json; charset=UTF-8'),
            'media': ('video.mp4', video_binary, 'video/mp4')
        }
        
        res = requests.post(url, headers=headers, files=files).json()
        if 'id' in res:
            return True, res['id']
        return False, f"YT Upload Error: {res.get('error', res)}"
    except Exception as e:
        return False, f"YT Exception: {e}"

# ==========================================
# 5. GOOGLE SHEET CONNECTOR
# ==========================================
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    client = gspread.service_account_from_dict(creds_dict)
    return client.open("Content_Master").sheet1

# ==========================================
# 6. MAIN MASTER RUNTIME EXECUTION
# ==========================================
def main():
    print("DEBUG: Master Social Automation Pipeline Started.")
    try:
        sheet = get_sheet()
        rows = sheet.get_all_records()
    except Exception as e:
        print(f"ERROR: Google Sheet connectivity failed: {e}")
        return

    for idx, row in enumerate(rows, start=2):
        status = str(row.get('status', '')).strip().lower()
        if status != 'pending':
            continue
            
        print(f"DEBUG: Processing row {idx}...")
        channel_name = str(row.get('channel', '')).strip().lower()
        video_url = row.get('video_url', '')
        caption = row.get('caption', '')
        platforms_to_post = [p.strip().lower() for p in str(row.get('platform', '')).split(',')]
        
        if 'billionaire' in channel_name:
            fb_page_id = os.environ.get('FB_PAGE_ID_BILLIONAIRE')
            ig_business_id = os.environ.get('IG_BUSINESS_ID_BILLIONAIRE')
        else:
            fb_page_id = os.environ.get('FB_PAGE_ID_AI_SALES')
            ig_business_id = os.environ.get('IG_BUSINESS_ID_AI_SALES')

        results = {}
        errors = []

        # EXECUTE INSTAGRAM
        if 'instagram' in platforms_to_post:
            ig_ok, ig_res = post_instagram_reel(ig_business_id, video_url, caption)
            if ig_ok:
                results['instagram'] = "Success"
            else:
                results['instagram'] = "Failed"
                errors.append(f"IG Error: {ig_res}")

        # EXECUTE FACEBOOK
        if 'facebook' in platforms_to_post:
            fb_ok, fb_res = post_facebook_reel(fb_page_id, video_url, caption)
            if fb_ok:
                results['facebook'] = "Success"
            else:
                results['facebook'] = "Failed"
                errors.append(f"FB Error: {fb_res}")

        # EXECUTE YOUTUBE
        if 'youtube' in platforms_to_post:
            yt_token = get_youtube_refresh_token(channel_name)
            yt_ok, yt_res = post_youtube_shorts(yt_token, video_url, caption, caption)
            if yt_ok:
                results['youtube'] = "Success"
            else:
                results['youtube'] = "Failed"
                errors.append(f"YT Error: {yt_res}")

        # Strict Status and Logging Updates to Sheet
        status_col_idx = list(row.keys()).index('status') + 1
        posted_at_col_idx = list(row.keys()).index('posted_at') + 1
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if errors:
            # Agar ek bhi platform fail hua toh sheet me direct 'failed' mark hoga aur log jayega
            sheet.update_cell(idx, status_col_idx, 'failed')
            error_msg = " | ".join(errors)
            # Row mapping check to update error log dynamically
            if 'error_log' in row:
                error_log_idx = list(row.keys()).index('error_log') + 1
                sheet.update_cell(idx, error_log_idx, error_msg)
            print(f"ROW {idx} FAILED: {error_msg}")
        else:
            # Jab tak saare platforms confirm successful nahi hote, tab tak posted nahi hoga
            sheet.update_cell(idx, status_col_idx, 'posted')
            sheet.update_cell(idx, posted_at_col_idx, current_time)
            if 'error_log' in row:
                error_log_idx = list(row.keys()).index('error_log') + 1
                sheet.update_cell(idx, error_log_idx, "All Platforms Uploaded Successfully")
            print(f"ROW {idx} SUCCESSFUL!")

if __name__ == "__main__":
    main()
