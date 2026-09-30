#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#define SLAM_UID_MAX_LEN   10
#define SLAM_NAME_LEN      16

// A card serial number, stored as raw bytes. Never as a string.
typedef struct {
    uint8_t bytes[SLAM_UID_MAX_LEN];
    uint8_t len;
} slam_uid_t;

// What the device decided about a tap.
typedef enum {
    TAP_UNKNOWN_CARD = 0,   // not in the card directory at all
    TAP_NO_SESSION,         // known card, but no lecture running here now
    TAP_NOT_ENROLLED,       // known student, not on this course
    TAP_PRESENT,            // accepted
    TAP_LATE,               // accepted after the grace period
    TAP_DUPLICATE,          // already recorded this session - never uploaded
    TAP_ADMIN,              // admin card, toggles enrolment mode
    TAP_READ_ERROR
} tap_outcome_t;

// How much we trust the timestamp on a record.
typedef enum {
    TIME_UNKNOWN = 0,   // rebooted with no network, clock is a guess
    TIME_DRIFT,         // derived from last sync plus uptime
    TIME_SYNCED         // set from the server within the last hour
} time_conf_t;

// One tap, as queued for upload. Changing this layout changes the flash
// slot size, so bump QLOG_LAYOUT in slam_queue.c whenever it changes.
typedef struct {
    slam_uid_t uid;
    int64_t    ts_utc;       // seconds since epoch, 0 when never synced
    int64_t    uptime_ms;    // uptime at the tap, meaningful within boot_id
    uint32_t   boot_id;      // which power-up this tap happened in
    uint32_t   session_id;   // 0 when no session was active
    uint16_t   student_id;   // 0 when the card is unknown
    uint32_t   client_id;    // counter within boot_id; the pair is unique
    uint8_t    outcome;      // tap_outcome_t - advisory, the server decides
    uint8_t    time_conf;    // time_conf_t
} tap_event_t;

// One line pair for the LCD, plus how to beep.
typedef enum {
    TONE_NONE = 0,
    TONE_ACCEPT,    // one short beep, green
    TONE_REJECT,    // two long beeps, red
    TONE_NEUTRAL    // one click
} tone_t;

typedef struct {
    char    line1[SLAM_NAME_LEN + 1];
    char    line2[SLAM_NAME_LEN + 1];
    uint8_t tone;       // tone_t
    uint16_t hold_ms;   // keep on screen at least this long
} ui_msg_t;

// Queues owned by slam_core.
extern QueueHandle_t slam_ui_q;      // ui_msg_t, to the display task
extern QueueHandle_t slam_store_q;   // tap_event_t, to the flash writer

void      slam_core_init(void);
void      slam_ui_post(const char *l1, const char *l2, tone_t tone, uint16_t hold_ms);
bool      slam_uid_equal(const slam_uid_t *a, const slam_uid_t *b);
int       slam_uid_cmp(const slam_uid_t *a, const slam_uid_t *b);
void      slam_uid_to_hex(const slam_uid_t *uid, char *out, size_t out_len);
int64_t   slam_now_utc(void);
time_conf_t slam_time_confidence(void);
void      slam_set_time(int64_t utc_seconds);
void      slam_set_time_ms(int64_t utc_ms);
int64_t   slam_uptime_ms(void);
uint32_t  slam_boot_id(void);
const char *slam_hw_id(void);   // "AA:BB:CC:DD:EE:FF", this reader's MAC
const char *slam_pair_secret(void);   // 32 hex chars, made at first boot

#define SLAM_FW_VERSION "0.2.0"
const char *slam_outcome_name(tap_outcome_t o);
