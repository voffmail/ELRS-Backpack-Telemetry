#include "io_port.h"

static Stream *s_port = nullptr;

void ioBegin() {
    Serial.begin(115200);
    s_port = &Serial;
}

size_t ioWrite(const uint8_t *data, size_t len) {
    if (!s_port || !data || !len) return 0;
    return s_port->write(data, len);
}

int ioRead() {
    if (!s_port) return -1;
    return s_port->read();
}

size_t ioAvailable() {
    if (!s_port) return 0;
    return (size_t)s_port->available();
}

bool ioHostConnected() {
    return (bool)Serial;
}
