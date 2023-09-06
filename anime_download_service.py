from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from urllib.parse import unquote
import deluge_client
import feedparser
import time
import re
import requests
import datetime
import os
import yaml

API_KEY = "------------------------------"
PUSHBULLET_API_URL = 'https://api.pushbullet.com/v2/pushes'
RSS_FEED_URL = "https://subsplease.org/rss/?r=1080"
PUSHBULLET_CHECK_INTERVAL = 5
RSS_CHECK_INTERVAL = 10
DOWNLOAD_FOLDER = '/media/pi/Drive/Anime'
DRY_RUN = False
DEBUG = False
PATTERN = r'\[(.*?)\] (.*?) - (\d+) \(1080p\) \[.*?\]\.mkv'

seen_entry_ids = set()
anime_list = dict()


def debug(*args, **kwargs):
    if DEBUG:
        print("DEBUG: ",end="")
        print(*args, **kwargs)


def info(*args, **kwargs):
    print("INFO: ",end="")
    print(*args, **kwargs)


def check_for_push(pb_last_success):
    def print_ratelimit(headers):
        if 'X-RateLimit-Remaining' in headers:
            remain = headers['X-RateLimit-Remaining']
            total = headers['X-RateLimit-Limit']
            until = datetime.datetime.fromtimestamp(
                float(headers['X-RateLimit-Reset'])).strftime('%Y-%m-%d %H:%M:%S')
            debug(f"Remain {remain}/{total} units, until {until}")
            
    def print_last_success():
        t = datetime.datetime.fromtimestamp(pb_last_success).strftime('%Y-%m-%d %H:%M:%S.%f')
        debug(f"Find push after {t}")

    headers = {
        'Access-Token': API_KEY,
    }

    current_time = time.time()
    try:
        response = requests.get(PUSHBULLET_API_URL, headers=headers, params={
                                "modified_after": str(int(pb_last_success))}, timeout=10)
    except requests.exceptions.HTTPError as http_e:
        print_ratelimit(response.headers)
        info("Check for push HTTPError")
        return pb_last_check
    except Exception as e:
        return pb_last_check

    print_last_success()
    if response.status_code == 200:
        pushes = response.json()['pushes']
        for push in pushes:
            if 'url' in push:
                link = push['url']
                debug(f"Receive {link}")
                download_anime(link)
        return current_time
    else:
        return pb_last_check


def check_rss(dry=False):
    try:
        feed = feedparser.parse(RSS_FEED_URL)
    except Exception as e:
        info("Check RSS Error")
        return
    for entry in feed.entries:
        entry_id = entry.get('id', '')
        if entry_id not in seen_entry_ids:
            seen_entry_ids.add(entry_id)
            if dry:
                continue
            rss_title = entry.get('title', '')
            link = entry.get('link', '')
            title, ep = get_title_ep(rss_title)
            info(f"RSS - Title: {title} - Episode: {ep}")
            if title != None and title in anime_list:
                push_notify(f"Download - Title: {title} - Episode: {ep}")
                download_episode(title, link)


def get_title_ep(name):
    match = re.search(PATTERN, name)
    if match:
        return match.group(2), match.group(3)
    else:
        return None, None


def download_anime(url):
    global dirty
    if "https://subsplease.org/shows" not in url:
        return

    options = webdriver.FirefoxOptions()
    options.add_argument("--headless")
    with webdriver.Firefox(options=options) as driver:
        driver.get(url)
        # Set a maximum wait time (in seconds)
        wait = WebDriverWait(driver, 10)
        # Wait until an Episode appears
        element = wait.until(EC.presence_of_element_located(
            (By.CLASS_NAME, "episode-title")))
        magnet_links = [i.get_attribute("href") for i in driver.find_elements(
            By.XPATH, "//a[starts-with(@href, 'magnet:')]")]
        magnet_links = [i for i in magnet_links if "1080p" in unquote(i)]
        anime_title = driver.find_element(By.CLASS_NAME, "entry-title").text

    if anime_title in anime_list:
        return  # or not? remove if in list?
    anime_list[anime_title] = {"link": url}
    dirty = True
    push_notify(f"Download anime: {anime_title}")
    for link in magnet_links:
        download_episode(anime_title, link)


def download_episode(title, link):
    if title not in anime_list:
        return

    deluge = deluge_client.DelugeRPCClient("mypi", 58846, "kotori", "123456")
    deluge.connect()

    download_path = os.path.join(DOWNLOAD_FOLDER, title)
    download_options = {
        'add_paused': False,
        'download_location': download_path,
    }

    _, ep = get_title_ep(unquote(link))
    info(f"Download {title} Episode {ep}")

    if DRY_RUN:
        return

    try:
        torrent_id = deluge.core.add_torrent_magnet(link, download_options)
        torrent_exist = False
    except Exception as e:
        pattern = r'\b([0-9a-fA-F]{40})\b'
        torrent_id = re.findall(pattern, str(e))[0]
        torrent_exist = True
    if torrent_exist:
        deluge.core.move_storage([torrent_id], download_path)

    deluge.disconnect()

def push_notify(noti):
    debug(f"Notify - {noti}")
    push_data = {
        'type': 'note',  
        'title': 'Anime Download Service',
        'body': noti
    }

    headers = {
        'Access-Token': API_KEY,
        'Content-Type': 'application/json'
    }
    try:
        requests.post(PUSHBULLET_API_URL, headers=headers, json=push_data)
    except Exception as e:
        info("Send push notify fail.")

    
def load_config():
    global anime_list
    with open(config_file_path, 'r') as config_file:
        anime_list = yaml.load(config_file, Loader=yaml.FullLoader)
    
def write_config():
    with open(config_file_path, 'w') as config_file:
        yaml.dump(anime_list, config_file)


rss_last_check = time.time()
pb_last_check = time.time()
pb_last_success = time.time()
check_rss(True)

config_folder = os.path.expanduser('~/.config/anime_download_service')
os.makedirs(config_folder, exist_ok=True)
config_file_path = os.path.join(config_folder, 'animelist.yaml')

if os.path.exists(config_file_path):
    load_config()
else:
    write_config()

dirty = False
    

while True:
    current_time = time.time()
    if current_time - pb_last_check >= PUSHBULLET_CHECK_INTERVAL:
        load_config()
        pb_last_success = check_for_push(pb_last_success)
        pb_last_check = current_time
        if dirty:
            write_config()
            dirty = False

    current_time = time.time()
    if current_time - rss_last_check >= RSS_CHECK_INTERVAL:
        load_config()
        check_rss()
        rss_last_check = current_time

    time.sleep(1)
