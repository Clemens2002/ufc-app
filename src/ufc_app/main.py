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

def is_fight_live(fight, segment, event):
    """
    Bepaal of een gevecht momenteel live is gebaseerd op:
    - Event status is "In Progress"
    - Gevechtsresultaat is nog niet bekend
    - Segment is begonnen
    """
    try:
        # Als het event niet bezig is, dan is geen enkel gevecht live
        if event.status != "In Progress":
            return False
        
        # Als het gevecht een resultaat heeft, is het voorbij
        if fight.result and fight.result.method:
            return False
        
        current_time = datetime.now(pytz.UTC)
        
        # Als het segment nog niet begonnen is, is het gevecht niet live
        if segment.start_time and segment.start_time > current_time:
            return False
        
        # Nu moeten we bepalen welk gevecht in het segment momenteel plaatsvindt
        # We vinden de index van dit gevecht in de lijst van gevechten
        fight_index = -1
        for i, f in enumerate(segment.fights):
            if f == fight:
                fight_index = i
                break
        
        if fight_index == -1:
            return False
            
        # Controleer voorgaande gevechten in hetzelfde segment
        for i in range(0, fight_index):
            prev_fight = segment.fights[i]
            # Als een voorgaand gevecht nog geen resultaat heeft, dan is dit gevecht nog niet begonnen
            if not prev_fight.result or not prev_fight.result.method:
                return False
                
        # Controleer of er een volgend gevecht in hetzelfde segment is
        # dat al wel een resultaat heeft (dan is dit gevecht al voorbij)
        if fight_index < len(segment.fights) - 1:
            next_fight = segment.fights[fight_index + 1]
            if next_fight.result and next_fight.result.method:
                return False
                
        # Als aan alle voorwaarden is voldaan, is dit gevecht waarschijnlijk live
        return True
    except:
        # Als er een fout optreedt, gaan we ervan uit dat het gevecht niet live is
        return False

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
                elif is_fight_live(fight, segment, event):
                    output.append("   🔴 LIVE NOW")
                else:
                    output.append("   🕒 Status: Not yet finished")
                
                output.append("-" * 50)
        
        # Voeg informatie over andere endpoints toe
        output.append("\n🔗 Andere endpoints:")
        output.append("  - /event/1250 (Vorig event)")
        output.append("  - /event/1251 (Huidig event)")
        output.append("  - /event/1252 (Volgend event)")
        
        # Voeg timestamp toe voor verse data
        output.append("\n🕒 Last Updated: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")))
        
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
        
        # Bereid de JSON data voor
        result_json = {
            "name": event.name,
            "status": event.status,
            "segments": []
        }
        
        for segment in event.card_segments:
            segment_data = {
                "name": segment.name,
                "start_time": str(segment.start_time),
                "fights": []
            }
            
            for fight in segment.fights:
                fight_data = {
                    "fighters": [fs.fighter.name for fs in fight.fighters_stats]
                }
                
                if fight.result:
                    fight_data["result"] = {
                        "method": fight.result.method,
                        "ending_round": fight.result.ending_round,
                        "ending_time": str(fight.result.ending_time)
                    }
                elif is_fight_live(fight, segment, event):
                    fight_data["status"] = "LIVE NOW"
                else:
                    fight_data["status"] = "Not yet finished"
                
                segment_data["fights"].append(fight_data)
            
            result_json["segments"].append(segment_data)
        
        return jsonify(result_json)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
