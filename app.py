# app.py
import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import time
import plotly.graph_objects as go

st.set_page_config(page_title="Dental Clinic Smile Audit", layout="wide")

st.title("🦷 Dental Clinic Smile Audit")

# ---------------- INPUTS ----------------
clinic_name = st.text_input("Clinic Name")
address = st.text_input("Address")
phone = st.text_input("Phone Number")
website = st.text_input("Website URL (include http/https)")

if st.button("Run Audit"):
    results = {}
    
    # ---------------- SCRAPING HELPERS ----------------
    def fetch_html(url):
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
        except Exception:
            return None
        return None

    def find_years_in_operation(soup):
        if not soup: return "Search limited"
        text = soup.get_text(" ", strip=True)
        years = re.findall(r"(19|20)\d{2}", text)
        if years:
            return min(years)  # earliest year found
        return "Search limited"

    def find_specialties(soup):
        if not soup: return "Search limited"
        text = soup.get_text(" ", strip=True).lower()
        keywords = ["general dentistry", "orthodontics", "implants", "cosmetic", "pediatric", "family dentistry"]
        found = [k for k in keywords if k in text]
        return ", ".join(found) if found else "Search limited"

    def website_health(url, soup):
        if not url: return "Search limited"
        score = 0
        # HTTPS
        if url.startswith("https"): score += 30
        # Mobile friendly
        if soup and soup.find("meta", {"name": "viewport"}): score += 30
        # Load speed (rough time)
        try:
            t0 = time.time()
            requests.get(url, timeout=5)
            load_time = time.time() - t0
            if load_time < 2: score += 40
            elif load_time < 5: score += 20
        except:
            pass
        return f"{score}/100"

    def social_presence(soup):
        if not soup: return "Search limited"
        links = [a.get("href") for a in soup.find_all("a", href=True)]
        fb = [l for l in links if "facebook.com" in l]
        ig = [l for l in links if "instagram.com" in l]
        return f"Facebook: {len(fb)>0}, Instagram: {len(ig)>0}"

    # ---------------- RUN CHECKS ----------------
    soup = fetch_html(website) if website else None

    results["Clinic Name"] = clinic_name or "Search limited"
    results["Address"] = address or "Search limited"
    results["Phone"] = phone or "Search limited"
    results["Website"] = website or "Search limited"

    results["Years in Operation"] = find_years_in_operation(soup)
    results["Specialties"] = find_specialties(soup)
    results["Google Business Profile"] = "Search limited"  # Needs Maps scraping
    results["Search Visibility"] = "Search limited"        # Needs SERP scraping
    results["Website Health"] = website_health(website, soup)
    results["Social Media Presence"] = social_presence(soup)

    # Reviews placeholders (could extend with scraping SERPs)
    results["Google Reviews Avg"] = "Search limited"
    results["Total Reviews"] = "Search limited"
    results["Sentiment Highlights"] = "Search limited"
    results["Yelp/Healthgrades/Zocdoc Reviews"] = "Search limited"
    results["Top Positive Themes"] = "Search limited"
    results["Top Negative Themes"] = "Search limited"
    results["Review Response Rate"] = "Search limited"

    # Marketing / Experience placeholders
    results["Local SEO Score"] = "Search limited"
    results["Photos & Videos Online"] = len(soup.find_all("img")) if soup else "Search limited"
    results["Advertising Signals"] = "Google Ads/FB Pixel found" if soup and ("gtag.js" in soup.text or "fbq(" in soup.text) else "None"
    results["Appointment Booking"] = "Online booking detected" if soup and "book" in soup.text.lower() else "Search limited"
    results["Office Hours"] = "Search limited"
    results["Insurance Acceptance"] = "Search limited"
    results["Rating Comparison (Top 3 in City)"] = "Search limited"

    # Composite Smile Score (dummy logic – assign partial weights where data found)
    visibility = 20 if results["Website Health"] != "Search limited" else 10
    reputation = 10  # placeholder
    experience = 10 if results["Appointment Booking"] != "Search limited" else 5
    smile_score = visibility + reputation + experience

    results["Smile Score"] = smile_score

    # ---------------- DISPLAY ----------------
    st.subheader("📊 Audit Results")

    for k, v in results.items():
        st.write(f"**{k}:** {v}")

    st.subheader("Smile Score Gauge")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=smile_score,
        title={'text': "Smile Score"},
        gauge={'axis': {'range': [0, 100]},
               'bar': {'color': "green"}}
    ))
    st.plotly_chart(fig, use_container_width=True)
