"""SYNTHETIC software-only tests; no real-data benchmark or sensor starts."""
import copy,unittest
import cv2,numpy as np
from codec import selftest,sof,Encoder
from benchmark import quality,header
from sensor_msgs.msg import Image
class Tests(unittest.TestCase):
    def test_explicit_420(self):self.assertIn('PASS',selftest())
    def test_bad_jpeg_rejected(self):
        with self.assertRaises(ValueError):sof(b'notjpeg')
    def test_identity_quality(self):
        rng=np.random.RandomState(5);x=rng.randint(0,256,(64,64,3),dtype=np.uint8)
        r=quality(x,x);self.assertEqual(r['psnr_bgr_db'],100);self.assertAlmostEqual(r['ssim_gray'],1,places=5);self.assertEqual(r['corner_retention_fraction'],1);self.assertEqual(r['gradient_magnitude_mae'],0)
    def test_header_keeps_integer_precision(self):
        msg=Image();msg.header.seq=902;msg.header.stamp.secs=13984;msg.header.stamp.nsecs=210934000;msg.header.frame_id='zed2i_left_raw'
        restored=copy.deepcopy(msg);self.assertEqual(header(restored.header),header(msg.header));self.assertEqual(header(msg.header)['stamp_ns'],13984210934000)
if __name__=='__main__':unittest.main(verbosity=2)
