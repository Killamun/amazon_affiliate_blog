#!/usr/bin/env python3
"""
Amazon Affiliate Blog + Pinterest Generator
------------------------------------------
Works in two modes:
1. Manual Entry (no API needed) – paste Amazon links + product details
2. Live Search (requires Amazon Creators API credentials)

Your Associate Tag is used on every product link.
"""

import os
import io
import re
import textwrap
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import requests
import streamlit as st
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

# Optional Amazon Creators API
try:
    from amazon_creatorsapi import AmazonCreatorsApi, Country
    from amazon_creatorsapi.models import SortBy, SearchItemsResource, Condition
    HAS_AMAZON_LIB = True
except ImportError:
    HAS_AMAZON_LIB = False

load_dotenv()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_TAG = "familytreed01-20"


def extract_asin(url_or_asin: str) -> str | None:
    """Extract ASIN from an Amazon URL or return the string if it already looks like an ASIN."""
    text = url_or_asin.strip()

    # Already an ASIN?
    if re.fullmatch(r"[A-Z0-9]{10}", text, re.IGNORECASE):
        return text.upper()

    # Common Amazon URL patterns
    patterns = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/product/([A-Z0-9]{10})",
        r"asin=([A-Z0-9]{10})",
        r"/([A-Z0-9]{10})(?:[/?]|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return None


def make_affiliate_link(asin_or_url: str, tag: str = DEFAULT_TAG) -> str:
    """Turn any Amazon link or ASIN into a clean affiliate link."""
    asin = extract_asin(asin_or_url)
    if asin:
        return f"https://www.amazon.com/dp/{asin}?tag={tag}"
    # Fallback – just append the tag if possible
    if "amazon." in asin_or_url and "tag=" not in asin_or_url:
        separator = "&" if "?" in asin_or_url else "?"
        return f"{asin_or_url}{separator}tag={tag}"
    return asin_or_url


def get_api():
    """Create AmazonCreatorsApi client if credentials exist."""
    def get_val(key, default=""):
        if key in st.session_state and st.session_state.get(key):
            return st.session_state[key]
        try:
            if key in st.secrets:
                return st.secrets[key]
        except Exception:
            pass
        return os.getenv(key, default)

    cred_id = get_val("AMAZON_CREDENTIAL_ID") or get_val("cred_id")
    cred_secret = get_val("AMAZON_CREDENTIAL_SECRET") or get_val("cred_secret")
    tag = get_val("AMAZON_PARTNER_TAG") or get_val("partner_tag") or DEFAULT_TAG
    version = get_val("AMAZON_API_VERSION", "2.2")

    if not all([cred_id, cred_secret]):
        return None, tag

    try:
        api = AmazonCreatorsApi(
            credential_id=cred_id.strip(),
            credential_secret=cred_secret.strip(),
            version=version.strip(),
            tag=tag.strip(),
            country=Country.US,
            throttling=1.0,
        )
        return api, tag
    except Exception:
        return None, tag


def search_high_ticket_products(api, niche: str, min_price_cents: int, max_items: int = 6):
    """Search Amazon (only works with Creators API)."""
    resources = [
        SearchItemsResource.ITEM_INFO_DOT_TITLE,
        SearchItemsResource.IMAGES_DOT_PRIMARY_DOT_LARGE,
        SearchItemsResource.IMAGES_DOT_PRIMARY_DOT_MEDIUM,
        SearchItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_PRICE,
        SearchItemsResource.ITEM_INFO_DOT_FEATURES,
        SearchItemsResource.CUSTOMER_REVIEWS_DOT_STAR_RATING,
        SearchItemsResource.CUSTOMER_REVIEWS_DOT_COUNT,
    ]

    result = api.search_items(
        keywords=niche,
        search_index="All",
        item_count=min(10, max_items + 4),
        min_price=min_price_cents,
        min_reviews_rating=4,
        sort_by=SortBy.AVGCUSTOMERREVIEWS,
        condition=Condition.NEW,
        resources=resources,
    )

    products = []
    for item in (result.items or []):
        try:
            title = item.item_info.title.display_value if item.item_info and item.item_info.title else "Unknown"
            image_url = None
            if item.images and item.images.primary:
                image_url = (item.images.primary.large.url if item.images.primary.large
                             else item.images.primary.medium.url if item.images.primary.medium else None)

            price = None
            currency = "USD"
            if item.offers_v2 and item.offers_v2.listings:
                listing = item.offers_v2.listings[0]
                if listing.price and listing.price.money:
                    price = listing.price.money.amount
                    currency = listing.price.money.currency_code or "USD"

            url = getattr(item, "detail_page_url", None) or f"https://www.amazon.com/dp/{item.asin}?tag={api.tag}"

            features = []
            if item.item_info and item.item_info.features and item.item_info.features.display_values:
                features = item.item_info.features.display_values[:5]

            rating = None
            review_count = 0
            if item.customer_reviews:
                if item.customer_reviews.star_rating:
                    rating = item.customer_reviews.star_rating.value
                if item.customer_reviews.count:
                    review_count = item.customer_reviews.count

            if price is None or price < (min_price_cents / 100):
                continue

            products.append({
                "asin": item.asin,
                "title": title,
                "image_url": image_url,
                "price": float(price),
                "currency": currency,
                "url": url,
                "features": features,
                "rating": rating,
                "review_count": review_count,
            })
        except Exception:
            continue

    products.sort(key=lambda p: ((p["rating"] or 0) * 20 + (p["review_count"] or 0) / 1000), reverse=True)
    return products[:max_items]
