import os
import json
import gspread
import requests
import pytz
from datetime import datetime
from google.oauth2.service_account import Credentials

TIMEZONE = pytz.timezone('Asia/Kolkata')
SHEET_NAME = 'Content_Master'
WINDOW_SEC = 86400

# Channel to secret mapping
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
        if str(row.get('status','')).strip().lower() != 'pending':
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
        return None
    
    # Get client credentials from env
    client_id = os.environ.get('YT_CLIENT_ID', '')
    client_secret = os.environ.get('YT_CLIENT_SECRET', '')
    
    r = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    })
    
    if r.status_code == 200:
        return r.json().get('access_token')
    return None

def post_youtube(row):
    if 'youtube' not in str(row.get('platform', '')):
        return True, 'skipped'
    
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
        'https://www.googleapis.com/upload/youtube/v3/videos'
        '?uploadType=resumable&part=snippet,status',
        headers={**headers, 'Content-Type': 'application/json'},
        json=meta, timeout=30
    )
    
    if init.status_code != 200:
        return False, init.text[:200]
    
    upload_url = init.headers.get('Location', '')
    vid = requests.get(row['video_url'], stream=True, timeout=120)
    up = requests.put(upload_url, data=vid.content,
                      headers={'Content-Type': 'video/*'}, timeout=300)
    
    return (True, up.json().get('id')) if up.status_code in [200, 201] \
        else (False, up.text[:200])

def post_facebook(row):
    if 'fb' not in str(row.get('platform', '')):
        return True, 'skipped'
    
    channel = row['channel'].lower()
    pid = FB_PAGE_IDS.get(channel, '')
    tok = FB_TOKENS.get(channel, '')
    
    if not pid or not tok:
        return False, 'FB credentials missing'
    
    r = requests.post(
        f'https://graph.facebook.com/v19.0/{pid}/videos',
        data={
            'file_url': row['video_url'],
            'title': row['title'],
            'description': row['description'] + '\n' + row['hashtags'],
            'access_token': tok
        }, timeout=60)
    
    return (True, r.json().get('id')) if r.status_code == 200 \
        else (False, r.text[:200])

def post_instagram(row):
    if 'insta' not in str(row.get('platform', '')):
        return True, 'skipped'
    
    import time
    channel = row['channel'].lower()
    iid = IG_IDS.get(channel, '')
    tok = IG_TOKENS.get(channel, '')
    
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

def main():
    now_str = datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
    print(f'🚀 Started at {now_str} IST')
    
    sheet = get_sheet()
    pending = get_pending(sheet)
    
    if not pending:
        print('✅ No posts due now.')
        return
    
    for row_num, post in pending:
        print(f'\n📤 Posting: {post["title"]} | {post["channel"]} | {post["platform"]}')
        
        errors = []
        fb_ok, fb_msg = post_facebook(post)
        ig_ok, ig_msg = post_instagram(post)
        yt_ok, yt_msg = post_youtube(post)
        
        if not fb_ok: errors.append(f'FB:{fb_msg}')
        if not ig_ok: errors.append(f'IG:{ig_msg}')
        if not yt_ok: errors.append(f'YT:{yt_msg}')
        
        status = 'posted' if not errors else \
                 ('failed' if len(errors) == 3 else 'partial')
        
        update_row(sheet, row_num, status, now_str, ' | '.join(errors))
        print(f'{"✅" if status=="posted" else "⚠️"} {status}')

if __name__ == '__main__':
    main()
