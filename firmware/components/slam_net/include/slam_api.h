#pragma once

#include <stdbool.h>
#include "esp_err.h"
#include "slam_store.h"
#include "slam_cfg.h"

typedef struct {
    int64_t  server_utc_ms;   // server time now, round trip allowed for
    uint32_t directory_version;
    uint32_t bundle_version;
    bool     enroll_mode;
    bool     has_session;
    bool     placed;          // the reader has a venue in the dashboard
    char     firmware_latest[16];
} hello_result_t;

// What the server said to an unregistered reader announcing itself.
typedef enum {
    PAIR_NONE = 0,
    PAIR_WAITING,     // show `code` on the screen until an admin claims us
    PAIR_DONE,        // `token` is ours; save it and carry on normally
    PAIR_TAKEN        // registered to an account already
} pair_state_t;

typedef struct {
    pair_state_t state;
    char    code[8];
    char    token[CFG_TOKEN_LEN];
    char    name[65];
    int64_t server_utc_ms;
} announce_result_t;

esp_err_t slam_api_init(void);

// Unregistered: say we are here, and learn our pairing code or token.
esp_err_t slam_api_announce(announce_result_t *out, const char *local_ip);

// One request carrying everything the device would otherwise poll for.
esp_err_t slam_api_hello(hello_result_t *out, size_t queue_depth);

// Fetches only when the version differs. ESP_ERR_NOT_FOUND means the
// server had nothing new, which is the normal case.
esp_err_t slam_api_fetch_bundle(uint32_t have_version);
esp_err_t slam_api_fetch_directory(uint32_t have_version);

// Uploads up to max_records from the queue, then marks them sent.
esp_err_t slam_api_upload(size_t max_records, size_t *uploaded);

// Reports a card seen while in enrolment mode.
esp_err_t slam_api_enroll(const slam_uid_t *uid);
