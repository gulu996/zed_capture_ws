#!/usr/bin/env python3
"""Run manually in normal Jetson SSH terminal; laptop reads only, no sensors."""
import datetime
import hashlib
import io
import json
import pathlib
import shlex
import subprocess
import sys
import tarfile

D = pathlib.Path(__file__).resolve().parent
DEST = pathlib.Path((D / "regression_destination.txt").read_text().strip())
REMOTE = r'''
import os,sys,json,hashlib,pathlib,stat,tarfile,io,socket,datetime
roots={
 "l2c":pathlib.Path("/home/gulu/data/zed_l2b_eval/l2c_shadow/20261018_182513"),
 "zed_time_bridge":pathlib.Path("/home/gulu/zed_git_worktrees/zed2i-ros1-time-bridge/integrations/zed2i_ros1/zed_time_bridge")
}
suffixes={".py",".json",".jsonl",".csv",".tsv",".md",".yaml",".yml",".txt",".sha256",".log",".sh",".xml",".cfg",".ini",".hpp",".h",".cpp",".c"}
skipdirs={".git","__pycache__","camera","left","right","build","devel","install"}
rows=[];omitted=[];total=0
for label,root in roots.items():
 if not root.is_dir():raise RuntimeError("Missing reference directory: "+str(root))
 for parent,dirs,files in os.walk(str(root),followlinks=False):
  dirs[:]=sorted(d for d in dirs if d not in skipdirs and not pathlib.Path(parent,d).is_symlink())
  for name in sorted(files):
   p=pathlib.Path(parent,name)
   if p.is_symlink():
    omitted.append({"path":str(p),"reason":"SYMLINK_NOT_FOLLOWED"});continue
   st=p.stat()
   if not stat.S_ISREG(st.st_mode):continue
   if p.suffix.lower() not in suffixes and name not in ("SHA256SUMS","CMakeLists.txt"):
    omitted.append({"path":str(p),"reason":"NOT_CODE_OR_METADATA"});continue
   if st.st_size>64*1024*1024:raise RuntimeError("Metadata file exceeds 64MiB safety limit: "+str(p))
   total+=st.st_size
   if total>256*1024*1024:raise RuntimeError("Selected metadata exceeds 256MiB; stop for a narrower selection")
   h=hashlib.sha256()
   with p.open("rb") as f:
    for block in iter(lambda:f.read(1048576),b""):h.update(block)
   relative=label+"/"+p.relative_to(root).as_posix()
   rows.append({"source":str(p),"relative":relative,"bytes":st.st_size,"mtime_ns":st.st_mtime_ns,"sha256":h.hexdigest()})
if not any(r["relative"].endswith("/evaluate_open_capture.py") for r in rows):
 raise RuntimeError("Existing evaluator missing; no substitute algorithm will be transferred")
manifest={"hostname":socket.gethostname(),"read_only_transfer":True,"created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"source_roots":{k:str(v) for k,v in roots.items()},"file_count":len(rows),"total_bytes":total,"files":rows,"omitted":omitted}
payload=(json.dumps(manifest,indent=2)+"\n").encode()
with tarfile.open(fileobj=sys.stdout.buffer,mode="w|") as tf:
 info=tarfile.TarInfo("remote_manifest.json");info.size=len(payload);tf.addfile(info,io.BytesIO(payload))
 for r in rows:
  p=pathlib.Path(r["source"]);st=p.stat()
  if st.st_size!=r["bytes"] or st.st_mtime_ns!=r["mtime_ns"]:raise RuntimeError("Source changed during transfer: "+str(p))
  info=tarfile.TarInfo(r["relative"]);info.size=r["bytes"];info.mode=0o600
  with p.open("rb") as f:tf.addfile(info,f)
  st=p.stat()
  if st.st_size!=r["bytes"] or st.st_mtime_ns!=r["mtime_ns"]:raise RuntimeError("Source changed while reading: "+str(p))
'''

def main():
    if not DEST.is_dir():
        raise SystemExit("Prepared destination is missing: " + str(DEST))
    if any(DEST.iterdir()):
        raise SystemExit("Destination is not empty; refusing to overwrite or resume: " + str(DEST))
    print("L2D2_REG_DIR=" + str(DEST), flush=True)
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "laptop",
           "python3 -c " + shlex.quote(REMOTE)]
    with (DEST / "transfer_stderr.log").open("xb") as errors:
        child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors)
        received = {}
        manifest = None
        failure = None
        try:
            with tarfile.open(fileobj=child.stdout, mode="r|") as archive:
                for member in archive:
                    path = pathlib.PurePosixPath(member.name)
                    if not member.isfile() or path.is_absolute() or ".." in path.parts:
                        raise ValueError("Unsafe archive member: " + member.name)
                    if manifest is None and member.name != "remote_manifest.json":
                        raise ValueError("Manifest must be first")
                    if member.size > 64 * 1024 * 1024:
                        raise ValueError("Member exceeds safety budget")
                    target = DEST.joinpath(*path.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    h = hashlib.sha256()
                    length = 0
                    with archive.extractfile(member) as source, target.open("xb") as output:
                        while True:
                            block = source.read(1048576)
                            if not block:
                                break
                            h.update(block)
                            output.write(block)
                            length += len(block)
                    if member.name == "remote_manifest.json":
                        manifest = json.loads(target.read_text())
                        print("Remote files=%d; selected bytes=%d; hostname=%s" %
                              (manifest["file_count"], manifest["total_bytes"], manifest["hostname"]), flush=True)
                    else:
                        received[member.name] = {"bytes": length, "sha256": h.hexdigest()}
            code = child.wait(timeout=15)
            if code:
                raise RuntimeError("SSH transfer returned %d; see transfer_stderr.log" % code)
            expected = {r["relative"]: {"bytes": r["bytes"], "sha256": r["sha256"]}
                        for r in manifest["files"]}
            if received != expected or len(received) != manifest["file_count"]:
                raise ValueError("File count/size/SHA256 verification failed")
        except Exception as exc:
            failure = str(exc)
            # Close only this transfer pipe; never touch acquisition processes.
            child.stdout.close()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                failure += "; transfer SSH process still running"
        result = {"status": "VERIFIED" if failure is None else "FAILED",
                  "L2D2_REG_DIR": str(DEST), "files_received": len(received),
                  "sha256_matches": failure is None, "failure": failure,
                  "hardware_started": False, "laptop_modified": False}
        with (DEST / "transfer_verification.json").open("x") as f:
            json.dump(result, f, indent=2)
        print(json.dumps(result, indent=2))
        return 0 if failure is None else 2

if __name__ == "__main__":
    sys.exit(main())
