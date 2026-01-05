from ..config import DDM_DISCOUNT_FLOOR
from ..utils.math_utils import discount,growing_value

def calculate_ddm(divs,g,r):
    if r is None: r=DDM_DISCOUNT_FLOOR
    last=divs[-1]
    fc=[last*((1+g)**t) for t in range(1,6)]
    npv=sum(discount(d,r,t) for t,d in enumerate(fc,start=1))
    tv=growing_value(fc[-1],r,g,5)
    return npv+tv
