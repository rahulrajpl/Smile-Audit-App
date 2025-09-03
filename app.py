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
from xhtml2pdf import pisa  # pure-Python PDF engine

# ------------------------ Page & Config ------------------------
st.set_page_config(page_title="Smile Audit", layout="wide")

# Title & Subtitle
st.title("Smile Audit")
st.subheader("Undertake an AI based Smile Audit to know the digital health of your Clinic")

# Keys (prefer Streamlit secrets, fallback to env)
PLACES_API_KEY = st.secrets.get("GOOGLE_PLACES_API_KEY", os.getenv("GOOGLE_PLACES_API_KEY"))
CSE_API_KEY    = st.secrets.get("GOOGLE_CSE_API_KEY", os.getenv("GOOGLE_CSE_API_KEY"))
CSE_CX         = st.secrets.get("GOOGLE_CSE_CX", os.getenv("GOOGLE_CSE_CX"))

DEBUG = st.sidebar.checkbox("Show debug info")

# ------------------------ Utility Functions ------------------------
def section_df(section_dict):
    rows = []
    for i, (k, v) in enumerate(section_dict.items(), start=1):
        rows.append({
            "S.No": i,
            "Metric": k,
            "Result": v,
            "Comments/ Recommendations": advise(k, v)
        })
    return pd.DataFrame(rows)

def show_table(title, data_dict):
    st.markdown(f"#### {title}")
    df = section_df(data_dict)
    st.dataframe(df, use_container_width=True, height=400)

# (👉 keep all your API helpers, scraping functions, scoring functions, and `advise()` function unchanged)
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

# ------------------------ Input Form ------------------------
with st.form("audit_form"):
    clinic_name = st.text_input("Clinic Name")
    address = st.text_input("Address")
    phone = st.text_input("Phone Number")
    website = st.text_input("Website URL (include http/https)")
    submitted = st.form_submit_button("Run Audit")

if not submitted:
    st.info("Enter details and click **Run Audit**.")
    st.stop()

# ------------------------ Run your existing audit logic here ------------------------
# (👉 keep your scraping, API calls, visibility, reputation, marketing, experience, competitive sections here)
# For brevity not repeated, but you must retain all existing logic from your last working version.

# Example placeholders after computing everything:
overview = {
    "Practice Name": clinic_name or "Search limited",
    "Address": address or "Search limited",
    "Phone": phone or "Search limited",
    "Website": website or "Search limited",
    "Years in Operation": "2010",
    "Specialties Highlighted": "General Dentistry, Implants"
}
visibility = {"GBP Completeness (estimate)": "80/100", "Search Visibility (Page 1?)": "Yes (Page 1)"}
reputation = {"Google Reviews (Avg)": "4.5/5", "Total Google Reviews": 128}
experience = {"Appointment Booking": "Online booking (link/form)", "Office Hours": "Mon–Fri 9–5"}
marketing = {"Photos/Videos on Website": "12 photos"}
competitive = {"Avg Rating of Top 3 Nearby": "4.7"}
smile, vis_score, rep_score, exp_score = 78, 22, 32, 24
reviews = [{"relative_time": "2 weeks ago", "rating": 5, "author_name": "Alice", "text": "Great staff and clean clinic!"}]

# ------------------------ Tabs UI ------------------------
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🏥 Overview",
    "🌐 Visibility",
    "⭐ Reputation",
    "👥 Experience",
    "📢 Marketing",
    "📊 Competitive",
    "⬇️ Export"
])

with tab1:
    st.markdown("### 1) Practice Overview")
    for idx, (k, v) in enumerate(overview.items(), start=1):
        st.markdown(f"**{idx}. {k}:** {v}")

    st.markdown("### 🧭 Smile Score")
    col1, col2, col3 = st.columns(3)
    col1.metric("Visibility", f"{vis_score}/30")
    col2.metric("Reputation", f"{rep_score}/40")
    col3.metric("Experience", f"{exp_score}/30")

    st.progress(int(smile))

    if smile >= 75:
        st.success("Great digital presence! Your clinic is performing very well 🎉")
    elif smile >= 50:
        st.warning("Your digital presence is decent but there is room to improve.")
    else:
        st.error("⚠️ Critical improvement needed in digital presence!")

with tab2:
    show_table("2) Online Presence & Visibility", visibility)

with tab3:
    show_table("3) Patient Reputation & Feedback", reputation)
    if reviews:
        with st.expander("📖 See Recent Google Reviews"):
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

with tab4:
    show_table("5) Patient Experience & Accessibility", experience)

with tab5:
    show_table("4) Marketing Signals", marketing)

with tab6:
    show_table("6) Competitive Benchmark", competitive)

with tab7:
    st.markdown("### 📂 Export Options")

    # Export CSV
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
    export_df = pd.DataFrame(all_rows, columns=["Section","Metric","Result","Comments/ Recommendations"])

    st.download_button("⬇️ Download full results (CSV)",
                       data=export_df.to_csv(index=False).encode("utf-8"),
                       file_name=f"{(clinic_name or 'clinic').replace(' ','_')}_smile_audit.csv",
                       mime="text/csv")

    # Export PDF (reuse your existing PDF generation logic here)
    pdf_bytes = b"%PDF-1.4..."  # placeholder, replace with your PDF builder
    st.download_button(
        "📄 Download One-Page PDF",
        data=pdf_bytes,
        file_name=f"{(clinic_name or 'clinic').replace(' ','_')}_smile_audit.pdf",
        mime="application/pdf"
    )
