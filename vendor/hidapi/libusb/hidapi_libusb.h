/* Local build adapter: this application uses only the portable HIDAPI API.
 * hid.c defines its libusb extension itself; no extension is called here.
 * Upstream portable declarations and stdint are sufficient for this build.
 */
#pragma once
#include <stdint.h>
#include "hidapi.h"
