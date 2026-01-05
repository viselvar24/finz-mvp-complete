import numpy as np

def calculate_mvm(eps: float, peer_list: list):
    """
    MVM = median(peer_PE) * EPS
    """    
    if not peer_list:
        return None
    peer_pes = [p["pe"] for p in peer_list if p["pe"] is not None]
    if not peer_pes:
        return None
    return np.median(peer_pes) * eps

