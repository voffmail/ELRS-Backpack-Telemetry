# ELRS Backpack Telemetry

[English follow Russian](#english)

Android-приложение для телеметрии ExpressLRS: принимает данные по Wi-Fi от TX-бэкпака и показывает их в двух вкладках — «Телеметрия» и «Карта». Карта работает при наличии интернета. Записать трек вместе с телеметрией можно вручную или автоматически, а затем воспроизвести на карте.

```
Дрон / FC ──► ELRS RX ──► TX-модуль ──► ELRS Backpack ──Wi-Fi/UDP──► приложение
```

<table>
  <tr>
    <td><img src="docs/screenshots/telemetry.png" alt="Вкладка «Телеметрия»" width="300"></td>
    <td><img src="docs/screenshots/map-track.jpg" alt="Вкладка «Карта» с записанным треком" width="300"></td>
  </tr>
  <tr>
    <td align="center"><sub>Телеметрия</sub></td>
    <td align="center"><sub>Карта и трек</sub></td>
  </tr>
</table>

## Установка

1. Откройте [последний релиз](https://github.com/voffmail/ELRS-Backpack-Telemetry/releases/latest).
2. Скачайте APK `ELRS-Backpack-Telemetry-vX.Y.Z.apk`.
3. Установите его на телефон с Android 7.0+. Разрешите установку из неизвестных источников.
4. Обновления устанавливаются поверх предыдущей версии.

## Быстрый старт

1. Подключите телефон и ELRS TX Backpack к одной Wi-Fi-сети.
2. На аппаратуре задайте: ELRS Lua → Backpack → Telemetry → WiFi. Не используйте «WiFi Connectivity».
3. Запустите приложение. По умолчанию используется UDP-порт `14550`; если он изменён, укажите тот же порт в настройках приложения.

Для ПК есть Python-вьюер — удобен для разработки и запуска на ноутбуке в поле. Инструкция в [DEVELOP.md](DEVELOP.md).

## Разработчикам

Сборка, toolchain, CI, релизы, ключ MapTiler и команды проверки — в [DEVELOP.md](DEVELOP.md).

Технический справочник — [docs/REFERENCE.md](docs/REFERENCE.md): API, CRSF-кадры, Range, карта, диагностика и ограничения.

Исходный код: [github.com/voffmail/ELRS-Backpack-Telemetry](https://github.com/voffmail/ELRS-Backpack-Telemetry).

## Поддержать автора

[Рассказы ветра на Rutube](https://rutube.ru/channel/36225989/)

## Лицензия

MIT. См. [LICENSE](LICENSE).

---

## English

**ELRS Backpack Telemetry** is an Android app for ExpressLRS telemetry: it receives data over Wi-Fi from an ELRS TX backpack and shows it in two tabs, Telemetry and Map. The map requires internet access. Tracks can be recorded together with telemetry, manually or automatically, and played back on the map later.

```
Drone / FC ──► ELRS RX ──► TX module ──► ELRS Backpack ──Wi-Fi/UDP──► app
```

### Installation

1. Open the [latest release](https://github.com/voffmail/ELRS-Backpack-Telemetry/releases/latest).
2. Download `ELRS-Backpack-Telemetry-vX.Y.Z.apk`.
3. Install it on a phone running Android 7.0+. Allow installation from unknown sources.
4. Updates install over the previous version.

### Quick start

1. Connect the phone and the ELRS TX backpack to the same Wi-Fi network.
2. On the radio, set: ELRS Lua → Backpack → Telemetry → WiFi. Do not use “WiFi Connectivity”.
3. Start the app. It listens on UDP port `14550` by default; if the port was changed, set the same port in the app settings.

A Python viewer is also available for PC — useful for development and running on a laptop in the field. See [DEVELOP.md](DEVELOP.md).

### For developers

Build, toolchain, CI, releases, MapTiler key and regression checks are described in [DEVELOP.md](DEVELOP.md).

Technical reference — [docs/REFERENCE.md](docs/REFERENCE.md): API, CRSF frames, Range, map, troubleshooting and limitations.

Source code: [github.com/voffmail/ELRS-Backpack-Telemetry](https://github.com/voffmail/ELRS-Backpack-Telemetry).

### Support the author

[Рассказы ветра on Rutube](https://rutube.ru/channel/36225989/)

### License

MIT. See [LICENSE](LICENSE).
