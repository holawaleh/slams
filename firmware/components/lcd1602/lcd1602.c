#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "slam_board.h"
#include "lcd1602.h"

static const char *TAG = "lcd";

// How the PCF8574 expander pins map to the display.
#define PIN_RS   0x01
#define PIN_RW   0x02
#define PIN_EN   0x04
#define PIN_BL   0x08

#define LCD_TIMEOUT_MS   200

static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_dev;
static uint8_t s_backlight = PIN_BL;
static bool    s_ready = false;

static void raw_write(uint8_t v)
{
    i2c_master_transmit(s_dev, &v, 1, LCD_TIMEOUT_MS);
}

// One 4 bit half of a byte, pulsed in with the enable line.
static void send_nibble(uint8_t nibble, uint8_t rs)
{
    uint8_t base = (uint8_t)((nibble & 0xF0) | s_backlight | rs);
    raw_write(base);
    raw_write((uint8_t)(base | PIN_EN));
    esp_rom_delay_us(2);
    raw_write(base);
    esp_rom_delay_us(50);
}

static void send_byte(uint8_t value, uint8_t rs)
{
    send_nibble((uint8_t)(value & 0xF0), rs);
    send_nibble((uint8_t)(value << 4), rs);
}

// Appends the six expander bytes that clock one value into the display.
// Batching a whole line into one I2C transfer is far cheaper than
// sending each byte as its own transaction.
static void pack_byte(uint8_t *buf, size_t *n, uint8_t value, uint8_t rs)
{
    const uint8_t nib[2] = { (uint8_t)(value & 0xF0), (uint8_t)(value << 4) };
    for (int i = 0; i < 2; i++) {
        uint8_t base = (uint8_t)(nib[i] | s_backlight | rs);
        buf[(*n)++] = base;
        buf[(*n)++] = (uint8_t)(base | PIN_EN);
        buf[(*n)++] = base;
    }
}

static void write_line(uint8_t row, const char *text)
{
    // 1 address command plus 16 characters, six expander bytes each.
    uint8_t buf[(1 + 16) * 6];
    size_t n = 0;

    pack_byte(buf, &n, (uint8_t)(0x80 | (row ? 0x40 : 0x00)), 0);

    size_t len = text ? strlen(text) : 0;
    for (int i = 0; i < 16; i++) {
        char c = (i < (int)len) ? text[i] : ' ';
        pack_byte(buf, &n, (uint8_t)c, PIN_RS);
    }
    i2c_master_transmit(s_dev, buf, n, LCD_TIMEOUT_MS);
}

esp_err_t lcd1602_init(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = SLAM_I2C_PORT,
        .sda_io_num = SLAM_PIN_I2C_SDA,
        .scl_io_num = SLAM_PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    esp_err_t err = i2c_new_master_bus(&bus_cfg, &s_bus);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2c bus init failed: %s", esp_err_to_name(err));
        return err;
    }

    // Scan, so a wrong backpack address shows up plainly in the log.
    int found = 0;
    uint8_t first = 0;
    for (uint8_t a = 0x08; a < 0x78; a++) {
        if (i2c_master_probe(s_bus, a, 50) == ESP_OK) {
            ESP_LOGI(TAG, "i2c device at 0x%02X", a);
            if (!found) first = a;
            found++;
        }
    }
    if (!found) {
        ESP_LOGE(TAG, "no i2c devices - check SDA/SCL, 5V and ground");
        return ESP_ERR_NOT_FOUND;
    }

    uint8_t addr = SLAM_LCD_ADDR;
    if (i2c_master_probe(s_bus, addr, 50) != ESP_OK) {
        ESP_LOGW(TAG, "0x%02X not present, using 0x%02X instead", addr, first);
        addr = first;
    }

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = addr,
        .scl_speed_hz = SLAM_I2C_CLOCK_HZ,
    };
    err = i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev);
    if (err != ESP_OK) return err;

    // HD44780 wake-up. The display starts in 8 bit mode and has to be
    // talked down into 4 bit mode with specific delays.
    vTaskDelay(pdMS_TO_TICKS(50));
    send_nibble(0x30, 0); vTaskDelay(pdMS_TO_TICKS(5));
    send_nibble(0x30, 0); esp_rom_delay_us(150);
    send_nibble(0x30, 0); esp_rom_delay_us(150);
    send_nibble(0x20, 0); esp_rom_delay_us(150);

    send_byte(0x28, 0);   // 4 bit, two lines, 5x8 characters
    send_byte(0x08, 0);   // display off
    send_byte(0x01, 0);   // clear
    vTaskDelay(pdMS_TO_TICKS(3));
    send_byte(0x06, 0);   // move cursor right after each character
    send_byte(0x0C, 0);   // display on, no cursor, no blink

    s_ready = true;
    ESP_LOGI(TAG, "ready at 0x%02X", addr);
    return ESP_OK;
}

void lcd1602_show(const char *line1, const char *line2)
{
    if (!s_ready) return;
    write_line(0, line1);
    write_line(1, line2);
}

void lcd1602_backlight(bool on)
{
    s_backlight = on ? PIN_BL : 0x00;
    if (s_ready) raw_write(s_backlight);
}
