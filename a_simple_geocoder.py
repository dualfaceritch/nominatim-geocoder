
import os
import sys
import time
import argparse
import requests
import pandas as pd

# ---------- Setup ----------

# Nominatim's usage policy requires a User-Agent that identifies your app.
# os.getenv reads an environment variable so your real email stays out of the
# code (important if you push to a public GitHub repo).
# The second argument is the fallback used when the variable isn't set.
HEADERS = {
    "User-Agent": f"PortfolioGeocoder/1.0 ({os.getenv('CONTACT_EMAIL', 'you@example.com')})"
}


# A Session reuses the same connection for every request, which is faster
# than calling requests.get() each time. Headers set here apply to all calls.
session = requests.Session()
session.headers.update(HEADERS)

MIN_IMPORTANCE = 0.1  # below this --> "needs_review"
REQUEST_DELAY = 1   # seconds between requests (nominatim policy)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description = "Geocode Addresses using the OpenStreetMap using Nominatim API"
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        default="addresses.txt",
        help="Path to the input text file (default: addresses.txt)",

        )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="geocoded_addresses.csv",
        help="Output CSV path (default: geocoded_addresses.csv)"
        )
    return parser.parse_args()
# ---------- Geocoding one address ----------

def geocode_address(address: str, retries: int = 3) -> dict:
    # Build the "empty" result first. Every code path returns the same keys,
    # so the DataFrame you create later always has consistent columns.
    base = {
        "address": address,
        "lat": None,
        "lon": None,
        "display_name": None,
        "confidence": None,
        "status": "not_found",
        "used_fallback": False,
    }

    # Networks fail randomly (timeouts, rate limits), so try a few times
    # instead of letting one failure kill the whole run.
    for attempt in range(retries):
        try:
            r = session.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": address, "format": "jsonv2", "limit": 1},
                timeout=15,  # without a timeout, a dead connection hangs forever
            )

            # 429 = "Too Many Requests": the server wants you to slow down.
            # Wait longer on each attempt (5s, 10s, 15s). This is "backoff".
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue  # skip the rest of this pass and try again

            # Raises an exception for other bad codes (404, 500, ...),
            # which the except block below catches.
            r.raise_for_status()

            data = r.json()

            # Empty list = Nominatim found nothing.
            if not data:
                return base

            top = data[0]  # limit=1, so there's only one result


            # It's a rough quality signal. Tune MIN_IMPORTANCE at the top of the file.
            importance = float(top.get("importance", 0))

            # .update() overwrites only the keys we give it.
            # float() converts the lat/lon strings from the API into numbers.
            base.update(
                lat=float(top["lat"]),
                lon=float(top["lon"]),
                display_name=top.get("display_name"),
                confidence=round(importance, 2),
                status="found" if importance >= MIN_IMPORTANCE else "needs_review",
            )
            return base

        # RequestException is the parent class of timeouts, connection errors
        # and HTTP errors, so one except catches all of them.
        except requests.RequestException as e:
            print(f"  [!] Request failed: {e}")
            time.sleep(2 * (attempt + 1))

    # Every attempt failed. "error" is different from "not_found":
    # one means the request kept failing, the other means no match exists.
    base["status"] = "error"
    return base

def geocode_with_fallback(address: str) -> dict:
    """
    Try the full address first, then progressively drop leading parts.

    Example: "123 Main St, Springfield, IL, USA"
      i=0 -> "123 Main St, Springfield, IL, USA"
      i=1 -> "Springfield, IL, USA"
      i=2 -> "IL, USA"
      i=3 -> "USA"
    """
    parts = [p.strip() for p in address.split(",") if p.strip()]

    # try full address, then drop the first part, then the next...
    for i in range(len(parts)):
        query = ",".join(parts[i:])
        result = geocode_address(query)
        
        if result['status'] not in ("not_found", "error"):
            result['address'] = address     # keep original input
            result['used_fallback'] = (i >0) # separate columns
            return result
        time.sleep(REQUEST_DELAY)   
    
    # Nothing matched. reuse the last's attempt result instead of re-querying  
    result['address'] = address                  
    return result             


def get_unique_filename(filename: str) ->str:
    # split "geocoded_addresses.csv" into ("geocoded_addresses", ".csv")
    name , ext = os.path.splitext(filename)

    # if file doesnt exist yet, we can use the name as it is.
    if not os.path.exists(filename):
        return filename

    # otherwise keep counting up until we find a name that's free
    counter = 2
    while os.path.exists(f"{name}({counter}){ext}"):
        counter += 1
    return f"{name}({counter}){ext}"    


# ---------- Main program ----------

# This block only runs when you execute the file directly
# (python geocoder.py), not when another file imports it.
if __name__ == "__main__":
    args = parse_args()
    
    if not os.path.exists(args.input_file):
        print(f"Error: input file not found: {args.input_file}")
        sys.exit(1)

    # Read addresses, stripping whitespace and skipping blank lines.
    with open(args.input_file, "r", encoding="utf-8") as f:
        addresses = [line.strip() for line in f if line.strip()]

    results = []
    print(f"Starting geocoding of {len(addresses)} addresses...\n")

    for a in addresses:
        print(f"Geocoding: {a}")
        result = geocode_with_fallback(a)  # use the fallback
        results.append(result)

        # Show a short status line for each address.
        if result["status"] in ("found", "needs_review"):
            name = result["display_name"] or "No name available"
            short_name = name[:60] + "..." if len(name) > 60 else name

            tag = " (fallback)" if result['used_fallback'] else ""
            print(f"  --> {result['status']}{tag}: {short_name}")
        else:
            print(f"  --> {result['status']}")

        print("-" * 60)

        # Important: Nominatim allows at most 1 request per second.
        # This pause is between addresses; the retry logic above handles
        # failures for a single address.
        time.sleep(1)

    # A list of dictionaries turns directly into a DataFrame.
    df = pd.DataFrame(results)

    # Reorder and rename columns to be client-friendly.
    df = df[["address", "lat", "lon", "display_name", "confidence", "status", "used_fallback"]]

    df.columns = ["Input Address", "Latitude", "Longitude",
                  "Matched Name", "Confidence", "Status", "Used Fallback"]

    print("\n======= RESULTS =======")
    print(df.head().to_string(index=False)) #show preview       

    # use the output filename from argparse
    output_file = get_unique_filename(args.output)
    df.to_csv(output_file, index=False)
    print(f"\nSaved to: {output_file}")
