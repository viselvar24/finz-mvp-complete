def discount(v,r,t): return v/((1+r)**t)
def growing_value(cf_last,r,g,periods):
    return (cf_last*(1+g))/(r-g)/((1+r)**periods)
