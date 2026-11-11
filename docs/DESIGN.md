# ELRS ESP-NOW USB Dongle — техническое описание

## 1. Назначение

USB-приемник ESP-NOW принимает телеметрию ExpressLRS от TX-бэкпака по ESP-NOW и отдаёт
её в смартфон по native USB CDC. Разбор CRSF и отображение остаются на
стороне Android-приложения или внешнего вьюера. Приемник ESP-NOW — прозрачный транспорт.

```text
ELRS TX module
      │ UART
      ▼
TX backpack (ESP-NOW, group MAC)
      │ ESP-NOW
      ▼
ESP32-C3/S3/C6 dongle ──USB CDC──► Android
                              │
                        CRSF-кадры
                              │
                     телеметрия и карта
```

## 2. Решения

| Вопрос | Решение |
|---|---|
| Формат выхода | сырые ESP-NOW payload'ы с CRSF-кадрами, native USB CDC |
| MAVLink | не формируется (донгл остаётся CRSF; MAVLink — Wi-Fi-путь приложения) |
| Android | встроенный вьюер из каталога `android/` |
| Конфигурация | NVS + протокол `AA 55` по USB CDC |
| ПК-вьюер | `tlm_viewer.py` + `tools/serial_bridge.py` |
| Лицензия | MIT |

## 3. Прошивка

| Параметр | Значение |
|---|---|
| Env | `esp32-c3-usb-otg`, `esp32-s3-usb-otg`, `esp32-c6-usb-otg` |
| Плата | ESP32-C3 / ESP32-S3 / ESP32-C6 с native USB (Super Mini, DevKitC-1) |
| Данные | `Serial` (USB CDC) |
| PHY | BGN (`11B│11G│11N`) |

Фраза/UID хранятся в NVS. Прошивка собирается только под native USB.
S3-сборка рассчитана на `esp32-s3-devkitc-1`; LED — WS2812 на GPIO48
(переопределяется `-DELRS_LED_PIN`). C6-сборка — ESP32-C6 Super Mini,
статусный LED GPIO15 (active-high).

## 4. ESP-NOW и binding

### 4.1. UID

Два режима:

- **phrase**: UID = первые 6 байт
  `MD5("-DMY_BINDING_PHRASE=\"<phrase>\"")`, младший бит первого байта
  очищен. Пустая phrase означает factory MAC.
- **manual UID**: ровно 6 байт; all-zero запрещён; LSB первого байта
  очищается как в ELRS. Phrase может быть пустой.

Приемник ESP-NOW ставит UID на STA-интерфейс до старта ESP-NOW. Android-приложение и
`tools/dongle_config.py` читают и меняют режим и phrase/UID через
конфигурационный протокол.

### 4.2. PHY

PHY — BGN (`11B│11G│11N`). Другие PHY-режимы не используются.

### 4.3. Приём

- Wi-Fi STA без подключения к AP.
- `esp_wifi_stop` → `esp_wifi_set_mac` → `esp_wifi_start`.
- `esp_now_init`, `esp_now_register_recv_cb`.
- Callback только копирует кадр в очередь; запись в USB — в `loop`.
- При переполнении очереди отбрасывается самый старый кадр.

## 5. USB и поток данных

### 5.1. Порт

- Данные и конфигурация идут в `Serial` (native USB CDC).
- `CORE_DEBUG_LEVEL=0`; в поток данных ничего не печатается.
- Отладка, если включена, выводится в `Serial0` и не попадает в USB-поток.

### 5.2. Формат

Приемник ESP-NOW отдаёт сырой ESP-NOW payload. Обычно это MSP v2-обёртка `$X<` + CRSF.
Android-приложение сканирует поток на CRSF-адреса `0xC8/0xEA/0xEE`, проверяет
длину и CRC8 и передаёт каждый валидный CRSF-кадр в общий парсер телеметрии.

## 6. Конфигурационный протокол

Кадр:

```text
AA 55 | ver=1 | type | len LE16 | payload | CRC16 LE16
```

CRC16-CCITT-FALSE по `ver..payload`. Команды:

- `GET_CONFIG` — UID, phrase, version, uidMode;
- `SET_CONFIG` — phrase (phrase-режим; пустая phrase разрешена);
- `SET_UID` — 6-байтовый UID (manual-режим);
- `GET_STATS` — счётчики и ready;
- `RESET`, `PING`.

Фраза/UID сохраняются в NVS. Factory MAC используется только как
boot-fallback, когда UID не настроен.

## 7. Android-приложение

- USB host + `usb-serial-for-android` (CDC ACM), без root.
- Приложение принимает только native-USB приемники ESP-NOW Espressif (`VID 0x303A`).
- При открытии приложение само подключается к найденному USB-приемнику ESP-NOW.
- Конфиг читается автоматически.
- Phrase/Manual UID — переключатель; редактируется только одно поле.
- Источник телеметрии переключается в настройках (шестерёнка в шапке):
  «Сеть» (Wi-Fi/UDP) или «ESP-NOW по USB».
- Foreground service + `PARTIAL_WAKE_LOCK`; Wi-Fi-локи держатся только в
  сетевом режиме.
- Уведомление тихое (LOW, без звука/вибрации) в обычном режиме; при переходе в
  энергосбережение постоянное уведомление один раз подаёт звук. Цвет и иконка
  соответствуют статусу связи.

## 8. Индикация

- ESP32-C3 с native USB: синий LED GPIO8, active-low, управление `digitalWrite`.
- ESP32-S3-DevKitC-1: WS2812 на GPIO48, синий при активности (`neopixelWrite`).
  `-DELRS_LED_PIN=<n>` меняет пин, `-DELRS_LED_PIN=-1` отключает LED,
  `-DELRS_LED_RGB=0` включает режим обычного LED.
- ESP32-C6 Super Mini: обычный статусный LED GPIO15, active-high; WS2812 на
  GPIO8 не используется.

`LinkStatus` не зависит от протокола:

```cpp
struct LinkStatus {
    bool known;
    bool up;
    uint8_t quality;
    uint32_t lastMs;
    LinkSource source; // None, Crsf, Mavlink
};
```

Сейчас его заполняет CRSF-парсер (`0x14`); позже сможет заполнять
MAVLink-парсер. Состояния LED:

- off — нет UID, нет USB-хоста или нет пакетов >3 с;
- solid — пакеты идут, но линка/телеметрии нет (включая LQ=0);
- blink 200/200 — пакеты и `LinkStatus.up`;
- 3 импульса / 2 с — ошибка ESP-NOW или queue drops.

Таймаут потери линка — 0.5 с.

## 9. Симулятор и стенд

`sim/` имитирует Betaflight и отдаёт полный набор CRSF-кадров: GPS, GPS time,
GPS extended, Vario, Battery, Baro, Link, Attitude, Flight mode, Device info
и sequence. GPS движется по кругу (радиус/скорость — build flags), ~46
пакетов/с.

Стенд без телефона: `sim` → приемник ESP-NOW → USB → `tools/serial_bridge.py` → UDP
`14550` → внешний вьюер.

## 10. Web Flasher и CI

- `webflasher/` — страница ESP Web Tools (Web Serial) с автоопределением платы.
- Прошиваются `esp32-c3-usb-otg`, `esp32-s3-usb-otg` и `esp32-c6-usb-otg`;
  каждый образ — merged binary с offset 0, общий `manifest.json` содержит builds
  по chipFamily.
- `scripts/make_webflasher.py` собирает Pages-сайт: index, общий `manifest.json`,
  merged-образы и SHA256SUMS.
- `.github/workflows/webflasher.yml` на GitHub Release собирает образы,
  деплоит GitHub Pages и прикладывает assets к релизу.
- Pages включается один раз: Settings → Pages → Source: GitHub Actions.

Другие workflows: сборка прошивки и APK, тесты.

## 11. Риски и ограничения

1. **Binding phrase/UID**: неверные значения → тишина; нужна диагностика
   счётчиков и LED.
2. **Native-USB reset**: открытие CDC-порта может один раз перезагрузить
   плату; приложение и мост переживают reconnect.
3. **Питание**: телефон не заряжается при OTG; учитывать ток и нагрев.
4. **MAVLink**: приложение поддерживает MAVLink в Wi-Fi-режиме; USB-приемник
   ESP-NOW остаётся CRSF-транспортом. Для QGC нужен Wi-Fi-путь или отдельный
   MAVLink-мост.
5. **Web Serial**: только desktop Chrome/Edge; fallback — PlatformIO/esptool.

## 12. Лицензия

Новый код — MIT. Сторонние компоненты и лицензии —
в [THIRD_PARTY.md](../THIRD_PARTY.md).
