from ufc_data_scraper.ufc_scraper import scrape_event_url, scrape_event_fmid, get_event_fmid
from flask import jsonify, request, Response
import os
from . import app
from datetime import datetime, timedelta
import pytz

# Fallback event IDs als we niets kunnen vinden
DEFAULT_CURRENT_EVENT_ID = 1251
DEFAULT_LAST_EVENT_ID = 1250

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "message": "UFC Data API is running",
        "endpoints": [
            "/latest",  # Huidige/aankomende event
            "/last_completed",  # Laatste afgelopen event
            "/pretty_output",  # Prettig leesbare versie van huidige event
            "/pretty_output/last_completed"  # Prettig leesbare versie van laatste event
        ]
    })

@app.route('/latest')
def get_latest_event():
    try:
        # Direct scrapen, geen caching
        event = scrape_event_fmid(DEFAULT_CURRENT_EVENT_ID)
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

@app.route('/last_completed')
def get_last_completed_event():
    try:
        # Direct scrapen, geen caching
        event = scrape_event_fmid(DEFAULT_LAST_EVENT_ID)
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

@app.route('/pretty_output')
def pretty_output():
    try:
        # Direct scrapen, geen caching
        event = scrape_event_fmid(DEFAULT_CURRENT_EVENT_ID)
        
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
        # Direct scrapen, geen caching
        event = scrape_event_fmid(DEFAULT_LAST_EVENT_ID)
        
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

@app.route('/fights/schedule')
def get_fights_schedule():
    try:
        # Get timezone parameter with UTC as default
        timezone_str = request.args.get('timezone', 'UTC')
        try:
            timezone = pytz.timezone(timezone_str)
        except:
            timezone = pytz.UTC
            
        # Direct scrapen, geen caching
        event = scrape_event_fmid(DEFAULT_CURRENT_EVENT_ID)
        
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
