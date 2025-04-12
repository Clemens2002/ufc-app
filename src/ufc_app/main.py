from ufc_data_scraper.ufc_scraper import scrape_event_url, scrape_event_fmid, get_event_fmid
from flask import jsonify, request, Response
import os
from . import app
from datetime import datetime, timedelta
import pytz

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "message": "UFC Data API is running",
        "endpoints": [
            "/event/<event_fmid>",
            "/latest",
            "/upcoming",
            "/fights/schedule",
            "/pretty_output",
            "/pretty_output/<int:event_fmid>"
        ]
    })

@app.route('/event/<int:event_fmid>')
def get_event(event_fmid):
    try:
        event = scrape_event_fmid(event_fmid)
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
        # This is a placeholder - you might need to implement a way to find the latest event
        latest_fmid = 1251  # Replace with the latest UFC event FMID
        return get_event(latest_fmid)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/pretty_output')
@app.route('/pretty_output/<int:event_fmid>')
def pretty_output(event_fmid=None):
    try:
        if event_fmid is None:
            # Default to the latest event
            event_fmid = 1251  # Replace with the latest UFC event FMID
        
        event = scrape_event_fmid(event_fmid)
        
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

@app.route('/upcoming')
def get_upcoming_fights():
    try:
        # Get the current time in UTC
        now = datetime.now(pytz.UTC)
        
        # This is a placeholder - you might need to implement a way to find the latest event
        latest_fmid = 1251  # Replace with the latest UFC event FMID
        event = scrape_event_fmid(latest_fmid)
        
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
            
        # This is a placeholder - you might need to implement a way to find the latest event
        latest_fmid = 1251  # Replace with the latest UFC event FMID
        event = scrape_event_fmid(latest_fmid)
        
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
