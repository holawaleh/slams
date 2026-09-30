#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "esp_log.h"
#include "esp_littlefs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "slam_store.h"

static const char *TAG = "store";

#define MOUNT_POINT   "/slam"
#define NAMES_PATH    MOUNT_POINT "/names.bin"
#define NAMES_TMP     MOUNT_POINT "/names.tmp"
#define DIR_PATH      MOUNT_POINT "/dir.bin"
#define ROSTER_PATH   MOUNT_POINT "/roster.bin"
#define MAX_STUDENTS  4096

static dir_entry_t    *s_dir;
static size_t          s_dir_count;
static uint32_t        s_dir_version;
// Names live in a file, one 16-byte record per directory entry and in
// the same order, so thousands of names cost no RAM. Only valid while
// the in-memory directory is in that same order.
static bool            s_names_ok;
// The network task replaces the directory while the card task reads it.
static SemaphoreHandle_t s_dir_lock;

static roster_entry_t *s_roster;
static size_t          s_roster_count;
static session_t       s_session;

static uint8_t        *s_present;         // one bit per student id
// Whether the server has this reader in a venue. A reader that is not
// placed never has a lecture, and should say why rather than
// "No lecture now". Assumed placed until a check-in says otherwise.
static bool            s_placed = true;

void slam_set_placed(bool placed) { s_placed = placed; }
static uint32_t        s_next_client_id = 1;

// ---------------- directory ----------------

static int dir_cmp(const void *a, const void *b)
{
    const dir_entry_t *x = a, *y = b;
    uint8_t n = (x->len < y->len) ? x->len : y->len;
    int c = memcmp(x->uid, y->uid, n);
    if (c != 0) return c;
    return (int)x->len - (int)y->len;
}

static void dir_lock(void)   { if (s_dir_lock) xSemaphoreTake(s_dir_lock, portMAX_DELAY); }
static void dir_unlock(void) { if (s_dir_lock) xSemaphoreGive(s_dir_lock); }

const char *slam_dir_names_tmp(void) { return NAMES_TMP; }

// ---- kept on flash, so a restart without network still knows every
// card and the current lecture. Without this, every student tapping
// after an offline restart saw "Unknown card".

typedef struct { uint32_t magic, version, count, names_ok; } dir_file_hdr_t;
typedef struct { uint32_t magic, count; session_t session; } roster_file_hdr_t;
#define DIR_FILE_MAGIC     0x31524453u    // "SDR1"
#define ROSTER_FILE_MAGIC  0x31535253u    // "SRS1"

// Caller holds the directory lock.
static void dir_save(void)
{
    FILE *f = fopen(DIR_PATH ".tmp", "wb");
    if (!f) return;
    dir_file_hdr_t h = { DIR_FILE_MAGIC, s_dir_version, (uint32_t)s_dir_count, s_names_ok };
    bool ok = fwrite(&h, sizeof(h), 1, f) == 1 &&
              (!s_dir_count ||
               fwrite(s_dir, sizeof(dir_entry_t), s_dir_count, f) == s_dir_count);
    fclose(f);
    remove(DIR_PATH);
    if (!ok || rename(DIR_PATH ".tmp", DIR_PATH) != 0) {
        remove(DIR_PATH ".tmp");
        ESP_LOGW(TAG, "could not save the directory to flash");
    }
}

static void dir_restore(void)
{
    FILE *f = fopen(DIR_PATH, "rb");
    if (!f) return;
    dir_file_hdr_t h;
    if (fread(&h, sizeof(h), 1, f) == 1 && h.magic == DIR_FILE_MAGIC && h.count <= 20000) {
        dir_entry_t *buf = malloc(h.count ? h.count * sizeof(dir_entry_t) : 1);
        if (buf && fread(buf, sizeof(dir_entry_t), h.count, f) == h.count) {
            s_dir = buf;
            s_dir_count = h.count;
            s_dir_version = h.version;
            FILE *n = fopen(NAMES_PATH, "rb");
            s_names_ok = h.names_ok && n;
            if (n) fclose(n);
            ESP_LOGI(TAG, "directory from flash: %u cards%s", (unsigned)h.count,
                     s_names_ok ? ", with names" : "");
        } else {
            free(buf);
        }
    }
    fclose(f);
}

static void roster_save(void)
{
    FILE *f = fopen(ROSTER_PATH ".tmp", "wb");
    if (!f) return;
    roster_file_hdr_t h = { ROSTER_FILE_MAGIC, (uint32_t)s_roster_count, s_session };
    bool ok = fwrite(&h, sizeof(h), 1, f) == 1 &&
              (!s_roster_count ||
               fwrite(s_roster, sizeof(roster_entry_t), s_roster_count, f) == s_roster_count);
    fclose(f);
    remove(ROSTER_PATH);
    if (!ok || rename(ROSTER_PATH ".tmp", ROSTER_PATH) != 0) remove(ROSTER_PATH ".tmp");
}

static void roster_restore(void)
{
    FILE *f = fopen(ROSTER_PATH, "rb");
    if (!f) return;
    roster_file_hdr_t h;
    if (fread(&h, sizeof(h), 1, f) == 1 && h.magic == ROSTER_FILE_MAGIC && h.count <= MAX_STUDENTS) {
        roster_entry_t *buf = malloc(h.count ? h.count * sizeof(roster_entry_t) : 1);
        if (buf && fread(buf, sizeof(roster_entry_t), h.count, f) == h.count) {
            s_roster = buf;
            s_roster_count = h.count;
            s_session = h.session;
            // The lecture may be long over by now; slam_decide checks the
            // start and end once the clock is known, and the server
            // judges every tap anyway.
            ESP_LOGI(TAG, "roster from flash: session %u (%s), %u students",
                     (unsigned)h.session.session_id, h.session.course, (unsigned)h.count);
        } else {
            free(buf);
        }
    }
    fclose(f);
}

// names_tmp: a file of 16-byte names in the same order as entries, or
// NULL when there are none. Swapped in together with the entries.
esp_err_t slam_dir_install(const dir_entry_t *entries, size_t count,
                           uint32_t version, const char *names_tmp)
{
    if (count > 20000) return ESP_ERR_INVALID_SIZE;

    // The server sends the list sorted. Keep its order so entry i and
    // name i stay together; only sort (and give up on names) if not.
    bool sorted = true;
    for (size_t i = 1; i < count && sorted; i++)
        sorted = dir_cmp(&entries[i - 1], &entries[i]) < 0;

    dir_lock();
    dir_entry_t *buf = realloc(s_dir, count * sizeof(dir_entry_t));
    if (!buf && count) { dir_unlock(); return ESP_ERR_NO_MEM; }
    s_dir = buf;
    if (count) memcpy(s_dir, entries, count * sizeof(dir_entry_t));
    if (!sorted) qsort(s_dir, count, sizeof(dir_entry_t), dir_cmp);
    s_dir_count = count;
    s_dir_version = version;

    remove(NAMES_PATH);
    s_names_ok = names_tmp && sorted && rename(names_tmp, NAMES_PATH) == 0;
    dir_save();
    dir_unlock();

    ESP_LOGI(TAG, "directory: %u cards, version %u, %u bytes%s",
             (unsigned)count, (unsigned)version,
             (unsigned)(count * sizeof(dir_entry_t)),
             s_names_ok ? ", with names" : "");
    return ESP_OK;
}

esp_err_t slam_dir_load(const dir_entry_t *entries, size_t count, uint32_t version)
{
    return slam_dir_install(entries, count, version, NULL);
}

// The holder's name for entry e, from the names file. Caller holds the
// directory lock. A few milliseconds: fine next to a 5 ms card read.
static bool dir_name(const dir_entry_t *e, char *out)
{
    out[0] = 0;
    if (!s_names_ok || !e) return false;
    FILE *f = fopen(NAMES_PATH, "rb");
    if (!f) return false;
    size_t idx = (size_t)(e - s_dir);
    bool ok = fseek(f, (long)(idx * SLAM_NAME_LEN), SEEK_SET) == 0 &&
              fread(out, 1, SLAM_NAME_LEN, f) == SLAM_NAME_LEN;
    fclose(f);
    out[ok ? SLAM_NAME_LEN : 0] = 0;
    return ok && out[0];
}

const dir_entry_t *slam_dir_find(const slam_uid_t *uid)
{
    size_t lo = 0, hi = s_dir_count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        const dir_entry_t *e = &s_dir[mid];
        uint8_t n = (e->len < uid->len) ? e->len : uid->len;
        int c = memcmp(e->uid, uid->bytes, n);
        if (c == 0) c = (int)e->len - (int)uid->len;
        if (c == 0) return e;
        if (c < 0) lo = mid + 1; else hi = mid;
    }
    return NULL;
}

size_t   slam_dir_count(void)   { return s_dir_count; }
uint32_t slam_dir_version(void) { return s_dir_version; }

// ---------------- roster ----------------

static int roster_cmp(const void *a, const void *b)
{
    return (int)((const roster_entry_t *)a)->student_id
         - (int)((const roster_entry_t *)b)->student_id;
}

esp_err_t slam_roster_load(const session_t *s, const roster_entry_t *entries, size_t count)
{
    roster_entry_t *buf = realloc(s_roster, count * sizeof(roster_entry_t));
    if (!buf && count) return ESP_ERR_NO_MEM;
    s_roster = buf;
    if (count) memcpy(s_roster, entries, count * sizeof(roster_entry_t));
    qsort(s_roster, count, sizeof(roster_entry_t), roster_cmp);
    s_roster_count = count;
    s_session = *s;
    slam_present_clear_all();
    roster_save();
    ESP_LOGI(TAG, "session %u (%s): %u students",
             (unsigned)s->session_id, s->course, (unsigned)count);
    return ESP_OK;
}

const roster_entry_t *slam_roster_find(uint16_t student_id)
{
    size_t lo = 0, hi = s_roster_count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (s_roster[mid].student_id == student_id) return &s_roster[mid];
        if (s_roster[mid].student_id < student_id) lo = mid + 1; else hi = mid;
    }
    return NULL;
}

const session_t *slam_session(void)   { return &s_session; }
size_t slam_roster_count(void)        { return s_roster_count; }

// ---------------- present bitmap ----------------

bool slam_present_get(uint16_t id)
{
    if (!s_present || id >= MAX_STUDENTS) return false;
    return (s_present[id >> 3] >> (id & 7)) & 1;
}

void slam_present_set(uint16_t id)
{
    if (!s_present || id >= MAX_STUDENTS) return;
    s_present[id >> 3] |= (uint8_t)(1 << (id & 7));
}

void slam_present_clear_all(void)
{
    if (s_present) memset(s_present, 0, MAX_STUDENTS / 8);
}

// ---------------- the decision ----------------

tap_outcome_t slam_decide(const slam_uid_t *uid, tap_event_t *ev,
                          char *l1, char *l2)
{
    memset(ev, 0, sizeof(*ev));
    ev->uid       = *uid;
    ev->ts_utc    = slam_now_utc();
    ev->uptime_ms = slam_uptime_ms();
    ev->boot_id   = slam_boot_id();
    ev->time_conf = (uint8_t)slam_time_confidence();
    ev->client_id = s_next_client_id++;

    // Copy what we need out of the directory under its lock; the network
    // task may replace it the moment we let go.
    dir_entry_t found;
    char name[SLAM_NAME_LEN + 1] = "";
    dir_lock();
    const dir_entry_t *hit = slam_dir_find(uid);
    if (hit) {
        found = *hit;
        dir_name(hit, name);
    }
    dir_unlock();
    const dir_entry_t *card = hit ? &found : NULL;

    if (!card) {
        char hex[SLAM_UID_MAX_LEN * 2 + 1];
        slam_uid_to_hex(uid, hex, sizeof(hex));
        // A 10 byte UID is 20 hex characters and the line holds 16, so
        // show the first 14 and mark that it was cut.
        snprintf(l1, SLAM_NAME_LEN + 1, "Unknown card");
        if (strlen(hex) <= SLAM_NAME_LEN) {
            snprintf(l2, SLAM_NAME_LEN + 1, "%.16s", hex);
        } else {
            snprintf(l2, SLAM_NAME_LEN + 1, "%.14s..", hex);
        }
        ev->outcome = TAP_UNKNOWN_CARD;
        return TAP_UNKNOWN_CARD;
    }

    ev->student_id = card->student_id;

    // Who this is, for the top line: the directory's name, else the
    // roster's, else the student number as a last resort.
    const roster_entry_t *r = slam_roster_find(card->student_id);
    if (!name[0] && r) snprintf(name, sizeof(name), "%.16s", r->name);
    if (!name[0]) snprintf(name, sizeof(name), "ID %u",
                           (unsigned)(card->student_id % 100000));

    if (card->flags & DIR_FLAG_ADMIN) {
        snprintf(l1, SLAM_NAME_LEN + 1, "%.16s", name);
        snprintf(l2, SLAM_NAME_LEN + 1, "Admin card");
        ev->outcome = TAP_ADMIN;
        return TAP_ADMIN;
    }

    if (!s_session.active) {
        snprintf(l1, SLAM_NAME_LEN + 1, "%.16s", name);
        snprintf(l2, SLAM_NAME_LEN + 1, s_placed ? "No lecture now" : "No venue set");
        ev->outcome = TAP_NO_SESSION;
        return TAP_NO_SESSION;
    }

    ev->session_id = s_session.session_id;

    if (!r) {
        snprintf(l1, SLAM_NAME_LEN + 1, "%.16s", name);
        snprintf(l2, SLAM_NAME_LEN + 1, "Not in %.9s", s_session.course);
        ev->outcome = TAP_NOT_ENROLLED;
        return TAP_NOT_ENROLLED;
    }

    // The roster arrives before the lecture starts and stays a little
    // after it ends, but a tap only counts between start and end. The
    // server makes the real decision; this just keeps the beep honest.
    // Without a clock we cannot tell, so accept and let the server judge.
    int64_t now = ev->ts_utc;
    bool clock_known = (ev->time_conf != TIME_UNKNOWN);
    if (clock_known && (now < s_session.starts_utc || now > s_session.ends_utc)) {
        snprintf(l1, SLAM_NAME_LEN + 1, "%.16s", name);
        snprintf(l2, SLAM_NAME_LEN + 1,
                 now < s_session.starts_utc ? "Not started yet" : "Lecture ended");
        ev->outcome = TAP_NO_SESSION;
        return TAP_NO_SESSION;
    }

    if (slam_present_get(card->student_id)) {
        snprintf(l1, SLAM_NAME_LEN + 1, "%.16s", name);
        snprintf(l2, SLAM_NAME_LEN + 1, "already marked");
        ev->outcome = TAP_DUPLICATE;
        return TAP_DUPLICATE;      // caller must not queue this
    }

    bool late = clock_known &&
                (now > s_session.starts_utc + (int64_t)s_session.grace_minutes * 60);

    slam_present_set(card->student_id);
    snprintf(l1, SLAM_NAME_LEN + 1, "%.16s", name);
    snprintf(l2, SLAM_NAME_LEN + 1, late ? "LATE %.10s" : "OK %.12s", s_session.course);
    ev->outcome = late ? TAP_LATE : TAP_PRESENT;
    return (tap_outcome_t)ev->outcome;
}

// ---------------- init ----------------

esp_err_t slam_store_init(void)
{
    esp_vfs_littlefs_conf_t conf = {
        .base_path = MOUNT_POINT,
        .partition_label = "storage",
        .format_if_mount_failed = true,
        .dont_mount = false,
    };
    esp_err_t err = esp_vfs_littlefs_register(&conf);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "littlefs mount failed: %s", esp_err_to_name(err));
        return err;
    }

    size_t total = 0, used = 0;
    esp_littlefs_info(conf.partition_label, &total, &used);
    ESP_LOGI(TAG, "littlefs %u/%u bytes used", (unsigned)used, (unsigned)total);

    s_dir_lock = xSemaphoreCreateMutex();
    dir_restore();
    roster_restore();
    s_present = calloc(MAX_STUDENTS / 8, 1);
    if (!s_present) return ESP_ERR_NO_MEM;

    esp_err_t qerr = slam_queue_init();
    if (qerr != ESP_OK) return qerr;
    ESP_LOGI(TAG, "queue holds %u events from before reboot",
             (unsigned)slam_queue_depth());
    return ESP_OK;
}






