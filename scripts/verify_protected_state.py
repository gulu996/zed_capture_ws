#!/usr/bin/env python3
"""Read-only verification against saved original-system baseline."""
import hashlib,json,os,pathlib,subprocess,time
WS=pathlib.Path(__file__).resolve().parents[1];BASE=pathlib.Path('/home/jetson/jetson_zed_audit_20261015_163125')
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
changes=[];hashed=0;records=json.loads((BASE/'filesystem_baseline.json').read_text())
for old in records:
    p=pathlib.Path(old['path'])
    try:
        st=p.lstat()
        for key,actual in [('size',st.st_size),('mtime_ns',st.st_mtime_ns),('mode',oct(st.st_mode))]:
            if key in old and old[key]!=actual:changes.append({'path':str(p),'field':key,'before':old[key],'after':actual})
        if 'symlink' in old and os.readlink(p)!=old['symlink']:changes.append({'path':str(p),'field':'symlink'})
        if 'sha256' in old:
            hashed+=1
            if sha(p)!=old['sha256']:changes.append({'path':str(p),'field':'sha256'})
    except OSError as e:changes.append({'path':str(p),'error':str(e)})
libs=json.loads((BASE/'linked_libraries_sha256.json').read_text());lib_changes=[]
for old in libs:
    try:
        if sha(old['path'])!=old['sha256']:lib_changes.append(old['path'])
    except OSError as e:lib_changes.append(str(e))
env=dict(os.environ,GIT_OPTIONAL_LOCKS='0')
git=subprocess.check_output(['git','-C','/home/jetson/catkin_ws','status','--short','--untracked-files=all'],env=env,text=True)
packages=subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'],text=True)
oldpkg=(WS/'evidence/packages_before.tsv').read_text()
# The snapshot's column convention is kept in the evidence; compare actual rows if identical.
r={'status':'VERIFIED' if not changes and not lib_changes else 'REVIEW_REQUIRED','filesystem_records_checked':len(records),'files_sha256_checked':hashed,'filesystem_changes':changes,'linked_library_hashes_checked':len(libs),'linked_library_changes':lib_changes,'git_status_unchanged':git==(WS/'evidence/catkin_git_before.txt').read_text(),'git_head':subprocess.check_output(['git','-C','/home/jetson/catkin_ws','rev-parse','HEAD'],text=True).strip(),'packages_unchanged':packages==oldpkg,'package_snapshot_format_before_first_line':oldpkg.splitlines()[0],'package_snapshot_format_after_first_line':packages.splitlines()[0],'cuda_link_exists':os.path.lexists('/usr/local/cuda'),'zed_sdk_exists':os.path.exists('/usr/local/zed'),'blas':os.path.realpath('/etc/alternatives/libblas.so.3-aarch64-linux-gnu'),'lapack':os.path.realpath('/etc/alternatives/liblapack.so.3-aarch64-linux-gnu'),'runtime_regression':'HARDWARE_PENDING; no original workspace build or sensor/map startup'}
r['status']='VERIFIED' if not changes and not lib_changes and r['git_status_unchanged'] and r['packages_unchanged'] else 'REVIEW_REQUIRED'
p=WS/'evidence'/('protected_state_%d.json'%time.time_ns());p.write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
