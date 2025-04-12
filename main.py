from src.ufc_app import app
import os

# Alleen als dit script direct wordt uitgevoerd
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
