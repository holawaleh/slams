#pragma once

#include <stdbool.h>
#include "esp_err.h"

// Starts the configuration web server. Safe to call more than once.
esp_err_t slam_portal_start(void);
void      slam_portal_stop(void);
bool      slam_portal_running(void);

// True if someone changed the network settings and the device should
// reconnect. The network task checks this and clears it.
bool slam_portal_take_dirty(void);
