from ..config import PE_NO_GROWTH,GIV_N_CONST
from ..data.bonds import get_aaa_yield

def calculate_giv(eps,g,country):
    cy=get_aaa_yield(country)
    avg=0.05
    pe=PE_NO_GROWTH+GIV_N_CONST*g
    return eps*pe*(avg/cy)
