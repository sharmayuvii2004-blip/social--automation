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

# ============================================================
# CONFIGURATION
# ============================================================
TIMEZONE = pytz.timezone('Asia/Kolkata')
SHEET_NAME = 'Content_Master'
WINDOW_SEC = 86400  # 24 hours

# Facebook & Instagram
FB_USER_TOKEN = os.environ.get('FB_USER_TOKEN', '')
FB_PAGE_ID_BILLIONAIRE = os.environ.get('FB_PAGE_ID_BILLIONAIRE', '1133625303164256')
FB_PAGE_ID_AI_SALES = os.environ.get('FB_PAGE_ID_AI_SALES', '1123448560851308')

# YouTube
YT_CLIENT_ID = os.environ.get('YT_CLIENT_ID', '')
YT_CLIENT_SECRET = os.environ.get('YT_CLIENT_SECRET', '')
YT_REFRESH_BILLIONAIRE = os.environ.get('YT_TOKEN_BILLIONAIRE', '')
YT_REFRESH_AI_SALES = os.environ.get('YT_TOKEN_AI_SALES', '')

# ============================================================
# GOOGLE SHEET
# ============================================================
def get_sheet():
    scopes = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    try:
        creds_json = json.loads(os.environ['GOOGLE_CREDS'])
        creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open(SHEET_NAME).sheet1
    except Exception as e:
        print(f"❌ Google Sheet Error: {e}")
        return None

def get_pending(sheet):
    rows = sheet.get_all_records()
    now = datetime.now(TIMEZONE)
    pending = []
    print(f"🕐 Current Time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📋 Total Rows: {len(rows)}")
    for i, row in enumerate(rows):
        status = str(row.get('status', '')).strip().lower()
        if status != 'pending':
            continue
        try:
            sched_str = str(row.get('schedule_datetime', '')).strip()
            if not sched_str:
                continue
            sched = datetime.strptime(sched_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=TIMEZONE)
            diff = (now - sched).total_seconds()
            if 0 <= diff <= WINDOW_SEC:
                pending.append((i + 2, row))
                print(f"✅ Row {i+2} is pending: {row.get('title', '')}")
        except Exception as e:
            print(f"⚠️ Row {i+2} date error: {e}")
    return pending

def update_row(sheet, row_num, status, posted_at='', error_log=''):
    try:
        sheet.update_cell(row_num, 9, status)
        if posted_at:
            sheet.update_cell(row_num, 10, posted_at)
        if error_log:
            sheet.update_cell(row_num, 11, str(error_log)[:500])
    except Exception as e:
        print(f"⚠️ Sheet update error: {e}")

# ============================================================
# VIDEO DOWNLOAD
# ============================================================
def download_video(video_url, filename='temp_video.mp4'):
    try:
        if "drive.google.com" in video_url:
            if "/d/" in video_url:
                file_id = video_url.split('/d/')[1].split('/')[0]
            elif "id=" in video_url:
                file_id = video_url.split('id=')[1].split('&')[0]
            else:
                file_id = video_url
            print(f"📥 Downloading from Google Drive: {file_id}")
            gdown.download(
                f"https://drive.google.com/uc?id={file_id}",
                filename, quiet=False, fuzzy=True
            )
        else:
            print(f"📥 Downloading from URL: {video_url}")
            r = requests.get(video_url, timeout=300, stream=True)
            with open(filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        size = os.path.getsize(filename)
        print(f"✅ Downloaded: {size/(1024*1024):.2f} MB")
        return filename, None
    except Exception as e:
        return None, f"Download failed: {e}"

# ============================================================
# YOUTUBE
# ============================================================
def get_yt_access_token(refresh_token):
    try:
        r = requests.post('https://oauth2.googleapis.com/token', data={
            'client_id': YT_CLIENT_ID,
            'client_secret': YT_CLIENT_SECRET,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }, timeout=30)
        if r.status_code == 200:
            return r.json().get('access_token'), None
        return None, f"YT token error: {r.text[:200]}"
    except Exception as e:
        return None, f"YT token exception: {e}"

def upload_youtube(row, channel):
    print(f"\n📺 YouTube Upload [{channel}]...")

    refresh_token = YT_REFRESH_BILLIONAIRE if 'billionaire' in channel else YT_REFRESH_AI_SALES
    access_token, err = get_yt_access_token(refresh_token)
    if not access_token:
        return False, err

    video_url = str(row.get('video_url', '')).strip()
    if not video_url:
        return False, "No video_url in sheet"

    video_path, err = download_video(video_url, 'yt_video.mp4')
    if not video_path:
        return False, err

    with open(video_path, 'rb') as f:
        video_data = f.read()

    title = str(row.get('title', 'Video')).strip()
    description = str(row.get('description', '')).strip()
    hashtags = str(row.get('hashtags', '')).strip()
    full_desc = f"{description}\n\n{hashtags}".strip()

    headers = {'Authorization': f'Bearer {access_token}'}
    meta = {
        'snippet': {
            'title': title,
            'description': full_desc,
            'tags': [t.replace('#', '').strip() for t in hashtags.split() if t],
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False
        }
    }

    # Init resumable upload
    init = requests.post(
        'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
        headers={**headers, 'Content-Type': 'application/json'},
        json=meta, timeout=30
    )
    if init.status_code != 200:
        return False, f"YT init error {init.status_code}: {init.text[:200]}"

    upload_url = init.headers.get('Location', '')
    up = requests.put(
        upload_url, data=video_data,
        headers={'Content-Type': 'video/mp4', 'Content-Length': str(len(video_data))},
        timeout=900
    )
    if up.status_code in [200, 201]:
        vid_id = up.json().get('id', 'unknown')
        print(f"✅ YouTube uploaded: {vid_id}")
        return True, f"YT:{vid_id}"
    return False, f"YT upload error {up.status_code}: {up.text[:200]}"

# ============================================================
# FACEBOOK
# ============================================================
def get_page_token(page_id):
    try:
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{page_id}",
            params={'fields': 'access_token', 'access_token': FB_USER_TOKEN},
            timeout=30
        )
        data = r.json()
        if 'access_token' in data:
            return data['access_token'], None
        return None, f"FB page token error: {data.get('error', {}).get('message', str(data))}"
    except Exception as e:
        return None, f"FB page token exception: {e}"

def upload_facebook(row, channel):
    print(f"\n📘 Facebook Upload [{channel}]...")

    page_id = FB_PAGE_ID_BILLIONAIRE if 'billionaire' in channel else FB_PAGE_ID_AI_SALES
    page_token, err = get_page_token(page_id)
    if not page_token:
        return False, err

    video_url = str(row.get('video_url', '')).strip()
    if not video_url:
        return False, "No video_url in sheet"

    video_path, err = download_video(video_url, 'fb_video.mp4')
    if not video_path:
        return False, err

    title = str(row.get('title', '')).strip()
    description = str(row.get('description', '')).strip()
    hashtags = str(row.get('hashtags', '')).strip()
    message = f"{title}\n\n{description}\n\n{hashtags}".strip()

    with open(video_path, 'rb') as f:
        files = {'source': ('video.mp4', f, 'video/mp4')}
        data = {'description': message, 'access_token': page_token}
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{page_id}/videos",
            files=files, data=data, timeout=900
        )

    if r.status_code == 200:
        vid_id = r.json().get('id', 'unknown')
        print(f"✅ Facebook uploaded: {vid_id}")
        return True, f"FB:{vid_id}"
    return False, f"FB error {r.status_code}: {r.text[:300]}"

# ============================================================
# INSTAGRAM
# ============================================================
def get_ig_id(page_id, page_token):
    try:
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{page_id}",
            params={'fields': 'instagram_business_account', 'access_token': page_token},
            timeout=30
        )
        data = r.json()
        ig = data.get('instagram_business_account', {})
        ig_id = ig.get('id')
        if ig_id:
            return ig_id, None
        return None, f"IG not linked to page {page_id}: {data}"
    except Exception as e:
        return None, f"IG ID exception: {e}"

def get_drive_direct_url(video_url):
    if "drive.google.com" in video_url:
        if "/d/" in video_url:
            file_id = video_url.split('/d/')[1].split('/')[0]
        elif "id=" in video_url:
            file_id = video_url.split('id=')[1].split('&')[0]
        else:
            return video_url
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return video_url

def upload_instagram(row, channel):
    print(f"\n📸 Instagram Upload [{channel}]...")

    page_id = FB_PAGE_ID_BILLIONAIRE if 'billionaire' in channel else FB_PAGE_ID_AI_SALES
    page_token, err = get_page_token(page_id)
    if not page_token:
        return False, err

    ig_id, err = get_ig_id(page_id, page_token)
    if not ig_id:
        return False, err

    video_url = str(row.get('video_url', '')).strip()
    if not video_url:
        return False, "No video_url in sheet"

    direct_url = get_drive_direct_url(video_url)
    title = str(row.get('title', '')).strip()
    description = str(row.get('description', '')).strip()
    hashtags = str(row.get('hashtags', '')).strip()
    caption = f"{title}\n\n{description}\n\n{hashtags}".strip()

    # Step 1: Create container
    r1 = requests.post(
        f"https://graph.facebook.com/v19.0/{ig_id}/media",
        data={
            'media_type': 'REELS',
            'video_url': direct_url,
            'caption': caption,
            'access_token': page_token
        }, timeout=60
    )
    if r1.status_code != 200:
        return False, f"IG container error: {r1.text[:300]}"

    container_id = r1.json().get('id')
    print(f"⏳ IG container created: {container_id} — waiting for processing...")

    # Step 2: Wait for processing
    for i in range(20):
        time.sleep(15)
        status_r = requests.get(
            f"https://graph.facebook.com/v19.0/{container_id}",
            params={'fields': 'status_code,status', 'access_token': page_token},
            timeout=30
        )
        status_data = status_r.json()
        status_code = status_data.get('status_code', '')
        print(f"  IG status ({i+1}/20): {status_code}")
        if status_code == 'FINISHED':
            break
        if status_code == 'ERROR':
            return False, f"IG processing error: {status_data}"

    # Step 3: Publish
    r2 = requests.post(
        f"https://graph.facebook.com/v19.0/{ig_id}/media_publish",
        data={'creation_id': container_id, 'access_token': page_token},
        timeout=60
    )
    if r2.status_code == 200:
        post_id = r2.json().get('id', 'unknown')
        print(f"✅ Instagram published: {post_id}")
        return True, f"IG:{post_id}"
    return False, f"IG publish error: {r2.text[:300]}"

# ============================================================
# MAIN
# ============================================================
def main():
    print("🚀 Automation Started")
    sheet = get_sheet()
    if not sheet:
        return

    pending = get_pending(sheet)
    if not pending:
        print("ℹ️ No pending posts found.")
        return

    print(f"\n📌 Found {len(pending)} pending post(s)\n")

    for row_num, post in pending:
        title = str(post.get('title', '')).strip()
        platform_raw = str(post.get('platform', '')).lower().strip()
        channel_raw = str(post.get('channel', '')).lower().strip()

        print(f"\n{'='*50}")
        print(f"📝 Row {row_num}: {title}")
        print(f"🎯 Platform: {platform_raw} | Channel: {channel_raw}")

        platforms = [p.strip() for p in platform_raw.split(',')]
        results = []
        errors = []

        for platform in platforms:
            if 'youtube' in platform or platform == 'yt':
                ok, msg = upload_youtube(post, channel_raw)
                if ok:
                    results.append(msg)
                else:
                    errors.append(f"YouTube: {msg}")

            elif 'facebook' in platform or platform == 'fb':
                ok, msg = upload_facebook(post, channel_raw)
                if ok:
                    results.append(msg)
                else:
                    errors.append(f"Facebook: {msg}")

            elif 'instagram' in platform or platform == 'ig' or platform == 'insta':
                ok, msg = upload_instagram(post, channel_raw)
                if ok:
                    results.append(msg)
                else:
                    errors.append(f"Instagram: {msg}")

        now_str = datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')

        if errors:
            error_summary = " | ".join(errors)
            success_summary = " | ".join(results) if results else "None"
            print(f"⚠️ Partial/Full Failure")
            print(f"  ✅ Success: {success_summary}")
            print(f"  ❌ Errors: {error_summary}")
            update_row(sheet, row_num, 'failed', now_str, error_summary)
        else:
            success_summary = " | ".join(results)
            print(f"🎉 All platforms posted successfully!")
            update_row(sheet, row_num, 'posted', now_str, f"All Success: {success_summary}")

    print(f"\n✅ Automation Complete!")

if __name__ == '__main__':
    main()
