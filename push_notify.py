#!/usr/bin/python3.9
import os
import yaml
import requests
from sys import argv
from syslog import syslog

PUSHBULLET_API_URL = "https://api.pushbullet.com/v2/pushes"

syslog(f"Start send push notify. {argv}")

config_folder = os.path.expanduser("~/.config/anime_download_service")
config_file_path = os.path.join(config_folder, "config.yaml")

if os.path.exists(config_file_path):
    with open(config_file_path, "r") as config_file:
        config = yaml.load(config_file, Loader=yaml.FullLoader)
        API_KEY = config["apikey"]
else:
    syslog("config.yaml not found")
    exit()

for arg in argv[1:]:
    syslog(arg)


push_data = {"type": "note", "title": "Anime Download Service", "body": f"Downloaded - {argv[2]}"}

headers = {"Access-Token": API_KEY, "Content-Type": "application/json"}
try:
    requests.post(PUSHBULLET_API_URL, headers=headers, json=push_data)
except Exception as e:
    syslog("Send push notify fail.")