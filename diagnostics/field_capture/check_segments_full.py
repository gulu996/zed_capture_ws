#!/usr/bin/env python3
"""Full strict adapter: original algorithms + all-segment GNSS accounting."""
import argparse,json,sys
from pathlib import Path
from field_common import WS
sys.path.insert(0,str(WS/'scripts'))
from segment_check import attest,records
import rosbag
from checker_bag import messages

def verify_contents(p):
    status=attest(p)
    for r in records(p):
        count=0;first=last=None;low=high=None;topics={}
        with rosbag.Bag(str(p/r['file']),'r',skip_index=True) as bag:
            for topic,msg,stamp in messages(bag):
                count+=1;last=stamp.to_nsec()
                if first is None:first=last;low=high=last
                low=min(low,last);high=max(high,last)
                item=topics.setdefault(topic,dict(datatype=msg._type,md5=msg._md5sum,messages=0))
                if item['datatype']!=msg._type or item['md5']!=msg._md5sum:raise ValueError('segment type mutation')
                item['messages']+=1
        # rosbag iterator sorts record times; compare extrema, not physical write order.
        if count!=r['messages'] or topics!=r['topics']:raise ValueError('segment actual contents/count mismatch')
        if count and (low!=r['min_record_ns'] or high!=r['max_record_ns']):raise ValueError('segment record time boundary mismatch')
    return status

def main():
    a=argparse.ArgumentParser();a.add_argument('session');a.add_argument('--output-dir',required=True);v=a.parse_args()
    p=Path(v.session);out=Path(v.output_dir);out.mkdir(exist_ok=True)
    try:
        evidence=verify_contents(p)
        (out/'segment_validation.json').write_text(json.dumps(evidence,indent=2))
    except Exception as e:
        (out/'check_result.json').write_text(json.dumps({'capture_integrity':'FAIL','errors':['segment validation: '+repr(e)]}))
        (out/'check_result.profile.json').write_text(json.dumps({'full_strict_completed':False}))
        return 2
    import checker_run,checker_strict_field
    checker_run.strict=checker_strict_field
    result=checker_run.run(p,out);print(json.dumps(result,indent=2));return 0 if result['capture_integrity']=='PASS' else 2
if __name__=='__main__':sys.exit(main())
