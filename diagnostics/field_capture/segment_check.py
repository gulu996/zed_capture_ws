"""Cheap closed-segment identity checks; full bag traversal remains manual."""
import json
from pathlib import Path

def records(p):
    with (Path(p)/'bag_segments.jsonl').open() as f:
        for line in f:
            if len(line)>65536:raise ValueError('oversized segment row')
            yield json.loads(line)

def attest(p):
    p=Path(p);total=0;parts=0
    if not (p/'bag_segments.json').exists() or any(p.glob('*.active')):raise ValueError('segment finalization missing')
    for r in records(p):
        parts+=1;expected='sensors.bag' if parts==1 else 'sensors_%09d.bag'%parts
        if r['segment']!=parts or r['file']!=expected or r['closed'] is not True:raise ValueError('segment order/identity/close mismatch')
        if (p/expected).stat().st_size!=r['bytes']:raise ValueError('segment size mismatch')
        n=r['messages']
        if n and r['first_message_ordinal']!=total+1:raise ValueError('segment boundary gap/duplicate')
        total+=n
        if r['last_message_ordinal']!=total or sum(t['messages'] for t in r['topics'].values())!=n:raise ValueError('segment message accounting mismatch')
    if not parts:raise ValueError('no segments')
    if sum(1 for _ in p.glob('*.bag'))!=parts:raise ValueError('unindexed bag')
    return {'closed':True,'segments':parts,'messages':total}
