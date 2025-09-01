# app.py
import os, time, re, requests, pandas as pd
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="Dental Clinic Smile Audit (API-Enhanced)", layout="wide")
st.title("🦷 Dental Clinic Smile Audit (API-Enhanced)")

# ------------------------ Secrets / Env ------------------------
PLACES_API_KEY = st.secrets.get("GOOGLE_PLACES_API_KEY", os.getenv("GOOGLE_PLACES_API_KEY"))
CSE_API_KEY    = st.secrets.get("GOOGLE_CSE_API_KEY", os.getenv("GOOGLE_CSE_API_KEY"))
CSE_CX         = st.secrets.get("GOOGLE_CSE_CX", os.getenv("GOOGLE_CSE_CX"))

DEBUG = st.sidebar.checkbox("Show debug info")

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

# ------------------------ Google Places ------------------------
def places_text_search(query: str):
    if not PLACES_API_KEY: return None
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": query, "key": PLACES_API_KEY}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    st.sidebar.write("Places status:", data.get("status"))
    st.sidebar.write("Places error_message:", data.get("error_message"))
    return r.json() if r.status_code == 200 else None

def places_find_place(text_query: str):
    """Fallback when text search can't find the right listing."""
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
    # IMPORTANT: include 'reviews' explicitly
    fields = ",".join([
        "name","place_id","formatted_address","international_phone_number","website",
        "opening_hours","photos","rating","user_ratings_total","types","geometry/location",
        "reviews"
    ])
    params = {"place_id": place_id, "fields": fields, "key": PLACES_API_KEY}
    r = requests.get(url, params=params, timeout=10)
    return r.json() if r.status_code == 200 else None

def find_best_place_id(clinic_name: str, address: str, website: str):
    """Try text search with full query, then by name, then fallback to find-place."""
    queries = []
    if clinic_name and address:
        queries.append(f"{clinic_name} {address}")
    if clinic_name:
        queries.append(clinic_name)
    if website:
        domain = get_domain(website)
        if domain:
            queries.append(domain)

    # text search first
    for q in queries:
        js = places_text_search(q)
        if DEBUG: st.sidebar.write("Text Search:", q, (js or {}).get("status"))
        if js and js.get("status") == "OK":
            res = js.get("results", [])
            if res:
                return res[0].get("place_id")

    # fallback to find-place
    for q in queries:
        js = places_find_place(q)
        if DEBUG: st.sidebar.write("Find Place:", q, (js or {}).get("status"))
        if js and js.get("status") == "OK":
            cands = js.get("candidates", [])
            if cands:
                return cands[0].get("place_id")

    return None

def rating_reviews_from_places(details: dict):
    if not details or details.get("status") != "OK":
        return "Search limited", "Search limited"
    res = details.get("result", {})
    rating = res.get("rating")
    count = res.get("user_ratings_total")
    return (f"{rating}/5" if rating is not None else "Search limited",
            count if count is not None else "Search limited")

def extract_reviews_from_places(details_json):
    """
    Returns: (reviews_list, rating_float_or_None, total_reviews_or_None)
    reviews_list: list of dicts {rating, text, time, author_name}
    """
    if not details_json or details_json.get("status") != "OK":
        return [], None, None
    res = details_json.get("result", {})
    reviews = res.get("reviews", []) or []
    simplified = []
    for rv in reviews:
        simplified.append({
            "rating": rv.get("rating"),
            "text": rv.get("text") or "",
            "time": rv.get("time"),
            "relative_time": rv.get("relative_time_description"),
            "author_name": rv.get("author_name")
        })
    rating = res.get("rating")
    total = res.get("user_ratings_total")
    return simplified, (float(rating) if rating is not None else None), (int(total) if total is not None else None)

def analyze_review_texts(reviews):
    """Keyword-based highlights & themes (no external NLP)."""
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
            if c > 0:
                scores[theme] = c
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    pos = count_hits(positive_themes)
    neg = count_hits(negative_themes)
    pos_total = sum(v for _, v in pos)
    neg_total = sum(v for _, v in neg)

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

# ------------------------ Custom Search (optional) ------------------------
def appears_on_page1_for_dentist_near_me(website: str, clinic_name: str, address: str):
    if not (CSE_API_KEY and CSE_CX): return "Search limited"
    try:
        domain = None
        if website:
            domain = get_domain(website)
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

def office_hours_from_places(details: dict):
    if not details or details.get("status") != "OK": return "Search limited"
    res = details["result"]
    oh = res.get("opening_hours", {})
    wt = oh.get("weekday_text")
    return "; ".join(wt) if wt else "Search limited"

def photos_count_from_places(details: dict):
    if not details or details.get("status") != "OK": return "Search limited"
    return len(details["result"].get("photos", []))

def accessibility_from_places(details: dict):
    # Places legacy doesn't expose full accessibility fields; keep limited.
    return "Search limited"

# ------------------------ Scoring ------------------------
def to_pct_from_score_str(s):
    try:
        if isinstance(s, str) and "/" in s:
            return int(s.split("/")[0])
    except:
        pass
    return None

def compute_smile_score(wh_pct, social_present, rating, reviews_total, booking, hours_present, insurance_clear, accessibility_present):
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

    # Places lookup
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
    social_present = "Facebook, Instagram" if soup and any("instagram.com" in (a.get('href') or '') for a in soup.find_all("a", href=True)) and any("facebook.com" in (a.get('href') or '') for a in soup.find_all("a", href=True)) else (
                     "Instagram" if soup and any("instagram.com" in (a.get('href') or '') for a in soup.find_all("a", href=True)) else (
                     "Facebook" if soup and any("facebook.com" in (a.get('href') or '') for a in soup.find_all("a", href=True)) else "None"))
    appears = appears_on_page1_for_dentist_near_me(website, clinic_name, address)
    gbp_score = "Search limited"; gbp_signals = "Search limited"
    if details and details.get("status") == "OK":
        # simple completeness proxy from details
        res = details["result"]
        score = 0; checks = []
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
        else: checks.append("Address ❌")
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

    # 3) Reputation (FIXED: pull reviews + themes)
    reviews, rating_val, total_reviews = extract_reviews_from_places(details) if details else ([], None, None)
    rating_str = f"{rating_val}/5" if isinstance(rating_val, (int,float)) else "Search limited"
    total_reviews_str = total_reviews if isinstance(total_reviews, int) else "Search limited"
    sentiment_summary, top_pos_str, top_neg_str = analyze_review_texts(reviews)

    reputation = {
        "Google Reviews (Avg)": rating_str,
        "Total Google Reviews": total_reviews_str,
        "Sentiment Highlights": sentiment_summary,
        "Yelp / Healthgrades / Zocdoc": "Search limited",
        "Top Positive Themes": top_pos_str,
        "Top Negative Themes": top_neg_str,
        "Review Response Rate": "Not available via Places API (GBP needed)"
    }

    # Show raw recent reviews table (if any)
    if reviews:
        st.markdown("### 🗣️ Recent Google Reviews (from Places)")
        rev_df = pd.DataFrame(reviews)[["relative_time","rating","author_name","text"]]
        st.dataframe(rev_df, use_container_width=True)
    elif DEBUG:
        st.warning("No reviews returned by Places Details for this listing (not unusual).")

    # 4) Marketing
    site_soup, t = soup, load_time
    marketing = {
        "Photos/Videos on Website": (lambda s: f"{len(s.find_all('img'))} photos, {len(s.find_all(['video','source']))} videos")(site_soup) if site_soup else "Search limited",
        "Photos count in Google": photos_count_from_places(details) if details else "Search limited",
        "Advertising Scripts Detected": advertising_signals(site_soup) if site_soup else "Search limited",
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
        "Accessibility Signals": "Search limited"  # legacy Places doesn't expose robust accessibility
    }

    # 6) Competitive
    competitive = {"Avg Rating of Top 3 Nearby": "Search limited"}

    # ------------------------ Scoring ------------------------
    def to_pct_from_score_str(s):
        try:
            return int(s.split("/")[0])
        except:
            return None
    wh_pct = to_pct_from_score_str(wh_str)
    social_present_val = visibility["Social Media Presence"]
    hours_present = isinstance(hours, str) and hours != "Search limited"
    insurance_clear = isinstance(insurance, str) and insurance not in ["Search limited", "Unclear"]
    accessibility_present = False  # kept false; not available via Places legacy

    smile, vis_score, rep_score, exp_score = (
        (lambda wh, sp, r, n, b, h, ins, acc:
            (lambda vis_parts:
                (round(((sum(vis_parts)/len(vis_parts)) if vis_parts else 0)/100*30 +   # Visibility
                       (((r/5)*100 + min(1, (n or 0)/500)*100)/2)/100*40 +              # Reputation
                       (((80 if "Online booking" in (b or "") else 40 if "Phone-only" in (b or "") else 0) +
                         (70 if h else 0) + (80 if ins else 0) + (70 if acc else 0))/4)/100*30, 1),
                 round((((sum(vis_parts)/len(vis_parts)) if vis_parts else 0)/100*30),1),
                 round(((((r/5)*100 if r else 0) + (min(1, (n or 0)/500)*100))/2)/100*40,1),
                 round((((80 if "Online booking" in (b or "") else 40 if "Phone-only" in (b or "") else 0) +
                         (70 if h else 0) + (80 if ins else 0) + (70 if acc else 0))/4)/100*30,1))
            )(([p for p in [wh, (100 if sp=="Facebook, Instagram" else 60 if sp in ("Facebook","Instagram") else 0)] if isinstance(p,(int,float))]))
        )(wh_pct, social_present_val,
          (rating_val if isinstance(rating_val,(int,float)) else 0),
          (total_reviews if isinstance(total_reviews,int) else 0),
          booking, hours_present, insurance_clear, accessibility_present)
    )

    # ------------------------ Display Tables ------------------------
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
                   'steps': [{'range': [0, 50], 'color': '#ffe5e5'},
                             {'range': [50, 75], 'color': '#fff6d6'},
                             {'range': [75, 100], 'color': '#e6ffe6'}]}
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

    # Debug raw JSON (safe snippet)
    if DEBUG:
        with st.expander("Raw Places Details JSON (truncated)"):
            st.code(str(details)[:5000])
