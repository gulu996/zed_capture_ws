"""C5-G opt-in policy; no hardware or ROS imports and no changes to old modes."""
import math, pathlib

def enabled(cfg):
    flag=cfg.get('long_recording',False)
    if type(flag) is not bool:raise ValueError('long_recording must be boolean')
    return flag

def validate(cfg,duration):
    if not enabled(cfg):return False
    if not math.isfinite(float(duration)) or not 0<float(duration)<=300:
        raise ValueError('C5-G supports >0..300s only; 20min PENDING_HARDWARE')
    if cfg.get('storage_mode')!='jpeg_files' or cfg.get('resolution')!='HD720' or cfg.get('fps')!=30 or cfg.get('jpeg_shadow_enable',False):
        raise ValueError('C5-G requires HD720/30 JPEG files, no shadow')
    reserve=float(cfg.get('minimum_free_gb',0))
    if not math.isfinite(reserve) or reserve<10:raise ValueError('C5-G requires finite >=10GB free reserve')
    return True

def node_arguments(cfg,duration):
    return ['_long_recording:='+str(validate(cfg,duration)).lower(),
            '_minimum_free_gb:='+str(cfg.get('minimum_free_gb',10))]

def guard_seconds(cfg,duration):
    return float(duration)+30 if validate(cfg,duration) else 55

def extra_resources(session):
    import shutil
    row={'disk_free_bytes':shutil.disk_usage(session).free,'thermal_millicelsius':{},'cpu_frequency_khz':{},'throttling':{}}
    for d in pathlib.Path('/sys/class/thermal').glob('thermal_zone*'):
        try:row['thermal_millicelsius'][(d/'type').read_text().strip()]=int((d/'temp').read_text())
        except (OSError,ValueError):pass
    for d in pathlib.Path('/sys/devices/system/cpu/cpufreq').glob('policy*'):
        for name in ('scaling_cur_freq','scaling_max_freq','cpuinfo_max_freq'):
            try:row['cpu_frequency_khz'][d.name+'/'+name]=int((d/name).read_text())
            except (OSError,ValueError):pass
    # Read only explicit throttle counters if provided by this kernel; frequency alone is not proof.
    for base in ('/sys/devices/platform/soctherm','/sys/devices/platform/soctherm-oc-event'):
        for p in pathlib.Path(base).glob('*event*cnt'):
            try:row['throttling'][str(p)]=p.read_text().strip()
            except OSError:pass
    if not row['throttling']:row['throttling']='UNAVAILABLE; frequency/temperature do not prove throttling'
    for name in ('serial_raw.bin','chunks.jsonl','lines.jsonl','time_observations.jsonl'):
        p=pathlib.Path(session)/'gnss'/name
        if p.exists():row['gnss_'+name+'_bytes']=p.stat().st_size
    return row
