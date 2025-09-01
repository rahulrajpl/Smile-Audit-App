# app.py
import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import time
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Dental Clinic Smile Audit", layout="wide")
st.title("🦷 Dental Clinic Smile Audit")

# ------------------------- HELPERS (NO APIs) -------------------------
def fetch_html(url: str):
    if not url:
        return None, None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/125.0 Safari/537.36"
        }
        t0 = time.time()
        r = requests.get(url, headers=headers, timeout=10)
        load_time = time.time() - t0
        if r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser"), load_time
    except Exception:
        pass
    return None, None

def years_in_operation(soup: BeautifulSoup):
    if not soup:
        return "Search limited"
    text = soup.get_text(" ", strip=True)
    # look for earliest plausible year mention
    years = re.findall(r"(19|20)\d{2}", text)
    if years:
        # Try common phrasing to increase confidence
        m = re.search(r"(established|since|serving since|founded)\D*(19|20)\d{2}", text, re.I)
        if m:
            return re.search(r"(19|20)\d{2}", m.group(0)).group(0)
        return min(years)
    return "Search limited"

def specialties_highlighted(soup: BeautifulSoup):
    if not soup:
        return "Search limited"
    text = soup.get_text(" ", strip=True).lower()
    keywords = [
        "general dentistry", "orthodontics", "braces", "implants", "implant", "cosmetic",
        "veneers", "whitening", "endodontics", "root canal", "periodontics", "gum",
        "pediatric", "children", "oral surgery", "tmj", "sleep apnea", "invisalign",
        "prosthodontics", "crowns", "bridges", "dental implants"
    ]
    found = sorted(set(k for k in keywords if k in text))
    return ", ".join(found) if found else "Search limited"

def google_business_profile_score():
    # Requires Google properties to assess fully; we abstain from scraping SERPs/Maps here.
    return "Search limited"

def search_visibility():
    # Would require SERP scraping to know “first page for dentist near me”.
    return "Search limited"

def website_health(url: str, soup: BeautifulSoup, load_time: float):
    if not url:
        return "Search limited", "No URL"
    checks = []
    score = 0

    # HTTPS
    if url.lower().startswith("https"):
        score += 34
        checks.append("HTTPS ✅")
    else:
        checks.append("HTTPS ❌")

    # Mobile-friendly (viewport meta)
    if soup and soup.find("meta", attrs={"name": "viewport"}):
        score += 33
        checks.append("Mobile-friendly ✅")
    else:
        checks.append("Mobile-friendly ❌")

    # Load speed (very rough heuristic)
    if load_time is not None:
        if load_time < 2:
            score += 33
            checks.append(f"Load speed ✅ ({load_time:.2f}s)")
        elif load_time < 5:
            score += 16
            checks.append(f"Load speed ⚠️ ({load_time:.2f}s)")
        else:
            checks.append(f"Load speed ❌ ({load_time:.2f}s)")
    else:
        checks.append("Load speed ❓")

    return f"{min(score,100)}/100", " | ".join(checks)

def social_presence(soup: BeautifulSoup):
    if not soup:
        return "Search limited", "Search limited"
    links = [a.get("href") for a in soup.find_all("a", href=True)]
    fb_links = [l for l in links if "facebook.com" in l]
    ig_links = [l for l in links if "instagram.com" in l]
    platforms = []
    if fb_links: platforms.append("Facebook")
    if ig_links: platforms.append("Instagram")
    present = ", ".join(platforms) if platforms else "None"
    # Without APIs/logins we can’t get follower count or frequency reliably
    details = "Search limited"
    return present, details

def google_reviews():
    # Needs SERP or place scraping; avoid here per "no APIs"
    return "Search limited", "Search limited"

def sentiment_highlights():
    # Would require gathering review snippets; skip here
    return "Search limited", "Search limited"

def other_reviews():
    # Yelp/Healthgrades/Zocdoc scraping is risky without APIs/logins; mark limited
    return "Search limited"

def review_response_rate():
    return "Search limited"

def local_seo_score(clinic_name: str, address: str, phone: str):
    # Requires directory cross-checks; avoid scraping multiple sites
    return "Search limited"

def media_count(soup: BeautifulSoup):
    if not soup:
        return "Search limited"
    imgs = len(soup.find_all("img"))
    vids = len(soup.find_all(["video", "source"]))
    return f"{imgs} photos, {vids} videos"

def advertising_signals(soup: BeautifulSoup):
    if not soup:
        return "Search limited"
    txt = soup.get_text(" ", strip=True)
    html = str(soup)
    signals = []
    # Google Ads/Analytics/Tag
    if "gtag(" in html or "gtag.js" in html or "google-analytics.com" in html:
        signals.append("Google tag")
    # Facebook Pixel
    if "fbq(" in html:
        signals.append("Facebook Pixel")
    return ", ".join(signals) if signals else "None detected"

def appointment_booking(soup: BeautifulSoup):
    if not soup:
        return "Search limited"
    text = soup.get_text(" ", strip=True).lower()
    patterns = ["book", "appointment", "schedule", "reserve"]
    if any(p in text for p in patterns):
        # try to detect embedded booking widgets
        if "calendar" in text or "calendly" in text or "zocdoc" in text:
            return "Online booking (embedded)"
        return "Online booking (link/form)"
    return "Phone-only or unclear"

def office_hours(soup: BeautifulSoup):
    if not soup:
        return "Search limited"
    text = soup.get_text("\n", strip=True)
    # Try to find common hours formats quickly
    match = re.search(r"(Mon(day)?\.?\s*-\s*Sun(day)?\.?.{0,40})", text, re.I) \
        or re.search(r"(Mon(day)?\.?.{0,40}\d{1,2}(:\d{2})?\s*(AM|PM).{0,20}\d{1,2}(:\d{2})?\s*(AM|PM))", text, re.I)
    return match.group(0) if match else "Search limited"

def insurance_acceptance(soup: BeautifulSoup):
    if not soup:
        return "Search limited"
    text = soup.get_text(" ", strip=True).lower()
    if "insurance" in text or "we accept" in text or "dppo" in text or "ppo" in text or "delta dental" in text:
        # Try to extract a sentence
        m = re.search(r"([^.]*insurance[^.]*\.)", text)
        return m.group(0) if m else "Mentioned on site"
    return "Unclear"

def rating_comparison():
    # Needs city-wide scraping; mark limited
    return "Search limited"

def compute_smile_score(visibility_subscores, reputation_subscores, experience_subscores):
    # Each subscore should be a number 0..100 or None (for limited)
    def avg(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return sum(vals)/len(vals) if vals else None

    # Visibility: GBP (NA), Search (NA), WebsiteHealth (%), SocialPresence (binary->%)
    # Convert available pieces to 0..100 where possible
    vis_list = []
    wh = visibility_subscores.get("Website Health %")
    if isinstance(wh, (int, float)):
        vis_list.append(wh)
    sp = visibility_subscores.get("Social Presence %")
    if isinstance(sp, (int, float)):
        vis_list.append(sp)
    vis_avg = avg(vis_list)
    vis_score = (vis_avg/100)*30 if vis_avg is not None else 10  # fallback minimal

    rep_avg = avg([reputation_subscores.get("Google Rating %"),
                   reputation_subscores.get("Review Volume %"),
                   reputation_subscores.get("Sentiment %"),
                   reputation_subscores.get("Response %")])
    rep_score = (rep_avg/100)*40 if rep_avg is not None else 10

    exp_avg = avg([experience_subscores.get("Booking %"),
                   experience_subscores.get("Hours %"),
                   experience_subscores.get("Insurance %"),
                   experience_subscores.get("Accessibility %")])
    exp_score = (exp_avg/100)*30 if exp_avg is not None else 10

    total = round((vis_score + rep_score + exp_score), 1)
    return total, round(vis_score,1), round(rep_score,1), round(exp_score,1)

# ------------------------- INPUT UI -------------------------
with st.form("audit_form"):
    clinic_name = st.text_input("Clinic Name")
    address = st.text_input("Address")
    phone = st.text_input("Phone Number")
    website = st.text_input("Website URL (include http/https)")
    submitted = st.form_submit_button("Run Audit")

if not submitted:
    st.info("Enter details above and click **Run Audit** to generate the report.")
else:
    soup, load_time = fetch_html(website)

    # ------------------------- GATHER DATA -------------------------
    # 1. Practice Overview
    data_overview = {
        "Practice Name": clinic_name or "Search limited",
        "Location (address)": address or "Search limited",
        "Phone": phone or "Search limited",
        "Website": website or "Search limited",
        "Years in Operation": years_in_operation(soup),
        "Specialties Highlighted": specialties_highlighted(soup)
    }

    # 2. Online Presence & Visibility
    wh_score, wh_checks = website_health(website, soup, load_time)
    social_present, social_details = social_presence(soup)
    data_visibility = {
        "GBP Completeness": google_business_profile_score(),
        "Search Visibility (Page 1?)": search_visibility(),
        "Website Health Score": wh_score,
        "Website Health Checks": wh_checks,
        "Social Media Presence": social_present,
        "Social Media Details": social_details
    }

    # 3. Patient Reputation & Feedback
    g_avg, g_count = google_reviews()
    pos_high, neg_high = sentiment_highlights()
    data_reputation = {
        "Google Reviews (Avg)": g_avg,
        "Total Google Reviews": g_count,
        "Sentiment Highlights (Positive)": pos_high,
        "Sentiment Highlights (Negative)": neg_high,
        "Yelp / Healthgrades / Zocdoc": other_reviews(),
        "Top Positive Themes": "Search limited",
        "Top Negative Themes": "Search limited",
        "Review Response Rate": review_response_rate()
    }

    # 4. Marketing Signals
    data_marketing = {
        "Local SEO Score (NAP consistency)": local_seo_score(clinic_name, address, phone),
        "Number of Photos & Videos Online": media_count(soup),
        "Advertising Signals": advertising_signals(soup),
        "Social Proof (media/mentions)": "Search limited"
    }

    # 5. Patient Experience & Accessibility
    data_experience = {
        "Appointment Booking": appointment_booking(soup),
        "Office Hours": office_hours(soup),
        "Insurance Acceptance": insurance_acceptance(soup),
        "Accessibility Signals": "Search limited"  # would need maps/street data
    }

    # 6. Competitive Benchmark
    data_competitive = {
        "Compare Avg Rating vs Top 3 in City": rating_comparison()
    }

    # ------------------------- NUMERIC SUBSCORES FOR COMPOSITE -------------------------
    # Convert some heuristics to % for scoring where possible
    # Website health to %
    try:
        wh_percent = int(wh_score.split("/")[0]) if isinstance(wh_score, str) and "/" in wh_score else None
    except:
        wh_percent = None
    # Social presence (simple: any presence = 60%, both FB+IG = 100%)
    if social_present == "None":
        sp_percent = 0
    elif "Facebook" in social_present and "Instagram" in social_present:
        sp_percent = 100
    else:
        sp_percent = 60

    visibility_subscores = {
        "Website Health %": wh_percent,
        "Social Presence %": sp_percent
        # GBP/Search left as limited intentionally
    }

    # Reputation subscores placeholders (can't scrape reviews safely here)
    reputation_subscores = {
        "Google Rating %": None,
        "Review Volume %": None,
        "Sentiment %": None,
        "Response %": None
    }

    # Experience subscores (coarse heuristics)
    # Booking
    book_percent = 80 if "Online booking" in data_experience["Appointment Booking"] else (40 if "Phone-only" in data_experience["Appointment Booking"] else None)
    # Hours % unknown
    hours_percent = None
    # Insurance %
    insurance_percent = 80 if data_experience["Insurance Acceptance"] not in ["Search limited", "Unclear"] else None
    # Accessibility %
    accessibility_percent = None

    experience_subscores = {
        "Booking %": book_percent,
        "Hours %": hours_percent,
        "Insurance %": insurance_percent,
        "Accessibility %": accessibility_percent
    }

    smile_score, vis_score, rep_score, exp_score = compute_smile_score(
        visibility_subscores, reputation_subscores, experience_subscores
    )

    # ------------------------- DISPLAY IN TABLES -------------------------
    def show_table(title, data_dict):
        st.markdown(f"### {title}")
        df = pd.DataFrame(
            [(k, v) for k, v in data_dict.items()],
            columns=["Metric", "Result"]
        )
        # Make "Search limited" visually distinct
        df["Result"] = df["Result"].apply(lambda x: "Search limited" if (isinstance(x, str) and x.strip().lower()=="search limited") else x)
        st.dataframe(df, use_container_width=True)

    col1, col2 = st.columns([1,1])
    with col1:
        # BIG GAUGE
        st.markdown("### 🧭 Smile Score")
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=smile_score,
            title={'text': "Smile Score (0–100)"},
            gauge={
                'axis': {'range': [0, 100]},
                'bar': {'color': "seagreen"},
                'steps': [
                    {'range': [0, 50], 'color': '#ffe5e5'},
                    {'range': [50, 75], 'color': '#fff6d6'},
                    {'range': [75, 100], 'color': '#e6ffe6'}
                ]
            }
        ))
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        # Bucket breakdown table
        st.markdown("### 📦 Bucket Breakdown")
        bucket_df = pd.DataFrame([
            ["Visibility (30%)", vis_score],
            ["Reputation (40%)", rep_score],
            ["Experience (30%)", exp_score]
        ], columns=["Bucket", "Score"])
        st.dataframe(bucket_df, use_container_width=True)

    st.markdown("---")
    show_table("1) Practice Overview", data_overview)
    show_table("2) Online Presence & Visibility", data_visibility)
    show_table("3) Patient Reputation & Feedback", data_reputation)
    show_table("4) Marketing Signals", data_marketing)
    show_table("5) Patient Experience & Accessibility", data_experience)
    show_table("6) Competitive Benchmark", data_competitive)

    # Combined export
    all_rows = []
    def flatten(section, d):
        for k, v in d.items():
            all_rows.append([section, k, v])

    flatten("Practice Overview", data_overview)
    flatten("Visibility", data_visibility)
    flatten("Reputation", data_reputation)
    flatten("Marketing", data_marketing)
    flatten("Experience", data_experience)
    flatten("Competitive", data_competitive)
    all_rows.append(["Summary", "Smile Score", smile_score])
    all_rows.append(["Summary", "Visibility Bucket", vis_score])
    all_rows.append(["Summary", "Reputation Bucket", rep_score])
    all_rows.append(["Summary", "Experience Bucket", exp_score])

    export_df = pd.DataFrame(all_rows, columns=["Section", "Metric", "Result"])
    st.download_button(
        "⬇️ Download full results as CSV",
        data=export_df.to_csv(index=False).encode("utf-8"),
        file_name=f"{(clinic_name or 'clinic').replace(' ','_')}_smile_audit.csv",
        mime="text/csv"
    )

    st.caption("Note: This app avoids APIs and uses only lightweight scraping & heuristics. "
               "Where reliable data isn’t accessible without APIs, you’ll see “Search limited.”")
