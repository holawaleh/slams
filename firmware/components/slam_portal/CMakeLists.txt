idf_component_register(
    SRCS "slam_portal.c"
    INCLUDE_DIRS "include"
    REQUIRES slam_core slam_net slam_store
    PRIV_REQUIRES esp_http_server esp_wifi espressif__cjson
    EMBED_TXTFILES "portal.html"
)
