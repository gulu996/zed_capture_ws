#!/usr/bin/env python3
"""Independent output only. Refuse to overwrite an existing candidate build."""
import hashlib,json,pathlib,shlex,shutil,subprocess
from field_common import HERE,WS,verify_frozen
verify_frozen()
b=HERE/'build'; b.mkdir(exist_ok=False)
(b/'lib/zed_capture').mkdir(parents=True)
cm=WS/'build/zed_capture/CMakeFiles/zed_capture_node.dir'
flags={}
for line in (cm/'flags.make').read_text().splitlines():
    if ' = ' in line:
        k,v=line.split(' = ',1);flags[k]=shlex.split(v)
obj=b/'capture_node_field.o'; binary=b/'lib/zed_capture/zed_capture_node'
commands=[['/usr/bin/c++']+flags['CXX_FLAGS']+flags['CXX_DEFINES']+flags['CXX_INCLUDES']+
          ['-c',str(HERE/'capture_node_field.cpp'),'-o',str(obj)]]
link=shlex.split((cm/'link.txt').read_text())
link[link.index('-o')+1]=str(binary)
link=[str(obj) if x.endswith('capture_node.cpp.o') else x for x in link]
commands.append(link)
with (b/'build.log').open('x') as log:
    for command in commands:
        log.write(shlex.join(command)+'\n');log.flush()
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
shutil.copy2(WS/'devel/lib/libcapture_jpeg_shadow.so',b/'lib/libcapture_jpeg_shadow.so')
paths=[HERE/'capture_node_field.cpp',HERE/'field_stop.hpp',binary,b/'lib/libcapture_jpeg_shadow.so',
       WS/'devel/lib/libcapture_oc.a',WS/'devel/lib/libcapture_hidapi.a']
manifest={'commands':commands,'sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
(b/'manifest.json').write_text(json.dumps(manifest,indent=2))
verify_frozen()
print(binary)
