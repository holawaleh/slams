#include <string.h>
#include "esp_log.h"
#include "nvs.h"
#include "slam_cfg.h"

static const char *TAG = "cfg";
#define NVS_NS "slamcfg"

// Used only on a reader that has never been configured. A new reader
// knows where the service is but has no token: it announces itself and
// waits to be paired from the dashboard (Settings > Devices > Search).
#define DEFAULT_BASE_URL  "https://slams-bez9.onrender.com"
#define DEFAULT_TOKEN     ""

static char s_url[CFG_URL_LEN];
static char s_token[CFG_TOKEN_LEN];

esp_err_t slam_cfg_init(void)
{
    strlcpy(s_url, DEFAULT_BASE_URL, sizeof(s_url));
    strlcpy(s_token, DEFAULT_TOKEN, sizeof(s_token));

    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) == ESP_OK) {
        size_t len = sizeof(s_url);
        nvs_get_str(h, "url", s_url, &len);
        len = sizeof(s_token);
        nvs_get_str(h, "token", s_token, &len);
        nvs_close(h);
    }

    ESP_LOGI(TAG, "backend %s", s_url);
    ESP_LOGI(TAG, "token %s", slam_cfg_ready() ? "set" : "NOT SET");
    return ESP_OK;
}

const char *slam_cfg_base_url(void) { return s_url; }
const char *slam_cfg_token(void)    { return s_token; }

bool slam_cfg_ready(void)
{
    return s_token[0] != 0;
}

static esp_err_t store(const char *key, const char *value)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_set_str(h, key, value);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err != ESP_OK)
        ESP_LOGE(TAG, "could not save %s: %s", key, esp_err_to_name(err));
    return err;
}

esp_err_t slam_cfg_set_base_url(const char *url)
{
    if (!url || !url[0]) return ESP_ERR_INVALID_ARG;
    strlcpy(s_url, url, sizeof(s_url));
    // Trailing slashes break path joining, so drop them here once.
    size_t n = strlen(s_url);
    while (n > 0 && s_url[n - 1] == '/') s_url[--n] = 0;
    return store("url", s_url);
}

esp_err_t slam_cfg_set_token(const char *token)
{
    if (!token || !token[0]) return ESP_ERR_INVALID_ARG;
    strlcpy(s_token, token, sizeof(s_token));
    return store("token", s_token);
}
