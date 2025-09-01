# app.py
import os
import time
import re
import requests
import pandas as pd
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="Dental Clinic Smile Audit", layout="wide")
st.title("🦷 Dental Clinic Smile Audit (API-Enhanced)")

# ------------------------ Secrets / Env ------------------------
# Prefer st.secrets; fallback to environment variables.
PLACES_API_KEY = st.secrets.get("GOOGLE_PLACES_API_KEY", os.getenv("GOOGLE_PLACES_API_KEY"))
CSE_API_KEY    = st.secrets.get("GOOGLE_CSE_API_KEY", os.getenv("GOOGLE_CSE_API_KEY"))
CSE_CX         = st.secrets.get("GOOGLE_CSE_CX", os.getenv("GOOGLE_CSE_CX"))

# ------------------------ Helpers ------------------------
def fetch_html(url: str):
    if not url:
        return None, None
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        t0 = time.time()
        r = requests.get(url, headers=headers, timeout=10)
        elapsed = time.time() - t0
        if r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser"), elapsed
    except Exception:
        pass
    return None, None

def get_domain(url: str):
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."): netloc = netloc[4:]
        return netloc
    except Exception:
        return None

def years_in_operation_from_site(soup: BeautifulSoup):
    if not soup: return "Search limited"
    text = soup.get_text(" ", strip=True)
    m = re.search(r"(established|since|serving since|founded)\D*((19|20)\d{2})", text, flags=re.I)
    if m:
        return m.group(2)
    # fallback earliest year
    years = re.findall(r"(19|20)\d{2}", text)
    return min(years) if years else "Search limited"

def specialties_from_site(soup: BeautifulSoup):
    if not soup: return "Search limited"
    text = soup.get_text(" ", strip=True).lower()
    keywords = [
        "general dentistry","orthodontics","braces","implants","implant","cosmetic",
        "veneers","whitening","endodontics","root canal","periodontics","gum",
        "pediatric","children","oral surgery","tmj","sleep apnea","invisalign",
        "prosthodontics","crowns","bridges","dental implants"
    ]
    found = sorted(set(k for k in keywords if k in text))
    return ", ".join(found) if found else "Search limited"

# ------------------------ Google Places API ------------------------
def places_text_search(query: str):
    if not PLACES_API_KEY: return None
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": query, "key": PLACES_API_KEY}
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def places_details(place_id: str):
    if not PLACES_API_KEY or not place_id: return None
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    fields = ",".join([
        "name","place_id","formatted_address","international_phone_number","website",
        "opening_hours","photos","rating","user_ratings_total","types","geometry/location",
        "reviews"  # <-- include reviews (up to 5 most relevant)
    ])
    params = {"place_id": place_id, "fields": fields, "key": PLACES_API_KEY}
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def find_best_place_id(clinic_name: str, address: str, website: str):
    # Try most-specific query first
    queries = []
    if clinic_name and address:
        queries.append(f"{clinic_name} {address}")
    if clinic_name:
        queries.append(clinic_name)
    if website:
        domain = get_domain(website)
        if domain:
            queries.append(domain)

    for q in queries:
        js = places_text_search(q)
        if not js or js.get("status") not in ("OK", "ZERO_RESULTS"): 
            continue
        candidates = js.get("results", [])
        if candidates:
            # naive best match = top result
            return candidates[0].get("place_id")
    return None

def gbp_completeness_estimate(details: dict):
    """
    We can't use Business Profile API for others' listings without ownership.
    So we estimate "GBP completeness" from Places Details fields:
    """
    if not details or details.get("status") != "OK": return "Search limited", None
    res = details["result"]
    score = 0
    checks = []

    if "opening_hours" in res:
        score += 20; checks.append("Hours ✅")
    else:
        checks.append("Hours ❌")

    if "photos" in res and len(res["photos"]) >= 3:
        score += 20; checks.append(f"Photos ✅ ({len(res['photos'])})")
    else:
        checks.append(f"Photos ❌ ({len(res.get('photos',[]))})")

    if res.get("website"):
        score += 15; checks.append("Website ✅")
    else:
        checks.append("Website ❌")

    if res.get("international_phone_number"):
        score += 15; checks.append("Phone ✅")
    else:
        checks.append("Phone ❌")

    if res.get("rating") and res.get("user_ratings_total", 0) > 0:
        score += 10; checks.append("Reviews ✅")
    else:
        checks.append("Reviews ❌")

    if "types" in res and any(t in res["types"] for t in ["dentist","dental_clinic"]):
        score += 10; checks.append("Category ✅")
    else:
        checks.append("Category ❌")

    if res.get("formatted_address"):
        score += 10; checks.append("Address ✅")
    else:
        checks.append("Address ❌")

    return f"{min(score,100)}/100", " | ".join(checks)

def office_hours_from_places(details: dict):
    if not details or details.get("status") != "OK": return "Search limited"
    res = details["result"]
    if "opening_hours" in res and "weekday_text" in res["opening_hours"]:
        return "; ".join(res["opening_hours"]["weekday_text"])
    return "Search limited"

def rating_reviews_from_places(details: dict):
    if not details or details.get("status") != "OK":
        return "Search limited", "Search limited"
    res = details["result"]
    rating = res.get("rating")
    count = res.get("user_ratings_total")
    return (f"{rating}/5" if rating else "Search limited",
            count if count is not None else "Search limited")

def accessibility_from_places(details: dict):
    if not details or details.get("status") != "OK": return "Search limited"
    opts = details["result"].get("accessibility_options")
    if not opts: return "Search limited"
    flags = []
    for k, v in opts.items():
        if v: flags.append(k.replace("_"," "))
    return ", ".join(flags) if flags else "Search limited"

def photos_count_from_places(details: dict):
    if not details or details.get("status") != "OK": return "Search limited"
    return len(details["result"].get("photos", []))

def extract_reviews_from_places(details_json):
    """
    Returns (reviews_list, rating_float_or_None, total_reviews_or_None)
    reviews_list: list of dicts with keys: rating, text, time, author_name (subset)
    """
    if not details_json or details_json.get("status") != "OK":
        return [], None, None
    res = details_json["result"]
    reviews = res.get("reviews", []) or []
    simplified = []
    for rv in reviews:
        simplified.append({
            "rating": rv.get("rating"),
            "text": rv.get("text") or "",
            "time": rv.get("time"),
            "author_name": rv.get("author_name")
        })
    rating = res.get("rating")
    total = res.get("user_ratings_total")
    return simplified, (float(rating) if rating is not None else None), (int(total) if total is not None else None)


def analyze_review_texts(reviews):
    """
    Very lightweight keyword-based analysis (no external NLP).
    Returns:
      - sentiment_highlights (str)
      - top_positive_themes (str)
      - top_negative_themes (str)
    """
    if not reviews:
        return "Search limited", "Search limited", "Search limited"

    # Canonical theme keywords (extend as you wish)
    positive_themes = {
        "friendly staff": ["friendly", "kind", "caring", "nice", "welcoming", "courteous"],
        "cleanliness": ["clean", "hygienic", "spotless"],
        "pain-free experience": ["painless", "no pain", "gentle", "pain free", "comfortable"],
        "professionalism": ["professional", "expert", "knowledgeable"],
        "communication": ["explained", "explain", "transparent", "informative"]
    }
    negative_themes = {
        "long wait": ["wait", "waiting", "late", "delay", "overbooked"],
        "billing issues": ["billing", "charges", "overcharged", "insurance problem", "invoice"],
        "front desk experience": ["front desk", "reception", "rude", "unhelpful"],
        "pain/discomfort": ["painful", "hurt", "rough", "uncomfortable"],
        "upselling": ["upsell", "salesy", "sold me", "pushy"]
    }

    # Flatten reviews to one text blob
    texts = " ".join((rv.get("text") or "") for rv in reviews).lower()

    def count_theme_hits(theme_dict):
        counts = {}
        for theme, kws in theme_dict.items():
            c = 0
            for kw in kws:
                c += texts.count(kw.lower())
            if c > 0:
                counts[theme] = c
        # sort by count desc
        return sorted(counts.items(), key=lambda x: x[1], reverse=True)

    pos_hits = count_theme_hits(positive_themes)
    neg_hits = count_theme_hits(negative_themes)

    # Sentiment highlights summary (quick & dirty)
    pos_total = sum(cnt for _, cnt in pos_hits)
    neg_total = sum(cnt for _, cnt in neg_hits)
    if pos_total == 0 and neg_total == 0:
        sentiment_summary = "Mixed/neutral (few obvious themes)"
    elif pos_total >= neg_total:
        sentiment_summary = f"Mostly positive mentions ({pos_total} vs {neg_total})"
    else:
        sentiment_summary = f"Mixed with notable concerns ({neg_total} negatives vs {pos_total} positives)"

    # Build readable theme strings (top 3)
    def to_theme_str(items):
        if not items:
            return "None detected"
        top = items[:3]
        return "; ".join([f"{name} ({cnt})" for name, cnt in top])

    top_pos_str = to_theme_str(pos_hits)
    top_neg_str = to_theme_str(neg_hits)

    return sentiment_summary, top_pos_str, top_neg_str


# ------------------------ Google Custom Search ------------------------
def appears_on_page1_for_dentist_near_me(website: str, clinic_name: str, address: str):
    if not (CSE_API_KEY and CSE_CX): return "Search limited"
    domain = get_domain(website) if website else None

    # very simple city extraction from address
    city = None
    if address and "," in address:
        parts = [p.strip() for p in address.split(",")]
        if len(parts) >= 2: city = parts[-2]  # e.g., "San Francisco"

    q = f"dentist near {city}" if city else f"dentist near me {clinic_name or ''}".strip()
    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": CSE_API_KEY, "cx": CSE_CX, "q": q, "num": 10},
            timeout=10
        )
        if r.status_code != 200:
            return "Search limited"
        data = r.json()
        items = data.get("items", [])
        # Check if clinic name or domain appears
        found = False
        for it in items:
            link = it.get("link","")
            title = it.get("title","")
            snippet = it.get("snippet","")
            if domain and get_domain(link) == domain:
                found = True; break
            if clinic_name and (clinic_name.lower() in title.lower() or clinic_name.lower() in snippet.lower()):
                found = True; break
        return "Yes (Page 1)" if found else "No (Not on Page 1)"
    except Exception:
        return "Search limited"

# ------------------------ Website checks ------------------------
def website_health(url: str, soup: BeautifulSoup, load_time: float):
    if not url: return "Search limited", "No URL"
    score = 0; checks = []
    if url.lower().startswith("https"):
        score += 34; checks.append("HTTPS ✅")
    else:
        checks.append("HTTPS ❌")
    if soup and soup.find("meta", attrs={"name": "viewport"}):
        score += 33; checks.append("Mobile-friendly ✅")
    else:
        checks.append("Mobile-friendly ❌")
    if load_time is not None:
        if load_time < 2:
            score += 33; checks.append(f"Load speed ✅ ({load_time:.2f}s)")
        elif load_time < 5:
            score += 16; checks.append(f"Load speed ⚠️ ({load_time:.2f}s)")
        else:
            checks.append(f"Load speed ❌ ({load_time:.2f}s)")
    else:
        checks.append("Load speed ❓")
    return f"{min(score,100)}/100", " | ".join(checks)

def social_presence_from_site(soup: BeautifulSoup):
    if not soup: return "Search limited", "Search limited"
    links = [a.get("href") for a in soup.find_all("a", href=True)]
    fb = any("facebook.com" in (l or "") for l in links)
    ig = any("instagram.com" in (l or "") for l in links)
    present = "None"
    if fb and ig: present = "Facebook, Instagram"
    elif fb: present = "Facebook"
    elif ig: present = "Instagram"
    return present, "Follower counts & activity require platform APIs/login"

def appointment_booking_from_site(soup: BeautifulSoup):
    if not soup: return "Search limited"
    text = soup.get_text(" ", strip=True).lower()
    if any(p in text for p in ["book", "appointment", "schedule", "reserve"]):
        if "calendly" in text or "zocdoc" in text or "square appointments" in text:
            return "Online booking (embedded)"
        return "Online booking (link/form)"
    return "Phone-only or unclear"

def insurance_from_site(soup: BeautifulSoup):
    if not soup: return "Search limited"
    text = soup.get_text(" ", strip=True).lower()
    if "insurance" in text or "we accept" in text or "ppo" in text or "delta dental" in text:
        m = re.search(r"([^.]*insurance[^.]*\.)", text)
        return m.group(0) if m else "Mentioned on site"
    return "Unclear"

def media_count_from_site(soup: BeautifulSoup):
    if not soup: return "Search limited"
    imgs = len(soup.find_all("img"))
    vids = len(soup.find_all(["video","source"]))
    return f"{imgs} photos, {vids} videos"

def advertising_signals(soup: BeautifulSoup):
    if not soup: return "Search limited"
    html = str(soup)
    signals = []
    if "gtag(" in html or "gtag.js" in html or "www.googletagmanager.com" in html:
        signals.append("Google tag")
    if "fbq(" in html:
        signals.append("Facebook Pixel")
    return ", ".join(signals) if signals else "None detected"

# ------------------------ Simple scoring buckets ------------------------
def to_pct_from_score_str(s):  # "85/100" -> 85
    try:
        if isinstance(s, str) and "/" in s:
            return int(s.split("/")[0])
    except Exception:
        pass
    return None

def compute_smile_score(wh_pct, social_present, rating, reviews_total, booking, hours_present, insurance_clear, accessibility_present):
    # Visibility (30%): website health + social presence + search/GBP not included here
    vis_parts = []
    if isinstance(wh_pct, (int,float)):
        vis_parts.append(wh_pct)
    # social presence crude %
    if social_present == "Facebook, Instagram":
        vis_parts.append(100)
    elif social_present in ("Facebook","Instagram"):
        vis_parts.append(60)
    else:
        vis_parts.append(0)
    vis_avg = sum(vis_parts)/len(vis_parts) if vis_parts else 0
    vis_score = (vis_avg/100)*30

    # Reputation (40%): rating + volume (cap 500)
    rep_parts = []
    if isinstance(rating, (int,float)):
        rep_parts.append((rating/5.0)*100)
    if isinstance(reviews_total, (int,float)):
        rep_parts.append(min(1, reviews_total/500)*100)
    rep_avg = sum(rep_parts)/len(rep_parts) if rep_parts else 0
    rep_score = (rep_avg/100)*40

    # Experience (30%): booking + hours + insurance + accessibility (presence only)
    exp_parts = []
    if booking and "Online booking" in booking: exp_parts.append(80)
    elif booking and "Phone-only" in booking: exp_parts.append(40)
    if hours_present: exp_parts.append(70)
    if insurance_clear: exp_parts.append(80)
    if accessibility_present: exp_parts.append(70)
    exp_avg = sum(exp_parts)/len(exp_parts) if exp_parts else 0
    exp_score = (exp_avg/100)*30

    total = round(vis_score + rep_score + exp_score, 1)
    return total, round(vis_score,1), round(rep_score,1), round(exp_score,1)

# ------------------------ UI ------------------------
with st.form("audit_form"):
    clinic_name = st.text_input("Clinic Name")
    address = st.text_input("Address")
    phone = st.text_input("Phone Number")
    website = st.text_input("Website URL (include http/https)")
    submitted = st.form_submit_button("Run Audit")

if not submitted:
    st.info("Enter details and click **Run Audit**.")
else:
    soup, load_time = fetch_html(website)

    # Places: identify listing
    place_id = find_best_place_id(clinic_name, address, website)
    details = places_details(place_id) if place_id else None

    # 1) Practice Overview
    overview = {
        "Practice Name": clinic_name or "Search limited",
        "Address": address or "Search limited",
        "Phone": phone or "Search limited",
        "Website": website or "Search limited",
        "Years in Operation": years_in_operation_from_site(soup),
        "Specialties Highlighted": specialties_from_site(soup),
    }

    # 2) Online Presence & Visibility
    wh_str, wh_checks = website_health(website, soup, load_time)
    gbp_score, gbp_checks = gbp_completeness_estimate(details) if details else ("Search limited","Search limited")
    appears = appears_on_page1_for_dentist_near_me(website, clinic_name, address)
    social_present, social_details = social_presence_from_site(soup)
    visibility = {
        "GBP Completeness (estimate)": gbp_score,
        "GBP Signals": gbp_checks,
        "Search Visibility (Page 1 for 'dentist near <city>')": appears,
        "Website Health Score": wh_str,
        "Website Health Checks": wh_checks,
        "Social Media Presence": social_present,
        "Social Media Details": social_details
    }

    # 3) Reputation (from Places)
    # --- Reputation (from Places) ---
    reviews, rating_val, total_reviews = extract_reviews_from_places(details) if details else ([], None, None)

    # Average rating string
    rating_str = (f"{rating_val}/5" if isinstance(rating_val, (int, float)) else "Search limited")
    # Total review count
    review_count = (total_reviews if isinstance(total_reviews, int) else "Search limited")

    # Sentiment + themes from first ~5 Google reviews
    sentiment_summary, top_pos_str, top_neg_str = analyze_review_texts(reviews)

    # Review response rate: not available via Places; requires GBP API for owned locations
    response_rate_str = "Not available via Places API (GBP needed)"

    reputation = {
        "Google Reviews (Avg)": rating_str,
        "Total Google Reviews": review_count,
        "Sentiment Highlights": sentiment_summary,
        "Yelp / Healthgrades / Zocdoc": "Search limited",
        "Top Positive Themes": top_pos_str,
        "Top Negative Themes": top_neg_str,
        "Review Response Rate": response_rate_str
    }


    # 4) Marketing Signals
    site_media = media_count_from_site(soup)
    site_ads = advertising_signals(soup)
    photos_count = photos_count_from_places(details) if details else "Search limited"
    marketing = {
        "Local SEO (NAP consistency)": "Search limited",
        "Photos/Videos on Website": site_media,
        "Photos count in Google": photos_count,
        "Advertising Scripts Detected": site_ads,
        "Social Proof (media/mentions)": "Search limited"
    }

    # 5) Patient Experience & Accessibility
    booking = appointment_booking_from_site(soup)
    hours = office_hours_from_places(details)
    insurance = insurance_from_site(soup)
    accessibility = accessibility_from_places(details)
    experience = {
        "Appointment Booking": booking,
        "Office Hours": hours,
        "Insurance Acceptance": insurance,
        "Accessibility Signals": accessibility
    }

    # 6) Competitive Benchmark (quick: average top 3 ratings from text search)
    top3_avg = "Search limited"
    if address and PLACES_API_KEY:
        # crude city extraction
        city = None
        if "," in address:
            parts = [p.strip() for p in address.split(",")]
            if len(parts) >= 2: city = parts[-2]
        q = f"dentist in {city}" if city else "dentist"
        js = places_text_search(q)
        if js and js.get("status") == "OK":
            ratings = []
            for r in js.get("results", [])[:3]:
                if "rating" in r: ratings.append(r["rating"])
            if ratings:
                top3_avg = round(sum(ratings)/len(ratings), 2)
    competitive = {"Avg Rating of Top 3 Nearby": top3_avg}

    # ------------------------ Scoring ------------------------
    wh_pct = to_pct_from_score_str(wh_str)
    rating_val = None
    if isinstance(rating_str, str) and rating_str.endswith("/5"):
        try:
            rating_val = float(rating_str.split("/")[0])
        except: pass
    reviews_total = review_count if isinstance(review_count, (int,float)) else None
    hours_present = isinstance(hours, str) and hours != "Search limited"
    insurance_clear = (isinstance(insurance, str) and insurance not in ["Search limited","Unclear"])
    accessibility_present = (isinstance(accessibility, str) and accessibility != "Search limited")

    smile, vis_score, rep_score, exp_score = compute_smile_score(
        wh_pct, social_present, rating_val, reviews_total, booking, hours_present, insurance_clear, accessibility_present
    )

    # ------------------------ Display ------------------------
    def show_table(title, data_dict):
        st.markdown(f"### {title}")
        df = pd.DataFrame([(k, v) for k, v in data_dict.items()], columns=["Metric", "Result"])
        st.dataframe(df, use_container_width=True)

    c1, c2 = st.columns([1,1])
    with c1:
        st.markdown("### 🧭 Smile Score")
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=smile,
            title={'text': "Smile Score (0–100)"},
            gauge={'axis': {'range': [0, 100]},
                   'bar': {'color': "seagreen"},
                   'steps': [
                       {'range': [0, 50], 'color': '#ffe5e5'},
                       {'range': [50, 75], 'color': '#fff6d6'},
                       {'range': [75, 100], 'color': '#e6ffe6'}
                   ]}
        ))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.markdown("### 📦 Bucket Breakdown")
        bucket_df = pd.DataFrame([
            ["Visibility (30%)", vis_score],
            ["Reputation (40%)", rep_score],
            ["Experience (30%)", exp_score]
        ], columns=["Bucket", "Score"])
        st.dataframe(bucket_df, use_container_width=True)

    st.markdown("---")
    show_table("1) Practice Overview", overview)
    show_table("2) Online Presence & Visibility", visibility)
    show_table("3) Patient Reputation & Feedback", reputation)
    show_table("4) Marketing Signals", marketing)
    show_table("5) Patient Experience & Accessibility", experience)
    show_table("6) Competitive Benchmark", competitive)

    # Export CSV
    all_rows = []
    def add_section(name, d):
        for k, v in d.items(): all_rows.append([name, k, v])
    add_section("Practice Overview", overview)
    add_section("Visibility", visibility)
    add_section("Reputation", reputation)
    add_section("Marketing", marketing)
    add_section("Experience", experience)
    add_section("Competitive", competitive)
    all_rows += [["Summary","Smile Score",smile],
                 ["Summary","Visibility Bucket",vis_score],
                 ["Summary","Reputation Bucket",rep_score],
                 ["Summary","Experience Bucket",exp_score]]
    export_df = pd.DataFrame(all_rows, columns=["Section","Metric","Result"])
    st.download_button("⬇️ Download full results (CSV)",
                       data=export_df.to_csv(index=False).encode("utf-8"),
                       file_name=f"{(clinic_name or 'clinic').replace(' ','_')}_smile_audit.csv",
                       mime="text/csv")

    st.caption("Notes: Uses Google Places + Custom Search. Business Profile API requires you to manage the listing; otherwise we estimate completeness from public Places fields.")
