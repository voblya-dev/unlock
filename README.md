# Unlock

<p align="center">
  <img src="assets/unlock-readme.png" alt="Unlock">
</p>

**Unlock 1.0.2** — Windows-приложение, которое объединяет DPI bypass, локальный Telegram-прокси и VPN-подключения в одном интерфейсе. Оно рассчитано на обычную установку: скачайте `UnlockSetup.exe`, выберите нужные ярлыки и дождитесь завершения.

> Unlock предназначен только для законного использования. Работа обхода зависит от провайдера, сети и региона; приложение не гарантирует доступность какого-либо отдельного сервиса.

## Что умеет

| Компонент | Возможности |
| --- | --- |
| DPI bypass | Запуск встроенного `winws.exe`/WinDivert с готовыми конфигурациями zapret для HTTPS, YouTube, Discord и других сайтов. |
| Benchmark | Проверка стратегий на HTTP/1.1, TLS 1.2 и TLS 1.3 с выбором наиболее подходящего варианта. |
| Эволюция | Генетический поиск и хранение пользовательской стратегии для текущей сети. |
| Telegram | Локальный MTProto WebSocket-мост, `tg://`-ссылка, передача настройки в Telegram Desktop и опциональный Fake TLS. |
| VPN | Импорт и запуск VLESS, VMess, Trojan, Shadowsocks, Hysteria2, WireGuard и AmneziaWG. |
| TUN | Маршрутизация приложений, UDP, игр и QUIC через виртуальный адаптер, когда системного прокси недостаточно. |
| Интерфейс | Home, VPN, Settings и Logs; трей, русский/английский язык, темы, акцентный цвет и управление запуском. |

## Установка

### Рекомендуемый способ

1. Откройте [Releases](https://github.com/voblya-dev/unlock/releases/latest) и скачайте `UnlockSetup.exe`.
2. Запустите установщик и оставьте или измените папку установки.
3. Отметьте нужные пункты: ярлык на рабочем столе, ярлык в меню «Пуск», запуск при входе и запуск после установки.
4. Нажмите **Install**.

Установщик скачивает актуальный `Unlock.zip` из GitHub Release, проверяет SHA-256 из манифеста и затем создаёт ярлыки. Ему не нужны права администратора для копирования файлов; права запрашиваются самим Unlock только при включении компонентов, которым они требуются.

### Обновление, переустановка и удаление

Если в выбранной папке уже найден `Unlock.exe`, основная кнопка установщика становится **Reinstall latest**. Она скачивает последнюю версию из Release и заменяет только файлы приложения; настройки, VPN-профили и логи сохраняются.

Кнопка **Remove** удаляет файлы Unlock из выбранной папки, ярлыки и запись автозапуска. Перед удалением установщик показывает подтверждение. Данные в `%APPDATA%\Unlock` намеренно не удаляются, чтобы профиль можно было использовать после повторной установки.

### Если нужен архив

Можно скачать `Unlock.zip`, распаковать его целиком и запустить `Unlock.exe`. Не переносите один `Unlock.exe`: рядом должна оставаться папка `_internal` и каталог `bin` со встроенными движками.

## Первое включение

1. Запустите Unlock.
2. Подтвердите UAC, если планируете DPI bypass или TUN.
3. Дождитесь первого benchmark либо выберите стратегию вручную в Settings.
4. На Home включите нужные компоненты.
5. При необходимости добавьте VPN-профиль на вкладке VPN.

Telegram-мост может работать самостоятельно. Для DPI bypass через WinDivert и для TUN необходимы права администратора.

## Интерфейс

### Home

- Основная кнопка включает или отключает выбранные движки.
- Отображаются состояние, активная DPI-стратегия, задержка, Telegram и статистика трафика.
- Game mode расширяет набор обрабатываемых портов для игр и голосовых сервисов.
- **Re-test / Benchmark** повторно проверяет доступные стратегии.

### VPN

- Сохранённые профили с независимым подключением и измерением задержки.
- Добавление по ссылке, файлу, drag-and-drop или QR-коду.
- Быстрое переключение между профилями.
- Отображение переданных и полученных данных.

Поддерживаемые ссылки: `vless://`, `vmess://`, `trojan://`, `ss://`, `hysteria2://`, `wg://`/WireGuard и конфигурации AmneziaWG. Подписки принимаются по HTTPS и ограничиваются по размеру.

### Settings

| Раздел | Настройки |
| --- | --- |
| Внешний вид | Системная, светлая или тёмная тема; язык; встроенные и пользовательские акцентные цвета. |
| Запуск | Автозапуск Windows, сворачивание в трей, автоматическое включение обхода или VPN, звуки и повторный benchmark. |
| Движки | DPI bypass, Telegram WebSocket bridge, передача прокси в Telegram, Fake TLS, ручной или автоматический выбор стратегии. |
| VPN | TUN и использование локального системного прокси. |

### Logs и системный трей

Logs показывает живой журнал с возможностью очистки. В системном трее доступны подключение/отключение DPI и VPN, показ окна, benchmark, эволюция стратегии и полный выход. Закрытие окна оставляет Unlock работающим в трее.

## Как устроено подключение

```text
Unlock
  |
  +-- DPI bypass: winws.exe + WinDivert
  |     +-- preset-конфигурации zapret и hostlist-файлы
  |
  +-- Telegram: tg-ws-proxy
  |     +-- локальный MTProto/WebSocket-мост на 127.0.0.1:1443
  |
  +-- VPN
        +-- sing-box: VLESS / VMess / Trojan / Shadowsocks / Hysteria2
        +-- wireproxy: WireGuard и AmneziaWG в proxy-режиме
        +-- AmneziaWG + Wintun: полноценный TUN с UDP
```

Компоненты независимы: можно использовать только Telegram, только VPN или DPI bypass без VPN. DPI-стратегии запускаются из `bin/zapret/configs/general*.bat`; Unlock извлекает аргументы `winws.exe` и применяет их без изменения исходных preset-файлов.

### Game mode

Обычные стратегии работают с нужными веб-портами. Game mode использует диапазон `1024–65535`, чтобы включить игровые и голосовые соединения. Он анализирует больше трафика, поэтому включайте его только при необходимости.

### Benchmark и эволюция

Benchmark проверяет доступность Discord, YouTube, Google и Cloudflare, TLS handshake и задержку TCP. Эволюция создаёт варианты стратегии мутацией и crossover, повторно проверяет их и сохраняет подтверждённый результат. Один запуск может занимать до 45 минут; его можно остановить, сохранив лучший найденный вариант.

## Локальные адреса и данные

| Ресурс | Значение |
| --- | --- |
| Telegram bridge | `127.0.0.1:1443` |
| VPN SOCKS5 | `127.0.0.1:2080` |
| VPN HTTP proxy | `127.0.0.1:2081` |
| VPN TUN | `172.19.0.1/30`, MTU `1400` |
| Настройки | `%APPDATA%\Unlock\config.json` |
| VPN-профили | `%APPDATA%\Unlock\vpn-config.json` |
| Логи | `%APPDATA%\Unlock\logs\unlock.log` |
| Эволюционные стратегии | `%APPDATA%\Unlock\evolved-strategies.json` |

Профили VPN и приватные ключи остаются на компьютере пользователя. Временные конфигурации WireGuard и TUN также создаются локально.

## Безопасность и права

- WinDivert и TUN требуют Administrator rights.
- Приложение допускает только один запущенный экземпляр.
- При аварийном завершении Unlock пытается восстановить системный прокси и остановить оставшийся VPN-интерфейс.
- Установщик проверяет контрольную сумму пакета, если она указана в манифесте релиза.
- Встроенные бинарники поставляются вместе с нужными лицензиями; лицензия `tg-ws-proxy` находится в `unlock/tgwsproxy/LICENSE`.

## Запуск из исходников

Требуются Windows 10/11, Python 3.12, файлы в `bin` и права администратора для WinDivert/TUN.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py main.py
```

Аргументы запуска:

```text
--minimized   запустить сразу в системном трее
--no-elevate  не выполнять повторный запуск через UAC
```

Если отсутствует `bin/zapret`, подготовьте его командой:

```powershell
py tools/fetch_zapret.py
```

## Сборка

```powershell
py -m pip install pyinstaller
py -m PyInstaller unlock.spec --noconfirm
```

Результат находится в `dist/Unlock/Unlock.exe`. Сборка намеренно **one-folder**: бинарники не распаковываются в `%TEMP%` при каждом старте, а Windows Defender реже ошибочно блокирует сетевые компоненты.

Одна прозрачная иконка применяется к приложению, трею и установщику. При обновлении её исходника пересоберите `assets/unlock-mask.png` и `assets/unlock-mask.ico`:

```powershell
py tools/make_icon.py
```

## Выпуск новой версии

Перед созданием тега синхронизируйте версию в `unlock/constants.py`, `loader/config.py` и `loader/__init__.py`, затем проверьте её:

```powershell
py -B tools/check_release_version.py --tag v1.0.2
```

GitHub Actions по тегу `v*`:

1. собирает `Unlock`;
2. упаковывает `Unlock.zip`;
3. создаёт `loader_manifest.json` с SHA-256 и URL пакета;
4. собирает `UnlockSetup.exe`;
5. публикует `Unlock.zip`, `loader_manifest.json`, `UnlockSetup.exe` и `SHA256SUMS.txt` в GitHub Release.

Для локальной сборки релизных артефактов:

```powershell
py -m PyInstaller unlock.spec --noconfirm
py -B tools/build_release_bundle.py --input dist/Unlock --output dist/Unlock.zip
py -B tools/build_unlock_setup.py `
  --zip dist/Unlock.zip `
  --version 1.0.2 `
  --package-url https://github.com/voblya-dev/unlock/releases/download/v1.0.2/Unlock.zip
```

## Проверка проекта

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
py -B tools/selftest_ui.py
py -B tools/selftest_tunnel.py
py -B tools/selftest_genome.py
py -B -m compileall -q unlock loader tools
```

Полный benchmark требует рабочего соединения с интернетом, доступности целевых сервисов и установленного `winws.exe`.

## Частые проблемы

**DPI не включается.** Подтвердите UAC и убедитесь, что рядом с приложением есть `bin/zapret/winws.exe`, `WinDivert64.sys` и `WinDivert.dll`.

**VPN сохранён, но не подключается.** Проверьте соответствующий движок: `sing-box.exe` для VLESS/VMess/Trojan/Shadowsocks/Hysteria2, `wireproxy.exe` для WireGuard proxy-режима, `amneziawg.exe` и `wintun.dll` для TUN.

**Telegram не принял ссылку.** Повторно предложите прокси на Home. После переключения Fake TLS Telegram получает новую ссылку.

**Окно не видно.** Проверьте системный трей: закрытие окна не завершает приложение. Повторный запуск покажет уже работающий экземпляр.

## Благодарности

Unlock использует zapret, WinDivert, sing-box, wireproxy, AmneziaWG, Wintun, tg-ws-proxy и PyQt6. Соблюдайте условия лицензий этих компонентов при распространении собственных сборок.

Репозиторий: [github.com/voblya-dev/unlock](https://github.com/voblya-dev/unlock)
