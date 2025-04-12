from ufc_data_scraper.ufc_scraper import scrape_event_url, scrape_event_fmid, get_event_fmid
from flask import jsonify
import os
from . import app

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "message": "UFC Data API is running",
        "endpoints": [
            "/event/<event_fmid>",
            "/latest"
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
