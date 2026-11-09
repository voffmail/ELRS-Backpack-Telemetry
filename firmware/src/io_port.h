#pragma once

#include <Arduino.h>

void ioBegin();
size_t ioWrite(const uint8_t *data, size_t len);
int ioRead();
size_t ioAvailable();

// True when a USB host has the data/control port open.
bool ioHostConnected();
