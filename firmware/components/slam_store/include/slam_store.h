#pragma once

#include "esp_err.h"
#include "slam_types.h"

// One card in the campus-wide directory. 11 bytes packed.
typedef struct __attribute__((packed)) {
    uint8_t  uid[SLAM_UID_MAX_LEN];
    uint8_t  len;
    uint16_t student_id;
    uint8_t  flags;          // bit 0 = admin card
} dir_entry_t;

#define DIR_FLAG_ADMIN   0x01

// One student enrolled in the session currently running.
typedef struct __attribute__((packed)) {
    uint16_t student_id;
    char     name[SLAM_NAME_LEN];
} roster_entry_t;

// The lecture this device is currently taking attendance for.
typedef struct {
    uint32_t session_id;
    char     course[12];
    int64_t  starts_utc;
    int64_t  ends_utc;
    uint16_t grace_minutes;
    bool     active;
} session_t;

esp_err_t slam_store_init(void);

// Directory: every active card on campus.
esp_err_t slam_dir_load(const dir_entry_t *entries, size_t count, uint32_t version);
// Same, plus a file of 16-byte names in entry order (see slam_dir_names_tmp).
esp_err_t slam_dir_install(const dir_entry_t *entries, size_t count,
                           uint32_t version, const char *names_tmp);
// Where the downloader writes the names before handing them over.
const char *slam_dir_names_tmp(void);
const dir_entry_t *slam_dir_find(const slam_uid_t *uid);
size_t   slam_dir_count(void);
uint32_t slam_dir_version(void);

// Roster: only the students in the current session.
esp_err_t slam_roster_load(const session_t *s, const roster_entry_t *entries, size_t count);
const roster_entry_t *slam_roster_find(uint16_t student_id);
const session_t *slam_session(void);
// From each check-in: whether the dashboard has put this reader in a venue.
void slam_set_placed(bool placed);
size_t   slam_roster_count(void);

// Present bitmap: has this student already been recorded this session?
bool slam_present_get(uint16_t student_id);
void slam_present_set(uint16_t student_id);
void slam_present_clear_all(void);

// The whole decision, in one call. Fills the event and the display lines.
tap_outcome_t slam_decide(const slam_uid_t *uid, tap_event_t *ev,
                          char *l1, char *l2);

// Upload queue: a circular log on its own raw flash partition.
esp_err_t slam_queue_init(void);
esp_err_t slam_queue_push(const tap_event_t *ev);
size_t    slam_queue_depth(void);
esp_err_t slam_queue_peek(tap_event_t *out, size_t max, size_t *got);
esp_err_t slam_queue_drop(size_t count);

