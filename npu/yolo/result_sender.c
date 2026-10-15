
/*
    Custom D3-G TCP result sender extracted from the local YOLO integration.
    ENLIGHT SDK types are provided by the separately installed SDK.
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

#define YOLO_D3G_DEFAULT_HOST   "127.0.0.1"
#define YOLO_D3G_DEFAULT_PORT   6001
#define YOLO_CONNECT_TIMEOUT_US 100000

static int g_yolo_d3g_socket = -1;

static int yolo_env_disabled(void)
{
    const char *disabled = getenv("YOLO_TCP_DISABLE");
    return disabled != NULL &&
           (strcmp(disabled, "1") == 0 || strcmp(disabled, "true") == 0);
}

static const char *yolo_d3g_host(void)
{
    const char *host = getenv("YOLO_RESULT_HOST");
    if (host == NULL || host[0] == '\0')
        host = getenv("D3G_RESULT_HOST");
    if (host == NULL || host[0] == '\0')
        host = getenv("D3G_HOST");
    if (host == NULL || host[0] == '\0')
        host = YOLO_D3G_DEFAULT_HOST;
    return host;
}

static int yolo_d3g_port(void)
{
    const char *port = getenv("YOLO_RESULT_PORT");
    if (port == NULL || port[0] == '\0')
        port = getenv("D3G_YOLO_RESULT_PORT");
    if (port == NULL || port[0] == '\0')
        return YOLO_D3G_DEFAULT_PORT;
    return atoi(port);
}

static void yolo_close_socket(void)
{
    if (g_yolo_d3g_socket >= 0) {
        close(g_yolo_d3g_socket);
        g_yolo_d3g_socket = -1;
    }
}

static int yolo_connect_with_timeout(const struct addrinfo *addr)
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
    timeout.tv_usec = YOLO_CONNECT_TIMEOUT_US;

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

static int yolo_open_d3g_socket(void)
{
    char port_text[16];
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    struct addrinfo *addr = NULL;
    int sock = -1;

    if (g_yolo_d3g_socket >= 0)
        return g_yolo_d3g_socket;

    snprintf(port_text, sizeof(port_text), "%d", yolo_d3g_port());
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    if (getaddrinfo(yolo_d3g_host(), port_text, &hints, &result) != 0)
        return -1;

    for (addr = result; addr != NULL; addr = addr->ai_next) {
        sock = yolo_connect_with_timeout(addr);
        if (sock >= 0)
            break;
    }

    freeaddrinfo(result);
    g_yolo_d3g_socket = sock;
    return g_yolo_d3g_socket;
}

static int yolo_send_all(const char *message, int length)
{
    int sent = 0;

    if (yolo_env_disabled())
        return 0;

    if (yolo_open_d3g_socket() < 0) {
        post_process_log("YOLO TCP: cannot connect to %s:%d\n",
                         yolo_d3g_host(), yolo_d3g_port());
        return -1;
    }

    while (sent < length) {
#ifdef MSG_NOSIGNAL
        int flags = MSG_NOSIGNAL;
#else
        int flags = 0;
#endif
        int rc = (int)send(g_yolo_d3g_socket, message + sent,
                           (size_t)(length - sent), flags);
        if (rc <= 0) {
            yolo_close_socket();
            return -1;
        }
        sent += rc;
    }

    return 0;
}

static int yolo_append(char *buffer, int size, int offset, const char *fmt, ...)
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

static int yolo_build_json(const enlight_objs_t *objects, char *buffer, int size)
{
    int i;
    int offset = 0;
    int count = 0;

    if (objects != NULL)
        count = objects->cnt;

    offset = yolo_append(buffer, size, offset,
                         "{\"source\":\"yocto-yolo\",\"objects\":[");

    for (i = 0; i < count; i++) {
        const enlight_obj_t *obj = &objects->obj[i];
        float width = obj->x_max - obj->x_min;
        float height = obj->y_max - obj->y_min;

        if (width < 0.0f)
            width = 0.0f;
        if (height < 0.0f)
            height = 0.0f;

        if (i > 0)
            offset = yolo_append(buffer, size, offset, ",");

        offset = yolo_append(
            buffer,
            size,
            offset,
            "{\"class\":%d,\"score\":%.4f,\"x\":%.2f,\"y\":%.2f,"
            "\"w\":%.2f,\"h\":%.2f}",
            obj->cls,
            obj->score,
            obj->x_min,
            obj->y_min,
            width,
            height);
    }

    offset = yolo_append(buffer, size, offset, "]}\n");
    return offset;
}

void yolo_send_objects(const enlight_objs_t *objects)
{
    char message[16384];
    int length;
    int count = 0;

    if (objects != NULL)
        count = objects->cnt;

    length = yolo_build_json(objects, message, (int)sizeof(message));
    if (length <= 0 || length >= (int)sizeof(message)) {
        post_process_log("YOLO TCP: message too large, objects=%d\n", count);
        return;
    }

    if (yolo_send_all(message, length) == 0)
        post_process_log("YOLO TCP sent: objects=%d\n", count);
}
