"""Explicit L2-D2-only binary/config binding. Defaults keep the deployed node."""
import hashlib,json,pathlib
WS=pathlib.Path(__file__).resolve().parents[1]
def selection(cfg):
    enabled=cfg.get('ima1_read_diagnostics',False)
    if type(enabled) is not bool:raise ValueError('ima1_read_diagnostics must be boolean')
    manifest=cfg.get('ima1_diagnostic_build_manifest')
    if manifest is None:
        if enabled:raise ValueError('IMA1 ON requires an explicit validated isolated build manifest')
        return WS/'devel/lib/zed_capture/zed_capture_node',[],None
    p=pathlib.Path(manifest).expanduser().resolve(strict=True)
    if WS/'diagnostics/ima1_l2d2' not in p.parents:
        raise ValueError('IMA1 build must be isolated under diagnostics/ima1_l2d2')
    data=json.loads(p.read_text());binary=pathlib.Path(data['binary']).resolve(strict=True)
    if p.parent not in binary.parents:raise ValueError('binary outside isolated build')
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=data['binary_sha256']:raise ValueError('IMA1 binary hash mismatch')
    for f,expected in data['files'].items():
        if hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()!=expected:raise ValueError('IMA1 build input changed: '+f)
    return binary,['_ima1_read_diagnostics:='+str(enabled).lower()],{'enabled':enabled,'build_manifest':str(p),'build_manifest_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'binary':str(binary),'binary_sha256':data['binary_sha256']}
def bind_result(session,identity):
    if identity is None:return
    s=pathlib.Path(session);meta=json.loads((s/'session.json').read_text())
    result=dict(identity,session_id=meta['session_id'],boot_id=meta['boot_id'],config_sha256=meta['config_sha256'],physical_sync='PENDING')
    if identity['enabled']:
        result['status']='DIAGNOSTIC_INCOMPLETE'
        try:
            summary=json.loads((s/'ima1_reader_diagnostics_summary.json').read_text())
            result['status']=summary['status'] if summary.get('complete_export') else 'DIAGNOSTIC_INCOMPLETE'
            if summary['stored']+summary['dropped']!=summary['eligible']:result['status']='DIAGNOSTIC_ACCOUNTING_FAILED'
            result['files']={name:hashlib.sha256((s/name).read_bytes()).hexdigest() for name in ('ima1_reader_diagnostics.jsonl','ima1_reader_diagnostics_summary.json')}
        except (OSError,ValueError,KeyError) as e:result['error']=str(e)
    else:result['status']='DIAGNOSTIC_OFF'
    with (s/'ima1_diagnostic_binding.json').open('x') as f:json.dump(result,f,indent=2)
