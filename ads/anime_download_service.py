import base64
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
import schedule
import logging
from logging import debug, info, warning
from bs4 import BeautifulSoup

API_KEY = "------------------------------"
PUSHBULLET_API_URL = "https://api.pushbullet.com/v2/pushes"
RSS_FEED_URL = "https://subsplease.org/rss/?r=1080"
PUSHBULLET_CHECK_INTERVAL = 5
RSS_CHECK_INTERVAL = 10
DOWNLOAD_FOLDER = "/media/pi/Drive/"
DRY_RUN = "dryrun" in os.environ
DEBUG = "debug" in os.environ
PATTERN = r"\[(.*?)\] (.*?) - (\d+(?:\.\d+)?)v?(\d*) \(1080p\) \[.*?\]\.mkv"
FALLBACK_PATTERN = r"\[.*?\]\s(.*?)\s-\s(.*?)\s\(.*?\)\s\[.*?\]\.mkv"
BATCH_PATTERN = r"\[(.*?)\] (.*?) \((\d+(?:-\d+)?)\) \(1080p\) \[Batch\]"
GENERIC_PATTERN = r"(.*?) - (\d+(?:\.\d+)?)v?(\d*)"
DELUGE_SERVER = os.environ.get("DELUGE_SERVER", "127.0.0.1")

log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ads.log")
LOGLEVEL = os.environ.get("LOGLEVEL", "INFO").upper()
logging.basicConfig(
    filename=log_file,
    encoding="utf-8",
    level=LOGLEVEL,
    format="%(asctime)s %(message)s",
)

### Todo
# deal with version
# reduce ram usage

class Pushbullet:
    def __init__(self, api_key):
        self.last_success = time.time()
        self.headers = {
            "Access-Token": api_key,
        }

    def get_ratelimit(self, headers):
        if "X-RateLimit-Remaining" in headers:
            remain = headers["X-RateLimit-Remaining"]
            total = headers["X-RateLimit-Limit"]
            until = datetime.datetime.fromtimestamp(
                float(headers["X-RateLimit-Reset"])
            ).strftime("%Y-%m-%d %H:%M:%S")
            return remain, total, until

    def check_for_push(self):
        current_time = time.time()
        failed = False
        try:
            response = requests.get(
                PUSHBULLET_API_URL,
                headers=self.headers,
                params={"modified_after": str(int(self.last_success))},
                timeout=10,
            )
        except requests.exceptions.HTTPError as http_e:
            remain, total, until = self.get_ratelimit(response.headers)
            debug(f"Remain {remain}/{total} units, until {until}")
            info("Check for push HTTPError")
            failed = True
        except Exception as e:
            info(f"Check for push error: {e}")
            failed = True

        if not failed and response.status_code == 200:
            pushes = response.json()["pushes"]
            self.last_success = current_time
            for push in pushes:
                push_handle(push)
        else:
            try:
                warning(f"Status code {response.status_code}")
            except Exception as e:
                pass
            warning("Check for push failed")


class Rss:
    def __init__(self, dry_run=False):
        self.seen_entry_ids = set()
        self.dry_run = dry_run

    def check_rss(self):
        try:
            feed = feedparser.parse(RSS_FEED_URL)
        except Exception as e:
            info("Check RSS Error")
            return
        for entry in feed.entries:
            entry_id = entry.get("id", "")
            if entry_id not in self.seen_entry_ids:
                self.seen_entry_ids.add(entry_id)
                if self.dry_run:
                    continue
                rss_title = entry.get("title", "")
                link = entry.get("link", "")
                title, ep = get_title_ep(rss_title)
                debug(f"RSS - Title: {title} - Episode: {ep}")
                if title != None and (title in anime_list):
                    info(f"New episode in RSS. Prepare to download - Title: {title} - Episode: {ep}")
                    download_torrents(title, link)


class GenericItem:
    def __init__(self, rss_link, title="", type="Anime"):
        self.rss_link = rss_link
        self.title = title
        self.type = type


class Generic:
    def __init__(self, dry_run=False):
        self.list_item = []
        self.dry_run = dry_run
        self.seen_entry_ids = set()
        self.load_list()

    def add_item(self, rss_link):
        self.list_item.append(GenericItem(rss_link))
        self.write_list()

    def check_rss(self):
        for item in self.list_item:
            try:
                feed = feedparser.parse(item.rss_link)
            except Exception as e:
                warning(f"Check RSS Error {item.rss_link}")
                return
            for entry in feed.entries:
                entry_id = entry.get("id", "")
                if entry_id not in self.seen_entry_ids:
                    self.seen_entry_ids.add(entry_id)
                    name = remove_frill(entry.get("title", ""))
                    title, _ = get_generic_title_ep(name)
                    if item.title == "":
                        item.title = title
                        push_notify(f"Download: {title}")
                    if self.dry_run:
                        continue
                    link = entry.get("link", "")
                    info(f"New item in RSS. Prepare to download - Title: {name}")
                    download_torrents(item.title, link)

    def load_list(self):
        if os.path.exists(generic_list_file_path):
            with open(generic_list_file_path, "r") as generic_file:
                self.list_item = yaml.unsafe_load(generic_file)
        else:
            self.write_list()

    def write_list(self):
        with open(generic_list_file_path, "w") as generic_file:
            yaml.dump(self.list_item, generic_file)


def push_handle(push):
    if "url" not in push:
        return
    link = push["url"]
    debug(f"Receive {link}")
    if "https://subsplease.org/shows" in link:
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
    elif "https://nyaa.si/?" in link or "https://sukebei.nyaa.si/?" in link:
        if "page=rss" in link:
            generic.add_item(link)
        else:
            generic.add_item(link + "&page=rss")
    elif "https://nyaa.si/view/" in link or "https://sukebei.nyaa.si/view/" in link:
        try:
            response = requests.get(link)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            magnet_link = soup.find('a', {'href': lambda x: x and x.startswith('magnet:')})['href']
            title = soup.find('h3', {'class': 'panel-title'}).text.strip()
            category = soup.find_all('a', {'href': lambda x: x and x.startswith('/?c')})[-1].text.strip()
            file_list_section = soup.find('div', {'class': 'torrent-file-list'})
            file_list = file_list_section.find_all('li')
            file_names = ''.join([file.text.strip() for file in file_list])
            if "Game" in category:
                if ".exe" in file_names:
                    download_torrents(title, magnet_link, torrentType="Game")
                else:
                    download_torrents(title, magnet_link, torrentType="iso")
        except Exception as e:
            warning(f"Fail to handle nyaasi link with error: {e}")
            push_notify("Fail to handle nyaasi link")


def get_title_ep(name):
    match = re.search(PATTERN, name)
    if match:
        return match.group(2), match.group(3)
    else:
        match = re.match(FALLBACK_PATTERN, name)
        if match:
            return match.group(1), match.group(2)
        else:
            return None, None


def get_generic_title_ep(name):
    match = re.search(GENERIC_PATTERN, name)
    if match:
        return match.group(1), match.group(2) + match.group(3)
    else:
        return None, None


def magnet_to_hash(magnet):
    query_params = parse_qs(urlparse(magnet).query)
    if "xt" not in query_params:
        return None
    xt_value = query_params.get("xt", [])[0].split(":")[-1]
    if len(xt_value) == 40:
        return bytes(xt_value)
    return bytes(b32decode(xt_value).hex(), encoding="ascii")


def get_anime_info(url):
    options = webdriver.FirefoxOptions()
    options.add_argument("--headless")
    with webdriver.Firefox(options=options) as driver:
        driver.get(url)
        # Set a maximum wait time (in seconds)
        wait = WebDriverWait(driver, 10)
        # Wait until an Episode appears
        try:
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "episode-title")))
        except:
            pass

        magnet_links = [
            i.get_attribute("href")
            for i in driver.find_elements(
                By.XPATH, "//a[starts-with(@href, 'magnet:')]"
            )
        ]
        magnet_links = [i for i in magnet_links if "1080p" in unquote(i)]
        anime_title = driver.find_element(By.CLASS_NAME, "entry-title").text
        for magnet_link in magnet_links:
            anime_title2, _ = get_title_ep(unquote(magnet_link))
            if anime_title2 != None:
                break
        if anime_title != anime_title2:
            info(f"get diffrent title: {anime_title} {anime_title2}")
    return anime_title2, magnet_links


def download_anime(url, batch=False, stop=False, move=False, force=False):
    debug(f"download_anime(): {url=}, {batch=} {stop=} {move=}")
    anime_title, magnet_links = get_anime_info(url)
    if anime_title in anime_list:
        if stop:
            del anime_list[anime_title]
            write_list()
        if not force:
            return
    anime_list[anime_title] = {"link": url}
    write_list()

    if move:
        push_notify(f"Move anime: {anime_title}")
    else:
        push_notify(f"Download anime: {anime_title}")

    batch_link = []
    episode_link = []
    for link in magnet_links:
        if re.search(BATCH_PATTERN, unquote(link)):
            batch_link.append(link)
        else:
            episode_link.append(link)

    if batch:
        download_torrents(anime_title, batch_link, move)
    else:
        download_torrents(anime_title, episode_link, move)


def download_torrents(title, links, move=False, torrentType="Anime"):
    if DRY_RUN:
        return

    if isinstance(links, str):
        links = [links]

    deluge = deluge_client.DelugeRPCClient(DELUGE_SERVER, 58846, "kotori", "123456")
    try:
        deluge.connect()
    except:
        warning(f"Failed to connect to deluge. Title: {title}")
        push_notify(f"Failed to connect to deluge. Title: {title}")
        return
    
    torrents_dict = deluge.core.get_torrents_status({}, ["name"])

    if torrentType=="Anime":
        download_path = os.path.join(DOWNLOAD_FOLDER, torrentType, title)
    else:
        download_path = os.path.join(DOWNLOAD_FOLDER, torrentType)
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
            if link.startswith("magnet:"):
                if magnet_to_hash(link) not in torrents_dict:
                    _, ep = get_title_ep(unquote(link))
                    info(f"Started download {title} - Episode {ep}")
                    deluge.core.add_torrent_magnet(link, download_options)
            else:
                if link.endswith(".torrent"):
                    response = requests.get(link)
                    if response.status_code != 200:
                        warning(f"Failed to download the torrent file {link}")
                    else:
                        encoded_content = base64.b64encode(response.content)
                        info(f"Started download {link}")
                        # TODO: pass torrent data to download_torrents()
                        try:
                            deluge.core.add_torrent_file(link, encoded_content, download_options) 
                        except:
                            info(f"Failed to download {link}, possibly because already downloaded")
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
    with open(anilist_file_path, "r") as anilist_file:
        anime_list = yaml.load(anilist_file, Loader=yaml.Loader)
    return anime_list


def write_list():
    with open(anilist_file_path, "w") as anilist_file:
        yaml.dump(anime_list, anilist_file)


def remove_bracket(text):
    pattern = r"\[.*?\]"
    return re.sub(pattern, "", text)


def remove_frill(text):
    return os.path.splitext(
        remove_bracket(text).replace("(1080p)", "").replace("(720p)", "")
    )[0].strip()


seen_entry_ids = set()
anime_list = dict()

config_folder = os.path.expanduser("~/.config/anime_download_service")
os.makedirs(config_folder, exist_ok=True)
anilist_file_path = os.path.join(config_folder, "animelist.yaml")
config_file_path = os.path.join(config_folder, "config.yaml")
generic_list_file_path = os.path.join(config_folder, "generic.yaml")

if os.path.exists(anilist_file_path):
    tmp = load_list()
    anime_list = dict()
    for key, value in tmp.items():
        new_key = key.replace("–", "-")
        anime_list[new_key] = value
write_list()

if os.path.exists(config_file_path):
    with open(config_file_path, "r") as config_file:
        config = yaml.load(config_file, Loader=yaml.FullLoader)
        API_KEY = config["apikey"]
else:
    info("config.yaml not found")
    exit()

pb = Pushbullet(API_KEY)
rss = Rss(DRY_RUN)
generic = Generic(DRY_RUN)

schedule.every(PUSHBULLET_CHECK_INTERVAL).seconds.do(pb.check_for_push)
schedule.every(RSS_CHECK_INTERVAL).seconds.do(rss.check_rss)
schedule.every(RSS_CHECK_INTERVAL).seconds.do(generic.check_rss)

while True:
    schedule.run_pending()
    time.sleep(1)
