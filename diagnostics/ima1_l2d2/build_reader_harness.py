#!/usr/bin/env python3
"""Extract the actual reader body for syscall-injected OFF/ON comparison.
No camera, ROS master, or real shared anchor file is opened.
"""
import pathlib,sys
source=pathlib.Path(sys.argv[1]).read_text()
method=sys.argv[3] if len(sys.argv)>3 else 'anchorLoop'
start=source.index(' void '+method+'(')
end=source.index('\n void ',start+1)
body=source[start:end].replace('void '+method+'(', 'void anchorLoop(')
out=pathlib.Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
(out/'reader_body.inc').write_text(body+'\n')
