import os
import requests

# ==========================================
# GITHUB SECRETS LOADING
# ==========================================
FB_USER_TOKEN = os.environ.get('FB_USER_TOKEN')
YT_CLIENT_ID = os.environ.get('YT_CLIENT_ID')
YT_CLIENT_SECRET = os.environ.get('YT_CLIENT_SECRET')

# ==========================================
# 1. INSTAGRAM AUTOMATION LOGIC
# ==========================================
def post_instagram_reel(instagram_business_id, video_url, caption):
    """Instagram Business Account par Reel publish karne ke liye"""
    if not instagram_business_id or not FB_USER_TOKEN:
        return False, "IG Credentials Missing"
    try:
        print(f"DEBUG IG: Container create kar rahe hain for ID: {instagram_business_id}")
        container_url = f"https://graph.facebook.com/v25.0/{instagram_business_id}/media"
        
        # Container initialization
        container_res = requests.post(container_url, data={
            'media_type': 'REELS',
            'video_url': video_url,
            'caption': caption,
            'access_token': FB_USER_TOKEN
        }).json()
        
        if 'id' not in container_res:
            return False, f"IG Container Error: {container_res}"
            
        container_id = container_res['id']
        
        # Wait for Instagram to process the video (Simple Poll/Status Check fallback)
        import time
        print("DEBUG IG: Waiting 30 seconds for Instagram to process the video container...")
        time.sleep(30)
        
        # Publish the container
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
# 2. FACEBOOK REEL AUTOMATION LOGIC (FIXED)
# ==========================================
def post_facebook_reel(page_id, video_binary, caption):
    """Facebook Page par Reel publish karne ke liye (Automated Page Token Fix)"""
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
                    print("DEBUG FB: Successfully fetched Page Access Token!")
                    break
        
        token_to_use = page_access_token if page_access_token else FB_USER_TOKEN
        
        print("DEBUG FB: Initializing Facebook Reel Upload...")
        init_url = f"https://graph.facebook.com/v25.0/{page_id}/video_reels"
        
        init_res = requests.post(init_url, data={
            'upload_phase': 'START',
            'access_token': token_to_use
        }).json()
        
        if 'video_id' not in init_res:
            return False, f"FB Init Error: {init_res}"
            
        video_id = init_res['video_id']
        upload_url = init_res['upload_url']
        
        print(f"DEBUG FB: Uploading Reel Binary to Facebook... Video ID: {video_id}")
        upload_res = requests.post(upload_url, headers={'Authorization': f'OAuth {token_to_use}'}, data=video_binary)
        
        print("DEBUG FB: Finalizing Facebook Reel Publication...")
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
# 3. YOUTUBE AUTOMATION LOGIC (FIXED)
# ==========================================
def get_youtube_refresh_token(channel_name):
    """Channel name ke basis par sahi refresh token load karne ka dynamic fix"""
    clean_name = str(channel_name).strip().lower()
    
    if 'billionaire' in clean_name:
        token = os.environ.get('YT_TOKEN_BILLIONAIRE')
    elif 'sales' in clean_name or 'ai_sales' in clean_name:
        token = os.environ.get('YT_TOKEN_AI_SALES')
    else:
        token = None
        
    if not token:
        print("DEBUG YT: Fallback token use kar rahe hain.")
        token = os.environ.get('YT_TOKEN_BILLIONAIRE') or os.environ.get('YT_TOKEN_AI_SALES')
        
    return token

def refresh_youtube_access_token(refresh_token):
    """Google API se Access token fetch karne ka production logic"""
    if not refresh_token or not YT_CLIENT_ID or not YT_CLIENT_SECRET:
        return None
    url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": YT_CLIENT_ID,
        "client_secret": YT_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    try:
        res = requests.post(url, data=data).json()
        return res.get("access_token")
    except Exception as e:
        print(f"DEBUG YT Refresh Exception: {e}")
        return None
