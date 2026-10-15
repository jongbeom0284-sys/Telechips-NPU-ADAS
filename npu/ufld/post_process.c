
/*
    Openedges Enlight Network Compiler
    UFLD lane post-process + D3-G TCP result sender
*/

#include "stdint.h"
#include "enlight_network.h"

#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#ifdef __i386__
#   include <stdio.h>
#   define post_process_log(...) do {printf(__VA_ARGS__);} while(0)
#else
#   define post_process_log(...) do {_printf(__VA_ARGS__);} while(0)
#endif

#define UFLD_GRIDING_NUM        200
#define UFLD_GRIDING_WITH_NONE  201
#define UFLD_ROWS               18
#define UFLD_LANES              4
#define UFLD_IMAGE_WIDTH        1280
#define UFLD_IMAGE_HEIGHT       720
#define UFLD_INPUT_WIDTH        800
#define UFLD_INPUT_HEIGHT       288
#define UFLD_D3G_DEFAULT_HOST   "127.0.0.1"
#define UFLD_D3G_DEFAULT_PORT   6000
#define UFLD_CONNECT_TIMEOUT_US 100000

typedef struct {
    int count;
    int x[UFLD_ROWS];
    int y[UFLD_ROWS];
} ufld_lane_points_t;

static int g_d3g_socket = -1;

static const int k_row_anchor[UFLD_ROWS] = {
    121, 131, 141, 150, 160, 170, 180, 189, 199,
    209, 219, 228, 238, 248, 258, 267, 277, 287
};

static int ufld_env_disabled(void)
{
    const char *disabled = getenv("UFLD_TCP_DISABLE");
    return disabled != NULL &&
           (strcmp(disabled, "1") == 0 || strcmp(disabled, "true") == 0);
}

static const char *ufld_d3g_host(void)
{
    const char *host = getenv("D3G_RESULT_HOST");
    if (host == NULL || host[0] == '\0')
        host = getenv("D3G_HOST");
    if (host == NULL || host[0] == '\0')
        host = UFLD_D3G_DEFAULT_HOST;
    return host;
}

static int ufld_d3g_port(void)
{
    const char *port = getenv("D3G_RESULT_PORT");
    if (port == NULL || port[0] == '\0')
        return UFLD_D3G_DEFAULT_PORT;
    return atoi(port);
}

static void ufld_close_socket(void)
{
    if (g_d3g_socket >= 0) {
        close(g_d3g_socket);
        g_d3g_socket = -1;
    }
}

static int ufld_connect_with_timeout(const struct addrinfo *addr)
{
    int sock;
    int flags;
    int rc;
    fd_set wfds;
    struct timeval timeout;
    int err = 0;
    socklen_t err_len = sizeof(err);

    sock = socket(addr->ai_family, addr->ai_socktype, addr->ai_protocol);
    if (sock < 0)
        return -1;

    flags = fcntl(sock, F_GETFL, 0);
    if (flags < 0 || fcntl(sock, F_SETFL, flags | O_NONBLOCK) < 0) {
        close(sock);
        return -1;
    }

    rc = connect(sock, addr->ai_addr, addr->ai_addrlen);
    if (rc < 0 && errno != EINPROGRESS) {
        close(sock);
        return -1;
    }

    FD_ZERO(&wfds);
    FD_SET(sock, &wfds);
    timeout.tv_sec = 0;
    timeout.tv_usec = UFLD_CONNECT_TIMEOUT_US;

    rc = select(sock + 1, NULL, &wfds, NULL, &timeout);
    if (rc <= 0 ||
        getsockopt(sock, SOL_SOCKET, SO_ERROR, &err, &err_len) < 0 ||
        err != 0) {
        close(sock);
        return -1;
    }

    (void)fcntl(sock, F_SETFL, flags);
    return sock;
}

static int ufld_open_d3g_socket(void)
{
    char port_text[16];
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    struct addrinfo *addr = NULL;
    int sock = -1;

    if (g_d3g_socket >= 0)
        return g_d3g_socket;

    snprintf(port_text, sizeof(port_text), "%d", ufld_d3g_port());
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    if (getaddrinfo(ufld_d3g_host(), port_text, &hints, &result) != 0)
        return -1;

    for (addr = result; addr != NULL; addr = addr->ai_next) {
        sock = ufld_connect_with_timeout(addr);
        if (sock >= 0)
            break;
    }

    freeaddrinfo(result);
    g_d3g_socket = sock;
    return g_d3g_socket;
}

static int ufld_send_all(const char *message, int length)
{
    int sent = 0;

    if (ufld_env_disabled())
        return 0;

    if (ufld_open_d3g_socket() < 0) {
        post_process_log("UFLD TCP: cannot connect to %s:%d\n",
                         ufld_d3g_host(), ufld_d3g_port());
        return -1;
    }

    while (sent < length) {
#ifdef MSG_NOSIGNAL
        int flags = MSG_NOSIGNAL;
#else
        int flags = 0;
#endif
        int rc = (int)send(g_d3g_socket, message + sent,
                           (size_t)(length - sent), flags);
        if (rc <= 0) {
            ufld_close_socket();
            return -1;
        }
        sent += rc;
    }

    return 0;
}

static int ufld_logit_index(int grid, int row, int lane)
{
    return (grid * UFLD_ROWS * UFLD_LANES) + (row * UFLD_LANES) + lane;
}

static int ufld_argmax_grid(const int8_t *logits, int row, int lane)
{
    int best_grid = 0;
    int8_t best_value = logits[ufld_logit_index(0, row, lane)];
    int grid;

    for (grid = 1; grid < UFLD_GRIDING_WITH_NONE; grid++) {
        int8_t value = logits[ufld_logit_index(grid, row, lane)];
        if (value > best_value) {
            best_value = value;
            best_grid = grid;
        }
    }

    return best_grid;
}

static void ufld_decode_lanes(const int8_t *logits,
                              ufld_lane_points_t lanes[UFLD_LANES])
{
    const float col_sample_w = (float)(UFLD_INPUT_WIDTH - 1) /
                               (float)(UFLD_GRIDING_NUM - 1);
    int lane;
    int row;

    memset(lanes, 0, sizeof(ufld_lane_points_t) * UFLD_LANES);

    for (lane = 0; lane < UFLD_LANES; lane++) {
        for (row = 0; row < UFLD_ROWS; row++) {
            int best_grid = ufld_argmax_grid(logits, row, lane);
            int x;
            int y;

            if (best_grid >= UFLD_GRIDING_NUM)
                continue;

            x = (int)(((float)(best_grid + 1) * col_sample_w *
                       (float)UFLD_IMAGE_WIDTH / (float)UFLD_INPUT_WIDTH) - 1.0f);
            y = (int)(((float)UFLD_IMAGE_HEIGHT *
                       (float)k_row_anchor[row] / (float)UFLD_INPUT_HEIGHT) - 1.0f);

            if (x < 0)
                x = 0;
            if (x >= UFLD_IMAGE_WIDTH)
                x = UFLD_IMAGE_WIDTH - 1;

            lanes[lane].x[lanes[lane].count] = x;
            lanes[lane].y[lanes[lane].count] = y;
            lanes[lane].count++;
        }
    }
}

static int ufld_valid_lane_count(const ufld_lane_points_t lanes[UFLD_LANES])
{
    int lane;
    int count = 0;

    for (lane = 0; lane < UFLD_LANES; lane++) {
        if (lanes[lane].count > 2)
            count++;
    }

    return count;
}

static float ufld_compute_steer(const ufld_lane_points_t lanes[UFLD_LANES])
{
    int lane;
    int have = 0;
    int left_x = UFLD_IMAGE_WIDTH;
    int right_x = 0;

    for (lane = 0; lane < UFLD_LANES; lane++) {
        int bottom_x;
        if (lanes[lane].count <= 2)
            continue;

        bottom_x = lanes[lane].x[lanes[lane].count - 1];
        if (bottom_x < left_x)
            left_x = bottom_x;
        if (bottom_x > right_x)
            right_x = bottom_x;
        have++;
    }

    if (have < 2)
        return 0.0f;

    return (((float)(left_x + right_x) * 0.5f) -
            ((float)UFLD_IMAGE_WIDTH * 0.5f)) /
           ((float)UFLD_IMAGE_WIDTH * 0.5f);
}

static int ufld_append(char *buffer, int size, int offset, const char *fmt, ...)
{
    va_list ap;
    int wrote;

    if (offset >= size)
        return offset;

    va_start(ap, fmt);
    wrote = vsnprintf(buffer + offset, (size_t)(size - offset), fmt, ap);
    va_end(ap);

    if (wrote < 0)
        return offset;
    if (offset + wrote >= size)
        return size - 1;
    return offset + wrote;
}

static int ufld_build_json(const ufld_lane_points_t lanes[UFLD_LANES],
                           float steer,
                           char *buffer,
                           int size)
{
    int lane;
    int point;
    int offset = 0;
    int first_lane = 1;
    float confidence = (float)ufld_valid_lane_count(lanes) / (float)UFLD_LANES;

    offset = ufld_append(
        buffer, size, offset,
        "{\"source\":\"yocto-ufld\",\"lane\":{\"steer\":%.4f,"
        "\"unit\":\"normalized\",\"confidence\":%.3f},\"lanePoints\":[",
        steer, confidence);

    for (lane = 0; lane < UFLD_LANES; lane++) {
        if (lanes[lane].count <= 2)
            continue;

        if (!first_lane)
            offset = ufld_append(buffer, size, offset, ",");
        first_lane = 0;

        offset = ufld_append(buffer, size, offset, "[");
        for (point = 0; point < lanes[lane].count; point++) {
            if (point > 0)
                offset = ufld_append(buffer, size, offset, ",");
            offset = ufld_append(buffer, size, offset, "[%d,%d]",
                                 lanes[lane].x[point], lanes[lane].y[point]);
        }
        offset = ufld_append(buffer, size, offset, "]");
    }

    offset = ufld_append(buffer, size, offset, "],\"objects\":[]}\n");
    return offset;
}

static int ufld_postprocess_and_send(enlight_act_tensor_t *output)
{
    ufld_lane_points_t lanes[UFLD_LANES];
    const int8_t *logits;
    int valid_lanes;
    float steer;
    char message[4096];
    int length;

    if (output == NULL)
        return -1;

    logits = (const int8_t *)enlight_get_tensor_addr(output);
    if (logits == NULL)
        return -1;

    ufld_decode_lanes(logits, lanes);
    valid_lanes = ufld_valid_lane_count(lanes);

    if (valid_lanes < 2) {
        post_process_log("UFLD lane result ignored: valid_lanes=%d\n",
                         valid_lanes);
        return valid_lanes;
    }

    steer = ufld_compute_steer(lanes);
    if (steer < -1.0f)
        steer = -1.0f;
    if (steer > 1.0f)
        steer = 1.0f;

    length = ufld_build_json(lanes, steer, message, (int)sizeof(message));
    if (length <= 0 || length >= (int)sizeof(message))
        return -1;

    if (ufld_send_all(message, length) == 0)
        post_process_log("UFLD TCP sent: steer=%.4f lanes=%d\n",
                         steer, valid_lanes);

    return valid_lanes;
}


/** @brief Run custom post-processing
 *
 *      Unknonw post-processing
 *
 *
 *  @param net_inst         instance Network instance.
 *  @param output_base      output tensor buffer base
 *  @param reserved
 *
 *  @return Return number of output
 */
int run_post_process(
    void *net_inst,
    void *output_base,
    int  num_input,
    void *reserved)
{
    enlight_network_t *inst;
    enlight_custom_postproc_t* custom_param;

    int i, num_output;
    enlight_act_tensor_t* output_tensors[MAX_NUM_OUTPUT];

    (void)num_input;
    (void)reserved;

    inst = (enlight_network_t *)net_inst;
    custom_param = (enlight_custom_postproc_t*)inst->post_proc_extension;

    num_output = enlight_custom_get_output_tensors(custom_param, output_tensors);

    for (i = 0; i < num_output; i++)
        output_tensors[i]->base = output_base;

    if (num_output > 0)
        (void)ufld_postprocess_and_send(output_tensors[0]);

    return num_output;
}
