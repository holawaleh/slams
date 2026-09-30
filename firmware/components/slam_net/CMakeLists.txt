idf_component_register(
    SRCS "slam_wifi.c" "slam_cfg.c" "slam_api.c"
    INCLUDE_DIRS "include"
    REQUIRES slam_core slam_store
    PRIV_REQUIRES esp_wifi esp_netif nvs_flash esp_event esp_timer
                  esp_http_client esp-tls mbedtls espressif__cjson
)
