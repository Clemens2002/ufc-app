from flask import Flask, jsonify
from ufc_data_scraper.ufc_scraper import (
    get_event_fmid,
    scrape_fighter_url,
    scrape_event_url,
    scrape_event_fmid,
)

app = Flask(__name__)
