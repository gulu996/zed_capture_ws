#!/usr/bin/env python3
import unittest,tempfile,pathlib
from analyze_real_session import sequence_kind,assess_anchor_coverage,read_video

class AnalysisTests(unittest.TestCase):
    def test_sequence_categories_and_wrap(self):
        self.assertEqual(sequence_kind(18,21),('gap',3))
        self.assertEqual(sequence_kind(18,18),('duplicate',0))
        self.assertEqual(sequence_kind(18,0)[0],'reset_or_backward')
        self.assertEqual(sequence_kind(0xffffffff,0),('normal',1))
    def test_history_gap_does_not_imply_all_images_unmappable(self):
        a=[{'validity':'HOST_ARRIVAL_ANCHOR','host_monotonic_ns':1000000000,'writer_epoch':3,'clock_source':2,'skipped_updates':0},
           {'validity':'HOST_ARRIVAL_ANCHOR','host_monotonic_ns':1020000000,'writer_epoch':3,'clock_source':2,'skipped_updates':3}]
        v=[{'pair_id':1,'timestamp_type':8192,'raw_ns':1010000000}, {'pair_id':2,'timestamp_type':8192,'raw_ns':990000000}]
        r=assess_anchor_coverage(v,a)
        self.assertEqual(sum(x['skipped_updates'] for x in a),3)
        self.assertEqual(r['input_coverage_counts'],{'CANDIDATE_BRACKET_ONLY':1,'BEFORE_FIRST_VALID_ANCHOR':1})
        self.assertEqual(r['status'],'PENDING')
    def test_unknown_clock_and_epoch_change_not_accepted(self):
        a=[{'validity':'HOST_ARRIVAL_ANCHOR','host_monotonic_ns':100,'writer_epoch':1,'clock_source':2},
           {'validity':'HOST_ARRIVAL_ANCHOR','host_monotonic_ns':200,'writer_epoch':2,'clock_source':2}]
        r=assess_anchor_coverage([{'pair_id':1,'timestamp_type':8192,'raw_ns':150},{'pair_id':2,'timestamp_type':0,'raw_ns':150}],a)
        self.assertEqual(r['input_coverage_counts'],{'ANCHOR_DOMAIN_CHANGE':1,'UNKNOWN_VIDEO_CLOCK':1})
    def test_legacy_bool_byte_read_without_modifying_file(self):
        # Only generated tiny fixture; never touch recorded CSV.
        with tempfile.TemporaryDirectory(prefix='zed_csv_test_') as d:
            p=pathlib.Path(d)/'v.csv';original=b'pair_id,payload_valid\n1,\x01\n2,0\n';p.write_bytes(original)
            self.assertEqual(read_video(p),[{'pair_id':1,'payload_valid':1},{'pair_id':2,'payload_valid':0}])
            self.assertEqual(p.read_bytes(),original)
    def test_host_time_reversal_requires_segmentation(self):
        a=[{'validity':'HOST_ARRIVAL_ANCHOR','host_monotonic_ns':200},
           {'validity':'HOST_ARRIVAL_ANCHOR','host_monotonic_ns':100}]
        r=assess_anchor_coverage([{'pair_id':1,'raw_ns':150}],a)
        self.assertEqual(r['input_coverage_counts'],{'ANCHOR_HOST_TIME_NOT_INCREASING':1})
if __name__=='__main__':unittest.main(verbosity=2)
