# Запуск вьюера на компьютере: Wi-Fi и ESP-NOW

На ПК телеметрию можно принимать двумя способами. Оба приводят к одному и тому
же веб-интерфейсу `tlm_viewer.py`:

- **Wi-Fi/UDP (по умолчанию)** — вьюер сам слушает UDP-порт, дополнительное
  железо не нужно.
- **ESP-NOW через USB-приемник (рекомендуется)** — приемник ESP-NOW принимает ESP-NOW и отдаёт
  CRSF по USB, а `tools/serial_bridge.py` превращает USB-поток в UDP для
  вьюера. Меньше засорения эфира, но нужен приемник ESP-NOW и кабель.

```text
Wi-Fi:    TX backpack ──Wi-Fi/UDP──► tlm_viewer.py
ESP-NOW:  TX backpack ──ESP-NOW──► ESP32-C3/S3/C6 приемник ESP-NOW ──USB──► serial_bridge.py ──UDP──► tlm_viewer.py
```

`tlm_viewer.py` **не открывает serial-порт сам**. ESP-NOW на ПК работает только
через отдельный мост `tools/serial_bridge.py` (или через Android-приложение на
телефоне).

## Общие требования

- Python 3.
- Для ESP-NOW — `pyserial`:
  - после `./init.sh` активируйте окружение: `source .toolchain/pio-env.sh`;
  - либо установите вручную: `python3 -m pip install pyserial`.
- Свободные порты: UDP `14550` и TCP `8080`.
- Для карты — интернет; ключ не нужен (см. [REFERENCE.md](REFERENCE.md)).

## Вариант 1. Wi-Fi/UDP (по умолчанию)

1. На аппаратуре: `ELRS Lua → Backpack → Telemetry → WiFi`.
   Не используйте `WiFi Connectivity` — это режим настройки передатчика.
2. Подключите компьютер к той же сети, что и бэкпак:
   - к точке `ExpressLRS TX Backpack XXXXXX` (пароль `expresslrs`), или
   - к домашней сети/хот-споту, куда подключён бэкпак.
3. Запустите вьюер:

   ```bash
   python3 tlm_viewer.py
   ```

4. Откройте `http://localhost:8080` или `http://<ip-компьютера>:8080`.

Параметры:

```bash
python3 tlm_viewer.py --udp-port 14550 --http-host 0.0.0.0 --http-port 8080
```

| Параметр | По умолчанию | Назначение |
|---|---|---|
| `--udp-port` | `14550` | UDP-порт, куда бэкпак шлёт телеметрию |
| `--http-host` | `0.0.0.0` | Адрес веб-сервера (`0.0.0.0` — доступен в сети) |
| `--http-port` | `8080` | Порт веб-интерфейса |

## Вариант 2. ESP-NOW через USB-приемник (рекомендуется)

### 1. Прошейте приемник ESP-NOW

Нужна плата с native USB — ESP32-C3 (Super Mini), ESP32-S3
или ESP32-C6 Super Mini — и прошивка `esp32-c3-usb-otg`, `esp32-s3-usb-otg`
либо `esp32-c6-usb-otg`.
Прошить можно:

- через web-flasher (Chrome/Edge на компьютере; плата определяется автоматически), или
- через PlatformIO: `./tools/pio run -d firmware -e <env> -t upload --upload-port <port>`.

Подробности — в [DEVELOP.md](../DEVELOP.md) и [DESIGN.md](DESIGN.md).

### 2. Переключите бэкпак в ESP-NOW

На аппаратуре: `ELRS Lua → Backpack → Telemetry → ESP-NOW`.

### 3. Найдите serial-порт приемника ESP-NOW

- Linux: `/dev/ttyACM0`, `/dev/ttyACM1`, … (native USB CDC);
- macOS: `/dev/tty.usbmodem*`;
- Windows: `COM3`, `COM4`, … в «Диспетчере устройств».

Список портов PlatformIO:

```bash
./tools/pio device list
```

На Linux может понадобиться доступ к порту: добавьте пользователя в группу
`dialout` и перезайдите в сессию.

### 4. Запустите вьюер и мост

Сначала вьюер (он должен слушать UDP), затем мост:

```bash
# терминал 1
python3 tlm_viewer.py

# терминал 2
source .toolchain/pio-env.sh
python3 tools/serial_bridge.py --serial /dev/ttyACM0 --udp 127.0.0.1:14550
```

Мост читает USB-поток, сканирует CRSF-кадры (`0xC8/0xEA/0xEE`, CRC8) и отправляет
каждый валидный кадр одной UDP-датаграммой. Вьюер разбирает их так же, как
Wi-Fi-телеметрию, и показывает в браузере `http://localhost:8080`.

Если вьюер запущен с другим UDP-портом, укажите его и мосту:

```bash
python3 tlm_viewer.py --udp-port 14551
python3 tools/serial_bridge.py --serial /dev/ttyACM0 --udp 127.0.0.1:14551
```

Параметры моста:

| Параметр | По умолчанию | Назначение |
|---|---|---|
| `--serial` | обязателен | serial-порт приемника ESP-NOW |
| `--baud` | `115200` | скорость; для native USB CDC обычно не важна |
| `--udp` | `127.0.0.1:14550` | адрес вьюера |
| `--broadcast` | выкл. | разрешить broadcast |
| `--stats-every` | `2.0` | период лога статистики, с (`0` — выкл.) |
| `--device-stats-every` | `10.0` | период `GET_STATS` у приемника ESP-NOW, с (`0` — выкл.) |
| `--reconnect` | `1.0` | пауза перед переоткрытием порта, с |

Мост печатает статистику в stderr: число кадров, CRC-ошибки, потери
последовательности, ответы приемника ESP-NOW на `GET_STATS`.

### 5. Настройте phrase/UID

Фраза/UID должны совпадать с бэкпаком. Настройка
идёт по тому же serial-порту, поэтому **мост нужно остановить** (порт занимает
только один процесс):

```bash
source .toolchain/pio-env.sh

# показать текущий конфиг (фраза печатается открытым текстом)
python3 tools/dongle_config.py --port /dev/ttyACM0 --show

# задать фразу
ELRS_BINDING_PHRASE='my-phrase' python3 tools/dongle_config.py --port /dev/ttyACM0

# или задать UID вручную
python3 tools/dongle_config.py --port /dev/ttyACM0 --uid AA:BB:CC:DD:EE:FE

# сбросить NVS
python3 tools/dongle_config.py --port /dev/ttyACM0 --reset
```

Фраза/UID сохраняются в NVS приемника ESP-NOW и переживают перезагрузку. На диск
компьютера `dongle_config.py` их не пишет. Подробности — в
[REFERENCE.md](REFERENCE.md#usb-приемник-esp-now).

Можно настроить приемник ESP-NOW и из Android-приложения: шестерёнка → «ESP-NOW по USB» →
binding phrase / UID.

## Что выбрать

| Критерий | Wi-Fi | ESP-NOW + USB |
|---|---|---|
| Дополнительное железо | не нужно | ESP32-C3 native USB, OTG/кабель |
| Настройка сети | AP или общая сеть | не нужна |
| Засорение 2.4 ГГц | AP/beacons/DHCP + трафик ПК | только короткие ESP-NOW-кадры |
| MAVLink/QGC | да, `Link Mode = MAVLink` | нет, только CRSF |
| ПК без Wi-Fi | нет | да |
| Быстрый старт | да | после прошивки приемника ESP-NOW |

## Диагностика

| Проблема | Что проверить |
|---|---|
| Вьюер не видит данные по Wi-Fi | `Telemetry = WiFi`, общая сеть, firewall, UDP-порт `14550` |
| `serial open failed` | правильный порт, data-кабель, права `dialout` (Linux), порт не занят |
| Мост работает, вьюер пуст | `--udp` моста совпадает с `--udp-port` вьюера; вьюер запущен |
| Порт занят | остановите мост перед `dongle_config.py` (или наоборот) |
| Приемник ESP-NOW не найден | native-USB ESP32-C3/S3/C6, прошивка `esp32-*-usb-otg`, USB-разрешение/OTG |
| Счётчики растут, связи с дроном нет | `0x14` с `LQ=0`: дрон/RX выключен или не совпадает phrase/UID |
| Карта не загружается | интернет и доступность OpenFreeMap/Esri/Sentinel; смотрите консоль браузера |

## Связанные документы

- [README](../README.md) — установка и быстрый старт.
- [REFERENCE.md](REFERENCE.md) — API, кадры, карта, диагностика.
- [BACKPACK-TELEMETRY-WIFI-VS-ESPNOW.md](BACKPACK-TELEMETRY-WIFI-VS-ESPNOW.md) — что выбрать.
- [DESIGN.md](DESIGN.md) — архитектура USB-приемника ESP-NOW.
- [DEVELOP.md](../DEVELOP.md) — сборка прошивки, web-flasher, CI.
