"""Dedicated persistent worker for scheduled hosting expiry."""
import os, time, logging
from app import app, process_expirations

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

if __name__ == "__main__":
    interval = max(15, int(os.environ.get("EXPIRY_CHECK_SECONDS", "30")))
    logging.info("CloudNest expiry worker started; interval=%s seconds", interval)
    while True:
        try:
            with app.app_context():
                process_expirations()
        except Exception:
            logging.exception("Expiry worker cycle failed")
        time.sleep(interval)
