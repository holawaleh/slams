#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "nvs_flash.h"
#include "esp_partition.h"
#include "soc/gpio_reg.h"
#include "soc/rtc.h"
#include "esp_rom_sys.h"
#include "esp_efuse.h"
#include "esp_efuse_table.h"
#include "driver/gpio.h"

#include "slam_board.h"
#include "slam_types.h"
#include "mfrc522.h"
#include "lcd1602.h"
#include "slam_store.h"
#include "slam_wifi.h"
#include "slam_cfg.h"
#include "slam_api.h"
#include "slam_portal.h"

static const char *TAG = "slam";

// This board once lost every flash write after its first boot while the
// writes reported success. Settings, tokens and taps all depend on flash,
// so check at every boot that a write really lands, and say so loudly
// if it does not. Uses the phy_init partition, which this build never
// reads (radio settings live in NVS).
// Runs first in app_main, before anything writes to flash. See
// SLAM_FLASH_IS_3V3 in slam_board.h for why. It changes nothing on a
// board where GPIO12 was low at reset, or where an eFuse sets the voltage.
static bool s_flash_forced_3v3;

static void flash_supply_3v3(void)
{
#if SLAM_FLASH_IS_3V3
    if (esp_efuse_read_field_bit(ESP_EFUSE_XPD_SDIO_FORCE))
        return;                             // an eFuse decides; leave it
    rtc_vddsdio_config_t cfg = rtc_vddsdio_get_config();
    if (cfg.tieh != RTC_VDDSDIO_TIEH_1_8V)
        return;                             // already 3.3 V
    cfg.force = 1;
    cfg.enable = 1;
    cfg.tieh = RTC_VDDSDIO_TIEH_3_3V;
    rtc_vddsdio_set_config(cfg);
    esp_rom_delay_us(50);                   // let the supply settle
    s_flash_forced_3v3 = true;
#endif
}

static void flash_self_check(void)
{
    const esp_partition_t *p = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_PHY, NULL);
    if (!p) {
        ESP_LOGW(TAG, "flash check skipped: no phy_init partition");
        return;
    }
    uint32_t pattern[4] = { 0x51A3F1A5, (uint32_t)esp_timer_get_time(),
                            0xC0FFEE00, 0x12345678 };
    uint32_t back[4] = {0};
    esp_err_t e1 = esp_partition_erase_range(p, 0, p->erase_size);
    esp_err_t e2 = esp_partition_write(p, 0, pattern, sizeof(pattern));
    esp_err_t e3 = esp_partition_read(p, 0, back, sizeof(back));
    bool ok = e1 == ESP_OK && e2 == ESP_OK && e3 == ESP_OK &&
              memcmp(pattern, back, sizeof(pattern)) == 0;
    if (ok) {
        if (s_flash_forced_3v3)
            ESP_LOGW(TAG, "flash check: write ok (GPIO12 was high at reset; "
                          "flash supply switched from 1.8 V to 3.3 V)");
        else
            ESP_LOGI(TAG, "flash check: write ok");
        return;
    }

    ESP_LOGE(TAG, "flash check FAILED: erase=%s write=%s read=%s "
             "wrote %08lx got %08lx",
             esp_err_to_name(e1), esp_err_to_name(e2), esp_err_to_name(e3),
             (unsigned long)pattern[0], (unsigned long)back[0]);

    // Found on the bench: GPIO12 (MTDI) is a strapping pin. If it is high
    // at reset, and the flash-voltage eFuse is not burned, the chip powers
    // its 3.3 V flash at 1.8 V. Reads still work; erase and write are
    // silently ignored. No restart fixes it - the pin has to be low at
    // reset, or the eFuse has to fix the voltage at 3.3 V.
    uint32_t strap = REG_READ(GPIO_STRAP_REG);
    if (strap & BIT(5)) {
        ESP_LOGE(TAG, "GPIO12 was HIGH at reset (strap 0x%02lx): flash is "
                      "powered at 1.8 V and cannot be written. Disconnect "
                      "whatever is on GPIO12 or add a 10k pull-down to GND, "
                      "or burn the flash-voltage eFuse to 3.3 V.",
                 (unsigned long)(strap & 0x3F));
        slam_ui_post("Storage fault", "GPIO12 is high", TONE_REJECT, 8000);
    } else {
        ESP_LOGE(TAG, "flash writes failing (strap 0x%02lx): nothing will be "
                      "saved this session. Check the power supply.",
                 (unsigned long)(strap & 0x3F));
        slam_ui_post("Storage fault", "settings not kept", TONE_REJECT, 8000);
    }
}

// How many recent unknown cards to remember for throttling.
#define UNK_RING 8

// Students listen for the beep rather than read the screen, so the
// patterns have to be distinguishable without looking.
static void beep(uint8_t tone)
{
    int on_ms, off_ms, count;
    switch (tone) {
        case TONE_ACCEPT:  on_ms = 80;  off_ms = 0;   count = 1; break;
        case TONE_REJECT:  on_ms = 250; off_ms = 120; count = 2; break;
        case TONE_NEUTRAL: on_ms = 30;  off_ms = 0;   count = 1; break;
        default: return;
    }
    for (int i = 0; i < count; i++) {
        gpio_set_level(SLAM_PIN_BUZZER, 1);
        gpio_set_level(SLAM_PIN_LED, 1);
        vTaskDelay(pdMS_TO_TICKS(on_ms));
        gpio_set_level(SLAM_PIN_BUZZER, 0);
        gpio_set_level(SLAM_PIN_LED, 0);
        if (off_ms) vTaskDelay(pdMS_TO_TICKS(off_ms));
    }
}

// ---- core 1: reads cards, decides locally, never waits on the network
static void rfid_task(void *arg)
{
    ESP_LOGI(TAG, "rfid_task on core %d", xPortGetCoreID());
    if (mfrc522_init() != ESP_OK) {
        slam_ui_post("Reader fault", "check wiring", TONE_REJECT, 0);
        vTaskDelete(NULL);
    }

    slam_uid_t uid, last = {0};
    int64_t last_ms = 0;
    int health_ticks = 0;
    struct { slam_uid_t uid; int64_t ms; } unk[UNK_RING] = {0};
    int unk_next = 0;
    char hex[SLAM_UID_MAX_LEN * 2 + 1];

    while (1) {
        if (mfrc522_read_uid(&uid) == ESP_OK) {
            int64_t now_ms = esp_timer_get_time() / 1000;
            bool repeat = slam_uid_equal(&uid, &last) &&
                          (now_ms - last_ms) < SLAM_DEBOUNCE_HARD_MS;
            if (!repeat) {
                slam_uid_to_hex(&uid, hex, sizeof(hex));
                tap_event_t ev;
                char l1[SLAM_NAME_LEN + 1] = {0}, l2[SLAM_NAME_LEN + 1] = {0};
                tap_outcome_t out = slam_decide(&uid, &ev, l1, l2);
                bool accepted = (out == TAP_PRESENT || out == TAP_LATE);
                ESP_LOGI(TAG, "card %s -> %s", hex, slam_outcome_name(out));
                slam_ui_post(l1, l2,
                             accepted ? TONE_ACCEPT :
                             (out == TAP_DUPLICATE ? TONE_NEUTRAL : TONE_REJECT),
                             1500);

                // A duplicate costs nothing: no queue entry, no upload.
                // Unknown cards get a longer throttle, so idle tapping
                // with a bank card cannot fill the queue.
                bool suppress = (out == TAP_DUPLICATE);
                if (out == TAP_UNKNOWN_CARD) {
                    for (int i = 0; i < UNK_RING; i++) {
                        if (slam_uid_equal(&uid, &unk[i].uid) &&
                            (now_ms - unk[i].ms) < SLAM_DEBOUNCE_UNKNOWN_MS) {
                            suppress = true;
                            break;
                        }
                    }
                    if (!suppress) {
                        unk[unk_next].uid = uid;
                        unk[unk_next].ms  = now_ms;
                        unk_next = (unk_next + 1) % UNK_RING;
                    }
                }
                if (!suppress) xQueueSend(slam_store_q, &ev, 0);

                last = uid;
                last_ms = now_ms;
            }
            mfrc522_halt();
        }

        if (++health_ticks >= (5000 / SLAM_RFID_POLL_MS)) {
            health_ticks = 0;
            if (!mfrc522_antenna_ok()) mfrc522_recover();
        }
        vTaskDelay(pdMS_TO_TICKS(SLAM_RFID_POLL_MS));
    }
}

// ---- core 0: owns the display, buzzer and LED
static void ui_task(void *arg)
{
    ESP_LOGI(TAG, "ui_task on core %d", xPortGetCoreID());
    if (lcd1602_init() != ESP_OK) {
        ESP_LOGE(TAG, "no display - continuing without it");
    }
    ui_msg_t m;
    while (1) {
        if (xQueueReceive(slam_ui_q, &m, portMAX_DELAY) == pdTRUE) {
            ESP_LOGI(TAG, "[LCD] %-16s | %-16s", m.line1, m.line2);
            lcd1602_show(m.line1, m.line2);
            beep(m.tone);
            // Hold the message, but let a newer tap interrupt. Without
            // this a queue of students falls behind the beeps. When it
            // has been read, go back to the idle prompt. A message with
            // no hold time (pairing code, a fault) stays until replaced.
            if (m.hold_ms) {
                ui_msg_t next;
                if (xQueuePeek(slam_ui_q, &next,
                               pdMS_TO_TICKS(m.hold_ms)) == pdTRUE) {
                    continue;
                }
                lcd1602_show("  Swipe card", "   to scan");
            }
        }
    }
}

// ---- core 1: drains events to flash so the card path stays fast
static void store_task(void *arg)
{
    ESP_LOGI(TAG, "store_task on core %d", xPortGetCoreID());
    tap_event_t e;
    while (1) {
        if (xQueueReceive(slam_store_q, &e, portMAX_DELAY) == pdTRUE) {
            // Flash writes are verified, so a lost write comes back as an
            // error. Try again before giving up on a student's tap.
            esp_err_t qerr = slam_queue_push(&e);
            for (int tries = 1; qerr != ESP_OK && tries < 3; tries++) {
                vTaskDelay(pdMS_TO_TICKS(200));
                qerr = slam_queue_push(&e);
            }
            ESP_LOGI(TAG, "queued %s (depth %u) %s",
                     slam_outcome_name(e.outcome),
                     (unsigned)slam_queue_depth(),
                     qerr == ESP_OK ? "" : "FAILED");
        }
    }
}

// ---- core 0: WiFi, heartbeat, bundle sync, batched upload
static void net_task(void *arg)
{
    ESP_LOGI(TAG, "net_task on core %d", xPortGetCoreID());
    ESP_ERROR_CHECK(slam_wifi_init());

    if (slam_wifi_connect_best() == ESP_OK) {
        // Keep the setup page reachable on the local network too, so the
        // backend address can be changed without unplugging anything.
        slam_wifi_start_ap(true);
        slam_ui_post("WiFi connected", slam_wifi_ip(), TONE_NONE, 2000);
    } else {
        slam_wifi_start_ap(false);
        char l2[SLAM_NAME_LEN + 1];
        snprintf(l2, sizeof(l2), "%.16s", slam_wifi_ap_pass());
        // A reader with no network saved cannot be set up without these,
        // so they stay. With networks saved but out of reach, the reader
        // still takes taps offline, so it returns to the idle prompt.
        slam_ui_post(slam_wifi_ap_ssid(), l2, TONE_NONE,
                     slam_wifi_count() == 0 ? 0 : 8000);
    }
    slam_portal_start();

    slam_cfg_init();
    slam_api_init();

    // The directory kept on flash counts: no need to fetch it again at
    // every boot when nothing changed.
    uint32_t dir_have = slam_dir_version(), bundle_have = 0;
    int64_t next_hello_ms = 0;

    // Pairing: a reader with no token, or whose token the server refuses
    // (it was removed from its account), announces itself and shows a
    // pairing code until an admin adds it from the dashboard.
    bool pairing = !slam_cfg_ready();
    char shown_code[8] = "";
    int64_t next_announce_ms = 0, next_pair_msg_ms = 0;

    while (1) {
        // Someone added a network on the setup page: try it now rather
        // than waiting out the backoff.
        if (slam_portal_take_dirty()) {
            ESP_LOGI(TAG, "network list changed, reconnecting");
            if (slam_wifi_connect_best() == ESP_OK) {
                slam_ui_post("WiFi connected", slam_wifi_ip(),
                             TONE_ACCEPT, 2000);
                next_hello_ms = 0;
            }
        }
        slam_wifi_tick();

        if (slam_wifi_online() && pairing) {
            int64_t now_ms = esp_timer_get_time() / 1000;
            if (now_ms >= next_announce_ms) {
                next_announce_ms = now_ms + 5000;
                announce_result_t a;
                if (slam_api_announce(&a, slam_wifi_ip()) == ESP_OK) {
                    slam_set_time_ms(a.server_utc_ms);
                    if (a.state == PAIR_DONE && a.token[0]) {
                        slam_cfg_set_token(a.token);
                        ESP_LOGI(TAG, "paired as %s", a.name);
                        // Taps made while unpaired belong to no account, and
                        // a reader moved between accounts must not carry the
                        // old school's taps into the new one.
                        size_t stale = slam_queue_depth();
                        if (stale) {
                            ESP_LOGW(TAG, "discarding %u taps from before pairing",
                                     (unsigned)stale);
                            slam_queue_drop(stale);
                        }
                        // Forget the previous account's cards and roster;
                        // the new account's are fetched on the next hello.
                        session_t none = {0};
                        slam_dir_load(NULL, 0, 0);
                        slam_roster_load(&none, NULL, 0);
                        dir_have = bundle_have = 0;
                        pairing = false;
                        shown_code[0] = 0;
                        next_hello_ms = 0;
                        slam_ui_post("Reader added", a.name, TONE_ACCEPT, 4000);
                    } else if (a.state == PAIR_WAITING &&
                               (strcmp(a.code, shown_code) != 0 ||
                                now_ms >= next_pair_msg_ms)) {
                        // Re-shown every 20 s so it comes back after a tap
                        // message has replaced it on the screen.
                        strlcpy(shown_code, a.code, sizeof(shown_code));
                        char l2[SLAM_NAME_LEN + 1];
                        snprintf(l2, sizeof(l2), "%.3s %.3s", a.code, a.code + 3);
                        slam_ui_post("Pair code", l2, TONE_NONE, 0);
                        ESP_LOGI(TAG, "waiting to be added, pairing code %s", a.code);
                        next_pair_msg_ms = now_ms + 20000;
                    } else if (a.state == PAIR_TAKEN && now_ms >= next_pair_msg_ms) {
                        // Registered, but our token was refused. Keep trying
                        // it in case that was a passing server problem.
                        slam_ui_post("Already added", "Re-pair in app", TONE_NONE, 0);
                        ESP_LOGW(TAG, "reader is registered; remove it in the "
                                      "dashboard to pair it again");
                        next_pair_msg_ms = now_ms + 20000;
                        if (slam_cfg_ready()) { pairing = false; next_hello_ms = now_ms + 60000; }
                    }
                }
            }
        } else if (slam_wifi_online()) {
            int64_t now_ms = esp_timer_get_time() / 1000;

            if (now_ms >= next_hello_ms) {
                hello_result_t h;
                esp_err_t herr = slam_api_hello(&h, slam_queue_depth());
                if (herr == ESP_ERR_INVALID_STATE) {
                    // No token, or the server no longer accepts it.
                    ESP_LOGW(TAG, "token refused, switching to pairing");
                    pairing = true;
                    next_announce_ms = 0;
                    next_pair_msg_ms = 0;
                } else if (herr == ESP_OK) {
                    slam_set_time_ms(h.server_utc_ms);
                    slam_set_placed(h.placed);

                    if (h.directory_version != dir_have &&
                        slam_api_fetch_directory(dir_have) == ESP_OK) {
                        dir_have = h.directory_version;
                    }
                    if (h.bundle_version != bundle_have &&
                        slam_api_fetch_bundle(bundle_have) == ESP_OK) {
                        bundle_have = h.bundle_version;
                    }

                    // Every 30 s during a lecture, every minute otherwise.
                    // The dashboard calls a reader online if it checked in
                    // within 5 minutes; at the old 10-minute idle interval
                    // a connected reader showed as offline most of the time.
                    next_hello_ms = now_ms + (h.has_session ? 30000 : 60000);
                } else {
                    next_hello_ms = now_ms + 60000;
                }
            }

            if (slam_queue_depth() > 0) {
                size_t sent = 0;
                slam_api_upload(SLAM_UPLOAD_BATCH_MAX, &sent);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

// ---- low priority: watch for heap fragmentation during development
static void health_task(void *arg)
{
    while (1) {
        ESP_LOGI(TAG, "heap free=%u largest_block=%u",
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_8BIT),
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
        vTaskDelay(pdMS_TO_TICKS(30000));
    }
}

static void init_gpio(void)
{
    // Drive the buzzer low immediately. GPIO2 is a strapping pin.
    gpio_config_t out = {
        .pin_bit_mask = (1ULL << SLAM_PIN_BUZZER) | (1ULL << SLAM_PIN_LED),
        .mode = GPIO_MODE_OUTPUT,
    };
    gpio_config(&out);
    gpio_set_level(SLAM_PIN_BUZZER, 0);
    gpio_set_level(SLAM_PIN_LED, 0);

    gpio_config_t in = {
        .pin_bit_mask = (1ULL << SLAM_PIN_CONFIG_BTN),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&in);
}

void app_main(void)
{
    flash_supply_3v3();
    init_gpio();

    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    slam_core_init();
    flash_self_check();
    ESP_ERROR_CHECK(slam_store_init());

    // Shown first at every boot: the ID an administrator types into the
    // dashboard to add this reader. Colons dropped to fit 16 columns.
    char hw[13];
    const char *id = slam_hw_id();
    for (int i = 0, j = 0; id[i] && j < 12; i++) if (id[i] != ':') hw[j++] = id[i];
    hw[12] = 0;
    slam_ui_post("Reader ID", hw, TONE_NONE, 4000);

    xTaskCreatePinnedToCore(ui_task,     "ui",     3072, NULL, 4, NULL, 0);
    xTaskCreatePinnedToCore(net_task,    "net",    8192, NULL, 5, NULL, 0);
    xTaskCreatePinnedToCore(rfid_task,   "rfid",   4096, NULL, 6, NULL, 1);
    xTaskCreatePinnedToCore(store_task,  "store",  4096, NULL, 3, NULL, 1);
    xTaskCreatePinnedToCore(health_task, "health", 2560, NULL, 1, NULL, 0);

    ESP_LOGI(TAG, "app_main done, free heap %u",
             (unsigned)esp_get_free_heap_size());
}



