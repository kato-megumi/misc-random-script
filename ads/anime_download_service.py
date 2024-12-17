import base64
import hashlib
import bencodepy
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from urllib.parse import unquote, urlparse, parse_qs, urljoin
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
import timeout_decorator

# Constants
API_KEY = "------------------------------"
PUSHBULLET_API_URL = "https://api.pushbullet.com/v2/pushes"
RSS_FEED_URL = "https://subsplease.org/rss/?r=1080"
PUSHBULLET_CHECK_INTERVAL = 5
RSS_CHECK_INTERVAL = 10
DOWNLOAD_FOLDER = "/media/pi/Drive/"
DRY_RUN = "dryrun" in os.environ
PATTERN = r"\[(.*?)\] (.*?) - (\d+(?:\.\d+)?)v?(\d*) \(1080p\) \[.*?\]\.mkv"
FALLBACK_PATTERN = r"\[.*?\]\s(.*?)\s-\s(.*?)\s\(.*?\)\s\[.*?\]\.mkv"
BATCH_PATTERN = r"\[(.*?)\] (.*?) \((\d+(?:-\d+)?)\) \(1080p\) \[Batch\]"
GENERIC_PATTERN = r"(.*?) - (\d+(?:\.\d+)?v?\d*)"
DELUGE_SERVER = os.environ.get("DELUGE_SERVER", "127.0.0.1")
SERVICE_NAME = "Anime Download Service"

# Global variables
torrents_dict = {}

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

    @timeout_decorator.timeout(300)
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
            query_time = self.last_success
            self.last_success = current_time
            for push in pushes:
                if push.get("title", "") != SERVICE_NAME and push["created"] >= query_time:
                    created = datetime.datetime.fromtimestamp(push["created"]).strftime('%F %T.%f')[:-3]
                    modified = datetime.datetime.fromtimestamp(push["modified"]).strftime('%F %T.%f')[:-3]
                    query_time_fmt = datetime.datetime.fromtimestamp(query_time).strftime('%F %T.%f')[:-3]
                    info(f"Pushbullet: Created: {created} Modified: {modified} Body: \"{push.get("body", "")}\" Url: \"{push.get("url", "")}\" Query time: {query_time_fmt}")
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

    @timeout_decorator.timeout(300)
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
    def __init__(self, rss_link, title="", torrent_type="Anime"):
        self.rss_link = rss_link
        self.title = title
        self.torrent_type = torrent_type
        self.episode = []


class Generic:
    def __init__(self, dry_run=False):
        self.list_item = []
        self.dry_run = dry_run
        self.seen_entry_ids = set()
        self.load_list()

    def add_item(self, rss_link, torrent_type="Anime"):
        if any(rss_link == item.rss_link for item in self.list_item):
            return
        self.list_item.append(GenericItem(rss_link, torrent_type=torrent_type))
        self.write_list()

    @timeout_decorator.timeout(300)
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
                    if item.torrent_type == "Anime":
                        title, ep = get_generic_title_ep(name)
                        if ep != None:
                            if ep in item.episode:
                                continue
                            else:
                                item.episode.append(ep)
                                self.write_list()
                        if item.title == "":
                            item.title = title
                            self.write_list()
                    else:
                        title = name
                    if self.dry_run:
                        continue
                    link = entry.get("link", "")
                    info(f"New item in RSS. Prepare to download - Title: {name}")
                    download_torrents(title, link, torrentType=item.torrent_type)

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
        debug("Pushbullet handle command")
        if "body" not in push:
            return
        try:
            command, target, *args = push["body"].split()
        except:
            return
        if any(command == c for c in ["list", "ls", "l"]):
            if any(target == c for c in ["gen", "generic", "g"]):
                push_notify("\n".join([f"{index+1}. {parse_qs(urlparse(item.rss_link).query)['q'][0]} - {item.torrent_type} - {item.title}"
                                       for index, item in enumerate(generic.list_item)]))
                return
        if any(command == c for c in ["del", "delete", "rm", "remove", "d", "r"]):
            if target == "gen" or target == "generic":
                args = [int(i) for i in args if i.isdigit()]
                for arg in args:
                    del generic.list_item[arg-1]
                generic.write_list()
                push_notify("\n".join([f"{index+1}. {parse_qs(urlparse(item.rss_link).query)['q'][0]}"
                                       for index, item in enumerate(generic.list_item)]))
                return
        return
    link = push["url"]
    debug(f"Pushbullet Receive {link}")
    if "https://subsplease.org/shows" in link:
        if "body" in push:
            actions = {"batch": "batch", "move": "move_only", "stop": "stop", "force": "force"}
            for key, value in actions.items():
                if key in push["body"]:
                    download_anime(link, **{value: True})
                    return
        download_anime(link)
    elif any(path in link for path in ["https://nyaa.si/?", "https://sukebei.nyaa.si/?", "https://nyaa.si/user/", "https://sukebei.nyaa.si/user/"]):
        if "page=rss" not in link:
            response = requests.get(link)
            if response.status_code != 200:
                warning(f"Failed to fetch torrent page {link}")
                return
            soup = BeautifulSoup(response.content, 'html.parser')
            link = urljoin(link, soup.find('a', {'href': lambda x: x and "page=rss" in x})['href'])
        # Determine the torrent type based on body of the push
        torrent_type = "iso" if "sukebei" in link else "Anime"
        if "body" in push:
            if "Game" in push["body"] or "game" in push["body"]:
                torrent_type = "Game"
            if "Manga" in push["body"] or "manga" in push["body"]:
                torrent_type = "Manga"
            elif "iso" in push["body"]:
                torrent_type = "iso"
        generic.add_item(link, torrent_type)
    elif "https://nyaa.si/view/" in link or "https://sukebei.nyaa.si/view/" in link:
        try:
            response = requests.get(link)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            torrent_tag = soup.find('a', {'href': lambda x: x and x.endswith('.torrent')})
            if torrent_tag:
                torrent_link = urljoin(link, torrent_tag['href'])
            else:
                torrent_link = soup.find('a', {'href': lambda x: x and x.startswith('magnet:')})['href']
            title = soup.find('h3', {'class': 'panel-title'}).text.strip()
            category = soup.find_all('a', {'href': lambda x: x and x.startswith('/?c')})[-1].text.strip()
            file_list_section = soup.find('div', {'class': 'torrent-file-list'})
            debug(f"Handle nyaa.si/view - {title=} - {category=} - {torrent_link=}")
            if "Game" in category:
                # Determine the torrent type based on the presence of .exe files in the file list section
                torrent_type = "Game" if file_list_section and any(".exe" in file.text for file in file_list_section.find_all('li')) else "iso"
                download_torrents(remove_frill(title), torrent_link, torrentType=torrent_type)
        except Exception as e:
            warning(f"Fail to handle nyaasi link {link} with error: {e}")
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
        return match.group(1), match.group(2)
    else:
        return None, None


def magnet_to_hash(magnet):
    query_params = parse_qs(urlparse(magnet).query)
    if "xt" not in query_params:
        return None
    xt_value = query_params.get("xt", [])[0].split(":")[-1]
    if len(xt_value) == 40:
        return xt_value.encode('utf-8')
    return b32decode(xt_value).hex().encode('utf-8')


def links_to_hashs(links):
    for link in links:
        if link.startswith("magnet:"):
            yield (magnet_to_hash(link), {"link": link})
        elif link.endswith(".torrent"):
            response = requests.get(link)
            if response.status_code != 200:
                warning(f"Failed to download the torrent file {link}")
                continue
            torrent_data = bencodepy.decode(response.content)
            torrent_info = bencodepy.encode(torrent_data[b'info'])
            info_hash = hashlib.sha1(torrent_info).hexdigest().encode('utf-8')
            name = torrent_data[b'info'][b'name'].decode('utf-8')
            content = base64.b64encode(response.content)
            yield (info_hash,
                {"link": link, "content": content, "name": name})


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


def download_anime(url, batch=False, stop=False, move_only=False, force=False):
    debug(f"download_anime(): {url=}, {batch=} {stop=} {move_only=}")
    anime_title, magnet_links = get_anime_info(url)
    if anime_title is None:
        push_notify(f"Get NoneType title")
        warning(f"Get NoneType title")

    if anime_title in anime_list:
        if stop:
            del anime_list[anime_title]
            write_list()
        if not (force or move_only):
            return
    anime_list[anime_title] = {"link": url}
    write_list()

    if move_only:
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
        download_torrents(anime_title, batch_link, move_only=move_only, move=True)
    else:
        download_torrents(anime_title, episode_link, move_only=move_only, move=True)


def download_torrents(title, links, move_only=False, move=False, torrentType="Anime"):
    if DRY_RUN:
        return

    global torrents_dict
    torrent_id = []

    if not isinstance(links, list):
        links = [links]

    hashs_dict = dict(links_to_hashs(links))
    debug(f"download_torrents() {title=} - {hashs_dict=}")
    hashs_dict = {k: v for k, v in hashs_dict.items() if k not in torrents_dict}
    debug(f"download_torrents() removed exist - {hashs_dict=}")
    if not hashs_dict:
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
    existed_hashs = [k for k in hashs_dict if k in torrents_dict]
    hashs_dict = {k: v for k, v in hashs_dict.items() if k not in torrents_dict}

    try:
        download_path = os.path.join(
            DOWNLOAD_FOLDER, torrentType,
            *(title,) if torrentType == "Anime" else ())
    except:
        warning(f"Failed to create download path. {title=} {torrentType=}")
        push_notify(f"Failed to create download path.")
        deluge.disconnect()
        return
    download_options = {
        "add_paused": False,
        "download_location": download_path,
    }

    if move and existed_hashs:
        deluge.core.move_storage(existed_hashs, download_path)

    if not hashs_dict:
        deluge.disconnect()
        return

    if not move_only:
        for torrent_info in hashs_dict.values():
            link = torrent_info["link"]
            if "content" not in torrent_info: # magnet link
                _, ep = get_title_ep(unquote(link))
                info(f"Started download {title} - Episode {ep}")
                torrent_id.append(deluge.core.add_torrent_magnet(link, download_options))
            else: # torrent file
                name = torrent_info.get("name")
                old_name = name
                if name.isdigit():
                    name = title
                    download_options["name"] = title
                info(f"Started download {name}")
                try:
                    torrent_id.append(deluge.core.add_torrent_file(link, torrent_info["content"], download_options))
                    if old_name.isdigit():
                        deluge.core.rename_folder(torrent_id[-1], old_name, name)
                except:
                    info(f"Failed to download {name}, possibly because already downloaded")
    deluge.disconnect()
    return torrent_id


def push_notify(noti):
    debug(f"Notify - {noti}")
    push_data = {"type": "note", "title": SERVICE_NAME, "body": noti}

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


def remove_extension(file_name):
    name, ext = os.path.splitext(file_name)
    if len(ext) in [4, 5] and ext[1:].isalnum() :  # including the dot, extensions will have length 4 or 5
        return name
    return file_name


def remove_bracket(text):
    pattern = r"\[.*?\]|\(.*?\)|\│.*?\│|\（.*?\）"
    return re.sub(pattern, "", text)


def remove_frill(text):
    return remove_extension(remove_bracket(text)).strip()


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
info("============== Service started ==============")

while True:
    schedule.run_pending()
    time.sleep(1)
