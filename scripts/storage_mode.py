from long_recording import validate as long_validate
"""Explicit C5F opt-in; legacy raw configurations remain default."""
def storage_arguments(cfg,duration):
    mode=cfg.get('storage_mode','raw_bag')
    if mode not in ['raw_bag','jpeg_files']:raise ValueError('unknown storage_mode')
    if mode=='raw_bag':return ['_storage_mode:=raw_bag']
    if cfg.get('jpeg_shadow_enable',False):raise ValueError('C5F and shadow mutually exclusive')
    if cfg['resolution']!='HD720' or cfg['fps']!=30 or not 0<float(duration)<=(300 if long_validate(cfg,duration) else 30):raise ValueError('C5F currently HD720/30, duration<=30')
    if cfg.get('jpeg_quality')!=95 or str(cfg.get('jpeg_subsampling'))!='420':raise ValueError('C5F requires explicit Q95/420')
    if cfg.get('image_encoding')!='8UC2' or cfg.get('pixel_layout')!='YUYV':raise ValueError('C5F raw input must be YUYV')
    ms=cfg.get('jpeg_sync_ms',1000)
    if type(ms) is not int or not 100<=ms<=5000:raise ValueError('jpeg_sync_ms must be integer 100..5000')
    policy=cfg.get('slam_image_gap_policy',{})
    if type(policy.get('max_events')) is not int or policy['max_events']<0 or not 0<=policy.get('max_missing_period_ratio',-1)<1 or policy.get('max_interval_ms',0)<=0:raise ValueError('explicit bounded application image gap policy required')
    return ['_storage_mode:=jpeg_files','_jpeg_sync_ms:='+str(ms)]
def bag_name(cfg):return 'sensors.bag' if cfg.get('storage_mode')=='jpeg_files' else 'data.bag'
