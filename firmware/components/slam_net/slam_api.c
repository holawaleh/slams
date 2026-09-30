#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "cJSON.h"
#include "slam_cfg.h"
#include "slam_api.h"

static const char *TAG = "api";

#define RESP_MAX     16384
#define HTTP_TIMEOUT 10000

// One handle, reused for every request. A TLS handshake costs 1-3
// seconds and about 40 KB of heap on this chip, so tearing the
// connection down between calls is the single most wasteful thing
// the old firmware did.
static esp_http_client_handle_t s_client;
static SemaphoreHandle_t        s_lock;
static char                    *s_resp;
static size_t                   s_resp_len;
static int64_t                  s_last_rtt_ms;

static esp_err_t on_event(esp_http_client_event_t *evt)
{
    if (evt->event_id == HTTP_EVENT_ON_DATA) {
        if (s_resp_len + evt->data_len < RESP_MAX) {
            memcpy(s_resp + s_resp_len, evt->data, evt->data_len);
            s_resp_len += evt->data_len;
            s_resp[s_resp_len] = 0;
        } else {
            ESP_LOGW(TAG, "response too large, truncated");
        }
    }
    return ESP_OK;
}

esp_err_t slam_api_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    s_resp = malloc(RESP_MAX);
    if (!s_resp || !s_lock) return ESP_ERR_NO_MEM;

    esp_http_client_config_t cfg = {
        .url = slam_cfg_base_url(),
        .event_handler = on_event,
        .timeout_ms = HTTP_TIMEOUT,
        .keep_alive_enable = true,
        .buffer_size = 2048,
        .buffer_size_tx = 1024,
        .crt_bundle_attach = esp_crt_bundle_attach,
    };
    s_client = esp_http_client_init(&cfg);
    if (!s_client) return ESP_FAIL;

    ESP_LOGI(TAG, "client ready for %s", slam_cfg_base_url());
    return ESP_OK;
}

// Performs one request. Returns the HTTP status, or -1 on failure.
static int request(const char *path, esp_http_client_method_t method,
                   const char *body)
{
    char url[CFG_URL_LEN + 64];
    snprintf(url, sizeof(url), "%s%s", slam_cfg_base_url(), path);

    s_resp_len = 0;
    s_resp[0] = 0;

    esp_http_client_set_url(s_client, url);
    esp_http_client_set_method(s_client, method);

    if (slam_cfg_ready()) {
        char auth[CFG_TOKEN_LEN + 16];
        snprintf(auth, sizeof(auth), "Device %s", slam_cfg_token());
        esp_http_client_set_header(s_client, "Authorization", auth);
    } else {
        esp_http_client_delete_header(s_client, "Authorization");
    }
    esp_http_client_set_header(s_client, "Content-Type", "application/json");
    // The server only accepts this reader's token from this reader.
    esp_http_client_set_header(s_client, "X-Device-Id", slam_hw_id());

    if (body) {
        esp_http_client_set_post_field(s_client, body, strlen(body));
    } else {
        esp_http_client_set_post_field(s_client, NULL, 0);
    }

    int64_t t0 = slam_uptime_ms();
    esp_err_t err = esp_http_client_perform(s_client);
    if (err != ESP_OK) {
        // The kept-alive connection can die underneath us - most often
        // when WiFi reconnects - and the next request then fails writing
        // to it. Drop it and try once more on a fresh connection, rather
        // than waiting a minute for the next attempt.
        ESP_LOGW(TAG, "%s failed: %s, retrying on a new connection",
                 path, esp_err_to_name(err));
        esp_http_client_close(s_client);
        s_resp_len = 0;
        s_resp[0] = 0;
        t0 = slam_uptime_ms();
        err = esp_http_client_perform(s_client);
    }
    s_last_rtt_ms = slam_uptime_ms() - t0;
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "%s failed: %s", path, esp_err_to_name(err));
        esp_http_client_close(s_client);
        return -1;
    }
    return esp_http_client_get_status_code(s_client);
}

// The server's time as of now, from a reply that was just received.
// The server stamped it somewhere during the round trip; half the round
// trip is the best estimate of how long ago that was. Falls back to the
// whole-second field for a server that predates server_utc_ms.
static int64_t reply_time_ms(cJSON *root)
{
    cJSON *v = cJSON_GetObjectItem(root, "server_utc_ms");
    if (v && cJSON_IsNumber(v))
        return (int64_t)cJSON_GetNumberValue(v) + s_last_rtt_ms / 2;
    v = cJSON_GetObjectItem(root, "server_utc");
    if (v && cJSON_IsNumber(v))
        return (int64_t)cJSON_GetNumberValue(v) * 1000;
    return 0;
}

// ---------------- heartbeat ----------------

esp_err_t slam_api_hello(hello_result_t *out, size_t queue_depth)
{
    if (!slam_cfg_ready()) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_lock, portMAX_DELAY);

    char body[128];
    snprintf(body, sizeof(body),
             "{\"firmware\":\"" SLAM_FW_VERSION "\",\"queue_depth\":%u}",
             (unsigned)queue_depth);

    int status = request("/api/device/hello/", HTTP_METHOD_POST, body);
    esp_err_t result = ESP_FAIL;

    if (status == 200) {
        cJSON *root = cJSON_Parse(s_resp);
        if (root) {
            memset(out, 0, sizeof(*out));
            cJSON *v;
            out->server_utc_ms = reply_time_ms(root);
            if ((v = cJSON_GetObjectItem(root, "directory_version")))
                out->directory_version = (uint32_t)cJSON_GetNumberValue(v);
            if ((v = cJSON_GetObjectItem(root, "bundle_version")))
                out->bundle_version = (uint32_t)cJSON_GetNumberValue(v);
            if ((v = cJSON_GetObjectItem(root, "enroll_mode")))
                out->enroll_mode = cJSON_IsTrue(v);
            if ((v = cJSON_GetObjectItem(root, "firmware_latest")) &&
                cJSON_IsString(v))
                strlcpy(out->firmware_latest, v->valuestring,
                        sizeof(out->firmware_latest));
            v = cJSON_GetObjectItem(root, "session");
            out->has_session = (v && !cJSON_IsNull(v));
            v = cJSON_GetObjectItem(root, "venue");
            out->placed = (v && cJSON_IsString(v));
            cJSON_Delete(root);
            result = ESP_OK;
        }
    } else if (status > 0) {
        ESP_LOGW(TAG, "hello returned %d: %.120s", status, s_resp);
        if (status == 401 || status == 403) result = ESP_ERR_INVALID_STATE;
    }

    xSemaphoreGive(s_lock);
    return result;
}

// ---------------- pairing ----------------

esp_err_t slam_api_announce(announce_result_t *out, const char *local_ip)
{
    memset(out, 0, sizeof(*out));
    xSemaphoreTake(s_lock, portMAX_DELAY);

    char body[192];
    snprintf(body, sizeof(body),
             "{\"secret\":\"%s\",\"firmware\":\"" SLAM_FW_VERSION "\","
             "\"local_ip\":\"%s\"}",
             slam_pair_secret(), local_ip ? local_ip : "");

    int status = request("/api/device/announce/", HTTP_METHOD_POST, body);
    esp_err_t result = ESP_FAIL;

    if (status == 200) {
        cJSON *root = cJSON_Parse(s_resp);
        if (root) {
            cJSON *st = cJSON_GetObjectItem(root, "status");
            cJSON *v;
            const char *s = cJSON_IsString(st) ? st->valuestring : "";
            if (strcmp(s, "waiting") == 0) {
                out->state = PAIR_WAITING;
                if ((v = cJSON_GetObjectItem(root, "code")) && cJSON_IsString(v))
                    strlcpy(out->code, v->valuestring, sizeof(out->code));
            } else if (strcmp(s, "paired") == 0) {
                out->state = PAIR_DONE;
                if ((v = cJSON_GetObjectItem(root, "token")) && cJSON_IsString(v))
                    strlcpy(out->token, v->valuestring, sizeof(out->token));
                if ((v = cJSON_GetObjectItem(root, "device")) && cJSON_IsString(v))
                    strlcpy(out->name, v->valuestring, sizeof(out->name));
            } else if (strcmp(s, "registered") == 0) {
                out->state = PAIR_TAKEN;
            }
            out->server_utc_ms = reply_time_ms(root);
            cJSON_Delete(root);
            result = out->state ? ESP_OK : ESP_FAIL;
        }
    } else if (status > 0) {
        ESP_LOGW(TAG, "announce returned %d: %.120s", status, s_resp);
    }

    xSemaphoreGive(s_lock);
    return result;
}

// ---------------- bundle ----------------

esp_err_t slam_api_fetch_bundle(uint32_t have_version)
{
    if (!slam_cfg_ready()) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_lock, portMAX_DELAY);

    char path[64];
    snprintf(path, sizeof(path), "/api/device/bundle/?version=%u",
             (unsigned)have_version);

    int status = request(path, HTTP_METHOD_GET, NULL);
    esp_err_t result = ESP_FAIL;

    if (status == 304) {
        result = ESP_ERR_NOT_FOUND;         // nothing changed, normal
    } else if (status == 200) {
        cJSON *root = cJSON_Parse(s_resp);
        if (root) {
            cJSON *sess = cJSON_GetObjectItem(root, "session");
            cJSON *list = cJSON_GetObjectItem(root, "roster");

            if (sess && !cJSON_IsNull(sess)) {
                session_t s = {0};
                cJSON *v;
                if ((v = cJSON_GetObjectItem(sess, "id")))
                    s.session_id = (uint32_t)cJSON_GetNumberValue(v);
                if ((v = cJSON_GetObjectItem(sess, "course")) &&
                    cJSON_IsString(v))
                    strlcpy(s.course, v->valuestring, sizeof(s.course));
                if ((v = cJSON_GetObjectItem(sess, "starts_utc")))
                    s.starts_utc = (int64_t)cJSON_GetNumberValue(v);
                if ((v = cJSON_GetObjectItem(sess, "ends_utc")))
                    s.ends_utc = (int64_t)cJSON_GetNumberValue(v);
                if ((v = cJSON_GetObjectItem(sess, "grace_minutes")))
                    s.grace_minutes = (uint16_t)cJSON_GetNumberValue(v);
                s.active = true;

                int n = cJSON_GetArraySize(list);
                roster_entry_t *rows = calloc(n ? n : 1, sizeof(roster_entry_t));
                if (rows) {
                    int k = 0;
                    cJSON *item;
                    cJSON_ArrayForEach(item, list) {
                        cJSON *id = cJSON_GetObjectItem(item, "id");
                        cJSON *nm = cJSON_GetObjectItem(item, "name");
                        if (!id) continue;
                        rows[k].student_id =
                            (uint16_t)cJSON_GetNumberValue(id);
                        if (nm && cJSON_IsString(nm))
                            strncpy(rows[k].name, nm->valuestring,
                                    SLAM_NAME_LEN);
                        k++;
                    }
                    slam_roster_load(&s, rows, k);
                    free(rows);
                    ESP_LOGI(TAG, "bundle: %s, %d students", s.course, k);
                    result = ESP_OK;
                }
            } else {
                session_t none = {0};
                slam_roster_load(&none, NULL, 0);
                ESP_LOGI(TAG, "no lecture scheduled here now");
                result = ESP_OK;
            }
            cJSON_Delete(root);
        }
    } else if (status > 0) {
        ESP_LOGW(TAG, "bundle returned %d", status);
    }

    xSemaphoreGive(s_lock);
    return result;
}

// ---------------- directory ----------------

// Layout 2 from the server: the card list with each holder's name, in
// pages so a large school fits the 16 KB receive buffer.
//   header  'SLM2' | version u32 | total u32 | offset u32 | count u32
//   record  uid[10] | len u8 | student u16 | flags u8 | name[16]
#define DIR2_HDR_LEN  20
#define DIR2_REC_LEN  30
#define DIR2_PAGE     400

esp_err_t slam_api_fetch_directory(uint32_t have_version)
{
    if (!slam_cfg_ready()) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_lock, portMAX_DELAY);

    esp_err_t result = ESP_FAIL;
    dir_entry_t *rows = NULL;
    FILE *names = NULL;
    uint32_t version = 0, total = 0, offset = 0;
    remove(slam_dir_names_tmp());       // never mix in a stale half-download

    for (;;) {
        char path[112];
        snprintf(path, sizeof(path),
                 "/api/device/directory/?layout=2&version=%u&offset=%u&limit=%u",
                 (unsigned)have_version, (unsigned)offset, DIR2_PAGE);
        int status = request(path, HTTP_METHOD_GET, NULL);

        if (status == 304 && offset == 0) { result = ESP_ERR_NOT_FOUND; break; }
        if (status != 200 || s_resp_len < DIR2_HDR_LEN) {
            if (status > 0) ESP_LOGW(TAG, "directory returned %d", status);
            break;
        }
        const uint8_t *p = (const uint8_t *)s_resp;
        if (offset == 0 && memcmp(p, "SLMD", 4) == 0 && s_resp_len >= 12) {
            // A server that predates layout 2 ignores ?layout= and sends
            // the old list in one piece: uid[10] len student flags, no
            // names. Use it rather than go without a directory.
            uint32_t v1, count1;
            memcpy(&v1, p + 4, 4);
            memcpy(&count1, p + 8, 4);
            if (12 + (size_t)count1 * 14 > s_resp_len) { ESP_LOGE(TAG, "directory short"); break; }
            rows = calloc(count1 ? count1 : 1, sizeof(dir_entry_t));
            if (!rows) break;
            for (uint32_t i = 0; i < count1; i++) {
                const uint8_t *r = p + 12 + i * 14;
                memcpy(rows[i].uid, r, 10);
                rows[i].len = r[10];
                memcpy(&rows[i].student_id, r + 11, 2);
                rows[i].flags = r[13];
            }
            result = slam_dir_install(rows, count1, v1, NULL);
            break;
        }
        if (memcmp(p, "SLM2", 4) != 0) { ESP_LOGE(TAG, "directory header wrong"); break; }
        uint32_t v, t, o, n;
        memcpy(&v, p + 4, 4);
        memcpy(&t, p + 8, 4);
        memcpy(&o, p + 12, 4);
        memcpy(&n, p + 16, 4);
        if (DIR2_HDR_LEN + (size_t)n * DIR2_REC_LEN > s_resp_len || o != offset) {
            ESP_LOGE(TAG, "directory page short or out of order");
            break;
        }

        if (offset == 0) {
            version = v;
            total = t;
            rows = calloc(total ? total : 1, sizeof(dir_entry_t));
            names = fopen(slam_dir_names_tmp(), "wb");
            if (!rows) { ESP_LOGE(TAG, "no memory for %u cards", (unsigned)total); break; }
            if (!names) ESP_LOGW(TAG, "cannot store names; showing numbers");
        } else if (v != version || t != total) {
            // Changed on the server mid-download. Start again next time.
            ESP_LOGW(TAG, "directory changed while downloading");
            break;
        }

        for (uint32_t i = 0; i < n && offset + i < total; i++) {
            const uint8_t *r = p + DIR2_HDR_LEN + i * DIR2_REC_LEN;
            dir_entry_t *e = &rows[offset + i];
            memcpy(e->uid, r, 10);
            e->len = r[10];
            memcpy(&e->student_id, r + 11, 2);
            e->flags = r[13];
            if (names && fwrite(r + 14, 1, 16, names) != 16) {
                fclose(names);
                names = NULL;
                remove(slam_dir_names_tmp());
            }
        }
        offset += n;
        if (offset >= total || n == 0) {
            if (names) { fclose(names); names = NULL; }
            FILE *check = fopen(slam_dir_names_tmp(), "rb");
            bool have_names = check != NULL;
            if (check) fclose(check);
            result = slam_dir_install(rows, total, version,
                                      have_names ? slam_dir_names_tmp() : NULL);
            break;
        }
    }

    if (names) { fclose(names); remove(slam_dir_names_tmp()); }
    free(rows);
    xSemaphoreGive(s_lock);
    return result;
}

// ---------------- upload ----------------

static const char *outcome_json(uint8_t o)
{
    switch (o) {
        case TAP_UNKNOWN_CARD: return "unknown";
        case TAP_NO_SESSION:   return "no_session";
        case TAP_NOT_ENROLLED: return "not_enrolled";
        case TAP_PRESENT:      return "present";
        case TAP_LATE:         return "late";
        case TAP_ADMIN:        return "admin";
        default:               return "read_error";
    }
}

static const char *conf_json(uint8_t c)
{
    switch (c) {
        case TIME_SYNCED: return "synced";
        case TIME_DRIFT:  return "drift";
        default:          return "unknown";
    }
}

esp_err_t slam_api_upload(size_t max_records, size_t *uploaded)
{
    *uploaded = 0;
    if (!slam_cfg_ready()) return ESP_ERR_INVALID_STATE;
    if (slam_queue_depth() == 0) return ESP_OK;
    if (max_records > 25) max_records = 25;

    tap_event_t *batch = calloc(max_records, sizeof(tap_event_t));
    if (!batch) return ESP_ERR_NO_MEM;

    size_t got = 0;
    slam_queue_peek(batch, max_records, &got);
    if (got == 0) {
        ESP_LOGW(TAG, "queue says %u pending but peek found none",
                 (unsigned)slam_queue_depth());
        free(batch);
        return ESP_OK;
    }

    // Built by hand rather than with cJSON: about 200 bytes per record
    // instead of a tree of allocations we would immediately discard.
    size_t cap = 64 + got * 240;
    char *body = malloc(cap);
    if (!body) { free(batch); return ESP_ERR_NO_MEM; }

    size_t n = snprintf(body, cap, "{\"records\":[");
    char hex[SLAM_UID_MAX_LEN * 2 + 1];
    char age[32];
    uint32_t boot = slam_boot_id();
    int64_t now_up = slam_uptime_ms();

    for (size_t i = 0; i < got && n < cap; i++) {
        slam_uid_to_hex(&batch[i].uid, hex, sizeof(hex));

        // For a tap from this power-up, say how long ago it was on the
        // uptime counter. The server subtracts that from its own clock,
        // so the tap is timed correctly even if this device never knew
        // the time when it was made. Taps from before a reboot have no
        // usable uptime and rely on ts_utc instead.
        age[0] = 0;
        if (batch[i].boot_id == boot && batch[i].uptime_ms <= now_up) {
            snprintf(age, sizeof(age), ",\"age_ms\":%lld",
                     (long long)(now_up - batch[i].uptime_ms));
        }

        // Unique across reboots: the per-boot counter restarts at 1, so
        // on its own it would collide with taps from an earlier boot and
        // the server would silently discard the new ones.
        unsigned long long cid =
            ((unsigned long long)batch[i].boot_id << 32) | batch[i].client_id;

        n += snprintf(body + n, cap - n,
            "%s{\"client_id\":%llu,\"uid\":\"%s\",\"outcome\":\"%s\","
            "\"ts_utc\":%lld,\"time_conf\":\"%s\",\"session_id\":%u%s}",
            i ? "," : "",
            cid, hex,
            outcome_json(batch[i].outcome),
            (long long)batch[i].ts_utc,
            conf_json(batch[i].time_conf),
            (unsigned)batch[i].session_id, age);
    }
    if (n < cap) n += snprintf(body + n, cap - n, "]}");
    if (n >= cap) {
        // snprintf truncated: sending half a JSON document would be
        // rejected every time and block the queue forever.
        ESP_LOGE(TAG, "upload body overflow (%u of %u)",
                 (unsigned)n, (unsigned)cap);
        free(body);
        free(batch);
        return ESP_ERR_NO_MEM;
    }

    xSemaphoreTake(s_lock, portMAX_DELAY);
    int status = request("/api/device/attendance/", HTTP_METHOD_POST, body);
    esp_err_t result = ESP_FAIL;

    if (status == 200) {
        cJSON *root = cJSON_Parse(s_resp);
        if (root) {
            cJSON *acc = cJSON_GetObjectItem(root, "accepted");
            slam_set_time_ms(reply_time_ms(root));

            int accepted = acc ? (int)cJSON_GetNumberValue(acc) : 0;
            // The server saw them, so drop the whole batch. A replay is
            // harmless anyway thanks to the client id constraint.
            slam_queue_drop(got);
            *uploaded = got;
            ESP_LOGI(TAG, "uploaded %u records, %d accepted, %u left",
                     (unsigned)got, accepted, (unsigned)slam_queue_depth());
            cJSON_Delete(root);
            result = ESP_OK;
        }
    } else if (status > 0) {
        ESP_LOGW(TAG, "upload returned %d: %.120s", status, s_resp);
    }
    xSemaphoreGive(s_lock);

    free(body);
    free(batch);
    return result;
}

// ---------------- enrolment ----------------

esp_err_t slam_api_enroll(const slam_uid_t *uid)
{
    if (!slam_cfg_ready()) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_lock, portMAX_DELAY);

    char hex[SLAM_UID_MAX_LEN * 2 + 1];
    slam_uid_to_hex(uid, hex, sizeof(hex));
    char body[96];
    snprintf(body, sizeof(body), "{\"uid\":\"%s\",\"client_id\":0}", hex);

    int status = request("/api/device/enroll/", HTTP_METHOD_POST, body);
    esp_err_t result = (status == 200) ? ESP_OK : ESP_FAIL;
    if (status == 200) ESP_LOGI(TAG, "reported card %s", hex);

    xSemaphoreGive(s_lock);
    return result;
}
