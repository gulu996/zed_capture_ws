#ifndef HIDAPI_CAPTURE_TRACE_H
#define HIDAPI_CAPTURE_TRACE_H
/* Private, statically linked capture diagnostics. No system HIDAPI ABI change.
 * arrival_monotonic_ns is libusb callback entry, NOT a USB hardware timestamp. */
#include "hidapi.h"
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
struct hid_capture_trace {
 uint64_t arrival_monotonic_ns, dequeue_monotonic_ns;
 uint64_t completed_reports, consumed_reports, queue_discards, queue_depth, queue_peak;
 uint64_t transfer_status[7]; /* libusb completion statuses 0..6, not physical packets */
 uint64_t submit_errors, event_loop_errors, read_timeouts, read_errors;
 uint64_t last_discard_arrival_ns;
 int wait_result;
};
int hid_read_capture_timeout(hid_device *dev, unsigned char *data, size_t length,
                            int milliseconds, struct hid_capture_trace *trace);
#ifdef __cplusplus
}
#endif
#endif
