#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#include <linux/fb.h>

#define LANE_ROWS 18
#define LANE_COUNT 4
#define INPUT_WIDTH 800.0f
#define INPUT_HEIGHT 288.0f

static const int row_anchor[LANE_ROWS] = {
    121, 131, 141, 150, 160, 170, 180, 189, 199,
    209, 219, 228, 238, 248, 258, 267, 277, 287
};

typedef struct {
    int x;
    int y;
} point_t;

static void put_pixel(uint8_t* fb, int stride, int width, int height, int x, int y, uint32_t color)
{
    if (x < 0 || y < 0 || x >= width || y >= height) {
        return;
    }

    *(uint32_t*)(fb + y * stride + x * 4) = color;
}

static void draw_disc(uint8_t* fb, int stride, int width, int height, int cx, int cy, int radius, uint32_t color)
{
    for (int y = -radius; y <= radius; y++) {
        for (int x = -radius; x <= radius; x++) {
            if (x * x + y * y <= radius * radius) {
                put_pixel(fb, stride, width, height, cx + x, cy + y, color);
            }
        }
    }
}

static void draw_line(uint8_t* fb, int stride, int width, int height, point_t a, point_t b, uint32_t color)
{
    int x0 = a.x;
    int y0 = a.y;
    int x1 = b.x;
    int y1 = b.y;
    int dx = abs(x1 - x0);
    int sx = x0 < x1 ? 1 : -1;
    int dy = -abs(y1 - y0);
    int sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;

    for (;;) {
        draw_disc(fb, stride, width, height, x0, y0, 3, color);

        if (x0 == x1 && y0 == y1) {
            break;
        }

        int e2 = 2 * err;
        if (e2 >= dy) {
            err += dy;
            x0 += sx;
        }
        if (e2 <= dx) {
            err += dx;
            y0 += sy;
        }
    }
}

static void clear_framebuffer(uint8_t* fb, size_t map_size)
{
    memset(fb, 0, map_size);
}

static void draw_lanes(uint8_t* fb, int stride, int width, int height,
                       point_t points[LANE_COUNT][LANE_ROWS],
                       int valid[LANE_COUNT][LANE_ROWS])
{
    const uint32_t colors[LANE_COUNT] = {
        0xffffd000u,
        0xff00ff00u,
        0xff00ffffu,
        0xffff40ffu,
    };

    for (int lane = 0; lane < LANE_COUNT; lane++) {
        int has_prev = 0;
        point_t prev = {0, 0};

        for (int row = 0; row < LANE_ROWS; row++) {
            if (!valid[lane][row]) {
                has_prev = 0;
                continue;
            }

            draw_disc(fb, stride, width, height, points[lane][row].x, points[lane][row].y, 5, colors[lane]);

            if (has_prev) {
                draw_line(fb, stride, width, height, prev, points[lane][row], colors[lane]);
            }

            prev = points[lane][row];
            has_prev = 1;
        }
    }
}

static void reset_lanes(point_t points[LANE_COUNT][LANE_ROWS], int valid[LANE_COUNT][LANE_ROWS])
{
    memset(points, 0, sizeof(point_t) * LANE_COUNT * LANE_ROWS);
    memset(valid, 0, sizeof(int) * LANE_COUNT * LANE_ROWS);
}

int main(int argc, char** argv)
{
    const char* fb_path = argc > 1 ? argv[1] : "/dev/fb0";
    int fb_fd;
    struct fb_var_screeninfo vinfo;
    struct fb_fix_screeninfo finfo;
    size_t map_size;
    uint8_t* fb;
    char line[512];
    point_t points[LANE_COUNT][LANE_ROWS];
    int valid[LANE_COUNT][LANE_ROWS];
    int collecting = 0;

    fb_fd = open(fb_path, O_RDWR);
    if (fb_fd < 0) {
        fprintf(stderr, "failed to open %s: %s\n", fb_path, strerror(errno));
        return 1;
    }

    if (ioctl(fb_fd, FBIOGET_VSCREENINFO, &vinfo) < 0 ||
        ioctl(fb_fd, FBIOGET_FSCREENINFO, &finfo) < 0) {
        fprintf(stderr, "failed to read framebuffer info: %s\n", strerror(errno));
        close(fb_fd);
        return 1;
    }

    if (vinfo.bits_per_pixel != 32) {
        fprintf(stderr, "unsupported framebuffer bpp: %u\n", vinfo.bits_per_pixel);
        close(fb_fd);
        return 1;
    }

    map_size = finfo.line_length * vinfo.yres_virtual;
    fb = mmap(NULL, map_size, PROT_READ | PROT_WRITE, MAP_SHARED, fb_fd, 0);
    if (fb == MAP_FAILED) {
        fprintf(stderr, "failed to mmap framebuffer: %s\n", strerror(errno));
        close(fb_fd);
        return 1;
    }

    reset_lanes(points, valid);
    clear_framebuffer(fb, map_size);

    /*
     * Added by Codex at 2026-05-25 17:41:00 KST.
     * Parse tcnnapp Point[j][k] logs and draw UFLD lanes on /dev/fb0.
     */
    while (fgets(line, sizeof(line), stdin) != NULL) {
        int row;
        int lane;
        float x;
        float y;

        fputs(line, stdout);
        fflush(stdout);

        if (sscanf(line, "Point[%d][%d] = (%f, %f)", &row, &lane, &x, &y) == 4) {
            if (!collecting) {
                reset_lanes(points, valid);
                collecting = 1;
            }

            if (row >= 0 && row < LANE_ROWS && lane >= 0 && lane < LANE_COUNT) {
                /*
                 * Adjusted by Codex at 2026-05-25 17:45:19 KST.
                 * tcnnapp's intended UFLD draw path uses row_anchor[17 - row],
                 * so do not use the printed y value directly.
                 */
                int sx = (int)(x * (float)vinfo.xres / INPUT_WIDTH);
                int sy = (int)((float)row_anchor[LANE_ROWS - 1 - row] *
                               (float)vinfo.yres / INPUT_HEIGHT);

                points[lane][row].x = sx;
                points[lane][row].y = sy;
                valid[lane][row] = 1;

                clear_framebuffer(fb, map_size);
                draw_lanes(fb, finfo.line_length, vinfo.xres, vinfo.yres, points, valid);
            }

            continue;
        }

        if (collecting) {
            clear_framebuffer(fb, map_size);
            draw_lanes(fb, finfo.line_length, vinfo.xres, vinfo.yres, points, valid);
            collecting = 0;
        }
    }

    munmap(fb, map_size);
    close(fb_fd);
    return 0;
}
