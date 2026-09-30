#pragma once

#include <stdbool.h>
#include "esp_err.h"

#define CFG_URL_LEN     96
#define CFG_TOKEN_LEN   72

// Backend address and device token, stored in NVS and editable later
// through the config portal. The defaults are only used on a device
// that has never been configured.
esp_err_t   slam_cfg_init(void);
const char *slam_cfg_base_url(void);
const char *slam_cfg_token(void);
esp_err_t   slam_cfg_set_base_url(const char *url);
esp_err_t   slam_cfg_set_token(const char *token);
bool        slam_cfg_ready(void);
