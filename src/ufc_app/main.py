from ufc_data_scraper.ufc_scraper import scrape_event_url, scrape_event_fmid, get_event_fmid
from flask import jsonify, request, Response
import os
import requests
from bs4 import BeautifulSoup
from . import app
from datetime import datetime, timedelta
import pytz
import json
import os.path
import threading
import time

# Cache voor UFC events om te voorkomen dat we constant dezelfde data scrapen
EVENT_CACHE = {}
# Cache voor het ID van de meest recente event
LATEST_EVENT_ID = None
# Cache voor het ID van het laatste afgelopen event
LAST_COMPLETED_EVENT_ID = None
# Maximum aantal events om in cache te houden
MAX_CACHE_SIZE = 10
# Pad naar bestand met opgeslagen historische events
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ufc_history.json')

# Laad historische events uit het bestand, als het bestaat
def load_history():
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"Error loading history: {e}")
        return {}

# Sla historische events op in het bestand
def save_history(history):
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f)
    except Exception as e:
        print(f"Error saving history: {e}")

# Haal de meest recente UFC event ID op (aankomend of lopend)
def get_latest_ufc_event_id():
    global LATEST_EVENT_ID
    
    if LATEST_EVENT_ID is not None:
        return LATEST_EVENT_ID
    
    try:
        # Scrape de UFC site voor de meest recente event ID
        response = requests.get("https://www.ufc.com/events")
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Zoek naar de eerste aankomende event (of meest recente)
            event_links = soup.select('.c-card-event--result__headline a')
            if event_links:
                # Pak de URL en haal de event ID eruit
                event_url = event_links[0]['href']
                if event_url.startswith('/event/'):
                    # Scrape het event om het FMID te krijgen
                    event = scrape_event_url(f"https://www.ufc.com{event_url}")
                    if event and hasattr(event, 'fmid'):
                        LATEST_EVENT_ID = event.fmid
                        return event.fmid
        
        # Als we hier komen, konden we geen event ID vinden, gebruik een standaard waarde
        return 1251  # Standaard UFC event ID als fallback
    except Exception as e:
        print(f"Error finding latest event: {e}")
        return 1251  # Standaard UFC event ID als fallback

# Haal het laatste afgelopen UFC event ID op
def get_last_completed_event_id():
    global LAST_COMPLETED_EVENT_ID
    
    if LAST_COMPLETED_EVENT_ID is not None:
        return LAST_COMPLETED_EVENT_ID
    
    try:
        # Probeer eerst de nieuwste event te krijgen
        latest_id = get_latest_ufc_event_id()
        
        # Controleer of de nieuwste event al afgelopen is
        latest_event = get_event_with_cache(latest_id)
        if latest_event.status == 'Completed':
            LAST_COMPLETED_EVENT_ID = latest_id
            return latest_id
        
        # Zo niet, dan zoeken we naar het laatste afgelopen event (meestal latest_id - 1)
        for event_id in range(latest_id - 1, latest_id - 10, -1):
            try:
                event = get_event_with_cache(event_id)
                if event.status == 'Completed':
                    LAST_COMPLETED_EVENT_ID = event_id
                    return event_id
            except:
                continue
        
        # Als we geen afgelopen event kunnen vinden, use a fallback
        return 1250  # Een oudere event ID als fallback
    except Exception as e:
        print(f"Error finding last completed event: {e}")
        return 1250  # Een oudere event ID als fallback

# Cache een event
def cache_event(event_id, event):
    global EVENT_CACHE
    
    # Voeg toe aan cache
    EVENT_CACHE[event_id] = {
        "timestamp": datetime.now(),
        "event": event
    }
    
    # Houd cache grootte in de gaten
    if len(EVENT_CACHE) > MAX_CACHE_SIZE:
        # Verwijder de oudste entry
        oldest = min(EVENT_CACHE.items(), key=lambda x: x[1]["timestamp"])
        del EVENT_CACHE[oldest[0]]

# Scrape een event met caching
def get_event_with_cache(event_id):
    global EVENT_CACHE
    
    # Controleer of het event in de cache zit en niet te oud is
    if event_id in EVENT_CACHE:
        cached = EVENT_CACHE[event_id]
        # Als de cache minder dan een uur oud is, gebruik deze
        if (datetime.now() - cached["timestamp"]).total_seconds() < 3600:
            return cached["event"]
    
    # Anders, scrape het event
    event = scrape_event_fmid(event_id)
    
    # Cache het event
    cache_event(event_id, event)
    
    # Sla het event op in de geschiedenis als het volledig is
    if event.status == 'Completed':
        history = load_history()
        history[str(event_id)] = {
            "name": event.name,
            "date": str(event.card_segments[0].start_time if event.card_segments else None),
            "segments": [{
                "name": segment.name,
                "fights": [{
                    "fighters": [fs.fighter.name for fs in fight.fighters_stats],
                    "result": {
                        "method": fight.result.method if fight.result else None,
                        "ending_round": fight.result.ending_round if fight.result else None,
                        "ending_time": str(fight.result.ending_time) if fight.result else None
                    } if fight.result else None
                } for fight in segment.fights]
            } for segment in event.card_segments]
        }
        save_history(history)
    
    return event

# Achtergrond taak om periodiek events te controleren en bij te werken
def background_task():
    while True:
        try:
            # Haal de meest recente event ID op
            latest_id = get_latest_ufc_event_id()
            
            # Update de cache met de nieuwste event
            if latest_id:
                event = get_event_with_cache(latest_id)
                
                # Als het een voltooide event is, probeer ook de volgende te vinden
                if event.status == 'Completed':
                    # Update de LAST_COMPLETED_EVENT_ID
                    global LAST_COMPLETED_EVENT_ID
                    LAST_COMPLETED_EVENT_ID = latest_id
                    
                    # Probeer de volgende event te vinden (meestal +1)
                    try:
                        next_event = scrape_event_fmid(latest_id + 1)
                        if next_event:
                            cache_event(latest_id + 1, next_event)
                            # Update de LATEST_EVENT_ID als we een nieuwere event vinden
                            global LATEST_EVENT_ID
                            LATEST_EVENT_ID = latest_id + 1
                    except:
                        pass
                else:
                    # Probeer het laatste afgelopen event te vinden
                    get_last_completed_event_id()
        except Exception as e:
            print(f"Error in background task: {e}")
        
        # Wacht 30 minuten voor de volgende controle
        time.sleep(1800)

# Start de achtergrond taak
threading.Thread(target=background_task, daemon=True).start()

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "message": "UFC Data API is running",
        "endpoints": [
            "/event/<event_fmid>",
            "/latest",
            "/last_completed",
            "/upcoming",
            "/fights/schedule",
            "/pretty_output",
            "/pretty_output/<int:event_fmid>",
            "/pretty_output/last_completed",
            "/history"
        ]
    })

@app.route('/event/<int:event_fmid>')
def get_event(event_fmid):
    try:
        event = get_event_with_cache(event_fmid)
        return jsonify({
            "name": event.name,
            "status": event.status,
            "segments": [
                {
                    "name": segment.name,
                    "start_time": str(segment.start_time),
                    "fights": [
                        {
                            "fighters": [fs.fighter.name for fs in fight.fighters_stats],
                            "result": {
                                "method": fight.result.method if fight.result else None,
                                "ending_round": fight.result.ending_round if fight.result else None,
                                "ending_time": str(fight.result.ending_time) if fight.result else None
                            } if fight.result else {"status": "Not yet finished"}
                        } for fight in segment.fights
                    ]
                } for segment in event.card_segments
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/latest')
def get_latest_event():
    try:
        latest_fmid = get_latest_ufc_event_id()
        return get_event(latest_fmid)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/last_completed')
def get_last_completed_event():
    try:
        last_completed_fmid = get_last_completed_event_id()
        return get_event(last_completed_fmid)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/history')
def get_history():
    try:
        history = load_history()
        return jsonify(history)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/pretty_output')
@app.route('/pretty_output/<int:event_fmid>')
def pretty_output(event_fmid=None):
    try:
        if event_fmid is None:
            # Default to the latest event
            event_fmid = get_latest_ufc_event_id()
        
        event = get_event_with_cache(event_fmid)
        
        output = []
        output.append("\n📅 Event: {}\n".format(event.name))
        
        for segment in event.card_segments:
            output.append("🎬 Segment: {} - Start: {}".format(segment.name, segment.start_time))
            for fight in segment.fights:
                fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
                output.append(" 🥋 " + " vs. ".join(fighter_names))
                
                if fight.result and fight.result.method:
                    output.append("   ✅ Result: {}".format(fight.result.method))
                    output.append("   ⏱️  Ended in round {} at {}".format(
                        fight.result.ending_round, fight.result.ending_time))
                else:
                    output.append("   🕒 Status: Not yet finished")
                
                output.append("-" * 50)
        
        # Join all lines with newlines and return as text response
        return Response("\n".join(output), mimetype='text/plain')
    except Exception as e:
        return Response("Error: " + str(e), mimetype='text/plain', status=500)

@app.route('/pretty_output/last_completed')
def pretty_output_last_completed():
    try:
        event_fmid = get_last_completed_event_id()
        event = get_event_with_cache(event_fmid)
        
        output = []
        output.append("\n📅 Laatste Afgelopen Event: {}\n".format(event.name))
        
        for segment in event.card_segments:
            output.append("🎬 Segment: {} - Start: {}".format(segment.name, segment.start_time))
            for fight in segment.fights:
                fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
                output.append(" 🥋 " + " vs. ".join(fighter_names))
                
                if fight.result and fight.result.method:
                    output.append("   ✅ Result: {}".format(fight.result.method))
                    output.append("   ⏱️  Ended in round {} at {}".format(
                        fight.result.ending_round, fight.result.ending_time))
                else:
                    output.append("   🕒 Status: Not yet finished")
                
                output.append("-" * 50)
        
        # Join all lines with newlines and return as text response
        return Response("\n".join(output), mimetype='text/plain')
    except Exception as e:
        return Response("Error: " + str(e), mimetype='text/plain', status=500)

@app.route('/upcoming')
def get_upcoming_fights():
    try:
        # Get the current time in UTC
        now = datetime.now(pytz.UTC)
        
        # Get the latest event
        latest_fmid = get_latest_ufc_event_id()
        event = get_event_with_cache(latest_fmid)
        
        upcoming_fights = []
        
        for segment in event.card_segments:
            segment_start = segment.start_time
            
            # Skip segments that have already started
            if segment_start and segment_start < now:
                continue
                
            for fight_index, fight in enumerate(segment.fights):
                # Estimate fight start time based on segment start time and position
                # This is an approximation - UFC fights typically last ~15-30 minutes including walkouts
                estimated_start = segment_start + timedelta(minutes=30 * fight_index) if segment_start else None
                
                # Only include fights that haven't finished
                if not fight.result:
                    fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
                    upcoming_fights.append({
                        "fighters": fighter_names,
                        "segment": segment.name,
                        "segment_start_time": str(segment_start) if segment_start else None,
                        "estimated_start_time": str(estimated_start) if estimated_start else None,
                        "fight_position": fight_index + 1
                    })
        
        return jsonify({
            "event_name": event.name,
            "upcoming_fights": upcoming_fights
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/fights/schedule')
def get_fights_schedule():
    try:
        # Get timezone parameter with UTC as default
        timezone_str = request.args.get('timezone', 'UTC')
        try:
            timezone = pytz.timezone(timezone_str)
        except:
            timezone = pytz.UTC
            
        # Get the latest event
        latest_fmid = get_latest_ufc_event_id()
        event = get_event_with_cache(latest_fmid)
        
        all_fights = []
        
        for segment in event.card_segments:
            segment_start = segment.start_time
            
            for fight_index, fight in enumerate(segment.fights):
                # Estimate fight start time based on segment start time and position
                estimated_start = None
                if segment_start:
                    # Add 30 minutes for each preceding fight in the segment
                    estimated_start = segment_start + timedelta(minutes=30 * fight_index)
                    # Convert to requested timezone
                    estimated_start = estimated_start.astimezone(timezone)
                    
                fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
                
                fight_data = {
                    "event_name": event.name,
                    "fighters": " vs ".join(fighter_names),
                    "segment": segment.name,
                    "segment_start_time": str(segment_start.astimezone(timezone)) if segment_start else None,
                    "estimated_start_time": str(estimated_start) if estimated_start else None,
                    "estimated_start_timestamp": int(estimated_start.timestamp()) if estimated_start else None,
                    "fight_position": fight_index + 1,
                    "status": "completed" if fight.result else "scheduled"
                }
                
                # Add result information if the fight is completed
                if fight.result:
                    fight_data["result"] = {
                        "method": fight.result.method,
                        "ending_round": fight.result.ending_round,
                        "ending_time": str(fight.result.ending_time)
                    }
                
                all_fights.append(fight_data)
        
        return jsonify({
            "event_name": event.name,
            "event_date": str(event.card_segments[0].start_time.astimezone(timezone).date()) if event.card_segments[0].start_time else None,
            "timezone": timezone_str,
            "fights": all_fights
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
