/* SYNTHETIC: use the actual private HIDAPI queue with injected completions.
 * No libusb init/device discovery/open/transfer submission is performed. */
#define libusb_submit_transfer capture_test_submit
#include "../../../vendor/hidapi/libusb/hid.c"
#undef libusb_submit_transfer
#include <assert.h>
static int submit_result=0;
int LIBUSB_CALL capture_test_submit(struct libusb_transfer *t){(void)t;return submit_result;}
int main(void){
 hid_device *dev=new_hid_device();unsigned char payload[64]={0},out[64];
 struct libusb_transfer tr={0};tr.user_data=dev;tr.buffer=payload;tr.actual_length=64;tr.status=LIBUSB_TRANSFER_COMPLETED;
 for(int i=0;i<80;++i){payload[0]=(unsigned char)i;read_callback(&tr);}
 assert(dev->capture_trace.completed_reports==80 && dev->capture_trace.queue_discards==48);
 assert(dev->capture_trace.queue_depth==32 && dev->capture_trace.queue_peak==33);
 struct hid_capture_trace t;
 for(int i=48;i<80;++i){
  assert(hid_read_capture_timeout(dev,out,sizeof(out),1,&t)==64 && out[0]==i);
  assert(t.arrival_monotonic_ns>0 && t.dequeue_monotonic_ns>=t.arrival_monotonic_ns);
  assert(t.completed_reports==t.consumed_reports+t.queue_discards+t.queue_depth);
 }
 assert(t.consumed_reports==32 && t.queue_depth==0 && t.last_discard_arrival_ns>0);
 assert(hid_read_capture_timeout(dev,out,sizeof(out),1,&t)==0);
 assert(t.read_timeouts==1 && t.wait_result==ETIMEDOUT && !t.arrival_monotonic_ns);
 assert(hid_read_timeout(dev,out,sizeof(out),0)==0); /* original API retained */
 tr.status=LIBUSB_TRANSFER_TIMED_OUT;read_callback(&tr);
 tr.status=LIBUSB_TRANSFER_ERROR;read_callback(&tr);
 tr.status=LIBUSB_TRANSFER_STALL;read_callback(&tr);
 tr.status=LIBUSB_TRANSFER_OVERFLOW;read_callback(&tr);
 submit_result=LIBUSB_ERROR_IO;read_callback(&tr);
 assert(hid_read_capture_timeout(dev,out,sizeof(out),1,&t)==-1);
 assert(t.read_errors==1 && t.submit_errors==1 && t.transfer_status[LIBUSB_TRANSFER_OVERFLOW]==2);
 assert(t.transfer_status[LIBUSB_TRANSFER_TIMED_OUT]==1 && t.transfer_status[LIBUSB_TRANSFER_ERROR]==1 && t.transfer_status[LIBUSB_TRANSFER_STALL]==1);
 free_hid_device(dev);
 puts("SYNTHETIC PASS: exact retained FIFO bytes, original queue limit, 48 observable discards, timeout/error counters, original API");
 return 0;
}
