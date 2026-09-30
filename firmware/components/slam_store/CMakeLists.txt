idf_component_register(
    SRCS "slam_store.c" "slam_queue.c"
    INCLUDE_DIRS "include"
    REQUIRES slam_core
    PRIV_REQUIRES joltwallet__littlefs esp_partition vfs
)
