# Debt Analysis Module for Perfient
import streamlit as st
from typing import List, Dict, Any
import os
import requests

st.set_page_config(page_title="Debt Analysis", layout="centered")

st.title("💳 Debt Analysis & Optimization")
st.markdown("""
Perfient helps you make smarter debt decisions. Explore new debt options or see if you can switch to a better deal based on your financial profile.
""")

tab1, tab2 = st.tabs(["🔍 New Debt Check", "🔄 Switch to Better Debt"])

# --- (a) New Debt Check ---
with tab1:
    st.header("Find the Best Interest Rate for You")
    st.markdown("""
    Enter your loan needs and we'll estimate the best available interest rate (APR) based on public rate tables from major German banks and your profile.
    """)
    loan_type = st.selectbox("Type of Loan", ["Personal Loan", "Home Loan", "Auto Loan", "Credit Card", "Student Loan", "Other"])
    amount = st.number_input("Loan Amount Needed ($)", min_value=1000, max_value=2_000_000, step=500, value=10_000)
    term_years = st.slider("Desired Term (years)", 1, 30, 5)
    credit_score = st.selectbox("Estimated Credit Score", ["Excellent (750+)", "Good (700-749)", "Fair (650-699)", "Poor (<650)"])
    purpose = st.text_input("Purpose (optional)")

    if st.button("Check Best Available Rate", key="search_debt"):
        best_rate = get_best_public_rate(loan_type, credit_score)
        st.success(f"The best available APR for a {loan_type} with your profile is **{best_rate:.2f}%** (public rate tables, Germany).")
        st.caption("Contact banks directly for personalized rates. Perfient does not broker loans.")

# --- (b) Switch to Better Debt ---
with tab2:
    st.header("Switch to a Better Debt Option")
    st.markdown("""
    Enter your current debt details. We'll check if you're paying a higher interest rate than necessary and show you the best available public rate for your profile.
    """)
    current_type = st.selectbox("Current Debt Type", ["Personal Loan", "Home Loan", "Auto Loan", "Credit Card", "Student Loan", "Other"], key="current_type")
    current_balance = st.number_input("Current Balance ($)", min_value=100, max_value=2_000_000, step=100, value=5000)
    current_apr = st.number_input("Current APR (%)", min_value=0.1, max_value=40.0, step=0.1, value=12.0)
    current_term = st.slider("Remaining Term (years)", 1, 30, 3)
    orig_lender = st.text_input("Current Lender (optional)", key="orig_lender")
    credit_score2 = st.selectbox("Estimated Credit Score", ["Excellent (750+)", "Good (700-749)", "Fair (650-699)", "Poor (<650)"], key="credit_score2")

    if st.button("Check for Better Rate", key="check_better_debt"):
        best_rate = get_best_public_rate(current_type, credit_score2)
        if current_apr > best_rate:
            st.warning(f"Your current APR of {current_apr:.2f}% is above the best available public rate of {best_rate:.2f}% for your profile.")
            st.info("Consider refinancing or consolidating your debt. Always check fees and eligibility.")
        else:
            st.success(f"Your current APR of {current_apr:.2f}% is competitive with the best available public rate ({best_rate:.2f}%).")

# --- Mock Web Scraping for Best Public Rates ---
def get_best_public_rate(loan_type: str, credit_score: str, country: str = "DE") -> float:
    """
    Simulate scraping public rate tables from major German banks/credit unions.
    Returns the best (lowest) available APR for the given loan type and credit score.
    """
    # Example mapping (in production, scrape real data)
    base_rates = {
        "Personal Loan": 5.2,
        "Home Loan": 3.1,
        "Auto Loan": 3.9,
        "Credit Card": 8.5,
        "Student Loan": 2.5,
        "Other": 6.0,
    }
    credit_mod = {
        "Excellent (750+)": -0.5,
        "Good (700-749)": 0.0,
        "Fair (650-699)": 1.0,
        "Poor (<650)": 2.5,
    }
    rate = base_rates.get(loan_type, 6.0) + credit_mod.get(credit_score, 0.0)
    return round(rate, 2)

st.markdown("---")
st.caption("Perfient does not provide financial advice or broker loans. Always compare offers and consult a professional if needed.")
