import csv
import json
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
WAIT_BETWEEN_RESPONSE_ERROR = 30
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
    # print("Done sleeping")

def get_response_rate_limited(url):
    count = 0
    MAX_COUNT = 10
    while count < MAX_COUNT:
        try:
            response = requests.get(url)
            if "x-ratelimit-remaining" not in response.headers:
                return response
            # Fuzzing this a bit cause otherwise it rate limits early
            if (int(response.headers["x-ratelimit-remaining"])) <= 2:
                sleep_until(int(response.headers["x-ratelimit-reset"]))
            return response
        except:
            print("Ran into error getting response, sleeping for {} seconds".format(WAIT_BETWEEN_RESPONSE_ERROR))
            time.sleep(WAIT_BETWEEN_RESPONSE_ERROR)
            count+=1
    raise Exception("Error getting response from {}".format(url))

def get_date(unfiltered_date):
    return unfiltered_date[:unfiltered_date.find("T")]

def find_number_one(leaderboard, maxScore):
    numberone = leaderboard["scores"][0]
    percentage = round(numberone["modifiedScore"] / (maxScore * numberone["multiplier"]) * 100, 2)
    playerName = numberone["leaderboardPlayerInfo"]["name"]
    pid = numberone["leaderboardPlayerInfo"]["id"]
    playerLink = "https://scoresaber.com/u/" + pid

    player = "=HYPERLINK(\"" + playerLink + "\", \"" + get_hyperlink_friendly(playerName) + "\")"
    date = get_date(numberone["timeSet"])

    return player, percentage, date


# strip extraneous data from scoresaber difficulty
def get_diff(difficulty):
    return difficulty[1:difficulty.rfind("_")]

def get_hyperlink_friendly(s):
    return s.replace('"', '""')

def get_number_ones(id, rankOnes):
    url = URL_PREFIX + str(id) + URL_RANKED
    page = 1
    done = False
    l = []
    while not done:
        try:
            response = get_response_rate_limited(url + str(page))
            for song in response.json()["scores"]:
                if song["pp"] <= 0:
                    done = True
                    break

                if song["leaderboardId"] in rankOnes:
                    l.append((song["leaderboardId"], song["timeSet"]))
                    if len(rankOnes) == len(l):
                        done = True
            page+=1
        except json.decoder.JSONDecodeError as e:
            print("Error with response, trying again in {} seconds: {}".format(WAIT_BETWEEN_RESPONSE_ERROR, e))
            time.sleep(WAIT_BETWEEN_RESPONSE_ERROR)
    return l

# write the json data to the output file
def write_data(data, file):
    with open(file, "w") as output:
        json.dump(data, output)

def get_song_data(song):
    id = song["id"]
    
    url = "https://scoresaber.com/api/leaderboard/by-id/" + str(id) + "/scores"
    try:
        response = get_response_rate_limited(url)

        url2 = "https://scoresaber.com/api/leaderboard/by-id/" + str(id) + "/info"
        response2 = get_response_rate_limited(url2)

        return find_number_one(response.json(), response2.json()["maxScore"])
    except Exception as e:
        print("ERROR: Couldn't get info for " +  song["songName"] + " - " + str(song["id"]) + ": " + url + " " +  str(e))
        return []

# get the data for all the songs returned in the api call
def get_data(response):
    global songs_calculated
    done = False
    data = []
    # stop once every song has been gathered or song we already scraped data for
    for song in response["leaderboards"]:
        # skipped unranked songs
        songs_calculated+=1
        songInfo = []
        id = song["id"]
        url = "https://scoresaber.com/leaderboard/" + str(id)
        songInfo.append("=HYPERLINK(\"" + url + "\", \"" + get_hyperlink_friendly(song["songName"] + " " + song["songSubName"]) + "\")")
        songInfo.append(song["levelAuthorName"])
        songInfo.append(get_diff(song["difficulty"]["difficultyRaw"]))
        songInfo.append(song["stars"])
        for x in get_song_data(song):
            songInfo.append(x)
        data.append(songInfo)
        print(songs_calculated, ": ", song["songName"])

    if len(response["leaderboards"]) == 0:
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

def main():
    data = []

    done = False
    page = 1
    while not done:
        url = url = "https://scoresaber.com/api/leaderboards?ranked=1&page=" + str(page)
        response = get_response_rate_limited(url)
        a = get_data(response.json())
        done = a[1]
        for x in a[0]:
            data.append(x)
        # back off for a bit
        sleep(WAIT_BETWEEN_API_CALLS)
        page+=1

    return data

if __name__ == "__main__":
    # data = main()
    # make_spreadsheet(data)
    update_spreadsheet(main())