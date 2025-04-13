from ufc_data_scraper.ufc_scraper import scrape_event_url, scrape_event_fmid, get_event_fmid
from flask import jsonify, request, Response
import os
from . import app
from datetime import datetime, timedelta
import pytz

# Constante waarden voor event IDs
DEFAULT_LAST_EVENT_ID = 1250
DEFAULT_CURRENT_EVENT_ID = 1251
DEFAULT_NEXT_EVENT_ID = 1252

@app.route('/')
def home():
    try:
        # Haal direct het huidige event op
        event = scrape_event_fmid(DEFAULT_CURRENT_EVENT_ID)
        
        # Maak een eenvoudige tekst weergave
        output = []
        output.append("\n📅 UFC Event: {}\n".format(event.name))
        output.append("📊 Status: {}\n".format(event.status))
        
        for segment in event.card_segments:
            output.append("🎬 {} - Start: {}".format(segment.name, segment.start_time))
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
        
        # Voeg informatie over andere endpoints toe
        output.append("\n🔗 Andere endpoints:")
        output.append("  - /event/1250 (Vorig event)")
        output.append("  - /event/1251 (Huidig event)")
        output.append("  - /event/1252 (Volgend event)")
        
        # Retourneer als plain text
        return Response("\n".join(output), mimetype='text/plain')
    except Exception as e:
        # Fallback naar JSON in geval van fouten
        return jsonify({
            "status": "online",
            "message": "UFC Data API is running",
            "endpoints": [
                "/event/1250",  # Laatste event (voorbeeld)
                "/event/1251",  # Huidige event (voorbeeld)
                "/event/1252",  # Volgende event (voorbeeld)
            ],
            "error": str(e)
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
