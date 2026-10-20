#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

#define GPFSEL0   0
#define GPSET0    7
#define GPCLR0    10
#define GPLEV0    13

#define SDA_PIN 2
#define SCL_PIN 3

static volatile uint32_t *gpio = NULL;
static int g_fd = -1;
static uint8_t prev_pages[16][128];
static int has_prev = 0;

static inline void gpio_as_output(int pin) {
    int reg = pin / 10;
    int shift = (pin % 10) * 3;
    uint32_t val = gpio[reg];
    val &= ~(7 << shift);
    val |= (1 << shift);
    gpio[reg] = val;
}

static inline void gpio_as_input(int pin) {
    int reg = pin / 10;
    int shift = (pin % 10) * 3;
    uint32_t val = gpio[reg];
    val &= ~(7 << shift);
    gpio[reg] = val;
}

static inline void gpio_set_low(int pin) {
    gpio[GPCLR0] = (1 << pin);
}

static inline void gpio_set_high(int pin) {
    gpio[GPSET0] = (1 << pin);
}

static inline void delay_half_us(void) {
    for (volatile int i = 0; i < 15; i++) {
        __asm__ volatile ("nop");
    }
}

static inline void sda_0(void) {
    gpio_set_low(SDA_PIN);
    gpio_as_output(SDA_PIN);
    delay_half_us();
}

static inline void sda_1(void) {
    gpio_as_input(SDA_PIN);
    delay_half_us();
}

static inline void scl_0(void) {
    gpio_set_low(SCL_PIN);
    gpio_as_output(SCL_PIN);
    delay_half_us();
}

static inline void scl_1(void) {
    gpio_as_input(SCL_PIN);
    delay_half_us();
}

static void i2c_start(void) {
    sda_1();
    scl_1();
    delay_half_us();
    sda_0();
    delay_half_us();
    scl_0();
    delay_half_us();
}

static void i2c_stop(void) {
    sda_0();
    delay_half_us();
    scl_1();
    delay_half_us();
    sda_1();
    delay_half_us();
}

static void i2c_send_byte(uint8_t b) {
    for (int i = 7; i >= 0; i--) {
        if ((b >> i) & 1) {
            sda_1();
        } else {
            sda_0();
        }
        scl_1();
        delay_half_us();
        scl_0();
        delay_half_us();
    }
    // 9th clock: ACK (we clock it, ignoring NACK)
    sda_1();
    scl_1();
    delay_half_us();
    scl_0();
    delay_half_us();
}

static void send_commands(const uint8_t *cmds, int count) {
    i2c_start();
    i2c_send_byte(0x78);
    i2c_send_byte(0x00);
    for (int i = 0; i < count; i++) {
        i2c_send_byte(cmds[i]);
    }
    i2c_stop();
}

int sh1107_init(void) {
    if (gpio == NULL) {
        g_fd = open("/dev/gpiomem", O_RDWR | O_SYNC);
        if (g_fd < 0) {
            perror("open /dev/gpiomem");
            return -1;
        }
        gpio = (volatile uint32_t *)mmap(NULL, 0x1000, PROT_READ | PROT_WRITE, MAP_SHARED, g_fd, 0);
        if (gpio == MAP_FAILED) {
            perror("mmap");
            gpio = NULL;
            return -2;
        }
    }

    uint8_t init_sequence[] = {
        0xAE,       // Display OFF
        0x00,       // Set lower column address 0
        0x10,       // Set higher column address 0
        0xDC, 0x00, // Set display start line 0
        0x81, 0x7F, // Set contrast to 127
        0x20,       // Set page addressing mode
        0xA0,       // Segment remap normal
        0xC0,       // COM output scan direction normal
        0xA4,       // Entire display normal
        0xA6,       // Normal display
        0xA8, 0x7F, // Set multiplex ratio: 128 lines
        0xD3, 0x00, // Set display offset 0
        0xD5, 0x50, // Set display clock divide
        0xDB, 0x35, // Set VCOM deselect level
        0xD9, 0x22, // Set pre-charge period
        0xAF        // Display ON!
    };
    send_commands(init_sequence, sizeof(init_sequence));
    has_prev = 0;
    return 0;
}

void sh1107_contrast(uint8_t contrast) {
    uint8_t cmds[] = { 0x81, contrast };
    send_commands(cmds, 2);
}

// Convert raw 1bpp PIL row-major (128x128 = 2048 bytes) to SH1107 page format (16 pages x 128 columns)
static void convert_pil_to_pages(const uint8_t *src, uint8_t dst[16][128]) {
    for (int page = 0; page < 16; page++) {
        int base_y = page * 8;
        uint8_t *page_dst = dst[page];
        for (int x = 0; x < 128; x++) {
            int byte_col = x >> 3;
            uint8_t mask = 0x80 >> (x & 7);
            uint8_t col_byte = 0;
            for (int bit = 0; bit < 8; bit++) {
                int y = base_y + bit;
                if (src[y * 16 + byte_col] & mask) {
                    col_byte |= (1 << bit);
                }
            }
            page_dst[x] = col_byte;
        }
    }
}

// Ultra-fast display update with dirty page tracking (only transmits modified pages)
void sh1107_display_raw(const uint8_t *raw_pil_bytes, int force_all) {
    uint8_t current_pages[16][128];
    convert_pil_to_pages(raw_pil_bytes, current_pages);

    for (int page = 0; page < 16; page++) {
        if (!force_all && has_prev && memcmp(current_pages[page], prev_pages[page], 128) == 0) {
            continue; // Skip unchanged page!
        }

        uint8_t page_cmds[] = {
            (uint8_t)(0xB0 | page),
            0x00,
            0x10
        };
        send_commands(page_cmds, 3);

        i2c_start();
        i2c_send_byte(0x78);
        i2c_send_byte(0x40);
        const uint8_t *pdata = current_pages[page];
        for (int c = 0; c < 128; c++) {
            i2c_send_byte(pdata[c]);
        }
        i2c_stop();

        memcpy(prev_pages[page], current_pages[page], 128);
    }
    has_prev = 1;
}

void sh1107_clear(void) {
    static uint8_t zeros[2048] = {0};
    sh1107_display_raw(zeros, 1);
}

void sh1107_close(void) {
    if (gpio != NULL) {
        munmap((void *)gpio, 0x1000);
        gpio = NULL;
    }
    if (g_fd >= 0) {
        close(g_fd);
        g_fd = -1;
    }
}
