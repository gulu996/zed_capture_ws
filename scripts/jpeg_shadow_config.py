"""C4 opt-in only. No environment/global capture policy changes."""
import pathlib,re,subprocess
WS=pathlib.Path(__file__).resolve().parents[1]
def shadow_arguments(cfg,duration):
    enabled=cfg.get('jpeg_shadow_enable',False)
    if type(enabled) is not bool:raise ValueError('jpeg_shadow_enable must be YAML true/false')
    if not enabled:return []
    if cfg['resolution']!='HD720' or cfg['fps']!=30 or not 0<float(duration)<=30:
        raise ValueError('C4 shadow requires native HD720/30 and duration<=30s')
    if cfg.get('image_encoding')!='8UC2' or cfg.get('pixel_layout')!='YUYV':raise ValueError('C4 requires original 8UC2/YUYV')
    return ['_jpeg_shadow_enable:=true']
def shadow_preflight(cfg,duration,environment):
    args=shadow_arguments(cfg,duration)
    if not args:return {'enabled':False,'status':'DISABLED','errors':[]}
    plugin=WS/'devel/lib/libcapture_jpeg_shadow.so'
    result={'enabled':True,'plugin':str(plugin),'errors':[]}
    if not plugin.is_file():result['errors'].append('JPEG shadow plugin not built')
    else:
        p=subprocess.run(['/usr/bin/ldd','-r',str(plugin)],env=environment,capture_output=True,text=True,timeout=20)
        result.update(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)
        if p.returncode:result['errors'].append('JPEG plugin ldd -r failed')
        for line in (p.stdout+'\n'+p.stderr).splitlines():
            if re.search(r'undefined symbol|not found|relocation error|cannot open shared object',line,re.I):result['errors'].append(line.strip())
            if re.match(r'\s*lib(turbojpeg|opencv_core|opencv_imgproc)',line):
                tokens=line.split();path=tokens[2] if len(tokens)>2 else ''
                if not pathlib.Path(path).resolve().as_posix().startswith('/usr/lib/aarch64-linux-gnu/'):
                    result['errors'].append('Non-system JPEG/OpenCV dependency: '+line.strip())
    result['status']='BLOCKED' if result['errors'] else 'SOFTWARE_TESTED'
    return result
