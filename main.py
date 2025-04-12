from ufc_data_scraper import ufc_scraper

# Vervang dit met het juiste FMID voor je event
event_fmid = 1251
event = ufc_scraper.scrape_event_fmid(event_fmid)

print(f"\n📅 Event: {event.name}\n")

for segment in event.card_segments:
    print(f"🎬 Segment: {segment.name} - Start: {segment.start_time}")
    for fight in segment.fights:
        fighter_names = [fs.fighter.name for fs in fight.fighters_stats]
        print(" 🥋 " + " vs. ".join(fighter_names))

        if fight.result and fight.result.method:
            print(f"   ✅ Result: {fight.result.method}")
            print(f"   ⏱️  Ended in round {fight.result.ending_round} at {fight.result.ending_time}")
        else:
            print("   🕒 Status: Not yet finished")

        print("-" * 50)
