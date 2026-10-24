#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <time.h>

// BCM2835 / BCM2711 GPIO register offsets in /dev/gpiomem (4-byte words)
#define GPFSEL0   0
#define GPSET0    7
#define GPCLR0    10
#define GPLEV0    13

// GPIO 2 = SDA, GPIO 3 = SCL
#define SDA_PIN 2
#define SCL_PIN 3

volatile uint32_t *gpio;

// Set pin as Output
static inline void gpio_as_output(int pin) {
    int reg = pin / 10;
    int shift = (pin % 10) * 3;
    uint32_t val = gpio[reg];
    val &= ~(7 << shift);
    val |= (1 << shift); // 001 = output
    gpio[reg] = val;
}

// Set pin as Input (high-Z, relying on internal/external pull-up)
static inline void gpio_as_input(int pin) {
    int reg = pin / 10;
    int shift = (pin % 10) * 3;
    uint32_t val = gpio[reg];
    val &= ~(7 << shift); // 000 = input
    gpio[reg] = val;
}

// Drive pin low (0V)
static inline void gpio_set_low(int pin) {
    gpio[GPCLR0] = (1 << pin);
}

// Drive pin high (3.3V)
static inline void gpio_set_high(int pin) {
    gpio[GPSET0] = (1 << pin);
}

// Set pin to Alt0 (I2C1 hardware controller)
static inline void gpio_as_alt0(int pin) {
    int reg = pin / 10;
    int shift = (pin % 10) * 3;
    uint32_t val = gpio[reg];
    val &= ~(7 << shift);
    val |= (4 << shift); // 100 = alt0
    gpio[reg] = val;
}

static inline void delay_half_us(void) {
    for (volatile int i = 0; i < 30; i++) {
        __asm__ volatile ("nop");
    }
}

// Open-drain simulation:
// To drive 0: set as output and drive low.
// To release (1): set as input (pull-up pulls it high).
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
    // 9th clock: ACK (we clock it, ignoring whatever is on SDA!)
    sda_1(); // Release SDA for slave
    scl_1();
    delay_half_us();
    scl_0();
    delay_half_us();
}

static void send_commands(const uint8_t *cmds, int count) {
    i2c_start();
    i2c_send_byte(0x78); // OLED I2C address 0x3C << 1
    i2c_send_byte(0x00); // Control byte: Co=0, D/C=0 (command stream)
    for (int i = 0; i < count; i++) {
        i2c_send_byte(cmds[i]);
    }
    i2c_stop();
}

static void send_data_page(uint8_t page, const uint8_t *data) {
    // Set page address
    uint8_t page_cmds[] = {
        0xB0 | (page & 0x0F), // Page address
        0x00,                 // Lower column 0
        0x10                  // Higher column 0
    };
    send_commands(page_cmds, sizeof(page_cmds));

    // Send 128 bytes of pixel data
    i2c_start();
    i2c_send_byte(0x78);
    i2c_send_byte(0x40); // Control byte: Co=0, D/C=1 (data stream)
    for (int i = 0; i < 128; i++) {
        i2c_send_byte(data[i]);
    }
    i2c_stop();
}

int main(int argc, char **argv) {
    int fd = open("/dev/gpiomem", O_RDWR | O_SYNC);
    if (fd < 0) {
        perror("open /dev/gpiomem");
        return 1;
    }
    gpio = (volatile uint32_t *)mmap(NULL, 0x1000, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (gpio == MAP_FAILED) {
        perror("mmap");
        return 1;
    }

    printf(">>> Initializing SH1107 OLED via open-drain bitbang (ignoring NACK)...\n");

    // Standard SH1107 128x128 Initialization
    uint8_t init_sequence[] = {
        0xAE,       // Display OFF
        0x00,       // Set lower column address 0
        0x10,       // Set higher column address 0
        0xDC, 0x00, // Set display start line 0
        0x81, 0x7F, // Set contrast to 127
        0x20,       // Set page addressing mode
        0xA0,       // Segment remap normal (0 to 127)
        0xC0,       // COM output scan direction normal (0 to 127)
        0xA4,       // Entire display normal (resume RAM)
        0xA6,       // Normal display (non-inverted)
        0xA8, 0x7F, // Set multiplex ratio: 128 lines (0x7F)
        0xD3, 0x00, // Set display offset 0
        0xD5, 0x50, // Set display clock divide
        0xDB, 0x35, // Set VCOM deselect level
        0xD9, 0x22, // Set pre-charge period
        0xAF        // Display ON!
    };
    send_commands(init_sequence, sizeof(init_sequence));

    printf(">>> Drawing test pattern: 128x128 border and MiniMix text/bars...\n");

    uint8_t frame[16][128];
    for (int p = 0; p < 16; p++) {
        for (int col = 0; col < 128; col++) {
            uint8_t byte_val = 0;
            // Border around all 4 edges
            if (p == 0) byte_val |= 0x01;         // Top edge
            if (p == 15) byte_val |= 0x80;        // Bottom edge
            if (col == 0 || col == 127) byte_val = 0xFF; // Left & Right edges

            // Diagnostic pattern in the middle: checkerboard stripes
            if (p >= 3 && p <= 12 && col >= 20 && col <= 107) {
                if (((col / 8) + p) % 2 == 0) {
                    byte_val |= 0xAA;
                } else {
                    byte_val |= 0x55;
                }
            }
            frame[p][col] = byte_val;
        }
    }

    // Write all 16 pages (128x128 pixels)
    for (int p = 0; p < 16; p++) {
        send_data_page(p, frame[p]);
    }

    printf(">>> SUCCESS: Full 128x128 test pattern written to OLED!\n");

    // Restore pins to ALT0 so hardware I2C can be used if needed
    // gpio_as_alt0(SDA_PIN);
    // gpio_as_alt0(SCL_PIN);
    close(fd);
    return 0;
}
