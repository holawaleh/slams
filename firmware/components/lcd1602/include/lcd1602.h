#pragma once

#include <stdbool.h>
#include "esp_err.h"

// Brings up I2C, scans the bus, and initialises the display.
// Logs every address found, so a wrong backpack address is obvious.
esp_err_t lcd1602_init(void);

// Writes both lines. Each is padded or cut to 16 characters.
// Does not clear the screen, so there is no flicker.
void lcd1602_show(const char *line1, const char *line2);

void lcd1602_backlight(bool on);
