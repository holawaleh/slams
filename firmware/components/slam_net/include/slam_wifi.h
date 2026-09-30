#pragma once

#include <stdbool.h>
#include "esp_err.h"

#define WIFI_MAX_NETWORKS   5
#define WIFI_SSID_LEN       33
#define WIFI_PASS_LEN       65

typedef struct {
    char ssid[WIFI_SSID_LEN];
    char pass[WIFI_PASS_LEN];
} wifi_net_t;

typedef enum {
    NET_BOOTING = 0,
    NET_CONNECTING,
    NET_CONNECTED,
    NET_AP_ONLY,        // no known network reachable, portal is open
    NET_DUAL            // connected, and the portal is still open
} net_state_t;

esp_err_t slam_wifi_init(void);

// Saved networks, stored in NVS. Tried in the order listed.
int       slam_wifi_count(void);
esp_err_t slam_wifi_get(int index, wifi_net_t *out);
esp_err_t slam_wifi_add(const char *ssid, const char *pass);
esp_err_t slam_wifi_remove(const char *ssid);

// Tries each saved network in turn. Falls back to the access point.
esp_err_t slam_wifi_connect_best(void);
void      slam_wifi_start_ap(bool keep_station);

net_state_t slam_wifi_state(void);
bool        slam_wifi_online(void);
const char *slam_wifi_ssid(void);
const char *slam_wifi_ip(void);
const char *slam_wifi_ap_ip(void);

// The access point password, derived from this device's MAC address so
// every unit differs. Shown on the display when the portal opens.
const char *slam_wifi_ap_pass(void);
const char *slam_wifi_ap_ssid(void);

// One nearby network, as returned by a scan.
typedef struct {
    char    ssid[WIFI_SSID_LEN];
    int8_t  rssi;
    bool    secure;
    bool    saved;      // already in our list
} wifi_scan_entry_t;

// Scans and fills up to max entries, strongest first. Returns the count.
// Scanning briefly disturbs an active connection, so call it only when
// someone is actually looking at the portal.
int slam_wifi_scan(wifi_scan_entry_t *out, int max);

// Called by the network task when it has nothing else to do.
void slam_wifi_tick(void);

