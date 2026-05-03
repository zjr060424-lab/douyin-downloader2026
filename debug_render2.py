"""Deep search for video data in RENDER_DATA JSON."""
from urllib.parse import unquote
import json
from bs4 import BeautifulSoup

html = open(r'C:\Users\zhou\AppData\Local\Temp\dydownload_debug.html', 'r', encoding='utf-8').read()
soup = BeautifulSoup(html, 'html.parser')
tag = soup.find('script', id='RENDER_DATA')
decoded = unquote(tag.string.strip())
data = json.loads(decoded)

def deep_search(obj, path='', max_depth=5):
    """Recursively search for keys containing video/aweme/play_addr data."""
    if max_depth <= 0:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            cur = f'{path}.{k}'
            if any(x in k.lower() for x in ['aweme', 'video_id', 'play_addr', 'item_list', 'detail']):
                if isinstance(v, dict):
                    print(f'\n[{cur}] (dict, {len(v)} keys):')
                    print(f'  Keys: {list(v.keys())[:15]}')
                elif isinstance(v, list):
                    print(f'\n[{cur}] (list, {len(v)} items)')
                    if v:
                        print(f'  First item type: {type(v[0]).__name__}')
                elif isinstance(v, str):
                    print(f'\n[{cur}] = {v[:200]}')
            deep_search(v, cur, max_depth - 1)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, dict):
                for k in item:
                    if any(x in k.lower() for x in ['aweme_id', 'video', 'play_addr', 'desc']):
                        deep_search(item, f'{path}[{i}]', max_depth - 1)

# Print top-level structure
print('=== Top-level keys: ===')
for k, v in data.items():
    if isinstance(v, dict):
        print(f'  {k}: dict with keys: {list(v.keys())[:20]}')

# Deep search for video-related data
print('\n=== Searching for video data ===')
deep_search(data)

# Also dump the app key structure 2 levels deep
print('\n=== App subtree (2 levels) ===')
def show_tree(obj, indent=0, max_depth=2):
    if max_depth <= 0:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            prefix = '  ' * indent
            if isinstance(v, dict):
                print(f'{prefix}{k}: dict({len(v)} keys) -> {list(v.keys())[:10]}')
                show_tree(v, indent + 1, max_depth - 1)
            elif isinstance(v, list):
                print(f'{prefix}{k}: list({len(v)} items)')
                if v and isinstance(v[0], dict):
                    print(f'{prefix}  [0]: {list(v[0].keys())[:10]}')
            else:
                val_str = str(v)[:100]
                print(f'{prefix}{k}: {val_str}')

show_tree(data)
