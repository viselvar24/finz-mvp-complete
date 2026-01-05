import os

# Use environment variable or fallback to hardcoded key
TIINGO_API_KEY = os.getenv("TIINGO_API_KEY", "12a4b6199b51d43953b990b9ec734b451e05d8e1")
FRED_API_KEY = os.getenv("FRED_API_KEY")

PE_NO_GROWTH = 7
GIV_N_CONST = 1
DCF_DISCOUNT_FLOOR = 0.04
DCF_TERMINAL_GROWTH = 0.02
DDM_DISCOUNT_FLOOR = 0.04
FALLBACK_YIELD = 0.03

# Only warn if no key is available (shouldn't happen with fallback)
if not TIINGO_API_KEY:
    import warnings
    warnings.warn("TIINGO_API_KEY not set - valuation analysis may fail")
