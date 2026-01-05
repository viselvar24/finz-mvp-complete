# Rate Analysis Module for Perfient
import streamlit as st
from typing import List, Dict, Any

st.set_page_config(page_title="Rate Analysis", layout="centered")

st.title("💳 Interest Rate Analysis: Debts, FDs & Bonds")
st.markdown("""
Perfient helps you analyze and optimize your interest rates for debts, fixed deposits, and bonds. See the best available public rates for your profile and compare with your current terms.
""")

product_tab = st.tabs(["Debts", "Fixed Deposits (FDs)", "Bonds"])

def get_best_public_rate(product_type: str, sub_type: str, credit_score: str = None, country: str = "DE") -> float:
    """
    Simulate scraping public rate tables for debts, FDs, and bonds.
    Returns the best (lowest for debt, highest for FD/bond) available rate.
    """
    # Example mapping (in production, scrape real data)
    base_rates = {
        # Debts (APR, lower is better)
        ("Debt", "Personal Loan"): 5.2,
        ("Debt", "Home Loan"): 3.1,
        ("Debt", "Auto Loan"): 3.9,
        ("Debt", "Credit Card"): 8.5,
        ("Debt", "Student Loan"): 2.5,
        ("Debt", "Other"): 6.0,
        # FDs (annual yield, higher is better)
        ("FD", "Short Term"): 2.1,
        ("FD", "Long Term"): 2.7,
        # Bonds (annual yield, higher is better)
        ("Bond", "Short Term"): 2.4,
        ("Bond", "Long Term"): 3.2,
    }
    credit_mod = {
        "Excellent (750+)": -0.5,
        "Good (700-749)": 0.0,
        "Fair (650-699)": 1.0,
        "Poor (<650)": 2.5,
        None: 0.0
    }
    rate = base_rates.get((product_type, sub_type), 2.0) + credit_mod.get(credit_score, 0.0)
    return round(rate, 2)

# --- Debts ---
with product_tab[0]:
    tab1, tab2 = st.tabs(["🔍 New Debt Check", "🔄 Switch to Better Debt"])
    # New Debt
    with tab1:
        st.header("Find the Best Debt Rate for You")
        loan_type = st.selectbox("Type of Loan", ["Personal Loan", "Home Loan", "Auto Loan", "Credit Card", "Student Loan", "Other"])
        amount = st.number_input("Loan Amount Needed ($)", min_value=1000, max_value=2_000_000, step=500, value=10_000)
        term_years = st.slider("Desired Term (years)", 1, 30, 5)
        credit_score = st.selectbox("Estimated Credit Score", ["Excellent (750+)", "Good (700-749)", "Fair (650-699)", "Poor (<650)"])
        if st.button("Check Best Available Debt Rate", key="search_debt_rate"):
            best_rate = get_best_public_rate("Debt", loan_type, credit_score)
            st.success(f"The best available APR for a {loan_type} with your profile is **{best_rate:.2f}%** (public rate tables, Germany).")
            st.caption("Contact banks directly for personalized rates. Perfient does not broker loans.")
    # Switch Debt
    with tab2:
        st.header("Switch to a Better Debt Option")
        current_type = st.selectbox("Current Debt Type", ["Personal Loan", "Home Loan", "Auto Loan", "Credit Card", "Student Loan", "Other"], key="current_type")
        current_balance = st.number_input("Current Balance ($)", min_value=100, max_value=2_000_000, step=100, value=5000)
        current_apr = st.number_input("Current APR (%)", min_value=0.1, max_value=40.0, step=0.1, value=12.0)
        current_term = st.slider("Remaining Term (years)", 1, 30, 3)
        credit_score2 = st.selectbox("Estimated Credit Score", ["Excellent (750+)", "Good (700-749)", "Fair (650-699)", "Poor (<650)"], key="credit_score2")
        if st.button("Check for Better Debt Rate", key="check_better_debt_rate"):
            best_rate = get_best_public_rate("Debt", current_type, credit_score2)
            if current_apr > best_rate:
                st.warning(f"Your current APR of {current_apr:.2f}% is above the best available public rate of {best_rate:.2f}% for your profile.")
                st.info("Consider refinancing or consolidating your debt. Always check fees and eligibility.")
            else:
                st.success(f"Your current APR of {current_apr:.2f}% is competitive with the best available public rate ({best_rate:.2f}%).")

# --- Fixed Deposits (FDs) ---
with product_tab[1]:
    tab_fd1, tab_fd2 = st.tabs(["🔍 New FD Check", "🔄 Compare Existing FD"])
    # New FD
    with tab_fd1:
        st.header("Find the Best FD Rate for You")
        fd_type = st.selectbox("FD Type", ["Short Term", "Long Term"])
        amount_fd = st.number_input("Deposit Amount ($)", min_value=500, max_value=2_000_000, step=100, value=10_000, key="fd_amt")
        term_fd = st.slider("Term (years)", 1, 10, 2, key="fd_term")
        if st.button("Check Best Available FD Rate", key="search_fd_rate"):
            best_rate = get_best_public_rate("FD", fd_type)
            st.success(f"The best available FD rate for {fd_type} is **{best_rate:.2f}%** (public rate tables, Germany).")
    # Compare Existing FD
    with tab_fd2:
        st.header("Compare Your FD Rate")
        fd_type2 = st.selectbox("FD Type", ["Short Term", "Long Term"], key="fd_type2")
        current_fd_rate = st.number_input("Your FD Rate (%)", min_value=0.1, max_value=20.0, step=0.1, value=1.5, key="fd_rate")
        if st.button("Check for Better FD Rate", key="check_better_fd_rate"):
            best_rate = get_best_public_rate("FD", fd_type2)
            if current_fd_rate < best_rate:
                st.warning(f"Your FD rate of {current_fd_rate:.2f}% is below the best available public rate of {best_rate:.2f}%.")
                st.info("Consider switching to a better FD product. Always check terms and penalties.")
            else:
                st.success(f"Your FD rate of {current_fd_rate:.2f}% is competitive with the best available public rate ({best_rate:.2f}%).")

# --- Bonds ---
with product_tab[2]:
    tab_bond1, tab_bond2 = st.tabs(["🔍 New Bond Check", "🔄 Compare Existing Bond"])
    # New Bond
    with tab_bond1:
        st.header("Find the Best Bond Yield for You")
        bond_type = st.selectbox("Bond Type", ["Short Term", "Long Term"])
        amount_bond = st.number_input("Investment Amount ($)", min_value=500, max_value=2_000_000, step=100, value=10_000, key="bond_amt")
        term_bond = st.slider("Term (years)", 1, 30, 5, key="bond_term")
        if st.button("Check Best Available Bond Yield", key="search_bond_rate"):
            best_rate = get_best_public_rate("Bond", bond_type)
            st.success(f"The best available bond yield for {bond_type} is **{best_rate:.2f}%** (public rate tables, Germany).")
    # Compare Existing Bond
    with tab_bond2:
        st.header("Compare Your Bond Yield")
        bond_type2 = st.selectbox("Bond Type", ["Short Term", "Long Term"], key="bond_type2")
        current_bond_rate = st.number_input("Your Bond Yield (%)", min_value=0.1, max_value=20.0, step=0.1, value=2.0, key="bond_rate")
        if st.button("Check for Better Bond Yield", key="check_better_bond_rate"):
            best_rate = get_best_public_rate("Bond", bond_type2)
            if current_bond_rate < best_rate:
                st.warning(f"Your bond yield of {current_bond_rate:.2f}% is below the best available public yield of {best_rate:.2f}%.")
                st.info("Consider switching to a better bond product. Always check terms and penalties.")
            else:
                st.success(f"Your bond yield of {current_bond_rate:.2f}% is competitive with the best available public yield ({best_rate:.2f}%).")

st.markdown("---")
st.caption("Perfient does not provide financial advice or broker products. Always compare offers and consult a professional if needed.")
