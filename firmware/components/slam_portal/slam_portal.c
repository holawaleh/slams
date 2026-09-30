#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_http_server.h"
#include "esp_system.h"
#include "cJSON.h"
#include "slam_types.h"
#include "slam_store.h"
#include "slam_wifi.h"
#include "slam_cfg.h"
#include "slam_portal.h"

static const char *TAG = "portal";

extern const char portal_html_start[] asm("_binary_portal_html_start");
extern const char portal_html_end[]   asm("_binary_portal_html_end");

static httpd_handle_t s_server;
static bool           s_dirty;

#define BODY_MAX 512

// ---------------- helpers ----------------

static esp_err_t send_json(httpd_req_t *req, int code, const char *json)
{
    char status[32];
    snprintf(status, sizeof(status), "%d %s", code,
             code == 200 ? "OK" : (code == 400 ? "Bad Request" : "Error"));
    httpd_resp_set_status(req, status);
    httpd_resp_set_type(req, "application/json");
    return httpd_resp_sendstr(req, json);
}

static esp_err_t send_detail(httpd_req_t *req, int code, const char *detail)
{
    char buf[192];
    snprintf(buf, sizeof(buf), "{\"detail\":\"%s\"}", detail);
    return send_json(req, code, buf);
}

// Reads a JSON body and parses it. Caller frees with cJSON_Delete.
static cJSON *read_body(httpd_req_t *req)
{
    if (req->content_len <= 0 || req->content_len >= BODY_MAX) return NULL;
    char buf[BODY_MAX];
    int got = httpd_req_recv(req, buf, req->content_len);
    if (got <= 0) return NULL;
    buf[got] = 0;
    return cJSON_Parse(buf);
}

static const char *str_of(cJSON *root, const char *key)
{
    cJSON *v = cJSON_GetObjectItem(root, key);
    return (v && cJSON_IsString(v)) ? v->valuestring : NULL;
}

// ---------------- handlers ----------------

static esp_err_t h_root(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, portal_html_start,
                           portal_html_end - portal_html_start - 1);
}

static esp_err_t h_status(httpd_req_t *req)
{
    char buf[512];
    snprintf(buf, sizeof(buf),
        "{\"device\":\"%s\",\"hw_id\":\"%s\",\"firmware\":\"" SLAM_FW_VERSION "\","
        "\"ssid\":\"%s\","
        "\"ip\":\"%s\",\"online\":%s,\"queue\":%u,\"cards\":%u,"
        "\"url\":\"%s\",\"token_set\":%s}",
        slam_wifi_ap_ssid(), slam_hw_id(), slam_wifi_ssid(),
        slam_wifi_online() ? slam_wifi_ip() : slam_wifi_ap_ip(),
        slam_wifi_online() ? "true" : "false",
        (unsigned)slam_queue_depth(), (unsigned)slam_dir_count(),
        slam_cfg_base_url(), slam_cfg_ready() ? "true" : "false");
    return send_json(req, 200, buf);
}

static esp_err_t h_networks(httpd_req_t *req)
{
    char buf[768];
    size_t n = snprintf(buf, sizeof(buf), "[");
    const char *current = slam_wifi_ssid();

    for (int i = 0; i < slam_wifi_count(); i++) {
        wifi_net_t net;
        if (slam_wifi_get(i, &net) != ESP_OK) continue;
        n += snprintf(buf + n, sizeof(buf) - n,
            "%s{\"ssid\":\"%s\",\"current\":%s}", i ? "," : "", net.ssid,
            (current[0] && strcmp(current, net.ssid) == 0) ? "true" : "false");
    }
    snprintf(buf + n, sizeof(buf) - n, "]");
    return send_json(req, 200, buf);
}

static esp_err_t h_scan(httpd_req_t *req)
{
    wifi_scan_entry_t found[16];
    int n = slam_wifi_scan(found, 16);

    size_t cap = 96 + n * 96;
    char *buf = malloc(cap);
    if (!buf) return send_detail(req, 500, "Out of memory.");

    size_t p = snprintf(buf, cap, "[");
    for (int i = 0; i < n; i++) {
        p += snprintf(buf + p, cap - p,
            "%s{\"ssid\":\"%s\",\"rssi\":%d,\"secure\":%s,\"saved\":%s}",
            i ? "," : "", found[i].ssid, found[i].rssi,
            found[i].secure ? "true" : "false",
            found[i].saved ? "true" : "false");
    }
    snprintf(buf + p, cap - p, "]");

    esp_err_t err = send_json(req, 200, buf);
    free(buf);
    return err;
}

static esp_err_t h_connect(httpd_req_t *req)
{
    cJSON *root = read_body(req);
    if (!root) return send_detail(req, 400, "Could not read the request.");

    const char *ssid = str_of(root, "ssid");
    const char *pass = str_of(root, "pass");
    esp_err_t err = ESP_ERR_INVALID_ARG;
    if (ssid && ssid[0]) err = slam_wifi_add(ssid, pass ? pass : "");
    cJSON_Delete(root);

    if (err == ESP_ERR_NO_MEM)
        return send_detail(req, 400,
            "Five networks already saved. Remove one first.");
    if (err == ESP_ERR_INVALID_ARG)
        return send_detail(req, 400, "Enter a network name.");
    if (err != ESP_OK) {
        // Kept in memory, so it still connects now, but it will be
        // forgotten at the next restart. Say so rather than "saved".
        s_dirty = true;
        return send_detail(req, 500,
            "Connecting, but the reader could not store this network "
            "and will forget it after a restart.");
    }

    // The network task does the reconnecting, so the page stays responsive.
    s_dirty = true;
    return send_detail(req, 200, "Saved. Connecting in the background.");
}

static esp_err_t h_remove(httpd_req_t *req)
{
    cJSON *root = read_body(req);
    if (!root) return send_detail(req, 400, "Could not read the request.");

    const char *ssid = str_of(root, "ssid");
    esp_err_t err = ssid ? slam_wifi_remove(ssid) : ESP_ERR_INVALID_ARG;
    cJSON_Delete(root);

    if (err != ESP_OK) return send_detail(req, 400, "Network not found.");
    return send_detail(req, 200, "Removed.");
}

static esp_err_t h_server(httpd_req_t *req)
{
    cJSON *root = read_body(req);
    if (!root) return send_detail(req, 400, "Could not read the request.");

    const char *url   = str_of(root, "url");
    const char *token = str_of(root, "token");
    bool changed = false, failed = false;

    if (url && url[0]) {
        if (strncmp(url, "http://", 7) != 0 && strncmp(url, "https://", 8) != 0) {
            cJSON_Delete(root);
            return send_detail(req, 400,
                "Address must start with http:// or https://");
        }
        if (slam_cfg_set_base_url(url) != ESP_OK) failed = true;
        changed = true;
    }
    // A blank token means keep the existing one, so it is never shown
    // back to the page and cannot be wiped by accident.
    if (token && token[0]) {
        if (slam_cfg_set_token(token) != ESP_OK) failed = true;
        changed = true;
    }
    cJSON_Delete(root);

    if (!changed) return send_detail(req, 400, "Nothing to change.");
    if (failed) return send_detail(req, 500,
        "The reader could not store these settings. It will use them "
        "until it restarts.");
    return send_detail(req, 200, "Saved. Restart to use the new settings.");
}

static esp_err_t h_reboot(httpd_req_t *req)
{
    send_detail(req, 200, "Restarting.");
    // Let the reply reach the browser before the chip resets.
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
    return ESP_OK;
}

// ---------------- lifecycle ----------------

static const httpd_uri_t ROUTES[] = {
    { .uri = "/",             .method = HTTP_GET,  .handler = h_root },
    { .uri = "/api/status",   .method = HTTP_GET,  .handler = h_status },
    { .uri = "/api/networks", .method = HTTP_GET,  .handler = h_networks },
    { .uri = "/api/scan",     .method = HTTP_GET,  .handler = h_scan },
    { .uri = "/api/connect",  .method = HTTP_POST, .handler = h_connect },
    { .uri = "/api/remove",   .method = HTTP_POST, .handler = h_remove },
    { .uri = "/api/server",   .method = HTTP_POST, .handler = h_server },
    { .uri = "/api/reboot",   .method = HTTP_POST, .handler = h_reboot },
};

esp_err_t slam_portal_start(void)
{
    if (s_server) return ESP_OK;

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.max_uri_handlers = 12;
    cfg.stack_size = 6144;
    cfg.lru_purge_enable = true;

    esp_err_t err = httpd_start(&s_server, &cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "could not start: %s", esp_err_to_name(err));
        s_server = NULL;
        return err;
    }
    for (size_t i = 0; i < sizeof(ROUTES) / sizeof(ROUTES[0]); i++) {
        httpd_register_uri_handler(s_server, &ROUTES[i]);
    }
    ESP_LOGI(TAG, "setup page at http://%s/", slam_wifi_ap_ip());
    if (slam_wifi_online()) {
        ESP_LOGI(TAG, "also at http://%s/", slam_wifi_ip());
    }
    return ESP_OK;
}

void slam_portal_stop(void)
{
    if (!s_server) return;
    httpd_stop(s_server);
    s_server = NULL;
}

bool slam_portal_running(void) { return s_server != NULL; }

bool slam_portal_take_dirty(void)
{
    bool d = s_dirty;
    s_dirty = false;
    return d;
}

