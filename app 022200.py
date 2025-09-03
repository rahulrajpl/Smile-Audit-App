# app.py
import os, io, re, time, math
from urllib.parse import urlparse

import requests
import pandas as pd
from bs4 import BeautifulSoup
import streamlit as st
import plotly.graph_objects as go

# HTML templating & PDF (Cloud-safe)
from jinja2 import Environment, FileSystemLoader, select_autoescape
from xhtml2pdf import pisa  # pure-Python PDF engine (works on Streamlit Cloud)

# ------------------------ Page & Config ------------------------
st.set_page_config(page_title="Dental Clinic Smile Audit ", layout="wide")
st.title("🦷 AI based Smile Audit ")
st.subheader("Comprehensive audit of your dental practice's online presence & patient experience")

# Keys (prefer Streamlit secrets, fallback to env)
PLACES_API_KEY = st.secrets.get("GOOGLE_PLACES_API_KEY", os.getenv("GOOGLE_PLACES_API_KEY"))
CSE_API_KEY    = st.secrets.get("GOOGLE_CSE_API_KEY", os.getenv("GOOGLE_CSE_API_KEY"))
CSE_CX         = st.secrets.get("GOOGLE_CSE_CX", os.getenv("GOOGLE_CSE_CX"))

DEBUG = st.sidebar.checkbox("Show debug info")

# Template paths
TEMPLATES_DIR = os.path.join(os.getcwd(), "templates")
ASSETS_DIR = os.path.join(TEMPLATES_DIR, "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)

# ------------------------ Create default branded template if missing ------------------------
def ensure_default_template():
    styles_css = """
@page { size: A4; margin: 16mm; }
:root {
  --primary: #184A75;  /* NeedleTail.ai Blue */
  --text: #1F2937;     /* Dark text */
  --muted: #6B7280;    /* Muted text */
  --bg: #F3F4F6;       /* Light gray */
  --green: #2E7D32;    /* Success */
  --red: #D32F2F;      /* Error */
  --white: #FFFFFF;
}
* { box-sizing: border-box; }
body { font-family: Arial, Helvetica, sans-serif; color: var(--text); }
.header { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--primary); color: var(--white); border-radius: 10px; }
.brand { display: flex; align-items: center; gap: 10px; }
.brand img { height: 28px; width: auto; }
.brand .title { font-weight: bold; font-size: 18px; }
.clinic-name { font-size: 13px; opacity: 0.9; }
.wrap { margin-top: 12px; }
.row { display: flex; gap: 12px; }
.card { flex: 1; border: 1px solid #E5E7EB; border-radius: 12px; background: var(--white); padding: 10px 12px; }
.card h3 { margin: 0 0 6px 0; font-size: 12px; color: var(--text); }
.kv { font-size: 12px; line-height: 1.35; color: var(--text); }
.small { font-size: 11px; color: var(--muted); }
.section-title { margin: 12px 0 6px 0; font-size: 13px; font-weight: bold; }
.grid-2 { display: table; width: 100%; }
.grid-2 .cell { display: table-cell; width: 50%; padding-right: 6px; }
.kpi { display: table; width: 100%; margin: 8px 0; }
.kpi .left { display: table-cell; width: 140px; vertical-align: middle; }
.kpi .right { display: table-cell; vertical-align: middle; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 10px; background: var(--bg); color: var(--text); }
.footer { margin-top: 6px; text-align: center; font-size: 10px; color: var(--muted); }
    """.strip()

    # NOTE: xhtml2pdf has limited CSS (no conic-gradients/SVG). We embed a PNG gauge image.
    html_template = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>{{ clinic_name }} — Smile Audit</title>
  <link rel="stylesheet" href="styles.css"/>
</head>
<body>
  <div class="header">
    <div class="brand">
      {% if logo_exists %}
        <img src="{{ logo_path }}" alt="Logo"/>
      {% endif %}
      <div class="title">AI Smile Audit</div>
    </div>
    <div class="clinic-name">{{ clinic_name }}</div>
  </div>

  <div class="wrap">
    <div class="kpi">
      <div class="left"><img src="{{ gauge_path }}" alt="Smile Gauge" style="width:120px;height:120px;"/></div>
      <div class="right">
        <div class="section-title">Bucket Scores</div>
        <div class="kv">Visibility (30%): <b>{{ vis_score }}</b></div>
        <div class="kv">Reputation (40%): <b>{{ rep_score }}</b></div>
        <div class="kv">Experience (30%): <b>{{ exp_score }}</b></div>
      </div>
    </div>

    <div class="row">
      <div class="card">
        <h3>Practice Overview</h3>
        <div class="kv"><span class="badge">Address</span> {{ overview.Address }}</div>
        <div class="kv"><span class="badge">Phone</span> {{ overview.Phone }}</div>
        <div class="kv"><span class="badge">Website</span> {{ overview.Website }}</div>
        <div class="kv"><span class="badge">Years</span> {{ overview['Years in Operation'] }}</div>
        <div class="kv"><span class="badge">Specialties</span> {{ overview['Specialties Highlighted'] }}</div>
      </div>

      <div class="card">
        <h3>Key KPIs</h3>
        <div class="kv"><span class="badge">GBP</span> {{ visibility['GBP Completeness (estimate)'] }}</div>
        <div class="kv"><span class="badge">Website Health</span> {{ visibility['Website Health Score'] }}</div>
        <div class="kv"><span class="badge">Search Visibility</span> {{ visibility['Search Visibility (Page 1?)'] }}</div>
        <div class="kv"><span class="badge">Google Rating</span> {{ reputation['Google Reviews (Avg)'] }}</div>
        <div class="kv"><span class="badge">Total Reviews</span> {{ reputation['Total Google Reviews'] }}</div>
      </div>
    </div>

    <div class="section-title">Top Recommendations</div>
    <div class="grid-2">
      {% for rec in recommendations %}
        <div class="cell"><div class="card small">{{ rec }}</div></div>
      {% endfor %}
    </div>

    <div class="footer">Generated for {{ clinic_name }}</div>
  </div>
</body>
</html>
    """.strip()

    css_path = os.path.join(TEMPLATES_DIR, "styles.css")
    html_path = os.path.join(TEMPLATES_DIR, "smile_report.html")
    if not os.path.exists(css_path):
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(styles_css)
    if not os.path.exists(html_path):
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_template)

ensure_default_template()

# # Optional: upload your logo (PNG) from sidebar and persist to /templates/assets/logo.png
# st.sidebar.markdown("### Branding")
# logo_file = st.sidebar.file_uploader("Upload logo (PNG)", type=["png"])
# if logo_file is not None:
#     with open(os.path.join(ASSETS_DIR, "logo.png"), "wb") as f:
#         f.write(logo_file.getbuffer())
#     st.sidebar.success("Logo uploaded")

# ------------------------ Utility & API helpers ------------------------
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
    if m: return m.group(2)
    yrs = re.findall(r"(19|20)\d{2}", text)
    return min(yrs) if yrs else "Search limited"

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

# --- Google Places ---
def places_text_search(query: str):
    if not PLACES_API_KEY: return None
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": query, "key": PLACES_API_KEY}
    r = requests.get(url, params=params, timeout=10)
    return r.json() if r.status_code == 200 else None

def places_find_place(text_query: str):
    if not PLACES_API_KEY: return None
    url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
    params = {
        "input": text_query,
        "inputtype": "textquery",
        "fields": "place_id,name,formatted_address,website",
        "key": PLACES_API_KEY
    }
    r = requests.get(url, params=params, timeout=10)
    return r.json() if r.status_code == 200 else None

def places_details(place_id: str):
    if not PLACES_API_KEY or not place_id: return None
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    fields = ",".join([
        "name","place_id","formatted_address","international_phone_number","website",
        "opening_hours","photos","rating","user_ratings_total","types","geometry/location",
        "reviews"
    ])
    params = {"place_id": place_id, "fields": fields, "key": PLACES_API_KEY}
    r = requests.get(url, params=params, timeout=10)
    return r.json() if r.status_code == 200 else None

def find_best_place_id(clinic_name: str, address: str, website: str):
    queries = []
    if clinic_name and address: queries.append(f"{clinic_name} {address}")
    if clinic_name: queries.append(clinic_name)
    if website:
        domain = get_domain(website)
        if domain: queries.append(domain)

    for q in queries:
        js = places_text_search(q)
        if DEBUG: st.sidebar.write("Text Search:", q, (js or {}).get("status"))
        if js and js.get("status") == "OK" and js.get("results"):
            return js["results"][0].get("place_id")

    for q in queries:
        js = places_find_place(q)
        if DEBUG: st.sidebar.write("Find Place:", q, (js or {}).get("status"))
        if js and js.get("status") == "OK" and js.get("candidates"):
            return js["candidates"][0].get("place_id")
    return None

def rating_and_reviews(details: dict):
    if not details or details.get("status") != "OK":
        return "Search limited", "Search limited", []
    res = details.get("result", {})
    rating = res.get("rating")
    count = res.get("user_ratings_total")
    reviews = res.get("reviews", []) or []
    simplified = []
    for rv in reviews:
        simplified.append({
            "relative_time": rv.get("relative_time_description"),
            "rating": rv.get("rating"),
            "author_name": rv.get("author_name"),
            "text": rv.get("text") or ""
        })
    rating_str = f"{rating}/5" if rating is not None else "Search limited"
    total_reviews = count if count is not None else "Search limited"
    return rating_str, total_reviews, simplified

def office_hours_from_places(details: dict):
    if not details or details.get("status") != "OK": return "Search limited"
    res = details["result"]
    oh = res.get("opening_hours", {})
    wt = oh.get("weekday_text")
    return "; ".join(wt) if wt else "Search limited"

def photos_count_from_places(details: dict):
    if not details or details.get("status") != "OK": return "Search limited"
    return len(details["result"].get("photos", []))

# --- Custom Search ---
def appears_on_page1_for_dentist_near_me(website: str, clinic_name: str, address: str):
    if not (CSE_API_KEY and CSE_CX): return "Search limited"
    try:
        domain = get_domain(website) if website else None
        city = None
        if address and "," in address:
            parts = [p.strip() for p in address.split(",")]
            if len(parts) >= 2: city = parts[-2]
        q = f"dentist near {city}" if city else f"dentist near me {clinic_name or ''}".strip()
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": CSE_API_KEY, "cx": CSE_CX, "q": q, "num": 10},
            timeout=10
        )
        if r.status_code != 200:
            return "Search limited"
        data = r.json()
        for it in data.get("items", []):
            link = it.get("link","")
            title = it.get("title","")
            snippet = it.get("snippet","")
            if domain and get_domain(link) == domain:
                return "Yes (Page 1)"
            if clinic_name and (clinic_name.lower() in title.lower() or clinic_name.lower() in snippet.lower()):
                return "Yes (Page 1)"
        return "No (Not on Page 1)"
    except Exception:
        return "Search limited"

# --- Website checks & parsing ---
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
    if not soup: return "None"
    links = [a.get("href") or "" for a in soup.find_all("a", href=True)]
    fb = any("facebook.com" in l for l in links)
    ig = any("instagram.com" in l for l in links)
    if fb and ig: return "Facebook, Instagram"
    if fb: return "Facebook"
    if ig: return "Instagram"
    return "None"

def media_count_from_site(soup: BeautifulSoup):
    if not soup: return "Search limited"
    imgs = len(soup.find_all("img"))
    vids = len(soup.find_all(["video","source"]))
    return f"{imgs} photos, {vids} videos"

def advertising_signals(soup: BeautifulSoup):
    if not soup: return "Search limited"
    html = str(soup)
    sig = []
    if "gtag(" in html or "gtag.js" in html or "www.googletagmanager.com" in html:
        sig.append("Google tag")
    if "fbq(" in html:
        sig.append("Facebook Pixel")
    return ", ".join(sig) if sig else "None detected"

def appointment_booking_from_site(soup: BeautifulSoup):
    if not soup: return "Search limited"
    t = soup.get_text(" ", strip=True).lower()
    if any(p in t for p in ["book", "appointment", "schedule", "reserve"]):
        if "calendly" in t or "zocdoc" in t or "square appointments" in t:
            return "Online booking (embedded)"
        return "Online booking (link/form)"
    return "Phone-only or unclear"

def insurance_from_site(soup: BeautifulSoup):
    if not soup: return "Search limited"
    t = soup.get_text(" ", strip=True).lower()
    if "insurance" in t or "we accept" in t or "ppo" in t or "delta dental" in t:
        m = re.search(r"([^.]*insurance[^.]*\.)", t)
        return m.group(0) if m else "Mentioned on site"
    return "Unclear"

# --- Sentiment/theme analysis (simple keyword approach on up to 5 Google reviews) ---
def analyze_review_texts(reviews):
    if not reviews:
        return "Search limited", "Search limited", "Search limited"
    text_blob = " ".join((rv.get("text") or "") for rv in reviews).lower()
    positive_themes = {
        "friendly staff": ["friendly","kind","caring","nice","welcoming","courteous"],
        "cleanliness": ["clean","hygienic","spotless"],
        "pain-free experience": ["painless","no pain","gentle","pain free","comfortable"],
        "professionalism": ["professional","expert","knowledgeable"],
        "communication": ["explained","explain","transparent","informative"]
    }
    negative_themes = {
        "long wait": ["wait","waiting","late","delay","overbooked"],
        "billing issues": ["billing","charges","overcharged","invoice","insurance problem"],
        "front desk experience": ["front desk","reception","rude","unhelpful"],
        "pain/discomfort": ["painful","hurt","rough","uncomfortable"],
        "upselling": ["upsell","salesy","sold me","pushy"]
    }
    def count_hits(theme_dict):
        scores = {}
        for theme, kws in theme_dict.items():
            c = 0
            for kw in kws:
                c += text_blob.count(kw)
            if c > 0: scores[theme] = c
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)
    pos = count_hits(positive_themes)
    neg = count_hits(negative_themes)
    pos_total = sum(v for _, v in pos); neg_total = sum(v for _, v in neg)
    if pos_total == 0 and neg_total == 0:
        sentiment = "Mixed/neutral (few obvious themes)"
    elif pos_total >= neg_total:
        sentiment = f"Mostly positive mentions ({pos_total} vs {neg_total})"
    else:
        sentiment = f"Mixed with notable concerns ({neg_total} negatives vs {pos_total} positives)"
    def top3(items):
        if not items: return "None detected"
        return "; ".join([f"{k} ({v})" for k, v in items[:3]])
    return sentiment, top3(pos), top3(neg)

# --- Scoring ---
def to_pct_from_score_str(s):
    try:
        if isinstance(s, str) and "/" in s:
            return int(s.split("/")[0])
    except:
        pass
    return None

def compute_smile_score(wh_pct, social_present, rating, reviews_total, booking, hours_present, insurance_clear, accessibility_present=False):
    vis_parts = []
    if isinstance(wh_pct, (int,float)): vis_parts.append(wh_pct)
    if social_present == "Facebook, Instagram": vis_parts.append(100)
    elif social_present in ("Facebook","Instagram"): vis_parts.append(60)
    else: vis_parts.append(0)
    vis_avg = sum(vis_parts)/len(vis_parts) if vis_parts else 0
    vis_score = (vis_avg/100)*30

    rep_parts = []
    if isinstance(rating, (int,float)): rep_parts.append((rating/5.0)*100)
    if isinstance(reviews_total, (int,float)): rep_parts.append(min(1, reviews_total/500)*100)
    rep_avg = sum(rep_parts)/len(rep_parts) if rep_parts else 0
    rep_score = (rep_avg/100)*40

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

# --- Advice (blank when API-limited) ---
def advise(metric, value):
    if value is None: return ""
    s = str(value).strip().lower()
    for marker in ["search limited", "not available via places api", "request_denied", "invalid request", "permission denied", "zero_results"]:
        if marker in s: return ""

    def pct_from_score_str(x):
        try:
            if isinstance(x, (int, float)): return int(x)
            if isinstance(x, str) and "/" in x: return int(x.split("/")[0])
        except: return None

    if "website health score" in metric.lower():
        pct = pct_from_score_str(value)
        return "You nailed it" if (pct is not None and pct >= 90) else "Improve HTTPS/mobile/speed"

    if "gbp completeness" in metric.lower():
        pct = pct_from_score_str(value)
        return "You nailed it" if (pct is not None and pct >= 90) else "Add hours, photos, website, phone on GBP"

    if "search visibility" in metric.lower():
        return "You nailed it" if "yes" in s else "Improve local SEO & citations"

    if "social media presence" in metric.lower():
        if "facebook, instagram" in s: return "You nailed it"
        if "facebook" in s or "instagram" in s: return "Add the other platform & post weekly"
        return "Add FB/IG links; post 2–3×/week"

    if "google reviews (avg)" in metric.lower():
        try:
            rating = float(str(value).split("/")[0])
            if rating >= 4.6: return "You nailed it"
            if rating >= 4.0: return "Ask happy patients for reviews to reach 4.6+"
            return "Address negatives & request fresh 5★ reviews"
        except: return ""

    if "total google reviews" in metric.lower():
        try:
            n = int(value)
            if n >= 300: return "You nailed it"
            if n >= 100: return "Run a monthly review drive to hit 300"
            return "Launch QR/SMS review ask at checkout"
        except: return ""

    if "appointment booking" in metric.lower():
        return "You nailed it" if "online booking" in s else "Add an online booking link/button"

    if "office hours" in metric.lower():
        return "Offer evenings/weekends to boost conversions"

    if "insurance acceptance" in metric.lower():
        return "You nailed it" if ("unclear" not in s) else "Publish accepted plans on site & GBP"

    if "sentiment highlights" in metric.lower():
        if "mostly positive" in s: return "You nailed it"
        if "mixed" in s: return "Fix top negatives & reply to reviews"
        return "Reply to negative themes with solutions"

    if "top positive themes" in metric.lower():
        return "Amplify these themes on website & ads" if ("none detected" not in s) else ""

    if "top negative themes" in metric.lower():
        if "none detected" in s: return "You nailed it"
        if "long wait" in s: return "Stagger scheduling & add SMS reminders"
        if "billing" in s: return "Clarify estimates & billing SOP"
        if "front desk" in s: return "Train front desk on empathy scripts"
        return "Tackle top 1–2 negative themes this month"

    if "photos" in metric.lower():
        return "You nailed it" if ("none" not in s and "0" not in s) else "Upload 10–20 clinic & team photos"

    if "advertising scripts" in metric.lower():
        return "You nailed it" if ("none" not in s) else "Add GA4/Ads pixel for conversion tracking"

    return ""

# ------------------------ UI form ------------------------
with st.form("audit_form"):
    clinic_name = st.text_input("Clinic Name")
    address = st.text_input("Address")
    phone = st.text_input("Phone Number")
    website = st.text_input("Website URL (include http/https)")
    submitted = st.form_submit_button("Run Audit")

if not submitted:
    st.info("Enter details and click **Run Audit**.")
    st.stop()

# ------------------------ Run audit ------------------------
soup, load_time = fetch_html(website)

place_id = find_best_place_id(clinic_name, address, website)
details = places_details(place_id) if place_id else None

if DEBUG:
    st.sidebar.write("Place ID:", place_id)
    st.sidebar.write("Details status:", (details or {}).get("status"))
    if details and "result" in details:
        st.sidebar.write("Result keys:", list(details["result"].keys()))

# 1) Overview
overview = {
    "Practice Name": clinic_name or "Search limited",
    "Address": address or "Search limited",
    "Phone": phone or "Search limited",
    "Website": website or "Search limited",
    "Years in Operation": years_in_operation_from_site(soup),
    "Specialties Highlighted": specialties_from_site(soup),
}

# 2) Visibility
wh_str, wh_checks = website_health(website, soup, load_time)
social_present = social_presence_from_site(soup)
appears = appears_on_page1_for_dentist_near_me(website, clinic_name, address)

gbp_score = "Search limited"; gbp_signals = "Search limited"
if details and details.get("status") == "OK":
    res = details["result"]; score = 0; checks = []
    if res.get("opening_hours"): score += 20; checks.append("Hours ✅")
    else: checks.append("Hours ❌")
    if res.get("photos"): score += 20; checks.append(f"Photos ✅ ({len(res.get('photos',[]))})")
    else: checks.append("Photos ❌ (0)")
    if res.get("website"): score += 15; checks.append("Website ✅")
    else: checks.append("Website ❌")
    if res.get("international_phone_number"): score += 15; checks.append("Phone ✅")
    else: checks.append("Phone ❌")
    if res.get("rating") and res.get("user_ratings_total",0)>0: score += 10; checks.append("Reviews ✅")
    else: checks.append("Reviews ❌")
    if "dentist" in res.get("types", []) or "dental_clinic" in res.get("types", []):
        score += 10; checks.append("Category ✅")
    else:
        checks.append("Category ❌")
    if res.get("formatted_address"): score += 10; checks.append("Address ✅")
    else:
        checks.append("Address ❌")
    gbp_score = f"{min(score,100)}/100"
    gbp_signals = " | ".join(checks)

visibility = {
    "GBP Completeness (estimate)": gbp_score,
    "GBP Signals": gbp_signals,
    "Search Visibility (Page 1?)": appears,
    "Website Health Score": wh_str,
    "Website Health Checks": wh_checks,
    "Social Media Presence": social_present
}

# 3) Reputation
rating_str, review_count_out, reviews = rating_and_reviews(details)
sentiment_summary, top_pos_str, top_neg_str = analyze_review_texts(reviews)

reputation = {
    "Google Reviews (Avg)": rating_str,
    "Total Google Reviews": review_count_out,
    "Sentiment Highlights": sentiment_summary,
    "Yelp / Healthgrades / Zocdoc": "Search limited",
    "Top Positive Themes": top_pos_str,
    "Top Negative Themes": top_neg_str,
    "Review Response Rate": "Not available via Places API (GBP needed)"
}

# 4) Marketing
marketing = {
    "Photos/Videos on Website": media_count_from_site(soup) if soup else "Search limited",
    "Photos count in Google": photos_count_from_places(details) if details else "Search limited",
    "Advertising Scripts Detected": advertising_signals(soup) if soup else "Search limited",
    "Local SEO (NAP consistency)": "Search limited",
    "Social Proof (media/mentions)": "Search limited"
}

# 5) Experience
booking = appointment_booking_from_site(soup)
hours = office_hours_from_places(details)
insurance = insurance_from_site(soup)
experience = {
    "Appointment Booking": booking,
    "Office Hours": hours,
    "Insurance Acceptance": insurance,
    "Accessibility Signals": "Search limited"
}

# 6) Competitive
competitive = {"Avg Rating of Top 3 Nearby": "Search limited"}

# ------------------------ Scoring ------------------------
wh_pct = to_pct_from_score_str(wh_str)
rating_val = None
try:
    if isinstance(rating_str, str) and rating_str.endswith("/5"):
        rating_val = float(rating_str.split("/")[0])
except Exception:
    pass
reviews_total = review_count_out if isinstance(review_count_out, (int, float)) else None
hours_present = isinstance(hours, str) and hours != "Search limited"
insurance_clear = isinstance(insurance, str) and insurance not in ["Search limited", "Unclear"]

smile, vis_score, rep_score, exp_score = compute_smile_score(
    wh_pct, social_present, rating_val, reviews_total, booking, hours_present, insurance_clear, accessibility_present=False
)

# ------------------------ Tables with advice ------------------------
def section_df(section_dict):
    rows = []
    for k, v in section_dict.items():
        rows.append({"S.No": len(rows)+1, "Metric": k, "Result": v, "Comments/ Recommendations": advise(k, v)})

    return pd.DataFrame(rows)

# def section_df(section_dict):
#     rows = []
#     for k, v in section_dict.items():
#         rows.append({
#             "S.No": len(rows)+1,
#             "Metric": k,
#             "Result": v,
#             "Comments/ Recommendations": advise(k, v)
#         })
#     return pd.DataFrame(rows)

# def show_table(title, data_dict):
#     st.markdown(f"### {title}")
#     df = section_df(data_dict)
#     st.dataframe(df, use_container_width=True, height=400)

def show_table(title, data_dict):
    st.markdown(f"### {title}")
    df = section_df(data_dict)
    st.dataframe(df, use_container_width=True, height=400)

def show_table(title, data_dict):
    st.markdown(f"### {title}")
    df = section_df(data_dict)
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
               'steps': [{'range': [0, 50], 'color': '#ffe5e5'},
                         {'range': [50, 75], 'color': '#fff6d6'},
                         {'range': [75, 100], 'color': '#e6ffe6'}]}
    ))
    st.plotly_chart(fig, use_container_width=True)
with c2:
    # st.markdown("### 📦 Bucket Breakdown")
    # bucket_df = pd.DataFrame([
    #     ["Visibility (30%)", vis_score],
    #     ["Reputation (40%)", rep_score],
    #     ["Experience (30%)", exp_score]
    # ], columns=["Bucket", "Score"])
    st.markdown("### 📦 Bucket Breakdown")
    col1, col2, col3 = st.columns(3)
    col1.metric("Visibility", f"{vis_score}/30")
    col2.metric("Reputation", f"{rep_score}/40")
    col3.metric("Experience", f"{exp_score}/30")
    # bucket_df["Comments/ Recommendations"] = bucket_df["Bucket"].apply(
    #     lambda b: "Double down on content & local SEO" if "Visibility" in b
    #     else ("Boost reviews & reply to negatives" if "Reputation" in b
    #           else "Enable online booking & publish hours/insurance")
    # )
    # st.dataframe(bucket_df, use_container_width=True)

st.markdown("---")
# show_table("1) Practice Overview", overview)

st.markdown("### 1) Practice Overview")
for idx, (k, v) in enumerate(overview.items(), start=1):
    st.markdown(f"**{idx}. {k}:** {v}")


show_table("2) Online Presence & Visibility", visibility)
show_table("3) Patient Reputation & Feedback", reputation)
if reviews:
    st.markdown("**Recent Google Reviews (sample)**")
    rev_df = pd.DataFrame(reviews)[["relative_time","rating","author_name","text"]]
    st.dataframe(
        rev_df,
        use_container_width=True,
        height=300,
        column_config={
            "relative_time": st.column_config.TextColumn("When", width="small"),
            "rating": st.column_config.NumberColumn("Rating", format="⭐ %d"),
            "author_name": st.column_config.TextColumn("Reviewer", width="medium"),
            "text": st.column_config.TextColumn("Review", width="large")
        }
    )

show_table("4) Marketing Signals", marketing)
show_table("5) Patient Experience & Accessibility", experience)
show_table("6) Competitive Benchmark", competitive)

# ------------------------ CSV export ------------------------
all_rows = []
def add_section(name, d):
    for k, v in d.items():
        all_rows.append([name, k, v, advise(k, v)])
add_section("Practice Overview", overview)
add_section("Visibility", visibility)
add_section("Reputation", reputation)
add_section("Marketing", marketing)
add_section("Experience", experience)
add_section("Competitive", competitive)
all_rows += [["Summary","Smile Score",smile,""],
             ["Summary","Visibility Bucket",vis_score,""],
             ["Summary","Reputation Bucket",rep_score,""],
             ["Summary","Experience Bucket",exp_score,""]]
export_df = pd.DataFrame(all_rows, columns=["Section","Metric","Result","Advice"])
st.download_button("⬇️ Download full results (CSV)",
                   data=export_df.to_csv(index=False).encode("utf-8"),
                   file_name=f"{(clinic_name or 'clinic').replace(' ','_')}_smile_audit.csv",
                   mime="text/csv")

# ------------------------ One-page PDF export (HTML → PDF via xhtml2pdf) ------------------------
# 1) Ensure template exists
ensure_default_template()

# 2) Create gauge PNG with plotly + kaleido (works on Streamlit Cloud)
gauge_png_path = os.path.join(ASSETS_DIR, "gauge.png")
gauge_fig = go.Figure(go.Indicator(
    mode="gauge+number",
    value=smile,
    title={'text': ""},
    gauge={'axis': {'range': [0, 100]},
           'bar': {'color': "#2E7D32"},
           'steps': [{'range': [0, 50], 'color': '#ffe5e5'},
                     {'range': [50, 75], 'color': '#fff6d6'},
                     {'range': [75, 100], 'color': '#e6ffe6'}]}
))
# Save the image (requires kaleido; included in requirements)
gauge_fig.write_image(gauge_png_path, scale=2, width=300, height=250)

# 3) Prepare context for HTML template
logo_path = os.path.join(ASSETS_DIR, "logo.png")
logo_exists = os.path.exists(logo_path)

# Pick top recommendations (skip blanks)
recs = [
    advise("Search Visibility (Page 1?)", visibility["Search Visibility (Page 1?)"]),
    advise("Google Reviews (Avg)", reputation["Google Reviews (Avg)"]),
    advise("Appointment Booking", experience["Appointment Booking"]),
]
recs = [r for r in recs if r] or ["Keep up the good work!"]
recs = recs[:4]

env = Environment(loader=FileSystemLoader(TEMPLATES_DIR),
                  autoescape=select_autoescape(['html', 'xml']))
template = env.get_template("smile_report.html")
html_str = template.render(
    clinic_name=clinic_name or "Clinic",
    overview=overview,
    visibility=visibility,
    reputation=reputation,
    experience=experience,
    vis_score=vis_score,
    rep_score=rep_score,
    exp_score=exp_score,
    gauge_path=gauge_png_path,     # absolute path on container
    logo_exists=logo_exists,
    logo_path=logo_path
)

# 4) Convert HTML → PDF with xhtml2pdf
pdf_buffer = io.BytesIO()
pisa.CreatePDF(src=html_str, dest=pdf_buffer)  # xhtml2pdf reads HTML string and writes to buffer
pdf_bytes = pdf_buffer.getvalue()

st.download_button(
    "📄 Download One-Page PDF",
    data=pdf_bytes,
    file_name=f"{(clinic_name or 'clinic').replace(' ','_')}_smile_audit.pdf",
    mime="application/pdf"
)
