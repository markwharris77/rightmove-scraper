# Rightmove Scraper

A reusable Python module to scrape property listings from Rightmove.

No HTML parsing — extracts data from the embedded `__NEXT_DATA__` JSON on Rightmove search pages, making it reliable and simple.

## Installation

```bash
pip install -r requirements.txt
```

Or with uv:

```bash
uv pip install -r requirements.txt
```

## Quick Start

```python
from rightmove_scraper import search

# Find 2-bed flats in Greater London under £500k
for page in search(
    location="REGION^93917",
    sale_type="buy",
    min_bedrooms=2,
    max_bedrooms=2,
    max_price=500000,
    property_type="flat",
    max_pages=3,
):
    for prop in page:
        print(f"{prop.price.display_price:>12}  {prop.bedrooms} bed  {prop.address}")
```

## Finding Location Identifiers

Browse Rightmove normally and look at the URL — the `locationIdentifier` query param is what you need:

- `REGION^93917` — Greater London
- `REGION^87414` — Manchester
- `REGION^55076` — Birmingham
- `REGION^117` — Scotland
- `STATION^2811` — Within 1 mile of a train station
- `OUTCODE^B20` — A postcode area
- Free text — just paste a location name or postcode

## API Reference

### `search(params=None, max_pages=1, delay=1.0, session=None, **kwargs)`

Generator that yields pages of `PropertyResult` objects.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `params` | `SearchParams` | `None` | Structured params object |
| `max_pages` | `int` | `1` | Max result pages (24/page). `0` = all |
| `delay` | `float` | `1.0` | Seconds between requests |
| `session` | `requests.Session` | `None` | Reusable HTTP session |
| `**kwargs` | — | — | Any `SearchParams` field as keyword |

### `SearchParams`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `location` | `str` | `""` | Rightmove location identifier |
| `sale_type` | `str` | `"buy"` | `"buy"` or `"rent"` |
| `radius` | `float` | `0.0` | Search radius in miles |
| `min_price` | `int` | `None` | Minimum price (£) |
| `max_price` | `int` | `None` | Maximum price (£) |
| `min_bedrooms` | `int` | `None` | Minimum bedrooms |
| `max_bedrooms` | `int` | `None` | Maximum bedrooms |
| `property_type` | `str` | `None` | `"flat"`, `"detached"`, `"terraced"`, etc. |
| `max_days_added` | `int` | `None` | `1`, `3`, `7`, `14`, or `30` |
| `include_sstc` | `bool` | `False` | Include sold subject to contract |
| `sort_by` | `str` | `None` | `"newest"`, `"oldest"`, `"lowest_price"`, `"highest_price"`, `"reduced"` |
| `must_have` | `List[str]` | `[]` | Keywords to prioritise |

### `PropertyResult`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `int` | Rightmove property ID |
| `bedrooms` | `int` | Number of bedrooms |
| `bathrooms` | `int` | Number of bathrooms |
| `summary` | `str` | Description text |
| `address` | `str` | Display address |
| `price` | `PriceInfo` | Structured price info |
| `location` | `PropertyLocation` | Latitude/longitude |
| `property_type` | `str` | Property type |
| `images` | `List[PropertyImage]` | Photos |
| `url` | `str` | Property detail page URL |
| `agent_name` | `str` | Estate agent name (detail page) |
| `featured` | `bool` | Featured/premium listing |

## Notes

- Respect Rightmove's terms of service — this is for personal use only
- Add a polite `delay` between requests
- Rightmove may block aggressive scraping