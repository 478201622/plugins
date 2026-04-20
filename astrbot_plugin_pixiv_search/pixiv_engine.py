import os
import requests
import json
import glob
import zipfile
from urllib.parse import quote


CONFIG_FILE = '/AstrBot/data/plugins/astrbot_plugin_pixiv_search/tag_mapping.json'

def load_tag_mapping():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except: return {}
    return {}


HISTORY_FILE = '/AstrBot/data/plugins/astrbot_plugin_pixiv_search/sent_history.json'

def translate_to_jp(keyword, proxy=None):
    try:
        url = f'https://www.pixiv.net/ajax/search/suggestions?word={quote(keyword)}'
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.pixiv.net/'}
        r = requests.get(url, headers=headers, timeout=5, proxies=proxy)
        if r.status_code == 200:
            data = r.json()
            candidates = data.get('body', {}).get('candidates', [])
            for cand in candidates:
                tag_name = cand.get('tag_name')
                if tag_name:
                    return tag_name
    except:
        pass
    return keyword

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try:
                return set(json.load(f))
            except: return set()
    return set()

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(list(history), f)

def get_illust_info(pid, proxy):
    try:
        url = f"https://www.pixiv.net/ajax/illust/{pid}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': f'https://www.pixiv.net/artworks/{pid}'
        }
        r = requests.get(url, headers=headers, timeout=10, proxies=proxy)
        if r.status_code == 200:
            data = r.json()
            if not data.get('error'):
                body = data.get('body', {})
                tags = [t.get('tag') for t in body.get('tags', {}).get('tags', [])]
                return tags
    except:
        pass
    return []

def find_local_pid(base_path, pid):
    search_pattern = os.path.join(base_path, "**", f"{pid}.*")
    matches = glob.glob(search_pattern, recursive=True)
    for match in matches:
        if match.lower().endswith(('.jpg', '.png', '.jpeg', '.gif')):
            return match
    return None

def download_by_pid(pid, base_path, proxy, save_tag=None):
    try:
        target_dir = os.path.join(base_path, save_tag if save_tag else 'Others')
        os.makedirs(target_dir, exist_ok=True)
        
        existing_path = find_local_pid(base_path, pid)
        if existing_path:
            if save_tag and (save_tag not in existing_path):
                new_path = os.path.join(target_dir, os.path.basename(existing_path))
                import shutil
                shutil.move(existing_path, new_path)
                return new_path
            return existing_path

        if not save_tag:
            tags = get_illust_info(pid, proxy)
            save_tag = 'Others'
            for t in tags:
                if t not in {'R-18', 'R18', 'pixiv', '女の子', '插画', 'オリジナル', 'original'}:
                    save_tag = t
                    break
        
        target_dir = os.path.join(base_path, save_tag)
        os.makedirs(target_dir, exist_ok=True)

        img_url = f"https://pixiv.cat/{pid}.jpg"
        headers = {'User-Agent': 'Mozilla/5.0'}
        img_r = requests.get(img_url, headers=headers, timeout=25, stream=True)
        if img_r.status_code == 200:
            content_type = img_r.headers.get('content-type', '')
            ext = 'png' if 'png' in content_type else 'jpg'
            save_path = os.path.join(target_dir, f"{pid}.{ext}")
            with open(save_path, 'wb') as f:
                for chunk in img_r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return save_path
    except:
        pass
    return None

def fetch_pixiv_image(keyword, num=1, base_path='/AstrBot/data/plugins/astrbot_plugin_pixiv_search/cache', proxy=None, is_admin=False, pack=False):
    raw_keyword = keyword
    os.makedirs(base_path, exist_ok=True)
    clean_keyword = str(keyword).lower().strip()
    tag_map = load_tag_mapping()
    target_tag = tag_map.get(clean_keyword, clean_keyword)
    if target_tag == clean_keyword:
        target_tag = translate_to_jp(clean_keyword, proxy)
    
    sent_history = load_history()
    p_ids = []
    try:
        ajax_url = f"https://www.pixiv.net/ajax/search/artworks/{quote(target_tag)}"
        params = {'word': target_tag, 'order': 'date_d', 'mode': 'safe', 'p': 1, 'type': 'all'}
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': f'https://www.pixiv.net/tags/{quote(target_tag)}/artworks'}
        r = requests.get(ajax_url, params=params, headers=headers, timeout=15, proxies=proxy)
        if r.status_code == 200:
            data = r.json()
            illusts = data.get('body', {}).get('illustManga', {}).get('data', [])
            p_ids = [str(item['id']) for item in illusts if 'id' in item and str(item['id']) not in sent_history]
    except:
        pass

    paths = []
    max_count = 20 if pack else num
    new_sent = []
    for pid in p_ids:
        if len(paths) >= max_count: break
        path = download_by_pid(pid, base_path, proxy, save_tag=target_tag)
        if path: 
            paths.append(path)
            new_sent.append(pid)

    if not paths: return [], '未找到新鲜图片'

    sent_history.update(new_sent)
    save_history(sent_history)

    if pack:
        zip_name = f"{target_tag}_{len(paths)}pics.zip"
        zip_path = os.path.join("/AstrBot/data/temp", zip_name)
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for p in paths:
                zipf.write(p, os.path.basename(p))
        return [zip_path], target_tag

    return paths[:num], raw_keyword
