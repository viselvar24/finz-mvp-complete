from ..config import DCF_DISCOUNT_FLOOR,DCF_TERMINAL_GROWTH
from ..utils.math_utils import discount,growing_value

def calculate_dcf(fcf,g,r):
    if r is None: r=DCF_DISCOUNT_FLOOR
    forecast=[fcf*((1+g)**t) for t in range(1,11)]
    npv=sum(discount(cf,r,t) for t,cf in enumerate(forecast,start=1))
    tv=growing_value(forecast[-1],r,DCF_TERMINAL_GROWTH,10)
    return npv+tv
