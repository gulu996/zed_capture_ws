from long_recording import validate as long_validate
"""Opt-in only: existing modes acquire no GNSS imports or startup dependencies."""
import hashlib,json,pathlib,sys,os
ROOT=pathlib.Path(__file__).resolve().parents[1]/'diagnostics/gnss_r2'
def gnss_arguments(cfg,duration):
    if type(cfg.get('gnss_enable',False)) is not bool:raise ValueError('gnss_enable must be boolean')
    if not cfg.get('gnss_enable',False):return ['_gnss_enable:=false']
    if cfg.get('storage_mode')!='jpeg_files' or cfg.get('resolution')!='HD720' or not 0<duration<=(300 if long_validate(cfg,duration) else 30):
        raise ValueError('GNSS-R2 requires independent C5-F HD720 <=30s configuration')
    if cfg.get('gnss_port')!='/dev/serial/by-id/usb-STMicroelectronics_STM32_Virtual_ComPort_5CF253593333-if00' or cfg.get('gnss_baud')!=921600 or cfg.get('gnss_dtr') is not True or cfg.get('gnss_rts') is not False:
        raise ValueError('GNSS identity/settings differ from verified receiver')
    return ['_gnss_enable:=true']
def modules():
    if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
    import gnss_r2_core,gnss_receiver
    return gnss_r2_core,gnss_receiver

def gnss_preflight(cfg,duration):
    gnss_arguments(cfg,duration)
    if not cfg.get('gnss_enable',False):return {'enabled':False,'errors':[]}
    result={'enabled':True,'errors':[],'measurement_mapping':'PENDING','requires_fix':False}
    try:
        core,receiver=modules();core.message_types();result['identity']=receiver.identity(core.PORT)
        if not os.access(core.PORT,os.R_OK|os.W_OK):raise RuntimeError('GNSS device access denied; no permission changes attempted')
        result['types']=[dict(topic=t,datatype=d,md5=m) for t,d,m in core.TOPICS]
    except Exception as e:result['errors'].append(str(e))
    return result

def software_hashes():
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in list(ROOT.glob('*.py'))+list((ROOT/'vendor').rglob('*.py'))+[pathlib.Path(__file__)]}
