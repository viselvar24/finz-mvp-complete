AAA_MAPPING={
 'US':{'series':'AAA','fallback':None},
 'UK':{'series':'IRLTLT01GBM156N','fallback':None},
 'EU':{'series':'IRLTLT01DEM156N','fallback':None},
 'JP':{'series':'IRLTLT01JPM156N','fallback':None},
 'AU':{'series':'IRLTLT01AUM156N','fallback':None},
 'CA':{'series':'IRLTLT01CAM156N','fallback':None},
 'IN':{'series':'IRLTLT01INM156N','fallback':None},
 'HK':{'series':None,'fallback':0.03},
 'SG':{'series':None,'fallback':0.03},
 'OTHER':{'series':None,'fallback':0.03},
}
def detect_region(code):
    code=code.upper()
    if code in AAA_MAPPING: return code
    if code in ['DE','FR','NL','BE','IT','ES','FI','AT','PT','IE']: return 'EU'
    return 'OTHER'
