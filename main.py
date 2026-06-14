import os
import requests
import json
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 1. ENVIRONMENT VARIABLES & CREDENTIALS
# ==========================================
FB_USER_TOKEN = os.environ.get('FB_USER_TOKEN')
YT_CLIENT_ID = os.environ.get('YT_CLIENT_ID')
YT_CLIENT_SECRET = os.environ.get('YT_CLIENT_SECRET')
GOOGLE_CREDS_JSON = os.environ.get('GOOGLE_CREDS') # Google Sheet Credentials

# ==========================================
# 2. INSTAGRAM AUTOMATION LOGIC
# ==========================================
def post_instagram_reel(instagram_business_id, video_url, caption):
    if not instagram_business_id or not FB_USER_TOKEN:
        return False, "IG Credentials Missing"
    try:
        print(f"DEBUG IG: Creating container for ID: {instagram_business_id}")
        container_url = f"https://graph.facebook.com/v25.0/{instagram_business_id}/media"
        container_res = requests.post(container_url, data={
            'media_type': 'REELS',
            'video_url': video_url,
            'caption': caption,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' not in container_res:
            return False, f"IG Container Error: {container_res}"
            
        container_id = container_res['id']
        print("DEBUG IG: Waiting 30 seconds for Instagram processing...")
        time.sleep(30)
        
        publish_url = f"https://graph.facebook.com/v25.0/{instagram_business_id}/media_publish"
        publish_res = requests.post(publish_url, data={
            'creation_id': container_id,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' in publish_res:
            return True, publish_res['id']
        return False, f"IG Publish Error: {publish_res}"
    except Exception as e:
        return False, f"IG Exception: {e}"

# ==========================================
# 3. FACEBOOK REEL AUTOMATION LOGIC
# ==========================================
def post_facebook_reel(page_id, video_url, caption):
    if not page_id or not FB_USER_TOKEN:
        return False, "FB Credentials Missing"
    try:
        print(f"DEBUG FB: Fetching Page Access Token for Page ID: {page_id}")
        accounts_url = f"https://graph.facebook.com/v25.0/me/accounts?access_token={FB_USER_TOKEN}"
        accounts_res = requests.get(accounts_url).json()
        
        page_access_token = None
        if 'data' in accounts_res:
            for page in accounts_res['data']:
                if str(page['id']) == str(page_id):
                    page_access_token = page['access_token']
                    print("DEBUG FB: Page Access Token fetched successfully!")
                    break
        
        token_to_use = page_access_token if page_access_token else FB_USER_TOKEN
        
        # Binary download for FB Upload API
        video_binary = requests.get(video_url).content
        
        print("DEBUG FB: Initializing Reel Upload...")
        init_url = f"https://graph.facebook.com/v25.0/{page_id}/video_reels"
        init_res = requests.post(init_url, data={'upload_phase': 'START', 'access_token': token_to_use}).json()
        
        if 'video_id' not in init_res:
            return False, f"FB Init Error: {init_res}"
            
        video_id = init_res['video_id']
        upload_url = init_res['upload_url']
        
        print(f"DEBUG FB: Uploading video binary...")
        requests.post(upload_url, headers={'Authorization': f'OAuth {token_to_use}'}, data=video_binary)
        
        print("DEBUG FB: Finalizing Publication...")
        publish_res = requests.post(init_url, data={
            'upload_phase': 'FINISH',
            'video_id': video_id,
            'video_state': 'PUBLISHED',
            'description': caption,
            'access_token': token_to_use
        }).json()
        
        if publish_res.get('success') or 'id' in publish_res:
            return True, publish_res.get('id', 'fb_success')
        return False, f"FB Finish Error: {publish_res}"
    except Exception as e:
        return False, f"FB Exception: {e}"

# ==========================================
# 4. YOUTUBE AUTOMATION LOGIC
# ==========================================
def get_youtube_refresh_token(channel_name):
    clean_name = str(channel_name).strip().lower()
    if 'billionaire' in clean_name:
        token = os.environ.get('YT_TOKEN_BILLIONAIRE')
    elif 'sales' in clean_name or 'ai_sales' in clean_name:
        token = os.environ.get('YT_TOKEN_AI_SALES')
    else:
        token = os.environ.get('YT_TOKEN_BILLIONAIRE') or os.environ.get('YT_TOKEN_AI_SALES')
    return token

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
        print(f"DEBUG YT Refresh Exception: {e}")
        return None

def post_youtube_shorts(refresh_token, video_url, title, description=""):
    access_token = refresh_youtube_access_token(refresh_token)
    if not access_token:
        return False, "YT Access Token Refresh Failed"
    try:
        print("DEBUG YT: Downloading asset for YouTube upload...")
        video_binary = requests.get(video_url).content
        
        # Multipart Upload initialization
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
        return False, f"YT Upload Error: {res}"
    except Exception as e:
        return False, f"YT Exception: {e}"

# ==========================================
# 5. GOOGLE SHEET CONNECTOR
# ==========================================
def get_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open("Content_Master").sheet1

# ==========================================
# 6. MAIN MASTER RUNTIME EXECUTION
# ==========================================
def main():
    print("DEBUG: Master Social Automation Pipeline Started.")
    try:
        sheet = get_sheet()
        rows = sheet.get_all_records()
        print(f"DEBUG: Total rows found in sheet = {len(rows)}")
    except Exception as e:
        print(f"ERROR: Google Sheet connectivity failed: {e}")
        return

    for idx, row in enumerate(rows, start=2): # Row 1 headers hote hain, loop 2 se shuru hoga
        status = str(row.get('status', '')).strip().lower()
        if status != 'pending':
            continue
            
        print(f"DEBUG: Processing row {idx}...")
        
        # Row details fetch parameters
        channel_name = str(row.get('channel', '')).strip().lower()
        video_url = row.get('video_url', '')
        caption = row.get('caption', '')
        platforms_to_post = [p.strip().lower() for p in str(row.get('platform', '')).split(',')]
        
        # Channel Dynamic Config Selection
        if 'billionaire' in channel_name:
            fb_page_id = os.environ.get('FB_PAGE_ID_BILLIONAIRE')
            ig_business_id = os.environ.get('IG_BUSINESS_ID_BILLIONAIRE') # Variable match fallback
        else:
            fb_page_id = os.environ.get('FB_PAGE_ID_AI_SALES')
            ig_business_id = os.environ.get('IG_BUSINESS_ID_AI_SALES')

        results = {}
        errors = []

        # EXECUTE INSTAGRAM
        if 'instagram' in platforms_to_post:
            ig_ok, ig_res = post_instagram_reel(ig_business_id, video_url, caption)
            results['instagram'] = "True" if ig_ok else "False"
            if not ig_ok: errors.append(f"IG: {ig_res}")

        # EXECUTE FACEBOOK
        if 'facebook' in platforms_to_post:
            fb_ok, fb_res = post_facebook_reel(fb_page_id, video_url, caption)
            results['facebook'] = "True" if fb_ok else "False"
            if not fb_ok: errors.append(f"FB: {fb_res}")

        # EXECUTE YOUTUBE
        if 'youtube' in platforms_to_post:
            yt_token = get_youtube_refresh_token(channel_name)
            yt_ok, yt_res = post_youtube_shorts(yt_token, video_url, caption, caption)
            results['youtube'] = "True" if yt_ok else "False"
            if not yt_ok: errors.append(f"YT: {yt_res}")

        # Compile and log string formats
        status_str = " | ".join([f"{k}:{v}" for k, v in results.items()])
        if errors:
            status_str += f" (Errors: {', '.join(errors)})"
            sheet.update_cell(idx, list(row.keys()).index('status') + 1, 'failed')
        else:
            sheet.update_cell(idx, list(row.keys()).index('status') + 1, 'success')
            
        # Log column updates
        if 'log' in row:
            sheet.update_cell(idx, list(row.keys()).index('log') + 1, status_str)
        print(f"ROW {idx} RESULT: {status_str}")

if __name__ == "__main__":
    main()
