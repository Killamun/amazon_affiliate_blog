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
def generate_blog_html(niche: str, products: list, year: int = None) -> str:
    year = year or datetime.now().year
    title = f"Best High-Ticket {niche.title()} in {year} – Top Premium Picks Worth Investing In"

    html_parts = [
        f"<h1>{title}</h1>",
        f"""
<p><em>Disclosure: As an Amazon Associate I earn from qualifying purchases. 
This post contains affiliate links. Prices and availability are accurate as of the publish date and may change.</em></p>

<p>Looking for premium, high-ticket {niche.lower()} that actually deliver value? 
We researched the most popular and highly-rated options currently available on Amazon. 
These are the products people are willing to spend more on because of quality, features, and proven performance.</p>

<p>Below are our top picks ranked by a combination of customer ratings, review volume, and overall popularity in the {niche.lower()} category.</p>
"""
    ]

    for i, p in enumerate(products, 1):
        price_str = f"${p['price']:.2f}" if p.get("currency", "USD") == "USD" else f"{p['price']:.2f} {p.get('currency', '')}"
        rating_str = f"{p['rating']:.1f}★ ({p.get('review_count', 0):,} reviews)" if p.get("rating") else "Highly rated"
        features_html = ""
        if p.get("features"):
            features_html = "<ul>" + "".join(f"<li>{f}</li>" for f in p["features"]) + "</ul>"

        img_html = ""
        if p.get("image_url"):
            img_html = f'<p><img src="{p["image_url"]}" alt="{p["title"]}" style="max-width:100%;height:auto;border-radius:8px;" loading="lazy"></p>'

        html_parts.append(f"""
<hr>
<h2>{i}. {p["title"]}</h2>
{img_html}
<p><strong>Price:</strong> {price_str} &nbsp;|&nbsp; <strong>Rating:</strong> {rating_str}</p>
<p>This standout {niche.lower()} option earns its high-ticket price through a combination of premium build quality, thoughtful features, and strong customer satisfaction. 
It consistently ranks among the most popular choices for buyers who want something that lasts and performs at a higher level.</p>
{features_html}
<p><a href="{p["url"]}" target="_blank" rel="nofollow sponsored" style="display:inline-block;background:#ff9900;color:#111;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">Check Current Price on Amazon →</a></p>
""")

    html_parts.append(f"""
<hr>
<h2>Final Thoughts</h2>
<p>Investing in high-quality {niche.lower()} pays off when you choose items with proven track records. 
The products above represent some of the most popular premium options available right now. 
Always double-check the latest reviews and pricing before purchasing, and consider your specific needs (size, features, warranty, etc.).</p>

<p>Which of these caught your eye? Let us know in the comments!</p>

<p><small>Last updated: {datetime.now().strftime("%B %d, %Y")}</small></p>
""")

    return "\n".join(html_parts)


def generate_pinterest_caption(niche: str, products: list) -> str:
    titles = [p["title"][:60] + "…" if len(p["title"]) > 60 else p["title"] for p in products[:3]]
    caption = f"""🔥 Best High-Ticket {niche.title()} on Amazon Right Now ({datetime.now().year})

Premium picks that people are actually buying and loving:

• {titles[0] if titles else "Top rated option"}
• {titles[1] if len(titles) > 1 else ""}
• {titles[2] if len(titles) > 2 else ""}

These are the higher-priced items that deliver real quality and strong reviews. Perfect if you’re ready to invest in something that lasts.

👉 Full roundup + current prices linked in bio / on the blog

#AmazonFinds #HighTicketAffiliate #AmazonMustHaves #{niche.replace(" ", "")} #PremiumFinds #AffiliateMarketing #AmazonDeals
"""
    return caption.strip()


def create_pinterest_image(niche: str, products: list) -> Image.Image:
    """Create a vertical 1000×1500 Pinterest pin."""
    W, H = 1000, 1500
    bg_color = (25, 25, 35)
    accent = (255, 153, 0)

    img = Image.new("RGB", (W, H), bg_color)
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    except Exception:
        font_large = ImageFont.load_default()
        font_med = font_large
        font_small = font_large

    # Header
    y = 40
    for line in [f"Best High-Ticket", f"{niche.title()}"]:
        bbox = draw.textbbox((0, 0), line, font=font_large)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, y), line, fill=(255, 255, 255), font=font_large)
        y += 60

    draw.text((W // 2, y + 10), f"Premium Picks {datetime.now().year}", fill=accent, font=font_med, anchor="mt")

    products = products[:4]
    thumbs = []
    for p in products:
        if not p.get("image_url"):
            continue
        try:
            resp = requests.get(p["image_url"], timeout=8)
            resp.raise_for_status()
            thumb = Image.open(io.BytesIO(resp.content)).convert("RGB")
            thumbs.append((thumb, p))
        except Exception:
            continue

    if not thumbs:
        draw.text((W // 2, H // 2), "Add product images for a better pin", fill=(180, 180, 180), font=font_med, anchor="mm")
        return img

    margin, gap = 40, 20
    cell_w = (W - 2 * margin - gap) // 2
    cell_h = 280
    start_y = 220

    for idx, (thumb, p) in enumerate(thumbs):
        row, col = divmod(idx, 2)
        x = margin + col * (cell_w + gap)
        y = start_y + row * (cell_h + 90)

        card = Image.new("RGB", (cell_w, cell_h + 70), (40, 40, 55))
        thumb.thumbnail((cell_w - 20, cell_h - 20), Image.Resampling.LANCZOS)
        card.paste(thumb, ((cell_w - thumb.width) // 2, 10))
        img.paste(card, (x, y))

        price_str = f"${p.get('price', 0):.0f}"
        draw.rectangle([x + 8, y + cell_h - 10, x + 90, y + cell_h + 28], fill=accent)
        draw.text((x + 16, y + cell_h - 5), price_str, fill=(20, 20, 20), font=font_small)

        short = p["title"][:38] + "…" if len(p["title"]) > 38 else p["title"]
        draw.multiline_text((x, y + cell_h + 35), textwrap.fill(short, width=28), fill=(220, 220, 220), font=font_small)

    # Footer
    footer_y = H - 120
    draw.rectangle([0, footer_y, W, H], fill=(15, 15, 25))
    draw.text((W // 2, footer_y + 25), "Full list + affiliate links on the blog", fill=(255, 255, 255), font=font_med, anchor="mt")
    draw.text((W // 2, footer_y + 70), "Tap to see current prices →", fill=accent, font=font_small, anchor="mt")

    return img
# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Amazon Affiliate Blog Generator",
    page_icon="🛒",
    layout="wide",
)

st.title("🛒 Amazon High-Ticket Affiliate Blog + Pinterest Generator")
st.caption("Works with or without Amazon Creators API • Uses your Associate Tag on every link")

# Sidebar
with st.sidebar:
    st.header("⚙️ Settings")

    mode = st.radio(
        "Mode",
        ["Manual Entry (Recommended for you)", "Live Amazon Search (needs API)"],
        index=0,
        help="Manual mode works right now with only your Associate Tag."
    )

    partner_tag = st.text_input(
        "Your Associate Tag",
        value=DEFAULT_TAG,
        help="This gets added to every product link"
    )
    st.session_state["partner_tag"] = partner_tag.strip() or DEFAULT_TAG

    st.divider()

    if mode.startswith("Live"):
        st.subheader("Creators API Credentials")
        st.info("Only needed for automatic search. You currently don’t have these yet.")
        st.text_input("Credential ID", key="cred_id")
        st.text_input("Credential Secret", type="password", key="cred_secret")
        st.text_input("API Version", value="2.2", key="api_version")


# ===================== MANUAL MODE =====================
if mode.startswith("Manual"):
    st.subheader("📝 Manual Product Entry")
    st.markdown("Paste Amazon product links (or ASINs). The app will automatically add your tag **`{}`** to every link.".format(partner_tag))

    niche = st.text_input("Niche / Blog Title Focus", value="standing desk",
                          help="Example: robot vacuum, espresso machine, noise cancelling headphones")

    st.markdown("### Add Products")
    st.caption("You can add up to 8 products. Fill in as much info as you have.")

    if "manual_products" not in st.session_state:
        st.session_state.manual_products = [{"url": "", "title": "", "price": "", "image_url": "", "features": ""}]

    for i, prod in enumerate(st.session_state.manual_products):
        with st.expander(f"Product {i+1}", expanded=(i == 0)):
            col1, col2 = st.columns([3, 1])
            with col1:
                url = st.text_input("Amazon Link or ASIN", value=prod["url"], key=f"url_{i}",
                                    placeholder="https://www.amazon.com/dp/B0XXXXXXX or just the ASIN")
            with col2:
                if st.button("Remove", key=f"rm_{i}") and len(st.session_state.manual_products) > 1:
                    st.session_state.manual_products.pop(i)
                    st.rerun()

            title = st.text_input("Product Title", value=prod["title"], key=f"title_{i}")
            price = st.text_input("Price (numbers only)", value=prod["price"], key=f"price_{i}", placeholder="349.99")
            image_url = st.text_input("Image URL (optional but recommended)", value=prod["image_url"], key=f"img_{i}",
                                      placeholder="Right-click product image on Amazon → Copy image address")
            features = st.text_area("Key Features (one per line)", value=prod["features"], key=f"feat_{i}", height=80)

            st.session_state.manual_products[i] = {
                "url": url,
                "title": title,
                "price": price,
                "image_url": image_url,
                "features": features,
            }

    if st.button("➕ Add another product"):
        st.session_state.manual_products.append({"url": "", "title": "", "price": "", "image_url": "", "features": ""})
        st.rerun()

    generate = st.button("🚀 Generate Blog + Pinterest Assets", type="primary", use_container_width=True)

    if generate:
        products = []
        for p in st.session_state.manual_products:
            if not p["url"] and not p["title"]:
                continue

            asin = extract_asin(p["url"]) if p["url"] else None
            aff_url = make_affiliate_link(p["url"] or asin or "", partner_tag)

            try:
                price_val = float(re.sub(r"[^\d.]", "", p["price"])) if p["price"] else 0.0
            except Exception:
                price_val = 0.0

            features_list = [f.strip() for f in p["features"].splitlines() if f.strip()] if p["features"] else []

            products.append({
                "asin": asin or "MANUAL",
                "title": p["title"] or "Product",
                "image_url": p["image_url"] or None,
                "price": price_val,
                "currency": "USD",
                "url": aff_url,
                "features": features_list,
                "rating": None,
                "review_count": 0,
            })

        if not products:
            st.error("Please add at least one product with a title or Amazon link.")
            st.stop()

        st.success(f"
