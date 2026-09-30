#include <string.h>
#include <stdlib.h>
#include "esp_log.h"
#include "esp_partition.h"
#include "slam_store.h"

static const char *TAG = "qlog";

#define SECT_SIZE    4096
#define SECT_HDR     8
// The low byte is the tap_event_t layout version. A sector written with
// another layout fails the magic check and is treated as empty, rather
// than being misread as garbage records. v2 added boot_id and uptime_ms.
#define QLOG_LAYOUT  0x02u
#define SECT_MAGIC   (0xA5C3A500u | QLOG_LAYOUT)
#define REC_PENDING  0x5A5A5A5Au
#define REC_SENT     0x00000000u
#define REC_EMPTY    0xFFFFFFFFu

typedef struct { uint32_t tag; tap_event_t ev; } qslot_t;

#define SLOT_SIZE      ((sizeof(qslot_t) + 3u) & ~3u)
#define SLOTS_PER_SECT ((SECT_SIZE - SECT_HDR) / SLOT_SIZE)

static const esp_partition_t *s_part;
static uint8_t  *s_buf;        // one sector, reused
static size_t    s_nsect;
static size_t    s_head;       // sector currently being filled
static size_t    s_tail;       // oldest sector still holding data
static size_t    s_widx;       // next free slot in the head sector
static uint32_t  s_seq;        // sequence number of the head sector
static size_t    s_pending;

static inline size_t slot_off(size_t sect, size_t idx)
{
    return sect * SECT_SIZE + SECT_HDR + idx * SLOT_SIZE;
}

static bool read_hdr(size_t sect, uint32_t *seq)
{
    uint32_t h[2];
    if (esp_partition_read(s_part, sect * SECT_SIZE, h, sizeof(h)) != ESP_OK)
        return false;
    if (h[0] != SECT_MAGIC) return false;
    *seq = h[1];
    return true;
}

static esp_err_t open_sector(size_t sect, uint32_t seq)
{
    esp_err_t err = esp_partition_erase_range(s_part, sect * SECT_SIZE, SECT_SIZE);
    if (err != ESP_OK) return err;
    uint32_t h[2] = { SECT_MAGIC, seq };
    return esp_partition_write(s_part, sect * SECT_SIZE, h, sizeof(h));
}

// How many pending records a sector holds, and where its first free slot is.
static void scan_sector(size_t sect, size_t *pending, size_t *first_free)
{
    *pending = 0;
    *first_free = SLOTS_PER_SECT;
    if (esp_partition_read(s_part, sect * SECT_SIZE, s_buf, SECT_SIZE) != ESP_OK)
        return;
    for (size_t i = 0; i < SLOTS_PER_SECT; i++) {
        uint32_t tag;
        memcpy(&tag, s_buf + SECT_HDR + i * SLOT_SIZE, 4);
        if (tag == REC_EMPTY) {
            if (*first_free == SLOTS_PER_SECT) *first_free = i;
            break;                  // slots are filled in order
        }
        if (tag == REC_PENDING) (*pending)++;
    }
}

esp_err_t slam_queue_init(void)
{
    s_part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, 0x40, "evtlog");
    if (!s_part) {
        ESP_LOGE(TAG, "evtlog partition missing");
        return ESP_ERR_NOT_FOUND;
    }
    s_buf = malloc(SECT_SIZE);
    if (!s_buf) return ESP_ERR_NO_MEM;

    s_nsect = s_part->size / SECT_SIZE;

    uint32_t best = 0, worst = 0xFFFFFFFFu;
    int head = -1, tail = -1;
    for (size_t i = 0; i < s_nsect; i++) {
        uint32_t seq;
        if (!read_hdr(i, &seq)) continue;
        if (head < 0 || seq > best)  { best = seq;  head = (int)i; }
        if (tail < 0 || seq < worst) { worst = seq; tail = (int)i; }
    }

    if (head < 0) {
        ESP_LOGI(TAG, "empty log, formatting sector 0");
        esp_err_t err = open_sector(0, 1);
        if (err != ESP_OK) return err;
        s_head = s_tail = 0;
        s_seq = 1;
        s_widx = 0;
        s_pending = 0;
    } else {
        s_head = (size_t)head;
        s_tail = (size_t)tail;
        s_seq  = best;
        size_t pend, freeidx;
        scan_sector(s_head, &pend, &freeidx);
        s_widx = freeidx;
        s_pending = 0;
        for (size_t i = 0; i < s_nsect; i++) {
            uint32_t seq;
            if (!read_hdr(i, &seq)) continue;
            size_t p, f;
            scan_sector(i, &p, &f);
            s_pending += p;
        }
    }

    ESP_LOGI(TAG, "%u sectors, %u slots each, capacity %u records",
             (unsigned)s_nsect, (unsigned)SLOTS_PER_SECT,
             (unsigned)(s_nsect * SLOTS_PER_SECT));
    ESP_LOGI(TAG, "head=%u slot=%u tail=%u pending=%u",
             (unsigned)s_head, (unsigned)s_widx,
             (unsigned)s_tail, (unsigned)s_pending);
    return ESP_OK;
}

esp_err_t slam_queue_push(const tap_event_t *ev)
{
    if (s_widx >= SLOTS_PER_SECT) {
        size_t next = (s_head + 1) % s_nsect;
        if (next == s_tail && s_nsect > 1) {
            size_t p, f;
            scan_sector(next, &p, &f);
            if (p) {
                ESP_LOGW(TAG, "log full, discarding %u oldest records",
                         (unsigned)p);
                s_pending -= p;
            }
            s_tail = (s_tail + 1) % s_nsect;
        }
        esp_err_t err = open_sector(next, ++s_seq);
        if (err != ESP_OK) return err;
        s_head = next;
        s_widx = 0;
    }

    qslot_t slot = { .tag = REC_PENDING, .ev = *ev };
    esp_err_t err = esp_partition_write(s_part, slot_off(s_head, s_widx),
                                        &slot, SLOT_SIZE);
    if (err != ESP_OK) {
        // With write verification on, a lost write is reported here. The
        // slot may hold part of the record, so never reuse it: mark it
        // spent (best effort) and let a retry use the next one.
        const uint32_t spent = REC_SENT;
        esp_partition_write(s_part, slot_off(s_head, s_widx), &spent, 4);
        s_widx++;
        ESP_LOGW(TAG, "slot write failed: %s", esp_err_to_name(err));
        return err;
    }
    s_widx++;
    s_pending++;
    return ESP_OK;
}

size_t slam_queue_depth(void) { return s_pending; }

esp_err_t slam_queue_peek(tap_event_t *out, size_t max, size_t *got)
{
    *got = 0;
    size_t sect = s_tail;
    for (size_t n = 0; n < s_nsect && *got < max; n++) {
        uint32_t seq;
        if (read_hdr(sect, &seq)) {
            if (esp_partition_read(s_part, sect * SECT_SIZE, s_buf, SECT_SIZE) == ESP_OK) {
                for (size_t i = 0; i < SLOTS_PER_SECT && *got < max; i++) {
                    qslot_t *s = (qslot_t *)(s_buf + SECT_HDR + i * SLOT_SIZE);
                    if (s->tag == REC_EMPTY) break;
                    if (s->tag == REC_PENDING) out[(*got)++] = s->ev;
                }
            }
        }
        if (sect == s_head) break;
        sect = (sect + 1) % s_nsect;
    }
    return ESP_OK;
}

// Marks the oldest count records as uploaded by zeroing their tag.
// No erase, no rewrite - flash allows ones to become zeros in place.
esp_err_t slam_queue_drop(size_t count)
{
    const uint32_t sent = REC_SENT;
    size_t sect = s_tail;
    for (size_t n = 0; n < s_nsect && count; n++) {
        uint32_t seq;
        if (read_hdr(sect, &seq) &&
            esp_partition_read(s_part, sect * SECT_SIZE, s_buf, SECT_SIZE) == ESP_OK) {
            for (size_t i = 0; i < SLOTS_PER_SECT && count; i++) {
                uint32_t tag;
                memcpy(&tag, s_buf + SECT_HDR + i * SLOT_SIZE, 4);
                if (tag == REC_EMPTY) break;
                if (tag != REC_PENDING) continue;
                if (esp_partition_write(s_part, slot_off(sect, i), &sent, 4) == ESP_OK) {
                    count--;
                    if (s_pending) s_pending--;
                }
            }
        }
        if (sect == s_head) break;
        sect = (sect + 1) % s_nsect;
    }

    // Retire fully uploaded sectors behind the head.
    while (s_tail != s_head) {
        size_t p, f;
        scan_sector(s_tail, &p, &f);
        if (p) break;
        s_tail = (s_tail + 1) % s_nsect;
    }
    return ESP_OK;
}
