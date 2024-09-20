from flask import Flask, render_template, url_for, jsonify, Response
from pymongo import MongoClient
from bson import json_util
from datetime import datetime, timedelta
from flask_apscheduler import APScheduler
import requests, time,json, os

app = Flask(__name__)
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()


mongoURI = os.getenv('MONGODB_URI')
client = MongoClient(mongoURI)
db = client.flask_database
events_collection = db.events

last_update_time = None
last_fetched_ids = set()

def fetch_event_ids():
    response = requests.get('https://gameinfo-sgp.albiononline.com/api/gameinfo/events')
    data = response.json()
    return set(event['EventId'] for event in data)

def fetch_event_details(event_id):
    response = requests.get(f'https://gameinfo-sgp.albiononline.com/api/gameinfo/events/{event_id}')
    data = response.json()
    return data

def fetch_and_check_events():
    global last_update_time, last_fetched_ids

    current_ids = fetch_event_ids()
    new_ids = current_ids - last_fetched_ids

    if new_ids:
        for event_id in new_ids:
            try:
                event_details = fetch_event_details(event_id)
                events_collection.update_one(
                    {'EventId': event_details['EventId']},
                    {'$set': event_details},
                    upsert=True,
                )
                print(f"Successfully updated event {event_id}")
            except Exception as e:
                print(f"Error updating event {event_id}: {e}")
        last_fetched_ids = current_ids
        last_update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"Updated {len(new_ids)} new events.")
        return True  # new events found
    else:
        print("No new events found.")
        return False  # nno new events found

@scheduler.task('interval', id='regular_check', seconds=90, misfire_grace_time=900)
def scheduled_update_event():
    with app.app_context():
        if not fetch_and_check_events():
           
            scheduler.add_job(
                func=scheduled_update_event, 
                trigger='date', 
                run_date=datetime.now() + timedelta(seconds=3), 
                id='delayed_event_check',  
                replace_existing=True      
            )

@app.route("/")
@app.route("/home")
def home():
    datas = events_collection.find().sort("TimeStamp", -1).limit(50)
    processed_datas = []
    for event in datas:
        try:
            timestamp = datetime.fromisoformat(event['TimeStamp'].replace('Z', '+00:00'))
        except ValueError:
            timestamp = event['TimeStamp']

        processed_event = {**event, 'TimeStamp': timestamp}
        processed_datas.append(processed_event)
    return render_template('home.html', datas=processed_datas, last_update=last_update_time)

@app.route("/events/<int:event_id>")
def events(event_id):
    data = events_collection.find({'EventId': event_id})
    return render_template('events.html', events=data)

def get_latest_events():
    datas = events_collection.find().sort("TimeStamp", -1).limit(50)
    processed_datas = []
    for event in datas:
        try:
            timestamp = datetime.fromisoformat(event['TimeStamp'].replace('Z', '+00:00'))
        except ValueError:
            timestamp = event['TimeStamp']

        processed_event = {
            'EventId': event['EventId'],
            'TimeStamp': timestamp.strftime('%Y-%m-%d %H:%M:%S') if isinstance(timestamp, datetime) else str(timestamp),
            'KillerName': event['Killer']['Name'],
            'VictimName': event['Victim']['Name']
        }
        processed_datas.append(processed_event)
    return processed_datas

def event_stream():
    while True:
        with app.app_context():
            latest_events = get_latest_events()
            data = {
                'events': latest_events,
                'last_update': last_update_time
            }
            yield f"data: {json.dumps(data)}\n\n"

@app.route('/stream')
def stream():
    return Response(event_stream(), content_type='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), threaded=True)
