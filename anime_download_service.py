from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from urllib.parse import unquote, urlparse, parse_qs
from base64 import b32decode
import deluge_client
import feedparser
import time
import re
import requests
import datetime
import os
import yaml

API_KEY = "------------------------------"
PUSHBULLET_API_URL = "https://api.pushbullet.com/v2/pushes"
RSS_FEED_URL = "https://subsplease.org/rss/?r=1080"
PUSHBULLET_CHECK_INTERVAL = 5
RSS_CHECK_INTERVAL = 10
DOWNLOAD_FOLDER = "/media/pi/Drive/Anime"
DRY_RUN = "dryrun" in os.environ
DEBUG = "debug" in os.environ
PATTERN = r"\[(.*?)\] (.*?) - (\d+(?:\.\d+)?)v?(\d*) \(1080p\) \[.*?\]\.mkv"
BATCH_PATTERN = r"\[(.*?)\] (.*?) \((\d+(?:-\d+)?)\) \(1080p\) \[Batch\]"

### Todo
# deal with version


def debug(*args, **kwargs):
    if DEBUG:
        print("DEBUG: ", end="")
        print(*args, **kwargs)


def info(*args, **kwargs):
    print("INFO: ", end="")
    print(*args, **kwargs)


def check_for_push(pb_last_success):
    def print_ratelimit(headers):
        if "X-RateLimit-Remaining" in headers:
            remain = headers["X-RateLimit-Remaining"]
            total = headers["X-RateLimit-Limit"]
            until = datetime.datetime.fromtimestamp(
                float(headers["X-RateLimit-Reset"])
            ).strftime("%Y-%m-%d %H:%M:%S")
            debug(f"Remain {remain}/{total} units, until {until}")

    def print_last_success():
        t = datetime.datetime.fromtimestamp(pb_last_success).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )
        debug(f"Find push after {t}")
        print_ratelimit(headers)

    headers = {
        "Access-Token": API_KEY,
    }

    current_time = time.time()
    try:
        response = requests.get(
            PUSHBULLET_API_URL,
            headers=headers,
            params={"modified_after": str(int(pb_last_success))},
            timeout=10,
        )
    except requests.exceptions.HTTPError as http_e:
        print_ratelimit(response.headers)
        info("Check for push HTTPError")
        return pb_last_check
    except Exception as e:
        return pb_last_check

    print_last_success()
    if response.status_code == 200:
        pushes = response.json()["pushes"]
        for push in pushes:
            push_handle(push)
        return current_time
    else:
        return pb_last_check


def push_handle(push):
    if "url" not in push:
        return
    link = push["url"]
    debug(f"Receive {link}")
    if "https://subsplease.org/shows" not in link:
        return
    if "body" in push:
        if "batch" in push["body"]:
            download_anime(link, batch=True)
            return
        if "move" in push["body"]:
            download_anime(link, move=True)
            return
        if "stop" in push["body"]:
            download_anime(link, stop=True)
            return
        if "force" in push["body"]:
            download_anime(link, force=True)
            return

    download_anime(link)


def check_rss(dry=False):
    try:
        feed = feedparser.parse(RSS_FEED_URL)
    except Exception as e:
        info("Check RSS Error")
        return
    for entry in feed.entries:
        entry_id = entry.get("id", "")
        if entry_id not in seen_entry_ids:
            seen_entry_ids.add(entry_id)
            if dry:
                continue
            rss_title = entry.get("title", "")
            link = entry.get("link", "")
            title, ep = get_title_ep(rss_title)
            info(f"RSS - Title: {title} - Episode: {ep}")
            if title != None and (title in anime_list):
                info(f"Download - Title: {title} - Episode: {ep}")
                download_torrents(title, link)


def get_title_ep(name):
    match = re.search(PATTERN, name)
    if match:
        return match.group(2), match.group(3)
    else:
        return None, None


def magnet_to_hash(magnet):
    query_params = parse_qs(urlparse(magnet).query)
    if "xt" not in query_params:
        return None
    xt_value = query_params.get("xt", [])[0].split(":")[-1]
    return bytes(b32decode(xt_value).hex(), encoding="ascii")


def get_anime_info(url):
    options = webdriver.FirefoxOptions()
    options.add_argument("--headless")
    with webdriver.Firefox(options=options) as driver:
        driver.get(url)
        # Set a maximum wait time (in seconds)
        wait = WebDriverWait(driver, 10)
        # Wait until an Episode appears
        element = wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "episode-title"))
        )
        magnet_links = [
            i.get_attribute("href")
            for i in driver.find_elements(
                By.XPATH, "//a[starts-with(@href, 'magnet:')]"
            )
        ]
        magnet_links = [i for i in magnet_links if "1080p" in unquote(i)]
        anime_title = driver.find_element(By.CLASS_NAME, "entry-title").text
    return anime_title.replace("–",'-'), magnet_links


def download_anime(url, batch=False, stop=False, move=False, force=False):
    global dirty

    debug(f"download_anime: {url=}, {batch=} {stop=} {move=}")
    anime_title, magnet_links = get_anime_info(url)
    if anime_title in anime_list:
        if stop:
            del anime_list[anime_title]
            dirty = True
        if not force:
            return
    anime_list[anime_title] = {"link": url}
    dirty = True

    if move:
        push_notify(f"Move anime: {anime_title}")
    else:
        push_notify(f"Download anime: {anime_title}")

    batch_link = []
    episode_link = []
    for link in magnet_links:
        if re.search(BATCH_PATTERN, unquote(link)):
            batch_link.append(link)
        elif get_title_ep(unquote(link))[1] != None:
            episode_link.append(link)

    if batch:
        download_torrents(anime_title, batch_link, move)
    else:
        download_torrents(anime_title, episode_link, move)


def download_torrents(title, links, move=False):
    if DRY_RUN:
        return

    if isinstance(links, str):
        links = [links]

    deluge = deluge_client.DelugeRPCClient("mypi", 58846, "kotori", "123456")
    deluge.connect()
    torrents_dict = deluge.core.get_torrents_status({}, ["name"])

    download_path = os.path.join(DOWNLOAD_FOLDER, title)
    download_options = {
        "add_paused": False,
        "download_location": download_path,
    }
    hash_list = [magnet_to_hash(i) for i in links]

    deluge.core.move_storage(
        [i for i in hash_list if i in torrents_dict], download_path
    )
    if not move:
        for link in links:
            if magnet_to_hash(link) not in torrents_dict:
                _, ep = get_title_ep(link)
                info(f"Download {title} Episode {ep}")
                deluge.core.add_torrent_magnet(link, download_options)
    deluge.disconnect()


def push_notify(noti):
    debug(f"Notify - {noti}")
    push_data = {"type": "note", "title": "Anime Download Service", "body": noti}

    headers = {"Access-Token": API_KEY, "Content-Type": "application/json"}
    try:
        requests.post(PUSHBULLET_API_URL, headers=headers, json=push_data)
    except Exception as e:
        info("Send push notify fail.")


def load_list():
    global anime_list
    with open(anilist_file_path, "r") as anilist_file:
        anime_list = yaml.load(anilist_file, Loader=yaml.FullLoader)


def write_list():
    with open(anilist_file_path, "w") as anilist_file:
        yaml.dump(anime_list, anilist_file)


rss_last_check = 0
pb_last_check = 0
pb_last_success = time.time()
dirty = False
seen_entry_ids = set()
anime_list = dict()
# check_rss(True)

config_folder = os.path.expanduser("~/.config/anime_download_service")
os.makedirs(config_folder, exist_ok=True)
anilist_file_path = os.path.join(config_folder, "animelist.yaml")
config_file_path = os.path.join(config_folder, "config.yaml")

if os.path.exists(anilist_file_path):
    load_list()
    tmp = anime_list
    anime_list = dict()
    for key, value in tmp.items():
        new_key = key.replace("–",'-')
        anime_list[new_key] = value
write_list()

if os.path.exists(config_file_path):
    with open(config_file_path, "r") as config_file:
        config = yaml.load(config_file, Loader=yaml.FullLoader)
        API_KEY = config["apikey"]
else:
    info("config.yaml not found")
    exit()

while True:
    current_time = time.time()
    if current_time - pb_last_check >= PUSHBULLET_CHECK_INTERVAL:
        load_list()
        pb_last_success = check_for_push(pb_last_success)
        pb_last_check = current_time
        if dirty:
            write_list()
            dirty = False

    current_time = time.time()
    if current_time - rss_last_check >= RSS_CHECK_INTERVAL:
        load_list()
        check_rss()
        rss_last_check = current_time

    time.sleep(1)
