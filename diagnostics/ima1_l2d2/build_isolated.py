#!/usr/bin/env python3
from pathlib import Path
import shlex,subprocess,json,hashlib,shutil,sys
W=Path('/home/jetson/zed_capture_ws');D=Path(__file__).resolve().parent
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
f=(W/'build/zed_capture/CMakeFiles/zed_capture_node.dir/flags.make').read_text()
v={l.split(' = ',1)[0]:shlex.split(l.split(' = ',1)[1]) for l in f.splitlines() if ' = ' in l}
obj=out/'capture_node.cpp.o';exe=out/'lib/zed_capture/zed_capture_node';exe.parent.mkdir(parents=True)
cmd=['/usr/bin/c++']+v['CXX_FLAGS']+v['CXX_DEFINES']+v['CXX_INCLUDES']+['-c',str(W/'src/zed_capture/src/capture_node.cpp'),'-o',str(obj)]
link=shlex.split((W/'build/zed_capture/CMakeFiles/zed_capture_node.dir/link.txt').read_text())
link=[str(obj) if a=='CMakeFiles/zed_capture_node.dir/src/capture_node.cpp.o' else str(exe) if a==str(W/'devel/lib/zed_capture/zed_capture_node') else a for a in link]
with (out/'build.log').open('x') as log:
 for argv in [cmd,link]:
  log.write(shlex.join(argv)+'\n');log.flush();subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT,check=True)
plugin=W/'devel/lib/libcapture_jpeg_shadow.so';shutil.copy2(plugin,out/'lib/libcapture_jpeg_shadow.so')
files=[W/'src/zed_capture/src/capture_node.cpp',W/'src/zed_capture/include/zed_capture/ima1_reader_diag.hpp',W/'src/zed_capture/include/zed_capture/core.hpp',W/'devel/lib/libcapture_oc.a',W/'devel/lib/libcapture_hidapi.a',plugin,exe,out/'lib/libcapture_jpeg_shadow.so']
h={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(out/'build_manifest.json').write_text(json.dumps({'binary':str(exe),'binary_sha256':h[str(exe)],'files':h,'no_production_binary_replacement':True},indent=2)+'\n')
print(exe)
