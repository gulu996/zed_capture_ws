from pathlib import Path
p=Path('/home/jetson/zed_capture_ws/src/zed_capture/src/capture_node.cpp')
s=p.read_text();a=s.index(' void anchorLoop(){');b=s.index('\n void recordVideoTiming',a);original=s[a:b]
new=original.replace('void anchorLoop(){','void anchorLoopDiagnostic(){\n  auto& d=*ima1_diag;')
new=new.replace('   if(poll_start-last_open>', '   capture::Ima1DiagEvent e;d.begin(e,poll_count.load(),poll_start,interval,late,fd);\n   if(poll_start-last_open>')
x='''    if(stat(anchor_path.c_str(),&st)==0 && st.st_size==64){if(fd<0||st.st_ino!=inode||st.st_dev!=device){if(fd>=0)close(fd);fd=open(anchor_path.c_str(),O_RDONLY|O_CLOEXEC);inode=st.st_ino;device=st.st_dev;have=false;}}
    else if(fd>=0){close(fd);fd=-1;have=false;std::lock_guard<std::mutex> lock(mutex);anchor_available=false;}'''
y='''    const int sr=stat(anchor_path.c_str(),&st),se=sr<0?errno:0;d.pathStat(e,sr,se,st);
    if(sr==0 && st.st_size==64){if(fd<0||st.st_ino!=inode||st.st_dev!=device){
     e.reopen=fd>=0?3:(d.open_failed?2:1);
     if(fd>=0){e.close_called=1;e.close_ret=close(fd);e.close_errno=e.close_ret<0?errno:0;}
     fd=open(anchor_path.c_str(),O_RDONLY|O_CLOEXEC);e.open_errno=fd<0?errno:0;e.open_called=1;e.open_ret=fd;
     d.open_failed=fd<0;if(fd>=0)++d.generation;
     inode=st.st_ino;device=st.st_dev;have=false;}}
    else {e.reopen=sr<0?4:5;if(fd>=0){e.close_called=1;e.close_ret=close(fd);e.close_errno=e.close_ret<0?errno:0;fd=-1;have=false;std::lock_guard<std::mutex> lock(mutex);anchor_available=false;}}'''
assert x in new;new=new.replace(x,y)
new=new.replace('   if(fd>=0){std::array', '   e.fd=fd;e.read_before=read_before;\n   if(fd>=0){std::array')
new=new.replace('    ssize_t na=pread(fd,a.data(),64,0),nb=pread(fd,b.data(),64,0);','''    e.attempted=1;e.a_before=d.tick(e.clock_valid,1);
    ssize_t na=pread(fd,a.data(),64,0);e.ae=na<0?errno:0;
    e.a_after=d.tick(e.clock_valid,2);e.b_before=d.tick(e.clock_valid,4);
    ssize_t nb=pread(fd,b.data(),64,0);e.be=nb<0?errno:0;''')
new=new.replace('    capture::Anchor state{};', '    e.b_after=read_after;e.clock_valid|=8;e.ar=na;e.br=nb;e.a=a;e.b=b;\n    capture::Anchor state{};')
new=new.replace('    if(stable){std::lock_guard', '    e.stable=stable;e.duplicate=stable && have && a==previous;\n    if(stable)e.validity=capture::Ima1ReaderDiag::code(capture::validity(state,read_after));\n    if(stable){std::lock_guard')
new=new.replace('   deadline=capture::nextPollDeadline', '   e.read_after=read_after;e.legacy_poll=interval>2000000ULL || late>1000000ULL || (fd>=0&&!stable);d.finish(e);\n   deadline=capture::nextPollDeadline')
new=new.replace('  }if(fd>=0)close(fd);', '  }if(fd>=0){d.final_close_called=true;d.final_close_ret=close(fd);d.final_close_errno=d.final_close_ret<0?errno:0;}')
s=s[:b]+'\n'+new+s[b:]
s=s.replace('#include "zed_capture/core.hpp"','#include "zed_capture/core.hpp"\n#include "zed_capture/ima1_reader_diag.hpp"')
s=s.replace(' void anchorLoop(){',' // OFF path kept byte-for-byte identical to the pre-D2 reader.\n void anchorLoop(){',1)
s=s.replace(' bool long_recording=false;', ' bool ima1_read_diagnostics=false;std::unique_ptr<capture::Ima1ReaderDiag> ima1_diag;\n bool long_recording=false;',1)
s=s.replace('  pnh.param("long_recording",', '  pnh.param("ima1_read_diagnostics",ima1_read_diagnostics,false);\n  pnh.param("long_recording",',1)
s=s.replace('  initShadow();', '  if(ima1_read_diagnostics)ima1_diag.reset(new capture::Ima1ReaderDiag);\n  initShadow();',1)
s=s.replace('try{anchorLoop();}', 'try{if(ima1_diag&&!ima1_diag->allocation_failed)anchorLoopDiagnostic();else anchorLoop();}')
s=s.replace('  return failed?2:0;', '''  if(ima1_diag){summary.close();if(!ima1_diag->dump(dir,failed))ROS_ERROR_STREAM("IMA1_DIAGNOSTIC_EXPORT_FAILED: "<<ima1_diag->error);}
  return failed?2:0;''')
p.write_text(s)
assert s[s.index(' void anchorLoop(){'):s.index('\n void anchorLoopDiagnostic')].rstrip()==original.rstrip()
