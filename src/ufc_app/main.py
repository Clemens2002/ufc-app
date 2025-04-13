from ufc_data_scraper.ufc_scraper import scrape_event_url, scrape_event_fmid, get_event_fmid
from flask import jsonify, request, Response, render_template_string
import os
from . import app
from datetime import datetime, timedelta
import pytz
import json
import requests
from bs4 import BeautifulSoup

# Fallback event IDs als de auto-detectie faalt
DEFAULT_LAST_EVENT_ID = 1250
DEFAULT_CURRENT_EVENT_ID = 1251
DEFAULT_NEXT_EVENT_ID = 1252

# Light-weight caching - sla de event IDs en timestamps op, niet de hele events
event_ids = {
    'last_finished': None,
    'ongoing': None,
    'upcoming': None,
    'last_check': None  # Timestamp van de laatste check
}

# Light-weight caching voor event data
event_cache = {}

def get_event_ids():
    """Haal de event IDs op met minimale caching"""
    global event_ids
    
    # Als we al een recente check hebben gedaan, gebruik die
    if event_ids['last_check'] and (datetime.now() - event_ids['last_check']).total_seconds() < 3600:
        # Als alle IDs gevuld zijn, return ze
        if event_ids['last_finished'] and (event_ids['ongoing'] is not None or event_ids['upcoming']):
            return event_ids
    
    # Anders, doe een nieuwe check
    try:
        # Zoek het meest recente en aankomende events
        # Dit is een eenvoudige benadering om recent events te vinden
        found_ids = []
        
        # Probeer UFC website te scrapen
        try:
            response = requests.get("https://www.ufc.com/events", timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                event_links = soup.select('.c-card-event--result__headline a')
                
                # Pak de eerste paar event links
                for link in event_links[:3]:
                    if link['href'].startswith('/event/'):
                        try:
                            event_url = f"https://www.ufc.com{link['href']}"
                            event = scrape_event_url(event_url)
                            if event and hasattr(event, 'fmid'):
                                found_ids.append(event.fmid)
                        except:
                            pass
        except:
            pass
        
        # Als we geen events hebben gevonden, gebruik fallbacks
        if not found_ids:
            found_ids = [DEFAULT_LAST_EVENT_ID, DEFAULT_CURRENT_EVENT_ID, DEFAULT_NEXT_EVENT_ID]
        
        # Als we slechts 1 event hebben gevonden, voeg de andere toe
        if len(found_ids) == 1:
            found_ids = [found_ids[0] - 1, found_ids[0], found_ids[0] + 1]
        elif len(found_ids) == 2:
            # Als we 2 events hebben, voeg een derde toe
            found_ids.append(found_ids[-1] + 1)
        
        # Sorteer de IDs en bepaal welke finished/ongoing/upcoming zijn
        status_map = {}
        for event_id in found_ids:
            try:
                event = scrape_event_fmid(event_id)
                status_map[event_id] = event.status
                # Cache this event while we have it
                event_cache[event_id] = {
                    'event': event,
                    'timestamp': datetime.now()
                }
            except:
                status_map[event_id] = "Unknown"
        
        # Vind de finished, ongoing en upcoming events
        finished_ids = [eid for eid, status in status_map.items() if status == "Completed"]
        ongoing_ids = [eid for eid, status in status_map.items() if status == "In Progress"]
        upcoming_ids = [eid for eid, status in status_map.items() if status not in ["Completed", "In Progress"]]
        
        # Als we geen ongoing event hebben, maak aannames op basis van de event IDs
        if not ongoing_ids and finished_ids and upcoming_ids:
            # Als we finished en upcoming hebben, dan is er momenteel geen ongoing
            event_ids['last_finished'] = max(finished_ids)
            event_ids['ongoing'] = None
            event_ids['upcoming'] = min(upcoming_ids)
        elif ongoing_ids:
            # Als we een ongoing event hebben
            event_ids['ongoing'] = ongoing_ids[0]
            # Kies de meest recente finished event
            event_ids['last_finished'] = max(finished_ids) if finished_ids else (event_ids['ongoing'] - 1)
            # Kies de eerstvolgende upcoming event
            event_ids['upcoming'] = min(upcoming_ids) if upcoming_ids else (event_ids['ongoing'] + 1)
        else:
            # Fallback: gebruik gewoon opeenvolgende IDs
            event_ids['last_finished'] = found_ids[0]
            event_ids['ongoing'] = found_ids[1]
            event_ids['upcoming'] = found_ids[2]
        
        # Update de timestamp
        event_ids['last_check'] = datetime.now()
    
    except Exception as e:
        # Als er iets misgaat, val terug op defaults
        if not event_ids['last_finished']:
            event_ids['last_finished'] = DEFAULT_LAST_EVENT_ID
        if not event_ids['ongoing']:
            event_ids['ongoing'] = DEFAULT_CURRENT_EVENT_ID
        if not event_ids['upcoming']:
            event_ids['upcoming'] = DEFAULT_NEXT_EVENT_ID
        event_ids['last_check'] = datetime.now()
    
    return event_ids

def get_event_with_cache(event_id):
    """Haal een event op met light-weight caching"""
    global event_cache
    
    # Check if we have a fresh cached version
    if event_id in event_cache:
        cache_entry = event_cache[event_id]
        # If cached less than 15 minutes ago, use it
        if (datetime.now() - cache_entry['timestamp']).total_seconds() < 900:
            return cache_entry['event']
    
    # If not cached or stale, fetch fresh data
    try:
        event = scrape_event_fmid(event_id)
        # Cache the result
        event_cache[event_id] = {
            'event': event,
            'timestamp': datetime.now()
        }
        # Keep the cache size reasonable
        if len(event_cache) > 5:
            # Remove the oldest entry
            oldest_id = min(event_cache.keys(), key=lambda k: event_cache[k]['timestamp'])
            del event_cache[oldest_id]
        return event
    except Exception as e:
        print(f"Error getting event {event_id}: {e}")
        raise

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>UFC Events API</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }
        h1, h2, h3 {
            color: #d20a0a;
        }
        h1 {
            border-bottom: 2px solid #d20a0a;
            padding-bottom: 10px;
        }
        .event {
            background: white;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 30px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .event-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
        }
        .event-title {
            margin-top: 0;
        }
        .status {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 14px;
            font-weight: bold;
        }
        .status-completed {
            background: #d9ffd9;
            color: #006400;
        }
        .status-progress {
            background: #ffe8cc;
            color: #cc5500;
        }
        .status-upcoming {
            background: #e6f7ff;
            color: #0066cc;
        }
        .segment {
            border-top: 1px solid #eee;
            padding-top: 10px;
            margin-top: 15px;
        }
        .segment-name {
            font-weight: bold;
            margin-bottom: 5px;
        }
        .segment-time {
            font-size: 14px;
            color: #666;
            margin-bottom: 10px;
        }
        .fight {
            padding: 10px;
            margin-bottom: 10px;
            border-left: 3px solid #d20a0a;
            background: #f9f9f9;
        }
        .fight-result {
            margin-top: 5px;
            font-size: 14px;
        }
        .result-method {
            color: #d20a0a;
            font-weight: bold;
        }
        .endpoint {
            background: #f0f0f0;
            padding: 8px;
            border-radius: 4px;
            font-family: monospace;
            margin-right: 10px;
            margin-bottom: 5px;
            display: inline-block;
        }
        .api-info {
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
        }
        @media (max-width: 600px) {
            body {
                padding: 10px;
            }
            .event-header {
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <h1>UFC Events API</h1>
    
    {% if events %}
        {% for event_type, event_data in events.items() %}
            {% if event_data %}
            <div class="event">
                <div class="event-header">
                    <h2 class="event-title">{{ event_data.name }}</h2>
                    {% if event_data.status == "Completed" %}
                        <span class="status status-completed">{{ event_data.status }}</span>
                    {% elif event_data.status == "In Progress" %}
                        <span class="status status-progress">{{ event_data.status }}</span>
                    {% else %}
                        <span class="status status-upcoming">{{ event_data.status }}</span>
                    {% endif %}
                </div>
                
                <h3>{{ event_type | replace('_', ' ') | title }}</h3>
                
                {% for segment in event_data.segments %}
                    <div class="segment">
                        <div class="segment-name">{{ segment.name }}</div>
                        <div class="segment-time">Start: {{ segment.start_time }}</div>
                        
                        {% for fight in segment.fights %}
                            <div class="fight">
                                <div class="fight-matchup">{{ " vs. ".join(fight.fighters) }}</div>
                                
                                {% if fight.result and fight.result.method %}
                                    <div class="fight-result">
                                        <span class="result-method">{{ fight.result.method }}</span>
                                        - Round {{ fight.result.ending_round }} at {{ fight.result.ending_time }}
                                    </div>
                                {% else %}
                                    <div class="fight-result">Status: Not yet finished</div>
                                {% endif %}
                            </div>
                        {% endfor %}
                    </div>
                {% endfor %}
            </div>
            {% endif %}
        {% endfor %}
    {% else %}
        <p>No events data available.</p>
    {% endif %}
    
    <div class="api-info">
        <h3>API Endpoints</h3>
        <div>
            <div class="endpoint">/latest</div>
            <div class="endpoint">/ongoing</div>
            <div class="endpoint">/upcoming</div>
            <div class="endpoint">/last_finished</div>
            <div class="endpoint">/pretty_output/ongoing</div>
            <div class="endpoint">/pretty_output/upcoming</div>
            <div class="endpoint">/pretty_output/last_finished</div>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    # Get all events data with only one request
    try:
        ids = get_event_ids()
        events = {}
        
        # Get the last finished event
        if ids['last_finished']:
            try:
                last_finished_event = get_event_with_cache(ids['last_finished'])
                events['last_finished'] = format_event_for_template(last_finished_event)
            except:
                pass
                
        # Get the ongoing event
        if ids['ongoing']:
            try:
                ongoing_event = get_event_with_cache(ids['ongoing'])
                events['ongoing'] = format_event_for_template(ongoing_event)
            except:
                pass
        
        # Get the upcoming event
        if ids['upcoming']:
            try:
                upcoming_event = get_event_with_cache(ids['upcoming'])
                events['upcoming'] = format_event_for_template(upcoming_event)
            except:
                pass
        
        # Return HTML response if events were loaded successfully
        if events:
            return render_template_string(HTML_TEMPLATE, events=events)
        
    except:
        pass
    
    # Fallback to JSON if anything fails
    return jsonify({
        "status": "online",
        "message": "UFC Data API is running",
        "endpoints": [
            "/latest",  # Huidige/aankomende event
            "/ongoing",  # Momenteel lopende event
            "/upcoming",  # Aankomende event
            "/last_finished",  # Laatste afgelopen event
            "/pretty_output/last_finished",  # Prettig leesbare versie van laatste event
            "/pretty_output/ongoing",  # Prettig leesbare versie van huidige event
            "/pretty_output/upcoming"  # Prettig leesbare versie van aankomend event
        ]
    })

def format_event_for_template(event):
    """Format event data for the HTML template"""
    segments = []
    for segment in event.card_segments:
        fights = []
        for fight in segment.fights:
            fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
            fight_data = {
                "fighters": fighter_names,
                "result": None
            }
            
            if fight.result and fight.result.method:
                fight_data["result"] = {
                    "method": fight.result.method,
                    "ending_round": fight.result.ending_round,
                    "ending_time": fight.result.ending_time
                }
            
            fights.append(fight_data)
            
        segments.append({
            "name": segment.name,
            "start_time": segment.start_time,
            "fights": fights
        })
    
    return {
        "name": event.name,
        "status": event.status,
        "segments": segments
    }

def get_event_json(event):
    """Zet een event om in JSON"""
    return {
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
    }

@app.route('/latest')
def get_latest_event():
    try:
        # Get event IDs
        ids = get_event_ids()
        
        # Gebruik ongoing als die er is, anders upcoming
        event_id = ids['ongoing'] if ids['ongoing'] else ids['upcoming']
        
        # Haal het event op
        event = get_event_with_cache(event_id)
        return jsonify(get_event_json(event))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/ongoing')
def get_ongoing_event():
    try:
        # Get event IDs
        ids = get_event_ids()
        
        if not ids['ongoing']:
            return jsonify({"error": "No ongoing event found"}), 404
        
        # Haal het event op
        event = get_event_with_cache(ids['ongoing'])
        return jsonify(get_event_json(event))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/upcoming')
def get_upcoming_event():
    try:
        # Get event IDs
        ids = get_event_ids()
        
        if not ids['upcoming']:
            return jsonify({"error": "No upcoming event found"}), 404
        
        # Haal het event op
        event = get_event_with_cache(ids['upcoming'])
        return jsonify(get_event_json(event))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/last_finished')
def get_last_finished_event():
    try:
        # Get event IDs
        ids = get_event_ids()
        
        if not ids['last_finished']:
            return jsonify({"error": "No finished event found"}), 404
        
        # Haal het event op
        event = get_event_with_cache(ids['last_finished'])
        return jsonify(get_event_json(event))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_pretty_output(event):
    """Maak een pretty output voor een event"""
    output = []
    output.append("\n📅 Event: {}\n".format(event.name))
    output.append("📊 Status: {}\n".format(event.status))
    
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
    return "\n".join(output)

@app.route('/pretty_output/ongoing')
def pretty_output_ongoing():
    try:
        # Get event IDs
        ids = get_event_ids()
        
        if not ids['ongoing']:
            return Response("Geen lopend event gevonden", mimetype='text/plain', status=404)
        
        # Haal het event op
        event = get_event_with_cache(ids['ongoing'])
        return Response(get_pretty_output(event), mimetype='text/plain')
    except Exception as e:
        return Response("Error: " + str(e), mimetype='text/plain', status=500)

@app.route('/pretty_output/upcoming')
def pretty_output_upcoming():
    try:
        # Get event IDs
        ids = get_event_ids()
        
        if not ids['upcoming']:
            return Response("Geen aankomend event gevonden", mimetype='text/plain', status=404)
        
        # Haal het event op
        event = get_event_with_cache(ids['upcoming'])
        return Response(get_pretty_output(event), mimetype='text/plain')
    except Exception as e:
        return Response("Error: " + str(e), mimetype='text/plain', status=500)

@app.route('/pretty_output/last_finished')
def pretty_output_last_finished():
    try:
        # Get event IDs
        ids = get_event_ids()
        
        if not ids['last_finished']:
            return Response("Geen afgelopen event gevonden", mimetype='text/plain', status=404)
        
        # Haal het event op
        event = get_event_with_cache(ids['last_finished'])
        return Response(get_pretty_output(event), mimetype='text/plain')
    except Exception as e:
        return Response("Error: " + str(e), mimetype='text/plain', status=500)

@app.route('/fights/schedule')
def get_fights_schedule():
    try:
        # Get timezone parameter with UTC as default
        timezone_str = request.args.get('timezone', 'UTC')
        try:
            timezone = pytz.timezone(timezone_str)
        except:
            timezone = pytz.UTC
        
        # Determine which event to use
        ids = get_event_ids()
        event_id = ids['ongoing'] if ids['ongoing'] else ids['upcoming']
        
        # Direct scrapen
        event = get_event_with_cache(event_id)
        
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
