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

def post_instagram_reel(instagram_business_id, video_url, caption):
    if not instagram_business_id or not FB_USER_TOKEN: return False, "IG_Auth_Missing"
    try:
        res = requests.post(f"https://graph.facebook.com/v25.0/{instagram_business_id}/media", data={
            'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'access_token': FB_USER_TOKEN
        }).json()
        if 'id' not in res: return False, f"IG_Container_Error: {json.dumps(res)}"
        container_id = res['id']
        time.sleep(40)
        pub_res = requests.post(f"https://graph.facebook.com/v25.0/{instagram_business_id}/media_publish", data={
            'creation_id': container_id, 'access_token': FB_USER_TOKEN
        }).json()
        if 'id' in pub_res: return True, f"IG_Live_{pub_res['id']}"
        return False, f"IG_Pub_Error: {json.dumps(pub_res)}"
    except Exception as e: return False, f"IG_Ex: {str(e)}"

def post_facebook_reel(page_id, video_url, caption):
    if not page_id or not FB_USER_TOKEN: return False, "FB_Auth_Missing"
    try:
        acc_res = requests.get(f"https://graph.facebook.com/v25.0/me/accounts?access_token={FB_USER_TOKEN}").json()
        page_access_token = next((p['access_token'] for p in acc_res.get('data', []) if str(p['id']) == str(page_id)), FB_USER_TOKEN)
        video_binary = requests.get(video_url).content
        init_res = requests.post(f"https://graph.facebook.com/v25.0/{page_id}/video_reels", data={'upload_phase': 'START', 'access_token': page_access_token}).json()
        if 'video_id' not in init_res: return False, f"FB_Init_Error: {json.dumps(init_res)}"
        requests.post(init_res['upload_url'], headers={'Authorization': f'OAuth {page_access_token}'}, data=video_binary)
        time.sleep(20)
        pub_res = requests.post(f"https://graph.facebook.com/v25.0/{page_id}/video_reels", data={
            'upload_phase': 'FINISH', 'video_id': init_res['video_id'], 'video_state': 'PUBLISHED', 'description': caption, 'access_token': page_access_token
        }).json()
        if pub_res.get('success') or 'id' in pub_res: return True, f"FB_Live_{pub_res.get('id', 'OK')}"
        return False, f"FB_Pub_Error: {json.dumps(pub_res)}"
    except Exception as e: return False, f"FB_Ex: {str(e)}"

def post_youtube_shorts(refresh_token, video_url, title):
    if not refresh_token: return False, "YT_Token_Missing"
    try:
        tokens = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": YT_CLIENT_ID, "client_secret": YT_CLIENT_SECRET, "refresh_token": refresh_token, "grant_type": "refresh_token"
        }).json()
        access_token = tokens.get("access_token")
        if not access_token: return False, f"YT_Auth_Failed: {json.dumps(tokens)}"
        video_binary = requests.get(video_url).content
        metadata = {"snippet": {"title": title[:100], "description": "#shorts", "categoryId": "22"}, "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
        res = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status",
                            headers={"Authorization": f"Bearer {access_token}"},
                            files={'snippet': (None, json.dumps(metadata), 'application/json; charset=UTF-8'), 'media': ('video.mp4', video_binary, 'video/mp4')}).json()
        if 'id' in res: return True, f"YT_Live_{res['id']}"
        return False, f"YT_API_Error: {json.dumps(res)}"
    except Exception as e: return False, f"YT_Ex: {str(e)}"

def main():
    try:
        client = gspread.service_account_from_dict(json.loads(GOOGLE_CREDS_JSON))
        sheet = client.open("Content_Master").sheet1
        
        # Pure index tracking instead of name mapping
        raw_rows = sheet.get_all_values()
        if not raw_rows: return
        headers = [h.strip().lower() for h in raw_rows[0]]
        
        # Hard alignment parameters
        idx_channel = headers.index('channel')
        idx_video = headers.index('video_url')
        idx_caption = headers.index('caption')
        idx_platform = headers.index('platform')
        idx_status = headers.index('status')
        idx_posted = headers.index('posted_at')
        idx_error = headers.index('error_log')
    except Exception as e:
        print(f"[FATAL] Initialization Error: {e}")
        return

    for row_num, row_data in enumerate(raw_rows[1:], start=2):
        if len(row_data) <= idx_status: continue
        status = str(row_data[idx_status]).strip().lower()
        
        if status != 'pending':
            continue

        channel_name = str(row_data[idx_channel]).strip().lower()
        video_url = str(row_data[idx_video]).strip()
        caption = str(row_data[idx_caption]).strip()
        
        # Clean comma dynamic string list format split
        platforms = [p.strip().lower() for p in str(row_data[idx_platform]).split(',') if p.strip()]
        
        print(f"\n[EXECUTION] Processing Row {row_num} -> Extracted Platforms: {platforms}")
        
        if not platforms:
            print(f"[WARN] Row {row_num} has no valid platforms listed in cell!")
            sheet.update_cell(row_num, idx_status + 1, 'failed')
            sheet.update_cell(row_num, idx_error + 1, "Error: Platform column was found empty or unreadable.")
            continue

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
            token = os.environ.get('YT_TOKEN_BILLIONAIRE') if 'billionaire' in channel_name else os.environ.get('YT_TOKEN_AI_SALES')
            ok, res = post_youtube_shorts(token, video_url, caption)
            status_logs.append(res)
            if not ok: has_failed = True

        ist_time = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        log_message = " | ".join(status_logs)

        if has_failed:
            sheet.update_cell(row_num, idx_status + 1, 'failed')
            sheet.update_cell(row_num, idx_error + 1, f"Partial Failure: {log_message}")
        else:
            sheet.update_cell(row_num, idx_status + 1, 'posted')
            sheet.update_cell(row_num, idx_posted + 1, ist_time)
            sheet.update_cell(row_num, idx_error + 1, f"All Success: {log_message}")

if __name__ == "__main__":
    main()
