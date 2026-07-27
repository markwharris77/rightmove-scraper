#!/usr/bin/env python3
"""Example: Find 2-bedroom flats for sale in Greater London under £500k."""

from rightmove_scraper import search


def main():
    print("Searching for 2-bed flats in Greater London under £500k...\n")

    for page in search(
        location="REGION^93917",  # Greater London
        sale_type="buy",
        min_bedrooms=2,
        max_bedrooms=2,
        max_price=500000,
        property_type="flat",
        max_pages=3,
        delay=1.5,
    ):
        print(f"--- Page with {len(page)} results ---")
        for p in page:
            print(f"{p.price.display_price:>12}  {p.bedrooms} bed  {p.address}")
        print()


if __name__ == "__main__":
    main()