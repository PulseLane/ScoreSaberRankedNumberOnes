import csv
import json
import urllib.request
from urllib.request import urlopen, Request
import lxml
from bs4 import BeautifulSoup
import os
from time import sleep

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
WAIT_BETWEEN_API_CALLS = 5
BACKOFF_TIME = 60 * 10
songs_calculated = 0

fields = ["Name", "Mapper", "Difficulty", "Star", "Player", "Acc"]

SHEET_NAME = "numberones.csv"

SHEET_ID = "1c9ZNa5G4o9DI54W4gh_97JmwscoErLz0L0yyH1to2dQ"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

MAIN_RANGE = "Main!A2:F"
TIME_RANGE = "Info!B1"

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

# strip extraneous data from scoresaber difficulty
def get_diff(difficulty):
    return difficulty[1:difficulty.rfind("_")]

# write the json data to the output file
def write_data(data, file):
    with open(file, "w") as output:
        json.dump(data, output)

def find_number_one(html):
    soup = BeautifulSoup(html, "lxml")

    percentages = soup.findAll("td", {"class": "percentage"})
    percentage = float(percentages[0].text.strip()[:-1])

    players = soup.findAll("span", {"class": "songTop pp"})
    player = str(players[0])[str(players[0]).find("> ") + 2:str(players[0]).find("</span>")]

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
            songInfo.append(song["name"])
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
        'valueInputOption': 'RAW',
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
        url = "http://scoresaber.com/api.php?function=get-leaderboards&cat=1&page=" + str(page) + "&limit=" + str(PAGE_LIMIT) +"&ranked=1"
        response = open_url(url)
        a = get_data(response)
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