import csv
import json
import urllib.request
from urllib.request import urlopen, Request
import lxml
from bs4 import BeautifulSoup
import os
import time
from time import sleep
import requests

import pickle
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from datetime import datetime


# too lazy to split into modules, so just gonna use one script for everything :)
DEBUG = True
STATUS_UPDATES = True
PAGE_LIMIT = 1000
FILE_NAME = "raw_pp.json"
# time in seconds
WAIT_BETWEEN_LEADERBOARD_CALLS = 1
WAIT_BETWEEN_API_CALLS = 1
BACKOFF_TIME = 60 * 10
songs_calculated = 0

fields = ["Name", "Mapper", "Difficulty", "Star", "Player", "Acc", "Date"]

SHEET_NAME = "numberones.csv"

SHEET_ID = "1c9ZNa5G4o9DI54W4gh_97JmwscoErLz0L0yyH1to2dQ"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

MAIN_RANGE = "Main!A2:G"
TIME_RANGE = "Info!B1"

SCORE_SABER_URL = "https://new.scoresaber.com"
URL_PREFIX = SCORE_SABER_URL + "/api/player/"
URL_RANKED = "/scores/top/"

class RankedMap:
    def __init__(self, name, mapper, difficulty):
        self.name = name
        self.mapper = mapper
        self.difficulty = difficulty

def sleep_until(sleep_time):
    current_time = datetime.now().timestamp()
    if (sleep_time < current_time):
        return
    print("Sleeping for {} seconds".format(sleep_time - current_time + 1))
    time.sleep(sleep_time - current_time + 1)
    print("Done sleeping")

def get_response_rate_limited(url):
    response = requests.get(url)
    if "x-ratelimit-remaining" not in response.headers:
        return response
    # Fuzzing this a bit cause otherwise it rate limits early
    if (int(response.headers["x-ratelimit-remaining"])) <= 2:
        sleep_until(int(response.headers["x-ratelimit-reset"]))
    return response

# strip extraneous data from scoresaber difficulty
def get_diff(difficulty):
    return difficulty[1:difficulty.rfind("_")]

def get_number_ones(id):
    url = URL_PREFIX + str(id) + URL_RANKED
    page = 1
    done = False
    l = []
    while not done:
        response = get_response_rate_limited(url + str(page))
        for song in response.json()["scores"]:
            if song["pp"] <= 0:
                done = True
                break

            if song["rank"] == 1:
                l.append((song["songName"], song["levelAuthorName"], get_diff(song["difficultyRaw"]), song["timeSet"]))
        page+=1
    return l

def open_url(url):
    done = False
    while not done:
        try:
            response = urlopen(urllib.request.Request(url, headers={"User-Agent": "ScoreSaber Ranked #1s Tracker"}))
            done = True
        # back off, sleep for 10 minutes
        except Exception as e:
            if DEBUG:
                print("Ran into error opening url: " + url + ", sleeping for 10 minutes")
                print(e)
            sleep(BACKOFF_TIME)
    return response

# write the json data to the output file
def write_data(data, file):
    with open(file, "w") as output:
        json.dump(data, output)

def find_number_one(html):
    soup = BeautifulSoup(html, "lxml")

    percentages = soup.findAll("td", {"class": "percentage"})
    percentage = float(percentages[0].text.strip()[:-1])

    players = soup.findAll("span", {"class": "songTop pp"})
    playerName = str(players[0])[str(players[0]).find("> ") + 2:str(players[0]).find("</span>")]

    players = soup.findAll("td", {"class": "player"})
    # print(players[0])
    delim = "href=\""
    pid = str(players[0])[str(players[0]).find(delim) + len(delim):]
    pid = pid[:pid.find("\"")]
    playerLink = "https://scoresaber.com" + pid

    player = "=HYPERLINK(\"" + playerLink + "\", \"" + playerName + "\")"

    return player, percentage

def get_song_data(song):
    uid = song["uid"]
    
    url = "https://scoresaber.com/leaderboard/" + str(uid)
    try:
        return find_number_one(open_url(url).read())
    except Exception as e:
        print("ERROR: Couldn't get info for " +  song["name"] + " - " + str(song["id"]) + ": " + url + " " +  str(e))
        return []

# get the data for all the songs returned in the api call
def get_data(response):
    global songs_calculated
    done = False
    data = []
    api_data = json.load(response)
    # stop once every song has been gathered or song we already scraped data for
    for song in api_data["songs"]:
        # skipped unranked songs
        if song["ranked"] == 1:
            songs_calculated+=1
            songInfo = []
            uid = song["uid"]
            url = "https://scoresaber.com/leaderboard/" + str(uid)
            songInfo.append("=HYPERLINK(\"" + url + "\", \"" + song["name"] + "\")")
            songInfo.append(song["levelAuthorName"])
            songInfo.append(get_diff(song["diff"]))
            songInfo.append(song["stars"])
            for x in get_song_data(song):
                songInfo.append(x)
            data.append(songInfo)
            print(songs_calculated, ": ", song["name"])
        # back off for a bit
        sleep(WAIT_BETWEEN_LEADERBOARD_CALLS)
    if len(api_data["songs"]) == 0:
        done = True

    return (data, done)

def make_spreadsheet(rows):
    with open(SHEET_NAME, "w", encoding="utf-8") as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(fields)
        csvwriter.writerows(rows)

def update_spreadsheet(rows):
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('sheets', 'v4', credentials=creds)

    current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") + " UTC"
    data = [
        {
            'range': MAIN_RANGE,
            'values': rows
        }
    ]
    body = {
        'valueInputOption': 'USER_ENTERED',
        'data': data
    }

    sheet = service.spreadsheets()
    sheet.values().clear(spreadsheetId=SHEET_ID,
                                range=MAIN_RANGE).execute()
    sheet.values().batchUpdate(spreadsheetId=SHEET_ID,
                                body=body).execute()

    body = {
        'values': [[current_time]]
    }
    sheet.values().update(spreadsheetId=SHEET_ID, range=TIME_RANGE,
                            valueInputOption="RAW", body=body).execute()

def decode_id(hyperlink):
    hyperlink = hyperlink[hyperlink.find("\"") + 1:]
    hyperlink = hyperlink[:hyperlink.find("\"")]
    hyperlink = hyperlink[hyperlink.rfind("/") + 1:]
    return hyperlink

def decode_player(hyperlink):
    hyperlink = hyperlink[:hyperlink.rfind("\"")]
    hyperlink = hyperlink[hyperlink.rfind("\"") + 1:]
    return hyperlink

def decode_song(hyperlink):
    hyperlink = hyperlink[:hyperlink.rfind("\"")]
    hyperlink = hyperlink[hyperlink.rfind("\"") + 1:]
    return hyperlink

def get_date(unfiltered_date):
    return unfiltered_date[:unfiltered_date.find("T")]

def get_dates(data):
    players = set()
    for song in data:
        # print(song)
        hyperlink = song[4]
        players.add((decode_player(hyperlink), decode_id(hyperlink)))
    print(players)
    playerRankedOnes = {}
    for player in players:
        playerRankedOnes[player[0]] = get_number_ones(player[1])
    for song in data:
        player = decode_player(song[4])
        for numberone in playerRankedOnes[player]:
            if numberone[0] == decode_song(song[0]) and numberone[1] == song[1] and numberone[2] == song[2]:
                song.append(get_date(numberone[3]))
    return data

def main():
    data = []

    done = False
    page = 1
    while not done:
        url = "http://scoresaber.com/api.php?function=get-leaderboards&cat=1&page=" + str(page) + "&limit=" + str(PAGE_LIMIT) +"&ranked=1"
        response = open_url(url)
        a = get_data(response)
        done = a[1]
        for x in a[0]:
            data.append(x)
        # back off for a bit
        sleep(WAIT_BETWEEN_API_CALLS)
        page+=1

    data = get_dates(data)
    return data

if __name__ == "__main__":
    # data = main()
    # make_spreadsheet(data)
    update_spreadsheet(main())