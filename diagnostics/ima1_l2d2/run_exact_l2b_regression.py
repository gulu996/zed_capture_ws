#!/usr/bin/env python3
"""Offline only. Invoke the unchanged evaluator; never use L2-C recovery policies."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time,shutil,csv
R=Path('/home/jetson/zed_capture_ws/diagnostics/l2d2_regression_20261018_203653')
O=Path(sys.argv[1]);PKG=R/'zed_time_bridge'
ENV=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',SENSOR_TIME_BRIDGE_PYTHON_ROOT='/home/jetson/catkin_ws/src/sensor_time_bridge/src')
FILES=('l2b_video_mapping.csv','l2b_anchor_observations.csv','l2b_clock_model.json','l2b_anchor_quality.json','l2b_validation_summary.json','provenance.json')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):
 with p.open('x') as f:json.dump(x,f,indent=2,ensure_ascii=False);f.write('\n')
def compare(old,new,allowed):
 result={}
 for n in FILES:
  same=sha(old/n)==sha(new/n)
  item={'byte_identical':same}
  if n in ('l2b_validation_summary.json','provenance.json'):
   key='source_sha256' if n=='l2b_validation_summary.json' else 'input_hashes'
   a=json.loads((old/n).read_text());b=json.loads((new/n).read_text());ah=a.pop(key);bh=b.pop(key)
   assert a==b,(n,'non-provenance content differs')
   assert all(bh.get(k)==v for k,v in ah.items()),(n,'existing input hashes differ')
   extra=set(bh)-set(ah);assert extra==set(allowed),(n,'unexpected hash keys',extra,allowed)
   item.update(non_hash_fields_equal=True,original_hashes_equal=True,added_source_hash_keys=sorted(extra))
  else:assert same,(str(new),n,'mapping/model/anchor result bytes differ')
  result[n]=item
 return result
results={}
for label,base,valid,pairs in [('A','baseline_A',887,903),('B','baseline_B',879,902),('EXTERNAL','EXTERNAL_ORIGINAL_BASELINE',873,887)]:
 baseline=R/'l2c'/base;p=json.loads((baseline/'provenance.json').read_text());sid=p['session_id'];src=Path('/home/jetson/zed_capture_data')/sid
 inp=O/(label+'_input_off');inp.mkdir();expected=p['input_hashes']
 for name,h in expected.items():
  assert Path(name).name==name and not name.endswith(('.bag','.jpg','.jpeg'))
  assert sha(src/name)==h,(label,name,'original changed');shutil.copy2(src/name,inp/name)
 extra=[]
 if 'capture_metrics.jsonl' not in expected:
  extra=['capture_metrics.jsonl'];shutil.copy2(src/extra[0],inp/extra[0])
 inp_on=O/(label+'_input_diagnostic_sidecars');shutil.copytree(inp,inp_on)
 fixture=Path('/home/jetson/zed_capture_ws/diagnostics/ima1_l2d2/enhanced_reader/diagnostic.jsonl')
 shutil.copy2(fixture,inp_on/'ima1_reader_diagnostics.jsonl')
 dump(inp_on/'ima1_reader_diagnostics_summary.json',{'synthetic_fixture':True,'purpose':'Prove diagnostic sidecars are not mapper input events','physical_sync':'PENDING','source_fixture_sha256':sha(fixture),'not_a_hardware_capture':True})
 stats={}
 for mode,folder in [('off',inp),('diagnostic_sidecars',inp_on)]:
  target=O/(label+'_'+mode);command=[sys.executable,'-B',str(PKG/'scripts/evaluate_open_capture.py'),'--input-dir',str(folder),'--outdir',str(target),'--session-id',sid]
  started=time.monotonic();print('RUN '+label+' '+mode,flush=True)
  with (O/(label+'_'+mode+'.log')).open('x') as log:
   r=subprocess.run(command,env=ENV,stdout=log,stderr=subprocess.STDOUT)
  if r.returncode:raise RuntimeError('Evaluator failed: '+str(O/(label+'_'+mode+'.log')))
  summary=json.loads((target/'l2b_validation_summary.json').read_text());assert (summary['valid_pairs'],summary['original_pair_count'])==(valid,pairs),(label,summary['valid_pairs'],summary['original_pair_count'])
  added=extra+(['ima1_reader_diagnostics.jsonl','ima1_reader_diagnostics_summary.json'] if mode!='off' else [])
  comparison=compare(baseline,target,added)
  with (target/'l2b_video_mapping.csv').open(newline='') as f:
   rows=list(csv.DictReader(f));good=[x for x in rows if x['valid']=='True']
  for row in good:assert int(row['mapped_stamp_ns'])==int(row['left_mapped_stamp_ns'])==int(row['right_mapped_stamp_ns'])
  stats[mode]={'valid_pairs':valid,'total_pairs':pairs,'rejected_pairs':summary['rejected_pairs'],'rejection_reasons':summary['rejection_reasons'],'elapsed_s':time.monotonic()-started,'comparison':comparison,'stereo_integer_timestamps_equal':True,'command':command}
  print(label+' '+mode+' PASS '+str(valid)+'/'+str(pairs),flush=True)
 stats['off_vs_sidecars']=compare(O/(label+'_off'),O/(label+'_diagnostic_sidecars'),['ima1_reader_diagnostics.jsonl','ima1_reader_diagnostics_summary.json'])
 stats['original_inputs_after']={n:sha(src/n) for n in expected};assert stats['original_inputs_after']==expected
 results[label]=stats;dump(O/(label+'_comparison.json'),stats)
dump(O/'exact_regression_result.json',{'status':'PASS','algorithm_modified':False,'thresholds_modified':False,'shadow_recovery_used':False,'diagnostic_fixture_only':True,'physical_sync':'PENDING','groups':results})
print('ALL_THREE_GROUPS_EXACT_PASS',flush=True)
