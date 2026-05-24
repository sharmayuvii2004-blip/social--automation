import os
import json
import gspread
import requests
import pytz
import mimetypes
from datetime import datetime
from google.oauth2.service_account import Credentials

TIMEZONE = pytz.timezone('Asia/Kolkata')
SHEET_NAME = 'Content_Master'
WINDOW_SEC = 86400

YT_TOKENS = {
    'billionaire': os.environ.get('YT_TOKEN_BILLIONARIE', ''),
    'ai_sales': os.environ.get('YT_TOKEN_AI_SALES', ''),
}

FB_PAGE_IDS = {
    'billionaire': os.environ.get('FB_PAGE_ID_BILLIONAIRE', ''),
    'ai_sales': os.environ.get('FB_PAGE_ID_AI_SALES', ''),
}

FB_TOKENS = {
    'billionaire': os.environ.get('FB_TOKEN_BILLIONAIRE', ''),
    'ai_sales': os.environ.get('FB_TOKEN_AI_SALES', ''),
}

IG_IDS = {
    'billionaire': os.environ.get('IG_ID_BILLIONAIRE', ''),
    'ai_sales': os.environ.get('IG_ID_AI_SALES', ''),
}

IG_TOKENS = {
    'billionaire': os.environ.get('IG_TOKEN_BILLIONAIRE', ''),
    'ai_sales': os.environ.get('IG_TOKEN_AI_SALES', ''),
}

def get_sheet():
    scopes = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds_json = json.loads(os.environ['GOOGLE_CREDS'])
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1

def get_pending(sheet):
    rows = sheet.get_all_records()
    now = datetime.now(TIMEZONE)
    print(f"DEBUG: Current time = {now}")
    print(f"DEBUG: Total rows = {len(rows)}")
    pending = []
    for i, row in enumerate(rows):
        print(f"DEBUG: Row {i+2} status={row.get('status')} schedule={row.get('schedule_datetime')}")
        if str(row.get('status', '')).strip().lower() != 'pending':
            continue
        try:
            sched = datetime.strptime(
                str(row['schedule_datetime']), '%Y-%m-%d %H:%M:%S'
            ).replace(tzinfo=TIMEZONE)
            diff = (now - sched).total_seconds()
            print(f"DEBUG: Row {i+2} diff={diff} seconds")
            if 0 <= diff <= WINDOW_SEC:
                pending.append((i + 2, row))
        except Exception as e:
            print(f"Row {i+2} error: {e}")
    return pending

def get_yt_access_token(channel):
    refresh_token = YT_TOKENS.get(channel, '')
    if not refresh_token:
        print(f"YT: No refresh token for channel={channel}")
        return None

    client_id = os.environ.get('YT_CLIENT_ID', '')
    client_secret = os.environ.get('YT_CLIENT_SECRET', '')

    print(f"YT: Getting access token for channel={channel}")
    r = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    })

    if r.status_code == 200:
        print(f"YT: Access token received successfully")
        return r.json().get('access_token')

    print(f"YT Token Error: {r.status_code} {r.text[:200]}")
    return None

def post_youtube(row):
    # Line 97 ko hata kar ye 2 lines likhein:
    platform_val = str(row.get('platform', '')).lower()
    if 'youtube' not in platform_val:
        return True, 'skipped'


    import mimetypes
    import re

    channel = row['channel'].lower()
    access_token = get_yt_access_token(channel)

    if not access_token:
        return False, 'YT token missing'

    headers = {'Authorization': f'Bearer {access_token}'}

    meta = {
        'snippet': {
            'title': row['title'],
            'description': row['description'] + '\n\n' + row['hashtags'],
            'tags': row['hashtags'].replace('#', '').split(),
        },
        'status': {'privacyStatus': 'public'}
    }

    init = requests.post(
        'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
        headers={**headers, 'Content-Type': 'application/json'},
        json=meta,
        timeout=30
    )

    if init.status_code != 200:
        print("YT Init Error:", init.text)
        return False, init.text[:200]

    upload_url = init.headers.get('Location', '')

    video_url = row['video_url']
        # Line 136 se 139 tak ko isse replace karein:
    if "drive.google.com" in video_url:
        import re
        if "/d/" in video_url:
            file_id = video_url.split('/d/')[1].split('/')[0]
        elif "id=" in video_url:
            file_id = video_url.split('id=')[1].split('&')[0]
        video_url = f"https://drive.google.com/uc?export=download&id={file_id}"

        
    print("YT Final URL:", video_url)

    vid = requests.get(
        video_url,
        stream=True,
        timeout=300,
        allow_redirects=True
    )

    content_type = vid.headers.get('Content-Type', '').lower()

    print("Drive Content-Type:", content_type)
    print("File Size:", len(vid.content))

    if 'text/html' in content_type:
        return False, 'Drive returned HTML page instead of media file'

    mime_type, _ = mimetypes.guess_type(video_url)

    if not mime_type:
        mime_type = content_type if content_type else 'video/mp4'

    video_data = vid.content

    upload_headers = {
        'Content-Type': mime_type,
        'Content-Length': str(len(video_data))
    }

    up = requests.put(
        upload_url,
        data=video_data,
        headers=upload_headers,
        timeout=900
    )

    try:
        response_json = up.json()
    except:
        response_json = {}

    if up.status_code in [200, 201]:
        print("✅ Upload Success")
        return True,
    response_json.get('id', 'uploaded')

    print("❌ Upload Failed:", up.status_code)
    print(up.text[:500])

    return False, up.text[:500]
def post_facebook(row):
    if 'fb' not in str(row.get('platform', '')):
        return True, 'skipped'

    channel = row['channel'].lower()
    pid = FB_PAGE_IDS.get(channel, '')
    tok = FB_TOKENS.get(channel, '')
    
    if not iid or not tok:
        return False, 'IG credentials missing'

    r1 = requests.post(
        f'https://graph.facebook.com/v19.0/{iid}/media',
        data={
            'media_type': 'REELS',
            'video_url': row['video_url'],
            'caption': row['description'] + '\n\n' + row['hashtags'],
            'access_token': tok
        }, timeout=60)

    if r1.status_code != 200:
        return False, r1.text[:200]

    cid = r1.json()['id']
    time.sleep(45)

    r2 = requests.post(
        f'https://graph.facebook.com/v19.0/{iid}/media_publish',
        data={'creation_id': cid, 'access_token': tok},
        timeout=60)

    return (True, r2.json().get('id')) if r2.status_code == 200 \
        else (False, r2.text[:200])

def update_row(sheet, row_num, status, posted_at='', error=''):
    sheet.update_cell(row_num, 10, status)
    sheet.update_cell(row_num, 11, posted_at)
    sheet.update_cell(row_num, 12, error[:200] if error else '')

# main function ko aise badlein:
def main():
    now_str = datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
    print(f'🚀 Started at {now_str} IST')

    sheet = get_sheet()
    pending = get_pending(sheet)

    if not pending:
        print('✅ No posts due now.')
        return

    for row_num, post in pending:
        print(f'\n📤 Posting: {post.get("title","")} | {post.get("channel","")}')

        # Abhi sirf YouTube run hoga
        yt_ok, yt_msg = post_youtube(post)
        print(f"YT: ok={yt_ok} msg={yt_msg}")

        if yt_ok and yt_msg != 'skipped':
            status = 'posted'
            error_msg = ''
        elif yt_msg == 'skipped':
            continue # Agar platform YouTube nahi hai toh skip karein
        else:
            status = 'failed'
            error_msg = f'YT:{yt_msg}'

        update_row(sheet, row_num, status, now_str, error_msg)
        print(f'{"✅" if status=="posted" else "❌"} {status}')
        

    

if __name__ == '__main__':
    main()
    


    
