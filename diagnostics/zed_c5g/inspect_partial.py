#!/usr/bin/env python3
"""Read-only triage. Never repairs/reindexes/truncates or promotes a partial session."""
import csv,json,pathlib,sys,hashlib
def inspect(root):
 root=pathlib.Path(root).resolve();rows=complete=partial=0;errors=[]
 index=root/'frames.csv'
 if index.exists():
  with index.open() as f:
   for r in csv.DictReader(f):
    rows+=1
    if None in r or any(v is None for v in r.values()):partial+=1;continue
    ok=r.get('status')=='WRITTEN'
    for eye in ('left','right'):
     p=(root/r.get(eye+'_path','')).resolve()
     try:expected=int(r.get(eye+'_bytes','0') or 0)
     except ValueError:expected=-1;ok=False
     if root not in p.parents or not p.is_file() or p.stat().st_size!=expected:ok=False
    complete+=ok
 else:errors.append('missing frames.csv')
 summary=root/'jpeg_files_summary.json';final=False
 if summary.exists():
  try:
   s=json.loads(summary.read_text());final=s.get('final_synced',False) and not s.get('failed',True)
  except (OSError,ValueError):errors.append('invalid JPEG final summary')
 raw=root/'gnss/serial_raw.bin';raw_hash=None;raw_bytes=None
 if raw.exists():
  h=hashlib.sha256();raw_bytes=0
  with raw.open('rb') as f:
   while True:
    b=f.read(65536)
    if not b:break
    h.update(b);raw_bytes+=len(b)
  raw_hash=h.hexdigest()
 return dict(status='READ_ONLY_TRIAGE_NOT_FULL_VALIDATION',indexed_rows=rows,
  present_pairs_with_matching_size=complete,noncomplete_or_missing_pairs=rows-complete,
  partial_index_rows=partial,jpeg_final_success_recorded=final,
  active_bags=[p.name for p in root.glob('*.active')],finalized_bags=[p.name for p in root.glob('*.bag')],
  gnss_raw_bytes=raw_bytes,gnss_raw_sha256=raw_hash,errors=errors,
  note='File existence/size is not JPEG decode or durability proof; .active bag needs separate authorized recovery on a copy; originals remain untouched.')
if __name__=='__main__':print(json.dumps(inspect(sys.argv[1]),indent=2))
