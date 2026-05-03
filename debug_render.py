"""Debug script to inspect RENDER_DATA content."""
import sys
from urllib.parse import unquote
import json
from bs4 import BeautifulSoup

html = open(r'C:\Users\zhou\AppData\Local\Temp\dydownload_debug.html', 'r', encoding='utf-8').read()
soup = BeautifulSoup(html, 'html.parser')
tag = soup.find('script', id='RENDER_DATA')

if tag and tag.string:
    raw = tag.string.strip()
    print(f'Raw length: {len(raw)}')
    print(f'First 200 raw: {raw[:200]}')

    decoded = unquote(raw)
    print(f'Decoded length: {len(decoded)}')
    print(f'First 500 decoded: {decoded[:500]}')

    try:
        data = json.loads(decoded)
        print(f'Top-level keys: {list(data.keys())[:20]}')
        for key in data:
            if 'aweme' in str(key).lower():
                print(f'Found key with aweme: {repr(key)}')
                val = data[key]
                if isinstance(val, dict):
                    print(f'  Sub-keys: {list(val.keys())[:10]}')
                    # Try to get detail
                    if 'detail' in val:
                        detail = val['detail']
                        if isinstance(detail, dict):
                            print(f'    detail keys: {list(detail.keys())[:10]}')
                            if 'video' in detail:
                                v = detail['video']
                                print(f'    video keys: {list(v.keys())[:10]}')
                                if 'play_addr' in v:
                                    print(f'    play_addr: {v["play_addr"]}')
    except json.JSONDecodeError as e:
        print(f'JSON decode error: {e}')
else:
    print('No RENDER_DATA tag found with string content')
    # Check all script tags with id
    for t in soup.find_all('script'):
        if t.has_attr('id'):
            has_str = bool(t.string)
            print(f'Script id={t["id"]}, has content: {has_str}')
            if has_str:
                print(f'  Content preview: {t.string[:100]}')
