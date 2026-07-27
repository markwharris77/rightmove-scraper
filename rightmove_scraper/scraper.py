"""
rightmove_scraper - Reusable Python module for scraping Rightmove property listings.

This module parses the embedded ``__NEXT_DATA__`` JSON available on Rightmove
search results pages, which is more reliable than HTML-based scraping.

Basic usage::

    from rightmove_scraper import search, SearchParams

    params = SearchParams(
        location="REGION^93917",       # Greater London
        sale_type="buy",
        min_price=200000,
        max_price=500000,
        min_bedrooms=2,
        max_bedrooms=3,
    )

    for page in search(params, max_pages=5):
        for prop in page:
            print(prop.price, prop.address, prop.bedrooms)
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Data-model classes
# ---------------------------------------------------------------------------


@dataclass
class PropertyImage:
    """A single photo of a property."""

    url: str
    caption: str


@dataclass
class PropertyLocation:
    latitude: float
    longitude: float


@dataclass
class PriceInfo:
    """Structured price information."""

    amount: int  # raw numeric amount (e.g. 630000)
    currency_code: str  # e.g. "GBP"
    display_price: str  # formatted string (e.g. "£630,000")
    display_qualifier: str  # e.g. "", "per month", "per week"
    frequency: str  # "not specified" for sale, "monthly" for rent
    is_poa: bool = False  # Price on Application


@dataclass
class PropertyResult:
    """A single property listing returned from a search."""

    id: int
    bedrooms: int
    bathrooms: int
    summary: str
    address: str
    price: PriceInfo
    location: PropertyLocation
    property_type: Optional[str] = None
    images: List[PropertyImage] = field(default_factory=list)
    floorplan_count: int = 0
    virtual_tour_count: int = 0
    agent_name: Optional[str] = None
    agent_phone: Optional[str] = None
    added_or_reduced: Optional[str] = None
    featured: bool = False
    url: str = ""

    def __post_init__(self):
        if not self.url:
            self.url = f"https://www.rightmove.co.uk/properties/{self.id}"


@dataclass
class SearchParams:
    """Parameters for a Rightmove property search.

    Parameters
    ----------
    location : str
        Rightmove location identifier, e.g. ``"REGION^93917"`` (Greater London),
        ``"STATION^2811"`` (within 1 mi of a train station), or a free-text
        postcode / area.
    sale_type : str
        ``"buy"`` (property-for-sale) or ``"rent"`` (property-to-rent).
    radius : float, optional
        Search radius in miles (0 = this area only, 0.25, 0.5, 1, 3, 5, …).
    min_price : int, optional
        Minimum price in GBP.
    max_price : int, optional
        Maximum price in GBP.
    min_bedrooms : int, optional
        Minimum number of bedrooms.
    max_bedrooms : int, optional
        Maximum number of bedrooms.
    property_type : str, optional
        Filter by property type.
        Common options: "detached", "semi-detached", "terraced", "flat",
        "bungalow", "park-home".
    max_days_added : int, optional
        Only show listings added within this many days (1, 3, 7, 14, 30).
        Rightmove values: 1, 3, 7, 14, 30.
    include_sstc : bool
        Include "Sold Subject to Contract" properties (buy only). Default False.
    sort_by : str, optional
        Sort order. Options: "newest", "oldest", "lowest_price", "highest_price",
        "reduced". Default "highest_price" (buy) or "newest" (rent).
    must_have : List[str], optional
        Keywords to prioritise (e.g. ["garden", "parking", "balcony"]).
    """

    location: str = ""
    sale_type: str = "buy"
    radius: float = 0.0
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_bedrooms: Optional[int] = None
    max_bedrooms: Optional[int] = None
    property_type: Optional[str] = None
    max_days_added: Optional[int] = None
    include_sstc: bool = False
    sort_by: Optional[str] = None
    must_have: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SORT_MAP = {
    "newest": 6,
    "oldest": 10,
    "lowest_price": 2,
    "highest_price": 1,
    "reduced": 16,
}

_PROPERTY_TYPE_MAP = {
    "detached": "detached",
    "semi-detached": "semi-detached",
    "terraced": "terraced",
    "flat": "flat",
    "bungalow": "bungalow",
    "park-home": "park-home",
    "land": "land",
}

_MAX_RADIUS_OPTIONS = [0, 0.25, 0.5, 1, 3, 5, 10, 15, 20, 30, 40]


def _clamp_radius(radius: float) -> float:
    """Snap *radius* to the nearest allowed value."""
    return min(_MAX_RADIUS_OPTIONS, key=lambda x: abs(x - radius))


def _build_url(params: SearchParams, index: int = 0) -> str:
    """Build the Rightmove search URL for the given *params* and page *index*."""
    endpoint = (
        "property-for-sale"
        if params.sale_type == "buy"
        else "property-to-rent"
    )

    sort_val = params.sort_by or ("highest_price" if params.sale_type == "buy" else "newest")
    sort_id = _SORT_MAP.get(sort_val, 6)

    query = {
        "searchType": "SALE" if params.sale_type == "buy" else "RENT",
        "locationIdentifier": params.location,
        "insId": "1",
        "radius": _clamp_radius(params.radius),
        "minPrice": str(params.min_price) if params.min_price else "",
        "maxPrice": str(params.max_price) if params.max_price else "",
        "minBedrooms": str(params.min_bedrooms) if params.min_bedrooms else "",
        "maxBedrooms": str(params.max_bedrooms) if params.max_bedrooms else "",
        "maxDaysSinceAdded": str(params.max_days_added) if params.max_days_added else "",
        "includeSSTC": "true" if params.include_sstc else "false",
        "sortBy": str(sort_id),
        "index": str(index),
        "propertyType": "",
        "primaryDisplayPropertyType": "",
        "secondaryDisplayPropertyType": "",
        "oldDisplayPropertyType": "",
        "oldPrimaryDisplayPropertyType": "",
        "newHome": "",
        "auction": "false",
    }

    base = f"https://www.rightmove.co.uk/{endpoint}/find.html"
    return f"{base}?{urlencode(query)}"


def _extract_properties_from_html(html: str) -> Tuple[List[dict], dict, int]:
    """Parse ``__NEXT_DATA__`` from *html* and return (properties, pagination, total_results)."""
    soup = BeautifulSoup(html, "html.parser")
    script_tag = soup.find("script", id="__NEXT_DATA__", type="application/json")
    if not script_tag:
        return [], {}, 0

    data = json.loads(script_tag.string)
    search_results = data.get("props", {}).get("pageProps", {}).get("searchResults", {})
    properties_raw = search_results.get("properties", [])
    pagination = search_results.get("pagination", {})
    result_count_raw = search_results.get("resultCount", "0")

    # "80,875" -> 80875
    total_results = int(re.sub(r"[^0-9]", "", str(result_count_raw)))

    return properties_raw, pagination, total_results


_PRICE_EXTRACT_RE = re.compile(r"£?([0-9,]+)")


def _parse_price(raw: dict) -> PriceInfo:
    """Convert the raw price dict from Rightmove into a ``PriceInfo``."""
    amount = raw.get("amount") or 0
    currency = raw.get("currencyCode", "GBP")
    display = raw.get("displayPrices", [{}])[0]
    freq = raw.get("frequency", "not specified")
    return PriceInfo(
        amount=amount,
        currency_code=currency,
        display_price=display.get("displayPrice", f"£{amount:,}"),
        display_qualifier=display.get("displayPriceQualifier", ""),
        frequency=freq,
        is_poa=(amount == 0),
    )


def _parse_property(raw: dict) -> PropertyResult:
    """Convert a raw property dict from the Rightmove API into a ``PropertyResult``."""
    price_raw = raw.get("price", {})
    loc_raw = raw.get("location", {})

    return PropertyResult(
        id=raw["id"],
        bedrooms=raw.get("bedrooms", 0),
        bathrooms=raw.get("bathrooms", 0),
        summary=raw.get("summary", "").strip(),
        address=raw.get("displayAddress", ""),
        price=_parse_price(price_raw),
        location=PropertyLocation(
            latitude=loc_raw.get("latitude", 0.0),
            longitude=loc_raw.get("longitude", 0.0),
        ),
        property_type=raw.get("propertyType"),
        images=[
            PropertyImage(url=img.get("srcUrl", ""), caption=img.get("caption", ""))
            for img in raw.get("images", [])
        ],
        floorplan_count=raw.get("numberOfFloorplans", 0),
        virtual_tour_count=raw.get("numberOfVirtualTours", 0),
        featured=raw.get("featuredProperty", False) or raw.get("premiumListing", False),
        added_or_reduced=raw.get("addedOrReduced"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search(
    params: Optional[SearchParams] = None,
    max_pages: int = 1,
    delay: float = 1.0,
    session: Optional[requests.Session] = None,
    **kwargs,
) -> Iterator[List[PropertyResult]]:
    """Search Rightmove and yield pages of property results.

    Each yielded value is a ``list`` of ``PropertyResult`` objects for a single
    result page (typically 24 results).  Iterate over the generator to get
    results from subsequent pages, up to ``max_pages``.

    Parameters
    ----------
    params : SearchParams, optional
        Structured search parameters.  If omitted, a ``SearchParams`` will be
        constructed from the **kwargs.
    max_pages : int
        Maximum number of result pages to fetch (default 1).  Set to ``0`` for
        all available pages.
    delay : float
        Seconds to wait between page requests (default 1.0).  Be respectful.
    session : requests.Session, optional
        Reusable requests session.  A fresh one is created when omitted.
    **kwargs
        Any ``SearchParams`` field can be passed as a keyword argument instead
        of building a ``SearchParams`` object explicitly.

    Yields
    ------
    List[PropertyResult]
        A single page of results.

    Examples
    --------
    >>> from rightmove_scraper import search
    >>> for page in search(location="REGION^93917", min_price=300000, max_pages=2):
    ...     for p in page:
    ...         print(p.price.display_price, p.address, p.bedrooms)
    """
    if params is None:
        params = SearchParams(**kwargs)

    sess = session or requests.Session()
    sess.headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )

    index = 0
    page_count = 0

    while True:
        if max_pages > 0 and page_count >= max_pages:
            break

        url = _build_url(params, index=index)
        resp = sess.get(url, timeout=30)
        resp.raise_for_status()

        properties_raw, pagination, total_results = _extract_properties_from_html(resp.text)

        if not properties_raw:
            break

        parsed = [_parse_property(p) for p in properties_raw]
        page_count += 1
        yield parsed

        # Determine next page index
        next_idx = pagination.get("next")
        if next_idx is None:
            break
        index = int(next_idx)
        if index == 0:  # shouldn't happen, but be safe
            break

        if delay > 0:
            time.sleep(delay)

    if session is None:
        sess.close()


def get_property_details(property_id: int, session: Optional[requests.Session] = None) -> dict:
    """Fetch the full details page for a single property.

    Returns the raw ``__NEXT_DATA__`` JSON dict so callers can extract whichever
    fields they need (e.g. full description, floorplan images, agent info).

    Parameters
    ----------
    property_id : int
        The Rightmove property ID.
    session : requests.Session, optional
        Reusable session.

    Returns
    -------
    dict
        The parsed ``__NEXT_DATA__`` JSON blob from the property detail page.
    """
    sess = session or requests.Session()
    url = f"https://www.rightmove.co.uk/properties/{property_id}"
    resp = sess.get(url, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__", type="application/json")
    if not script:
        raise ValueError(f"No __NEXT_DATA__ found on property page {property_id}")

    data = json.loads(script.string)
    if session is None:
        sess.close()
    return data