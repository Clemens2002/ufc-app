from ufc_data_scraper.ufc_scraper import scrape_event_url, scrape_event_fmid, get_event_fmid
from flask import jsonify, request, Response
import os
from . import app
from datetime import datetime, timedelta
import pytz
import time
import requests

# Constante waarden voor event IDs
DEFAULT_LAST_EVENT_ID = 1250
DEFAULT_CURRENT_EVENT_ID = 1251
DEFAULT_NEXT_EVENT_ID = 1252

def is_fight_live(fight, segment, event):
    """
    Verbeterde detectie van live gevechten gebaseerd op:
    - Event status check
    - Gevechtsresultaat check
    - Segment tijdcheck
    - Volgorde van gevechten
    """
    try:
        # Als het gevecht een resultaat heeft, is het voorbij
        if fight.result and fight.result.method:
            return False
        
        # Check event status - als het "In Progress" is, is er een fight bezig
        if event.status == "In Progress":
            current_time = datetime.now(pytz.UTC)
            
            # Als het segment nog niet begonnen is, is het gevecht niet live
            if segment.start_time and segment.start_time > current_time:
                return False
            
            # Vind index van het huidige gevecht
            fight_index = -1
            for i, f in enumerate(segment.fights):
                if f == fight:
                    fight_index = i
                    break
            
            if fight_index == -1:
                return False
                
            # Controleer voorgaande gevechten - moeten allemaal klaar zijn
            all_previous_completed = True
            for i in range(0, fight_index):
                prev_fight = segment.fights[i]
                if not prev_fight.result or not prev_fight.result.method:
                    all_previous_completed = False
                    break
            
            if not all_previous_completed:
                return False
                
            # Controleer volgende gevechten - als een volgende al klaar is, dan is dit niet live
            if fight_index < len(segment.fights) - 1:
                next_fight = segment.fights[fight_index + 1]
                if next_fight.result and next_fight.result.method:
                    return False
            
            # Probeer direct de UFC site te checken voor extra verificatie
            try:
                direct_check = check_ufc_site_for_live_status(fight)
                if direct_check is not None:
                    return direct_check
            except:
                pass
                
            # Als aan alle voorwaarden is voldaan, is dit gevecht waarschijnlijk live
            return True
            
        # Als event status niet "In Progress" is, is er nog een alternatieve check
        # Controleer of dit het eerste gevecht is zonder resultaat na een reeks gevechten met resultaten
        fight_index = -1
        for i, f in enumerate(segment.fights):
            if f == fight:
                fight_index = i
                break
                
        if fight_index > 0:
            # Alle voorgaande gevechten moeten afgelopen zijn
            all_previous_completed = True
            for i in range(0, fight_index):
                if not segment.fights[i].result or not segment.fights[i].result.method:
                    all_previous_completed = False
                    break
                    
            if all_previous_completed:
                # Probeer direct de UFC site te checken
                try:
                    direct_check = check_ufc_site_for_live_status(fight)
                    if direct_check is not None:
                        return direct_check
                except:
                    pass
                
                # Dit zou het huidige gevecht kunnen zijn, ook al zegt de API niet "In Progress"
                return True
                
        return False
    except:
        # Als er een fout optreedt, gaan we ervan uit dat het gevecht niet live is
        return False

def check_ufc_site_for_live_status(fight):
    """Probeert direct van de UFC site te bepalen of een gevecht LIVE is"""
    try:
        # Haal de UFC evenement pagina op
        response = requests.get("https://www.ufc.com/events", timeout=5)
        if response.status_code == 200:
            # Controleer of er "LIVE NOW" of soortgelijke indicaties zijn
            if "LIVE NOW" in response.text or "LIVE EVENT" in response.text:
                # Als de site aangeeft dat er een live event is, 
                # en dit gevecht heeft nog geen resultaat,
                # dan is het waarschijnlijk dit gevecht dat live is
                return True
    except:
        pass
    
    # Als we hier komen, geen directe bevestiging
    return None

@app.route('/')
def home():
    try:
        # Haal direct het huidige event op
        event = scrape_event_fmid(DEFAULT_CURRENT_EVENT_ID)
        
        # Maak een eenvoudige tekst weergave
        output = []
        output.append("\n📅 UFC Event: {}\n".format(event.name))
        output.append("📊 Status: {}\n".format(event.status))
        
        found_live_fight = False
        
        for segment in event.card_segments:
            output.append("🎬 {} - Start: {}".format(segment.name, segment.start_time))
            for fight in segment.fights:
                fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
                fighters_str = " vs. ".join(fighter_names)
                output.append(" 🥋 " + fighters_str)
                
                # Controleer de live status
                is_live = is_fight_live(fight, segment, event)
                
                if fight.result and fight.result.method:
                    output.append("   ✅ Result: {}".format(fight.result.method))
                    output.append("   ⏱️  Ended in round {} at {}".format(
                        fight.result.ending_round, fight.result.ending_time))
                elif is_live:
                    output.append("   🔴 LIVE NOW")
                    found_live_fight = True
                else:
                    output.append("   🕒 Status: Not yet finished")
                
                output.append("-" * 50)
        
        # Voeg informatie over andere endpoints toe
        output.append("\n🔗 Andere endpoints:")
        output.append("  - /event/1250 (Vorig event)")
        output.append("  - /event/1251 (Huidig event)")
        output.append("  - /event/1252 (Volgend event)")
        
        # Als we geen live gevecht gevonden hebben, voeg een notitie toe
        if not found_live_fight and event.status == "In Progress":
            output.append("\n⚠️ Event is 'In Progress' maar geen specifiek live gevecht geïdentificeerd.")
        
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
                fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
                
                fight_data = {
                    "fighters": fighter_names
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
