"""Field-only lifecycle policy. Legacy sensor validation remains unchanged."""
import math
from long_recording import validate as legacy_validate

def validate(cfg,duration):
    if not math.isfinite(float(duration)) or float(duration)<0:raise ValueError('field duration must be finite and >=0; 0 means continuous')
    if not legacy_validate(cfg,30):raise ValueError('field mode requires incremental long recording')
    return True

def guard_seconds(cfg,duration):
    validate(cfg,duration)
    # Receiver still enforces 3s no-byte failure and session stop/done handshake.
    return float('inf') if duration==0 else duration+60
