"""Software-only C5-I-A regressions. All process fixtures are explicitly synthetic."""
import contextlib,csv,hashlib,io,json,math,os,pathlib,signal,subprocess,sys,tempfile,time,types,unittest
from unittest.mock import patch,Mock
import yaml
import field_common as c
import field_capture as f
import check_field as ck
import session_field as sf
P=pathlib.Path

class Tests(unittest.TestCase):
    def test_reserved_null_pid_is_pending_without_proc_access(self):
        m={'boot_id':c.boot_id(),'manager_pid':None,'manager_start_ticks':None}
        with patch.object(c,'process',side_effect=AssertionError('reserved identity must not access proc')):
            for pid in (None,True,False,0,-1,'123',123.5):
                self.assertFalse(c.manager_alive(dict(m,manager_pid=pid)))
            for ticks in (None,True,[],{},'', 'bad'):
                self.assertFalse(c.manager_alive(dict(m,manager_pid=123,manager_start_ticks=ticks)))

    def test_launch_waits_for_delayed_identity_registration(self):
        # Exercise the actual launch() wait loop, which previous manager-only
        # fixtures skipped. No subprocess/sensor is started in this test.
        with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_START_RACE_') as t:
            root=P(t);data=root/'data';runtime=root/'runtime';state={'waits':0,'path':None}
            child=Mock();child.poll.return_value=None
            def spawn(argv,**kwargs):
                state['path']=P(argv[4])
                self.assertIsNone(c.identity(state['path'])['manager_pid'])
                return child
            def tick(_):
                state['waits']+=1
                if state['waits']==3:
                    p=state['path'];m=c.identity(p);m.update(manager_pid=123,manager_start_ticks='777')
                    c.atomic(p/'field_identity.json',m);c.atomic(p/'capture_status.json',dict(m,state='PREFLIGHT'))
            def proc(pid):
                self.assertEqual(pid,123);self.assertEqual(state['waits'],3)
                return {'state':'S','start_ticks':'777','argv':[str(c.HERE/'field_capture.py').encode(),b'_manager',str(state['path']).encode()]}
            output=io.StringIO()
            with patch.object(f,'ROOT',data),patch.object(f,'RUNTIME',runtime),patch.object(f,'verify_frozen',return_value={}),patch.object(f.subprocess,'Popen',side_effect=spawn) as launches,patch.object(f.time,'sleep',side_effect=tick),patch.object(c,'process',side_effect=proc),contextlib.redirect_stdout(output):
                self.assertEqual(f.launch(30,True),0)
            self.assertEqual(launches.call_count,1);self.assertEqual(state['waits'],3)
            self.assertIn('SESSION='+str(state['path']),output.getvalue())

    def test_duration_modes(self):
        for v in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):f.validate_duration(v)
        self.assertEqual(f.validate_duration(None),0);self.assertEqual(f.validate_duration(1200),1200);self.assertEqual(f.validate_duration(300),300);self.assertEqual(f.validate_duration(30),30)
    def test_unchanged_configuration(self):
        self.assertEqual(f.CONFIG.read_bytes(),(c.WS/'src/zed_capture/config/capture_hd720_c5g.yaml').read_bytes())
        c.verify_frozen()
    def test_no_auto_checker_or_forced_kill(self):
        s=(c.HERE/'session_field.py').read_text()
        self.assertNotIn("str(WS/'scripts/check_recording.py'),str(session)",s)
        for name in ('session_field.py','field_capture.py','field_common.py'):
            text=(c.HERE/name).read_text()
            for bad in ('SIGKILL','killall','pkill','os.kill('):self.assertNotIn(bad,text)
    def test_identity_pid_reuse_boot_and_cmdline(self):
        m={'boot_id':c.boot_id(),'manager_pid':123,'manager_start_ticks':'777','session_dir':'/tmp/x'}
        good={'state':'S','start_ticks':'777','argv':[str(c.HERE/'field_capture.py').encode(),b'_manager',b'/tmp/x']}
        with patch.object(c,'process',return_value=good):self.assertTrue(c.manager_alive(m));self.assertFalse(c.manager_alive(dict(m,boot_id='old')))
        for change in ({'start_ticks':'888'},{'state':'Z'},{'argv':[b'OTHER']}):
            with patch.object(c,'process',return_value=dict(good,**change)):self.assertFalse(c.manager_alive(m))
    def test_atomic_and_stop_validation(self):
        with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_') as t:
            p=P(t);m=self.ident(p);c.atomic(p/'field_identity.json',m)
            with patch.object(c,'manager_alive',return_value=True):
                self.assertEqual(c.request_stop(p),'STOP_REQUESTED');self.assertEqual(c.request_stop(p),'STOP_ALREADY_REQUESTED')
            self.assertTrue(c.stop_requested(p));r=c.load(p/'field_stop_request.json');r['token']='b'*32;c.atomic(p/'field_stop_request.json',r)
            with self.assertRaises(ValueError):c.stop_requested(p)
            c.atomic(p/'capture_status.json',{'state':'FINALIZED'})
            with patch.object(c,'manager_alive',side_effect=AssertionError('must not signal completed PID')):self.assertEqual(c.request_stop(p),'ALREADY_FINALIZED')
    def test_corrupt_metadata_refused(self):
        with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_') as t:
            p=P(t);(p/'field_identity.json').write_text('{')
            with self.assertRaises(ValueError):c.request_stop(p)
    def test_stale_heartbeat(self):
        with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_') as t:
            p=P(t);m=self.ident(p);c.atomic(p/'field_identity.json',m)
            c.atomic(p/'capture_status.json',dict(m,state='RECORDING',heartbeat_monotonic_ns=time.monotonic_ns()-6_000_000_000))
            with patch.object(f,'manager_alive',return_value=True):self.assertEqual(f.view(p)['state'],'STALE / UNKNOWN')
            with patch.object(f,'manager_alive',return_value=False):self.assertEqual(f.view(p)['state'],'MANAGER_LOST / UNKNOWN')
    def test_streaming_progress_integer_precision(self):
        source=c.ROOT/'20261018_185527_61ca19f8/frames.csv'
        a=c.FrameCounter()
        for _ in range(100):
            a.update(source)
            if not a.backlog:break
        self.assertEqual(a.written,8988);self.assertEqual(a.encoded,8988);self.assertEqual(a.errors,0)
        with source.open() as stream:r=next(csv.DictReader(stream));self.assertIsInstance(int(r['raw_ns']),int)
        b=c.tail_json(c.ROOT/'20261018_185527_61ca19f8/capture_metrics.jsonl');self.assertIsInstance(b['monotonic_ns'],int)
    def test_partial_rows_and_bounded_bad_line(self):
        with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_') as t:
            p=P(t)/'frames.csv';p.write_bytes(b'status,left_ok,right_ok,encoding_status\nWRIT')
            a=c.FrameCounter();a.update(p);self.assertEqual(a.rows,0)
            with p.open('ab') as stream:stream.write(b'TEN,1,1,ENCODED_420\n')
            a.update(p);self.assertEqual(a.written,1)
            with p.open('ab') as stream:stream.write(b'x'*65537)
            with self.assertRaises(ValueError):a.update(p)
    def test_legacy_history_finalization_eligible(self):
        p=c.ROOT/'20261018_185527_61ca19f8';e=ck.eligibility(p)
        self.assertEqual(e['FINALIZATION_STATUS'],'FINALIZED');self.assertEqual(e['DATA_INTEGRITY'],'PENDING')
        self.assertEqual(ck.command(p,P('/tmp/output with spaces'))[-1],'/tmp/output with spaces')
    def test_checks_refuse_active_unsynced_and_identity(self):
        with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_') as t:
            p=P(t);m=self.ident(p);c.atomic(p/'field_identity.json',m)
            c.atomic(p/'session.json',{'session_id':p.name,'config':{}})
            with patch.object(ck,'manager_alive',return_value=True):
                with self.assertRaises(RuntimeError):ck.eligibility(p)
            c.atomic(p/'session.json',{'session_id':'wrong'})
            with self.assertRaises(ValueError):ck.eligibility(p)
    def test_index_shutdown_source_invariance(self):
        base=(c.WS/'src/zed_capture/src/capture_node.cpp').read_text();candidate=(c.HERE/'capture_node_field.cpp').read_text()
        for key,end in [(' void stopGnss(){',' std::atomic<uint64_t> pairs'),(' void onVideo',' void on')]:
            if key not in base:continue
            if key==' void stopGnss(){':self.assertEqual(base[base.index(key):base.index(end)],candidate[candidate.index(key):candidate.index(end)])
        self.assertIn('NoSigintHandler',candidate);self.assertIn('while(ros::ok()&&!field_capture::stopping()',candidate)
        self.assertNotIn('ros::shutdown()',candidate)
    def test_hardware_lease_and_duplicate_launch(self):
        import fcntl
        with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_LOCK_') as t:
            p=P(t);fd=os.open(str(p/'hardware.lock'),os.O_CREAT|os.O_RDWR,0o600)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(f,'RUNTIME',p),patch.object(f,'verify_frozen',return_value={}):
                    with self.assertRaises(RuntimeError):f.launch(300,True)
            finally:os.close(fd)
    def test_stop_wait_timeout_no_escalation(self):
        with patch.object(f,'view',return_value={'state':'FINALIZING','manager_alive':True}),patch.object(f,'display'),patch.object(f,'load',return_value={}),patch.object(f.time,'monotonic',side_effect=[0,5]),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(f.wait_status(P('/tmp/SYNTHETIC'),False,True,1),2)
    def test_status_ctrlc_does_not_stop(self):
        with patch.object(f,'view',side_effect=KeyboardInterrupt),patch.object(f,'request_stop',side_effect=AssertionError('observer must not stop')):
            self.assertEqual(f.wait_status(P('/tmp/SYNTHETIC'),False,True),0)
    def test_stop_reused_pid_refuses_without_signal(self):
        with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_') as t:
            p=P(t);c.atomic(p/'field_identity.json',self.ident(p))
            with patch.object(c,'manager_alive',return_value=False):
                with self.assertRaises(RuntimeError):c.request_stop(p)
            self.assertFalse((p/'field_stop_request.json').exists())
    def test_final_sync_failure_not_success(self):
        p=c.ROOT/'20261018_185527_61ca19f8';real_load=c.load
        def altered(path,default=None):
            data=real_load(path,default)
            if str(path).endswith('jpeg_files_summary.json'):data=dict(data,final_synced=False)
            return data
        with patch.object(c,'load',side_effect=altered):
            self.assertEqual(c.finalized_evidence(p)['FINALIZATION_STATUS'],'FAILED')
    def test_bounded_progress_and_manifest_does_not_use_bag(self):
        with patch.object(f,'load',return_value={}),patch.object(f,'tail_json',return_value={}),patch.object(c.FrameCounter,'update'),patch.object(f.shutil,'disk_usage',return_value=types.SimpleNamespace(free=123)):
            row=f.Progress(P('/tmp/NO_SUCH_SYNTHETIC')).read();self.assertIsNone(row['elapsed_seconds']);self.assertIsNone(row['sensor_counters']['gnss_ros_written'])
    @staticmethod
    def ident(p):return {'session_id':p.name,'session_dir':str(p),'token':'a'*32,'boot_id':c.boot_id(),'manager_pid':None,'manager_start_ticks':None}
    def test_session_continuous_both_gnss_modes(self):self.candidate_modes(0)
    def test_session_twenty_minutes_both_gnss_modes(self):self.candidate_modes(1200)
    def test_session_candidate_both_gnss_modes_no_checker(self):
        self.candidate_modes()
    def test_session_status_disk_error_does_not_abort_cleanup(self):
        with patch.object(sf,'atomic',side_effect=OSError('SYNTHETIC_STATUS_DISK_FULL')),contextlib.redirect_stderr(io.StringIO()):
            self.candidate_modes()
    def candidate_modes(self,duration=300):
        for enabled in (False,True):
            with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_') as t:
                root=P(t);p=root/'SYNTHETIC_SESSION';p.mkdir();c.atomic(p/'field_identity.json',self.ident(p))
                cfg=yaml.safe_load(f.CONFIG.read_text());cfg.update(gnss_enable=enabled,output_root=t)
                config=root/'config with spaces.yaml';config.write_text(yaml.safe_dump(cfg))
                master=Mock();master.getSystemState.return_value=([('/livox/lidar',['existing']),('/livox/imu',['existing'])],[],[])
                master.getPublishedTopics.return_value=[('/livox/lidar','livox_ros_driver2/CustomMsg')]
                def spawn(*a,**kw):
                    child=Mock();child.poll.return_value=0;child.wait.return_value=0;child.returncode=0;child.pid=999999;return child
                with patch.dict(sys.modules,{'rosgraph':types.SimpleNamespace(Master=lambda _:master)}),patch.dict(os.environ,{'C5I_LOCK_FD':'99'}),patch.object(sys,'argv',['session_field','--field-session-dir',str(p),'--config',str(config),'--duration',str(duration)]),patch.object(sf,'preflight',return_value={'errors':[],'dynamic_dependencies':{}}),patch.object(sf,'capture_environment',return_value={'LD_LIBRARY_PATH':'SYNTHETIC'}),patch.object(sf.subprocess,'Popen',side_effect=spawn) as sp,patch.object(sf.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stdout='')) as run,patch.object(sf.signal,'signal'),patch.object(sf.socket,'setdefaulttimeout'),contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(sf.main(),0)
                self.assertEqual(sp.call_count,2 if enabled else 1)
                args=sp.call_args.args[0];self.assertIn('_duration:='+str(float(duration)),args)
                self.assertIn(str(c.BUILD/'lib/zed_capture/zed_capture_node'),args)
                self.assertFalse(any('check_recording' in ' '.join(x.args[0]) for x in run.call_args_list))
                self.assertEqual(c.load(p/'session.json')['config_path'],str(config))

class Processes(unittest.TestCase):
    ident=staticmethod(Tests.ident)
    def launch_fixture(self,p,scenario):
        c.atomic(p/'field_identity.json',self.ident(p));log=(p/'SYNTHETIC_manager.log').open('x')
        process=subprocess.Popen([sys.executable,'-B',str(c.HERE/'test_process_fixture.py'),'manager',str(p),scenario,
            str(c.HERE/'field_capture.py'),'_manager',str(p)],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        log.close();return process
    def await_file(self,p,timeout=10):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            if p.exists():return
            time.sleep(.05)
        self.fail('file timeout '+str(p))
    def scenario(self,kind):
        with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_PROCESS_') as t:
            p=P(t)/'SYNTHETIC_SESSION';p.mkdir();child=self.launch_fixture(p,kind)
            self.await_file(p/'capture_status.json')
            if kind=='init_stop':
                self.assertEqual(c.request_stop(p),'STOP_REQUESTED')
            elif kind not in ('auto300','disk_full'):
                self.await_file(p/'capture_metrics.jsonl')
                if kind=='hup_stop':
                    child.send_signal(signal.SIGHUP);time.sleep(.2);self.assertIsNone(child.poll());self.assertTrue(f.view(p)['manager_alive'])
                    self.assertEqual(c.request_stop(p),'STOP_REQUESTED')
                elif kind=='ctrlc':child.send_signal(signal.SIGINT)
                elif kind=='repeat_finalize':
                    c.request_stop(p);self.await_file(p/'field_node_status.json');self.assertEqual(c.request_stop(p),'STOP_ALREADY_REQUESTED')
            self.assertEqual(child.wait(timeout=15),2 if kind=='disk_full' else 0, (p/'SYNTHETIC_manager.log').read_text())
            final=c.load(p/'capture_finalization.json');self.assertEqual(final['FULL_STRICT_CHECK'],'PENDING')
            self.assertEqual(final['DATA_INTEGRITY'],'PENDING')
            if kind not in ('disk_full','init_stop'):
                self.assertTrue(final['BAG_FINALIZED']);self.assertTrue(final['JPEG_FINAL_SYNCED']);self.assertTrue(final['GNSS_FINAL_SYNCED'])
                import rosbag
                with rosbag.Bag(str(p/'sensors.bag')) as bag:self.assertEqual(sum(1 for _ in bag.read_messages()),1)
                self.assertEqual(c.request_stop(p),'ALREADY_FINALIZED')
            else:self.assertFalse((p/'sensors.bag').exists())
            self.assertFalse((p/'check_result.json').exists())
    def test_process_auto300_virtual(self):self.scenario('auto300')
    def test_process_hup_status_remote_stop(self):self.scenario('hup_stop')
    def test_process_ctrlc(self):self.scenario('ctrlc')
    def test_process_repeat_stop_in_finalization(self):self.scenario('repeat_finalize')
    def test_process_stop_initialization(self):self.scenario('init_stop')
    def test_process_disk_preflight_block(self):self.scenario('disk_full')

if __name__=='__main__':unittest.main(verbosity=2)
