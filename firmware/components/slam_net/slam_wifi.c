#include <string.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "slam_types.h"
#include "slam_wifi.h"

static const char *TAG = "wifi";

#define NVS_NS          "slamwifi"
#define NVS_KEY_COUNT   "count"
#define CONNECT_BIT     BIT0
#define FAIL_BIT        BIT1

static wifi_net_t        s_nets[WIFI_MAX_NETWORKS];
static int               s_count;
static int               s_current = -1;
static net_state_t       s_state = NET_BOOTING;
static EventGroupHandle_t s_events;
static esp_netif_t      *s_sta_netif;
static esp_netif_t      *s_ap_netif;
static bool              s_wifi_started;

static char s_ip[16]      = "0.0.0.0";
static char s_ap_ip[16]   = "0.0.0.0";
static char s_ap_ssid[WIFI_SSID_LEN];
static char s_ap_pass[16];

// Backoff so a dead network is not hammered. Your old firmware retried
// every 30 seconds forever, which is 2880 pointless attempts a day.
// Capped at a minute: a reader offline for 15 minutes after a short
// router hiccup misses most of a lecture's check-in window.
static const int RETRY_SECONDS[] = { 15, 30, 60 };
// Why the last attempt failed, from the disconnect event.
static volatile uint8_t s_last_reason;
static int     s_retry_step;
static int64_t s_next_retry_ms;

// ---------------- storage ----------------

static void load_networks(void)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) {
        ESP_LOGI(TAG, "no saved networks");
        return;
    }
    uint8_t n = 0;
    nvs_get_u8(h, NVS_KEY_COUNT, &n);
    if (n > WIFI_MAX_NETWORKS) n = WIFI_MAX_NETWORKS;

    for (uint8_t i = 0; i < n; i++) {
        char key[16];
        size_t len;

        snprintf(key, sizeof(key), "s%u", i);
        len = WIFI_SSID_LEN;
        if (nvs_get_str(h, key, s_nets[s_count].ssid, &len) != ESP_OK) continue;

        snprintf(key, sizeof(key), "p%u", i);
        len = WIFI_PASS_LEN;
        if (nvs_get_str(h, key, s_nets[s_count].pass, &len) != ESP_OK)
            s_nets[s_count].pass[0] = 0;

        ESP_LOGI(TAG, "saved network %d: %s", s_count, s_nets[s_count].ssid);
        s_count++;
    }
    nvs_close(h);
}

static esp_err_t save_networks(void)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;

    // Any failed write fails the save. Ignoring them once let the setup
    // page report "saved" for a network that was gone after a restart.
    err = nvs_erase_all(h);
    if (err == ESP_OK) err = nvs_set_u8(h, NVS_KEY_COUNT, (uint8_t)s_count);
    for (int i = 0; i < s_count && err == ESP_OK; i++) {
        char key[16];
        snprintf(key, sizeof(key), "s%d", i);
        err = nvs_set_str(h, key, s_nets[i].ssid);
        snprintf(key, sizeof(key), "p%d", i);
        if (err == ESP_OK) err = nvs_set_str(h, key, s_nets[i].pass);
    }
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err != ESP_OK)
        ESP_LOGE(TAG, "could not save networks: %s", esp_err_to_name(err));
    return err;
}

int slam_wifi_count(void) { return s_count; }

esp_err_t slam_wifi_get(int index, wifi_net_t *out)
{
    if (index < 0 || index >= s_count || !out) return ESP_ERR_INVALID_ARG;
    *out = s_nets[index];
    return ESP_OK;
}

esp_err_t slam_wifi_add(const char *ssid, const char *pass)
{
    if (!ssid || !ssid[0]) return ESP_ERR_INVALID_ARG;

    for (int i = 0; i < s_count; i++) {
        if (strcmp(s_nets[i].ssid, ssid) == 0) {
            strlcpy(s_nets[i].pass, pass ? pass : "", WIFI_PASS_LEN);
            ESP_LOGI(TAG, "updated %s", ssid);
            return save_networks();
        }
    }
    if (s_count >= WIFI_MAX_NETWORKS) return ESP_ERR_NO_MEM;

    strlcpy(s_nets[s_count].ssid, ssid, WIFI_SSID_LEN);
    strlcpy(s_nets[s_count].pass, pass ? pass : "", WIFI_PASS_LEN);
    s_count++;
    ESP_LOGI(TAG, "added %s", ssid);
    return save_networks();
}

esp_err_t slam_wifi_remove(const char *ssid)
{
    for (int i = 0; i < s_count; i++) {
        if (strcmp(s_nets[i].ssid, ssid) != 0) continue;
        for (int j = i; j < s_count - 1; j++) s_nets[j] = s_nets[j + 1];
        s_count--;
        if (s_current == i) s_current = -1;
        return save_networks();
    }
    return ESP_ERR_NOT_FOUND;
}

// ---------------- events ----------------

static void on_wifi_event(void *arg, esp_event_base_t base,
                          int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *d =
            (wifi_event_sta_disconnected_t *)data;
        // 15 = handshake timeout, almost always a wrong password.
        // 201 = the network was not found at all.
        s_last_reason = d->reason;
        ESP_LOGW(TAG, "disconnect reason %d%s", d->reason,
                 d->reason == 2   ? " (router did not answer in time)" :
                 d->reason == 15  ? " (wrong password?)" :
                 d->reason == 201 ? " (network not found)" : "");
        if (s_state == NET_CONNECTED || s_state == NET_DUAL) {
            ESP_LOGW(TAG, "disconnected from %s", slam_wifi_ssid());
            s_state = (s_ap_netif) ? NET_AP_ONLY : NET_CONNECTING;
            strcpy(s_ip, "0.0.0.0");
        }
        xEventGroupSetBits(s_events, FAIL_BIT);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)data;
        snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&e->ip_info.ip));
        ESP_LOGI(TAG, "got ip %s", s_ip);
        s_retry_step = 0;
        xEventGroupSetBits(s_events, CONNECT_BIT);
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STACONNECTED) {
        ESP_LOGI(TAG, "a client joined the config portal");
    }
}

// ---------------- init ----------------

esp_err_t slam_wifi_init(void)
{
    s_events = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    s_sta_netif = esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

    // Name and password both come from the MAC, so no two units on a
    // campus share an access point password.
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    snprintf(s_ap_ssid, sizeof(s_ap_ssid), "SLAM-%02X%02X%02X",
             mac[3], mac[4], mac[5]);
    snprintf(s_ap_pass, sizeof(s_ap_pass), "slam%02X%02X%02X",
             mac[5], mac[4], mac[3]);

    load_networks();
    ESP_LOGI(TAG, "ap ssid %s", s_ap_ssid);
    return ESP_OK;
}

// ---------------- connecting ----------------

static bool try_network(int index)
{
    wifi_config_t cfg = {0};
    strlcpy((char *)cfg.sta.ssid, s_nets[index].ssid, sizeof(cfg.sta.ssid));
    strlcpy((char *)cfg.sta.password, s_nets[index].pass,
            sizeof(cfg.sta.password));
    cfg.sta.threshold.authmode = s_nets[index].pass[0] ?
        WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;

    ESP_LOGI(TAG, "trying %s", s_nets[index].ssid);

    // Wait for the previous attempt to finish tearing down. Setting the
    // config while the driver is still connecting is refused outright,
    // which would skip every network after the first.
    esp_wifi_disconnect();
    for (int i = 0; i < 20; i++) {
        wifi_ap_record_t rec;
        if (esp_wifi_sta_get_ap_info(&rec) != ESP_OK) break;
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    vTaskDelay(pdMS_TO_TICKS(200));

    esp_err_t err = esp_wifi_set_config(WIFI_IF_STA, &cfg);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "set config failed: %s", esp_err_to_name(err));
        vTaskDelay(pdMS_TO_TICKS(500));
        return false;
    }

    // A router that is slow to answer (reason 2, auth expired; 4, assoc
    // expired) is usually fine a second later - on the bench most first
    // attempts failed this way and the retry went through. A wrong
    // password or a missing network will not change, so those give up.
    for (int attempt = 0; attempt < 4; attempt++) {
        // Clear the flags immediately before connecting, so a failure left
        // over from the previous attempt cannot end this one early.
        xEventGroupClearBits(s_events, CONNECT_BIT | FAIL_BIT);
        s_last_reason = 0;

        err = esp_wifi_connect();
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "connect call failed: %s", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(500));
            return false;
        }

        EventBits_t bits = xEventGroupWaitBits(
            s_events, CONNECT_BIT | FAIL_BIT, pdFALSE, pdFALSE,
            pdMS_TO_TICKS(12000));

        if (bits & CONNECT_BIT) {
            s_current = index;
            return true;
        }
        bool transient = s_last_reason == 2 || s_last_reason == 4 ||
                         s_last_reason == 8 || s_last_reason == 205;
        if (!transient) return false;
        ESP_LOGI(TAG, "retrying %s (%d of 3)", s_nets[index].ssid, attempt + 1);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    return false;
}

esp_err_t slam_wifi_connect_best(void)
{
    if (s_count == 0) {
        ESP_LOGW(TAG, "nothing saved, opening the portal");
        slam_wifi_start_ap(false);
        return ESP_ERR_NOT_FOUND;
    }

    s_state = NET_CONNECTING;

    // Make sure station mode is enabled. If the access point is already
    // running we need both, not one replacing the other.
    wifi_mode_t want = (s_ap_netif != NULL) ? WIFI_MODE_APSTA : WIFI_MODE_STA;
    wifi_mode_t mode = WIFI_MODE_NULL;
    esp_wifi_get_mode(&mode);
    if (mode != want) esp_wifi_set_mode(want);

    // Track the start explicitly. The reported mode is set during init,
    // so it cannot tell us whether the driver is actually running.
    if (!s_wifi_started) {
        esp_err_t err = esp_wifi_start();
        if (err != ESP_OK && err != ESP_ERR_WIFI_NOT_STOPPED) {
            ESP_LOGE(TAG, "wifi start failed: %s", esp_err_to_name(err));
            return ESP_FAIL;
        }
        s_wifi_started = true;
        vTaskDelay(pdMS_TO_TICKS(300));
    }

    // Try the one that worked last time before the whole list.
    if (s_current >= 0 && s_current < s_count && try_network(s_current)) {
        s_state = s_ap_netif ? NET_DUAL : NET_CONNECTED;
        return ESP_OK;
    }
    for (int i = 0; i < s_count; i++) {
        if (i == s_current) continue;
        if (try_network(i)) {
            s_state = s_ap_netif ? NET_DUAL : NET_CONNECTED;
            return ESP_OK;
        }
    }

    ESP_LOGW(TAG, "no saved network reachable");
    s_state = NET_AP_ONLY;
    return ESP_ERR_NOT_FOUND;
}

void slam_wifi_start_ap(bool keep_station)
{
    if (s_ap_netif == NULL) s_ap_netif = esp_netif_create_default_wifi_ap();

    wifi_config_t ap = {0};
    strlcpy((char *)ap.ap.ssid, s_ap_ssid, sizeof(ap.ap.ssid));
    ap.ap.ssid_len = strlen(s_ap_ssid);
    strlcpy((char *)ap.ap.password, s_ap_pass, sizeof(ap.ap.password));
    ap.ap.max_connection = 3;
    ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
    ap.ap.channel = 1;

    esp_wifi_set_mode(keep_station ? WIFI_MODE_APSTA : WIFI_MODE_AP);
    esp_wifi_set_config(WIFI_IF_AP, &ap);

    if (!s_wifi_started) {
        esp_wifi_start();
        s_wifi_started = true;
        vTaskDelay(pdMS_TO_TICKS(300));
    }

    esp_netif_ip_info_t info;
    if (esp_netif_get_ip_info(s_ap_netif, &info) == ESP_OK)
        snprintf(s_ap_ip, sizeof(s_ap_ip), IPSTR, IP2STR(&info.ip));

    s_state = keep_station ? NET_DUAL : NET_AP_ONLY;
    ESP_LOGI(TAG, "portal open: ssid %s pass %s at %s",
             s_ap_ssid, s_ap_pass, s_ap_ip);
}

// ---------------- status ----------------

net_state_t slam_wifi_state(void) { return s_state; }

bool slam_wifi_online(void)
{
    return (s_state == NET_CONNECTED || s_state == NET_DUAL)
        && strcmp(s_ip, "0.0.0.0") != 0;
}

const char *slam_wifi_ssid(void)
{
    return (s_current >= 0 && s_current < s_count)
        ? s_nets[s_current].ssid : "";
}

const char *slam_wifi_ip(void)      { return s_ip; }
const char *slam_wifi_ap_ip(void)   { return s_ap_ip; }
const char *slam_wifi_ap_pass(void) { return s_ap_pass; }
const char *slam_wifi_ap_ssid(void) { return s_ap_ssid; }

// Called repeatedly by the network task. Reconnects with a growing
// delay, and opens the portal once the device has clearly given up.
void slam_wifi_tick(void)
{
    if (slam_wifi_online()) return;

    int64_t now = esp_timer_get_time() / 1000;
    if (now < s_next_retry_ms) return;

    int wait = RETRY_SECONDS[s_retry_step];
    s_next_retry_ms = now + (int64_t)wait * 1000;

    ESP_LOGI(TAG, "reconnect attempt (next in %ds if this fails)", wait);
    if (slam_wifi_connect_best() != ESP_OK) {
        int max_step = (int)(sizeof(RETRY_SECONDS) / sizeof(RETRY_SECONDS[0])) - 1;
        if (s_retry_step < max_step) s_retry_step++;
        // After a few failures, open the portal so someone can fix it -
        // while attendance carries on from the cached roster.
        if (s_retry_step >= 2 && s_ap_netif == NULL) {
            slam_wifi_start_ap(true);
        }
    }
}








int slam_wifi_scan(wifi_scan_entry_t *out, int max)
{
    if (!out || max <= 0) return 0;

    // Scanning needs station mode. Keep the access point up if it is
    // running, or whoever is using the portal gets dropped.
    wifi_mode_t want = (s_ap_netif != NULL) ? WIFI_MODE_APSTA : WIFI_MODE_STA;
    wifi_mode_t mode = WIFI_MODE_NULL;
    esp_wifi_get_mode(&mode);
    if (mode != want) esp_wifi_set_mode(want);
    if (!s_wifi_started) {
        esp_wifi_start();
        s_wifi_started = true;
        vTaskDelay(pdMS_TO_TICKS(300));
    }

    wifi_scan_config_t cfg = { .show_hidden = false };
    if (esp_wifi_scan_start(&cfg, true) != ESP_OK) {
        ESP_LOGW(TAG, "scan failed");
        return 0;
    }

    uint16_t found = 0;
    esp_wifi_scan_get_ap_num(&found);
    if (found == 0) return 0;
    if (found > 32) found = 32;

    wifi_ap_record_t *recs = calloc(found, sizeof(wifi_ap_record_t));
    if (!recs) return 0;
    esp_wifi_scan_get_ap_records(&found, recs);

    int n = 0;
    for (uint16_t i = 0; i < found && n < max; i++) {
        if (recs[i].ssid[0] == 0) continue;

        // Skip a repeat of a name we already listed (mesh access points
        // appear once per radio).
        bool dup = false;
        for (int j = 0; j < n; j++) {
            if (strcmp(out[j].ssid, (char *)recs[i].ssid) == 0) dup = true;
        }
        if (dup) continue;

        strlcpy(out[n].ssid, (char *)recs[i].ssid, WIFI_SSID_LEN);
        out[n].rssi   = recs[i].rssi;
        out[n].secure = (recs[i].authmode != WIFI_AUTH_OPEN);
        out[n].saved  = false;
        for (int j = 0; j < s_count; j++) {
            if (strcmp(s_nets[j].ssid, out[n].ssid) == 0) out[n].saved = true;
        }
        n++;
    }
    free(recs);
    ESP_LOGI(TAG, "scan found %d networks", n);
    return n;
}




