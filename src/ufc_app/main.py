from ufc_data_scraper.ufc_scraper import scrape_event_url, scrape_event_fmid, get_event_fmid
from flask import jsonify, request, Response
import os
from . import app
from datetime import datetime, timedelta
import pytz
import time
import requests
from bs4 import BeautifulSoup
import json
import threading
import logging

# Constante waarden voor event IDs
DEFAULT_LAST_EVENT_ID = 1250
DEFAULT_CURRENT_EVENT_ID = 1251
DEFAULT_NEXT_EVENT_ID = 1252

# Light-weight caching zonder externe afhankelijkheden
event_cache = {}
last_check_time = None
CACHE_EXPIRY = 300  # 5 minuten cache expiry

# Configureer logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ufc_app')

def get_event_with_cache(event_id):
    """Haal event op met caching voor betere prestaties"""
    global event_cache, last_check_time
    
    current_time = datetime.now()
    
    # Als er een geldige cache is, gebruik die
    if event_id in event_cache:
        cache_time, cached_event = event_cache[event_id]
        # Als de cache nog vers is (< 5 minuten oud)
        if (current_time - cache_time).total_seconds() < CACHE_EXPIRY:
            logger.info(f"Cache hit voor event {event_id}")
            return cached_event
    
    # Anders, haal verse data op
    try:
        logger.info(f"Cache miss voor event {event_id}, ophalen verse data")
        event = scrape_event_fmid(event_id)
        # Update de cache
        event_cache[event_id] = (current_time, event)
        last_check_time = current_time
        
        # Houd de cache-grootte beperkt
        if len(event_cache) > 5:
            # Verwijder de oudste entry
            oldest_id = min(event_cache.keys(), 
                           key=lambda k: event_cache[k][0])
            del event_cache[oldest_id]
            
        return event
    except Exception as e:
        logger.error(f"Fout bij ophalen event {event_id}: {str(e)}")
        # Als er een fout optreedt en we hebben een verouderde cache, gebruik die als fallback
        if event_id in event_cache:
            logger.info(f"Gebruik verouderde cache als fallback voor event {event_id}")
            return event_cache[event_id][1]
        raise

def refresh_current_event():
    """Ververs de huidige event data in de achtergrond"""
    try:
        event = get_event_with_cache(DEFAULT_CURRENT_EVENT_ID)
        logger.info(f"Event {DEFAULT_CURRENT_EVENT_ID} ververst: {event.name}, status: {event.status}")
        
        # Controleer en log live gevechten
        for segment in event.card_segments:
            for fight in segment.fights:
                if is_fight_live(fight, segment, event):
                    fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
                    fighters_str = " vs. ".join(fighter_names)
                    logger.info(f"LIVE GEVECHT GEDETECTEERD: {fighters_str} in {segment.name}")
    except Exception as e:
        logger.error(f"Fout bij verversen event data: {str(e)}")

def start_background_refresh():
    """Start een achtergrondthread om event data te verversen"""
    def refresh_thread():
        while True:
            refresh_current_event()
            time.sleep(CACHE_EXPIRY)  # Wacht 5 minuten tussen verversingen
            
    thread = threading.Thread(target=refresh_thread, daemon=True)
    thread.start()
    logger.info("Achtergrond verversing gestart")

# Start de achtergrond verversing als we in een productie omgeving zijn
if not os.environ.get('FLASK_DEBUG'):
    start_background_refresh()

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
        event = get_event_with_cache(DEFAULT_CURRENT_EVENT_ID)
        
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
        output.append("  - /debug/live-detection (Test live detection)")
        output.append("  - /debug/simulate-live (Simuleer live event)")
        output.append("  - /api/status (API status en cache info)")
        
        # Als we geen live gevecht gevonden hebben, voeg een notitie toe
        if not found_live_fight and event.status == "In Progress":
            output.append("\n⚠️ Event is 'In Progress' maar geen specifiek live gevecht geïdentificeerd.")
        
        # Voeg timestamp toe voor verse data
        output.append("\n🕒 Last Updated: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")))
        
        # Retourneer als plain text
        return Response("\n".join(output), mimetype='text/plain')
    except Exception as e:
        logger.error(f"Fout in home endpoint: {str(e)}")
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
        event = get_event_with_cache(event_fmid)
        
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
        logger.error(f"Fout in get_event endpoint voor event {event_fmid}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/status')
def api_status():
    """Endpoint om API status en cache informatie te tonen"""
    global event_cache, last_check_time
    
    cache_info = []
    for event_id, (cache_time, event) in event_cache.items():
        age = (datetime.now() - cache_time).total_seconds()
        cache_info.append({
            "event_id": event_id,
            "event_name": event.name,
            "cache_age_seconds": round(age),
            "fresh": age < CACHE_EXPIRY
        })
    
    return jsonify({
        "status": "online",
        "last_check": last_check_time.isoformat() if last_check_time else None,
        "cache_expiry_seconds": CACHE_EXPIRY,
        "cached_events": cache_info,
        "version": "1.2.0",
        "background_refresh_active": not os.environ.get('FLASK_DEBUG')
    })

@app.route('/debug/live-detection')
def debug_live_detection():
    try:
        event = get_event_with_cache(DEFAULT_CURRENT_EVENT_ID)
        debug_info = []
        debug_info.append(f"Event: {event.name}")
        debug_info.append(f"Status: {event.status}")
        
        # Cache status
        global event_cache, last_check_time
        if last_check_time:
            cache_age = (datetime.now() - last_check_time).total_seconds()
            debug_info.append(f"Cache Last Updated: {last_check_time.strftime('%Y-%m-%d %H:%M:%S')}")
            debug_info.append(f"Cache Age: {round(cache_age)} seconds (expires at {CACHE_EXPIRY} seconds)")
        
        # Controleer UFC.com rechtstreeks
        try:
            response = requests.get("https://www.ufc.com/events", timeout=5)
            if response.status_code == 200:
                if "LIVE NOW" in response.text:
                    debug_info.append("UFC.com toont 'LIVE NOW' indicator")
                else:
                    debug_info.append("Geen 'LIVE NOW' indicator gevonden op UFC.com")
                    
                # Zoek specifieke HTML elementen
                soup = BeautifulSoup(response.text, 'html.parser')
                live_elements = soup.find_all(string=lambda text: text and 'live' in text.lower())
                debug_info.append(f"Aantal elementen met 'live' tekst: {len(live_elements)}")
                for i, elem in enumerate(live_elements[:5]):  # Toon eerste 5
                    debug_info.append(f"  - Live element {i+1}: {elem.strip()}")
        except Exception as e:
            debug_info.append(f"Fout bij het controleren van UFC.com: {str(e)}")
        
        # Analyseer alle gevechten
        for segment in event.card_segments:
            debug_info.append(f"\nSegment: {segment.name}, Start: {segment.start_time}")
            
            for i, fight in enumerate(segment.fights):
                fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
                fighters_str = " vs. ".join(fighter_names)
                
                # Test de volledige detectielogica
                is_live = is_fight_live(fight, segment, event)
                
                # Bekijk details waarom wel/niet live
                has_result = bool(fight.result and fight.result.method)
                
                debug_info.append(f"Fight {i+1}: {fighters_str}")
                debug_info.append(f"  - Has Result: {has_result}")
                debug_info.append(f"  - Result: {fight.result.method if has_result else 'None'}")
                debug_info.append(f"  - Is Live: {is_live}")
                
                # Check vorige en volgende gevechten
                if i > 0:
                    prev_fight = segment.fights[i-1]
                    prev_complete = bool(prev_fight.result and prev_fight.result.method)
                    debug_info.append(f"  - Previous fight complete: {prev_complete}")
                
                if i < len(segment.fights) - 1:
                    next_fight = segment.fights[i+1]
                    next_complete = bool(next_fight.result and next_fight.result.method)
                    debug_info.append(f"  - Next fight complete: {next_complete}")
        
        return Response("\n".join(debug_info), mimetype="text/plain")
    except Exception as e:
        logger.error(f"Fout in debug endpoint: {str(e)}")
        return f"Error in debug: {str(e)}"

@app.route('/debug/simulate-live')
def debug_simulate_live():
    # Simuleer live event detectie
    try:
        event_id = DEFAULT_CURRENT_EVENT_ID
        
        # Gebruik query parameter als die er is
        if request.args.get('event_id'):
            try:
                event_id = int(request.args.get('event_id'))
            except:
                pass
                
        event = get_event_with_cache(event_id)
        
        debug_info = []
        debug_info.append(f"Event: {event.name}")
        debug_info.append(f"Originele Status: {event.status}")
        
        # Maak een kopie van de belangrijkste eigenschappen (kan niet direct wijzigen door frozen=True)
        event_info = {
            "naam": event.name,
            "status": "In Progress",  # Gesimuleerde status
            "originele_status": event.status
        }
        debug_info.append(f"Gesimuleerde Status: In Progress")
        
        # Zoek een geschikt gevecht om te simuleren als "live"
        live_fight_found = False
        
        for segment in event.card_segments:
            debug_info.append(f"\nSegment: {segment.name}")
            
            for i, fight in enumerate(segment.fights):
                fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
                fighters_str = " vs. ".join(fighter_names)
                
                # Voor gesimuleerde detectie, zoek naar een niet-afgemaakt gevecht
                if not (fight.result and fight.result.method):
                    # Als dit gevecht geen resultaat heeft, maar voorgaande wel
                    is_candidate = True
                    
                    # Check of alle voorgaande gevechten resultaten hebben
                    for j in range(0, i):
                        prev_fight = segment.fights[j]
                        if not (prev_fight.result and prev_fight.result.method):
                            is_candidate = False
                            break
                            
                    if is_candidate:
                        live_fight_found = True
                        debug_info.append(f"Gesimuleerd LIVE fight: {fighters_str}")
                        debug_info.append("  (Dit gevecht zou als LIVE gemarkeerd worden als het event 'In Progress' was)")
                        
                        # Geef details 
                        debug_info.append(f"  - Fight positie: {i+1} van {len(segment.fights)}")
                        debug_info.append(f"  - Voorgaande gevechten hebben resultaten: Ja")
                        if i < len(segment.fights) - 1:
                            has_next = "Ja"
                            next_fight = segment.fights[i+1]
                            next_has_results = bool(next_fight.result and next_fight.result.method)
                            debug_info.append(f"  - Volgende gevecht heeft resultaat: {next_has_results}")
                        else:
                            debug_info.append(f"  - Laatste gevecht in segment: Ja")
                        
                        break
            
            if live_fight_found:
                break
        
        if not live_fight_found:
            debug_info.append("\nGeen geschikt gevecht gevonden om als LIVE te simuleren.")
            
            # Zoek niet-afgeronde gevechten om te analyseren waarom ze niet als live worden gedetecteerd
            no_result_fights = []
            for segment in event.card_segments:
                for i, fight in enumerate(segment.fights):
                    if not (fight.result and fight.result.method):
                        fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
                        fighters_str = " vs. ".join(fighter_names)
                        no_result_fights.append((segment.name, i, fighters_str))
            
            if no_result_fights:
                debug_info.append("\nGevechten zonder resultaat die niet als LIVE worden gedetecteerd:")
                for seg_name, idx, fighters in no_result_fights:
                    debug_info.append(f" - {seg_name}, Gevecht {idx+1}: {fighters}")
                    
                    # Geef mogelijke redenen
                    if idx > 0:
                        segment = next((s for s in event.card_segments if s.name == seg_name), None)
                        if segment:
                            prev_fight = segment.fights[idx-1]
                            if not (prev_fight.result and prev_fight.result.method):
                                debug_info.append(f"   Reden: Voorgaand gevecht heeft geen resultaat")
            else:
                debug_info.append("Alle gevechten hebben resultaten (afgelopen event).")
        
        # Instructies voor gebruik
        debug_info.append("\n\nInstructies voor testen tijdens een live event:")
        debug_info.append("1. Controleer de UFC website om te zien welk gevecht live is")
        debug_info.append("2. Ga naar /debug/live-detection om te zien of dat gevecht correct wordt gedetecteerd")
        debug_info.append("3. Als het event status 'In Progress' heeft maar geen gevecht als live is gemarkeerd,")
        debug_info.append("   controleer dan of de detectielogica correct functioneert")
        
        return Response("\n".join(debug_info), mimetype="text/plain")
    except Exception as e:
        logger.error(f"Fout in simulatie endpoint: {str(e)}")
        return f"Error in simulation: {str(e)}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
