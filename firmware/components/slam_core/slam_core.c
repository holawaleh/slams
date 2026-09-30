#include <string.h>
#include <stdio.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "slam_types.h"
#include "freertos/task.h"

static const char *TAG = "core";

QueueHandle_t slam_ui_q    = NULL;
QueueHandle_t slam_store_q = NULL;

// Clock without an RTC chip: anchor a known UTC time to a known uptime.
// The server is the only time source. Its clock is also the one that
// judges whether a tap counts, so there is nothing to gain from a second
// source like SNTP that could disagree with it.
static int64_t s_epoch_anchor_ms  = 0;   // server UTC at the moment of sync
static int64_t s_uptime_anchor_ms = 0;   // uptime at that moment
static bool    s_ever_synced      = false;
static portMUX_TYPE s_clock_lock  = portMUX_INITIALIZER_UNLOCKED;

// Counts power-ups, persisted in NVS. A tap's uptime only means
// something within the boot it was taken in, and the per-boot counter
// restarts at 1, so (boot_id, counter) is what makes a tap unique.
static uint32_t s_boot_id = 0;

static void load_boot_id(void)
{
    nvs_handle_t h;
    if (nvs_open("slam", NVS_READWRITE, &h) != ESP_OK) {
        // Without NVS every boot looks like boot 0 and client ids will
        // collide on the server. Loud, because it loses attendance.
        ESP_LOGE(TAG, "nvs unavailable, boot id stuck at 0");
        return;
    }
    uint32_t prev = 0;
    nvs_get_u32(h, "boot_id", &prev);
    s_boot_id = prev + 1;
    esp_err_t err = nvs_set_u32(h, "boot_id", s_boot_id);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err != ESP_OK) {
        // Not fatal today, but the next boot will reuse this id and its
        // taps will collide with this boot's on the server.
        ESP_LOGE(TAG, "could not save boot id: %s", esp_err_to_name(err));
    }
}

// The reader's identity: its WiFi MAC, burned into eFuse at the factory.
// The backend lets one hardware id belong to one account at a time.
static char s_hw_id[18];

static void load_hw_id(void)
{
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(s_hw_id, sizeof(s_hw_id), "%02X:%02X:%02X:%02X:%02X:%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

const char *slam_hw_id(void) { return s_hw_id; }

// A random secret made at first boot and kept in NVS. When the reader
// pairs, the server only hands its token to whoever announces with this
// secret, so copying the MAC address is not enough to steal a pairing.
static char s_pair_secret[33];

static void load_pair_secret(void)
{
    nvs_handle_t h;
    if (nvs_open("slam", NVS_READONLY, &h) != ESP_OK) return;
    size_t len = sizeof(s_pair_secret);
    if (nvs_get_str(h, "pair_secret", s_pair_secret, &len) != ESP_OK ||
        strlen(s_pair_secret) != 32) {
        s_pair_secret[0] = 0;
    }
    nvs_close(h);
}

// Made on first use rather than at boot: the hardware random number
// generator is only truly random once the WiFi radio is running, and
// the secret is first needed when the reader is online to announce.
const char *slam_pair_secret(void)
{
    if (s_pair_secret[0]) return s_pair_secret;
    uint8_t raw[16];
    esp_fill_random(raw, sizeof(raw));
    for (int i = 0; i < 16; i++)
        snprintf(s_pair_secret + i * 2, 3, "%02x", raw[i]);
    nvs_handle_t h;
    if (nvs_open("slam", NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_str(h, "pair_secret", s_pair_secret);
        nvs_commit(h);
        nvs_close(h);
    }
    return s_pair_secret;
}

void slam_core_init(void)
{
    slam_ui_q    = xQueueCreate(8,  sizeof(ui_msg_t));
    slam_store_q = xQueueCreate(32, sizeof(tap_event_t));
    load_boot_id();
    load_hw_id();
    load_pair_secret();
    ESP_LOGI(TAG, "queues created, boot %u, reader id %s",
             (unsigned)s_boot_id, s_hw_id);
}

uint32_t slam_boot_id(void)   { return s_boot_id; }
int64_t  slam_uptime_ms(void) { return esp_timer_get_time() / 1000; }

void slam_ui_post(const char *l1, const char *l2, tone_t tone, uint16_t hold_ms)
{
    ui_msg_t m = {0};
    if (l1) strlcpy(m.line1, l1, sizeof(m.line1));
    if (l2) strlcpy(m.line2, l2, sizeof(m.line2));
    m.tone    = (uint8_t)tone;
    m.hold_ms = hold_ms;
    // Never block the caller. A dropped status line is harmless.
    xQueueSend(slam_ui_q, &m, 0);
}

bool slam_uid_equal(const slam_uid_t *a, const slam_uid_t *b)
{
    if (a->len != b->len) return false;
    return memcmp(a->bytes, b->bytes, a->len) == 0;
}

// Ordering for binary search. Shorter UIDs sort before longer ones.
int slam_uid_cmp(const slam_uid_t *a, const slam_uid_t *b)
{
    uint8_t n = (a->len < b->len) ? a->len : b->len;
    int c = memcmp(a->bytes, b->bytes, n);
    if (c != 0) return c;
    return (int)a->len - (int)b->len;
}

void slam_uid_to_hex(const slam_uid_t *uid, char *out, size_t out_len)
{
    size_t p = 0;
    for (uint8_t i = 0; i < uid->len && p + 2 < out_len; i++) {
        p += snprintf(out + p, out_len - p, "%02X", uid->bytes[i]);
    }
    out[p] = 0;
}

void slam_set_time_ms(int64_t utc_ms)
{
    if (utc_ms <= 0) return;
    int64_t up = slam_uptime_ms();
    int64_t was = slam_now_utc();
    taskENTER_CRITICAL(&s_clock_lock);
    s_epoch_anchor_ms  = utc_ms;
    s_uptime_anchor_ms = up;
    s_ever_synced      = true;
    taskEXIT_CRITICAL(&s_clock_lock);
    if (was) {
        ESP_LOGD(TAG, "clock corrected by %lld s",
                 (long long)(utc_ms / 1000 - was));
    } else {
        ESP_LOGI(TAG, "clock set from server: %lld", (long long)(utc_ms / 1000));
    }
}

void slam_set_time(int64_t utc_seconds)
{
    slam_set_time_ms(utc_seconds * 1000);
}

int64_t slam_now_utc(void)
{
    taskENTER_CRITICAL(&s_clock_lock);
    bool synced = s_ever_synced;
    int64_t epoch = s_epoch_anchor_ms, anchor = s_uptime_anchor_ms;
    taskEXIT_CRITICAL(&s_clock_lock);
    if (!synced) return 0;
    return (epoch + (slam_uptime_ms() - anchor)) / 1000;
}

time_conf_t slam_time_confidence(void)
{
    taskENTER_CRITICAL(&s_clock_lock);
    bool synced = s_ever_synced;
    int64_t anchor = s_uptime_anchor_ms;
    taskEXIT_CRITICAL(&s_clock_lock);
    if (!synced) return TIME_UNKNOWN;
    return ((slam_uptime_ms() - anchor) < 3600 * 1000) ? TIME_SYNCED : TIME_DRIFT;
}

const char *slam_outcome_name(tap_outcome_t o)
{
    switch (o) {
        case TAP_UNKNOWN_CARD: return "unknown";
        case TAP_NO_SESSION:   return "no_session";
        case TAP_NOT_ENROLLED: return "not_enrolled";
        case TAP_PRESENT:      return "present";
        case TAP_LATE:         return "late";
        case TAP_DUPLICATE:    return "duplicate";
        case TAP_ADMIN:        return "admin";
        default:               return "read_error";
    }
}
