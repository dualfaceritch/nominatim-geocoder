# Portfolio Geocoder

Geocodes addresses via Nominatim (OpenStreetMap) with:
- Automatic retries with backoff on failures and rate limits
- Progressive fallback: drops leading address parts when the full match fails
- A "needs_review" status for low-confidence matches
- CSV output that never overwrites existing files

## Run

    pip install -r requirements.txt
    export CONTACT_EMAIL=you@example.com
    python a_simple_geocoder.py addresses.txt

## Output

A CSV with columns: Input Address, Latitude, Longitude, Matched Name,
Confidence, Status, Used Fallback.
