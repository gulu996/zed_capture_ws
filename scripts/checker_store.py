"""Private disk-backed exact evidence. Never writes to sensor inputs.
SQLite page cache capped at 4 MiB; exact numeric statistics capped at 2M values.
No approximate medians, floating timestamp conversion or discarded evidence.
"""
import array,contextlib,itertools,json,pathlib,sqlite3,tempfile
import numpy as np
class Store:
 def __init__(self, directory=None):
  self.temp=tempfile.TemporaryDirectory(prefix='c5h_',dir=directory)
  self.path=pathlib.Path(self.temp.name)/'evidence.sqlite'
  self.db=sqlite3.connect(str(self.path));self.db.execute('PRAGMA cache_size=-4096');self.db.execute('PRAGMA temp_store=FILE');self.db.execute('PRAGMA mmap_size=0');self.db.execute('PRAGMA journal_mode=OFF');self.db.execute('PRAGMA max_page_count=524288')
  self.counter=0
 def name(self):self.counter+=1;return 't'+str(self.counter)
 def seq(self,source=()):
  s=Sequence(self)
  for x in source:s.append(x)
  return s
 def close(self):self.db.close();self.temp.cleanup()
class Sequence:
 def __init__(self,store):
  self.store=store;self.name=store.name();self.n=0
  store.db.execute('CREATE TABLE '+self.name+' (i INTEGER PRIMARY KEY, v TEXT NOT NULL)')
 def append(self,x):
  payload=json.dumps(x,separators=(',',':'))
  if len(payload)>1048576:raise ValueError('FULL_STRICT evidence row memory budget exceeded')
  self.store.db.execute('INSERT INTO '+self.name+' VALUES (?,?)',(self.n,payload));self.n+=1
 def __len__(self):return self.n
 def __iter__(self):
  for (x,) in self.store.db.execute('SELECT v FROM '+self.name+' ORDER BY i'):yield json.loads(x)
 def __getitem__(self,i):
  if isinstance(i,slice):return itertools.islice(iter(self),*i.indices(self.n))
  if i<0:i+=self.n
  if not 0<=i<self.n:raise IndexError(i)
  return json.loads(self.store.db.execute('SELECT v FROM '+self.name+' WHERE i=?',(i,)).fetchone()[0])
 def __eq__(self,other):return equal(self,other)
 def __bool__(self):return self.n!=0
 def __add__(self,other):return self.store.seq(itertools.chain(self,other))
 def __repr__(self):return '<disk sequence rows=%d>'%self.n
class Index:
 def __init__(self,store):
  self.store=store;self.name=store.name();self.n=0
  store.db.execute('CREATE TABLE '+self.name+' (k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID')
 def key(self,k):return json.dumps(k,separators=(',',':'))
 def add(self,k,v=None):
  cur=self.store.db.execute('INSERT OR IGNORE INTO '+self.name+' VALUES (?,?)',(self.key(k),json.dumps(v,separators=(',',':'))));self.n+=cur.rowcount;return bool(cur.rowcount)
 def put(self,k,v):self.store.db.execute('INSERT OR REPLACE INTO '+self.name+' VALUES (?,?)',(self.key(k),json.dumps(v,separators=(',',':'))))
 def get(self,k,default=None):
  r=self.store.db.execute('SELECT v FROM '+self.name+' WHERE k=?',(self.key(k),)).fetchone();return json.loads(r[0]) if r else default
 def __contains__(self,k):return self.store.db.execute('SELECT 1 FROM '+self.name+' WHERE k=?',(self.key(k),)).fetchone() is not None
 def same_keys(self,other):
  return self.store.db.execute('SELECT k FROM '+self.name+' EXCEPT SELECT k FROM '+other.name+' LIMIT 1').fetchone() is None and self.store.db.execute('SELECT k FROM '+other.name+' EXCEPT SELECT k FROM '+self.name+' LIMIT 1').fetchone() is None
 def __len__(self):return self.n
 def __iter__(self):
  for (k,) in self.store.db.execute('SELECT k FROM '+self.name):yield json.loads(k)
def equal(a,b):
 sentinel=object()
 for x,y in itertools.zip_longest(a,b,fillvalue=sentinel):
  if x is sentinel or y is sentinel:return False
  # JSON-backed tuples become arrays; values remain exact integers.
  if isinstance(x,(tuple,list)) and isinstance(y,(tuple,list)):
   if tuple(x)!=tuple(y):return False
  elif x!=y:return False
 return True
class Numbers(array.array):
 LIMIT=2000000
 def __new__(cls,kind='q',items=()):return super().__new__(cls,kind,items)
 def append(self,x):
  if len(self)>=self.LIMIT:raise ValueError('FULL_STRICT numeric memory budget exceeded; no PASS')
  super().append(x)
def stats(values):
 if not len(values):return None
 a=np.asarray(values)
 return {str(p):float(np.percentile(a,p)) for p in [0,50,95,99,100]}
def dump(value,fp):
 """JSON with every original row/hash, streamed rather than list materialization."""
 if isinstance(value,dict):
  fp.write('{')
  for i,(k,v) in enumerate(value.items()):
   if i:fp.write(',')
   fp.write(json.dumps(k));fp.write(':');dump(v,fp)
  fp.write('}')
 elif isinstance(value,(Sequence,list,tuple,array.array)):
  fp.write('[')
  for i,v in enumerate(value):
   if i:fp.write(',')
   dump(v,fp)
  fp.write(']')
 else:fp.write(json.dumps(value))
