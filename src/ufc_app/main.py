from ufc_data_scraper.ufc_scraper import scrape_event_url

if __name__ == "__main__":
    url = "https://www.ufc.com/event/ufc-282"
    event = scrape_event_url(url)
    print("Event name:", event.name)
    print("Status:", event.status)
