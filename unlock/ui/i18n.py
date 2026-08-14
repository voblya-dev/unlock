"""Minimal translation table.

No Qt .ts/.qm toolchain: the string count is small and shipping compiled
catalogues inside a one-file build is more moving parts than it is worth.
``tr(key)`` returns English when a key has no translation for the active
language, so a missing entry degrades instead of crashing.
"""

from __future__ import annotations

import ctypes
import locale
import sys

EN = "en"
RU = "ru"
SYSTEM = "system"

LANGUAGES = {EN: "English", RU: "Русский"}

_current = EN


_RU: dict[str, str] = {
    # --- VPN server list
    "Ping all": "Пинговать все",
    "Checking…": "Проверяем…",
    "Unreachable": "Нет ответа",
    "Server ping": "Пинг сервера",
    # --- security / missing components
    "VPN component missing": "Нет компонента VPN",
    "%s is missing, so some VPN protocols cannot connect.":
        "%s отсутствует, поэтому часть VPN-протоколов не сможет подключиться.",
    "Windows Security may have quarantined the file. Open it to review and "
    "restore the file only if you trust this Unlock installation; otherwise reinstall Unlock.":
        "Защита Windows могла поместить файл в карантин. Откройте её, проверьте "
        "карантин и восстановите файл только если доверяете этой установке Unlock; "
        "иначе переустановите приложение.",
    "Open Windows Security": "Открыть «Безопасность Windows»",
    # --- window / tabs
    "Home": "Главная",
    "Routes": "Маршруты",
    "Settings": "Настройки",
    "Logs": "Журнал",
    "VPN": "VPN",
    "Главная": "Главная",
    "Маршруты": "Маршруты",
    "Настройки": "Настройки",
    "Журнал": "Журнал",
    # --- title bar
    "Minimise": "Свернуть",
    "Maximise": "Развернуть",
    # --- states
    "Not protected": "Без защиты",
    "Press the button to enable the bypass": "Нажмите кнопку, чтобы включить обход",
    "Connecting…": "Подключение…",
    "Starting the bypass engines": "Запуск движков обхода",
    "Protected": "Защищено",
    "Bypass active": "Обход активен",
    "Disconnecting…": "Отключение…",
    "Stopping the bypass engines": "Остановка движков обхода",
    "Benchmarking…": "Тестирование…",
    "Testing strategies": "Проверка конфигураций",
    "Error": "Ошибка",
    "See the Logs tab for details": "Подробности во вкладке «Журнал»",
    # --- home
    "Latency": "Задержка",
    "Strategy": "Конфигурация",
    "Telegram proxy": "Прокси Telegram",
    "Click to offer the proxy to Telegram again.":
        "Нажмите, чтобы снова предложить прокси в Telegram.",
    "Offered the proxy to Telegram.": "Прокси предложен в Telegram.",
    "Start the bypass first — the bridge is not running.":
        "Сначала включите обход — мост не запущен.",
    "Telegram bridge": "Мост Telegram",    "Not running": "Не запущен",
    "Re-test / Benchmark": "Перетестировать",
    # --- game mode
    "Game mode": "Игровой режим",
    "Voice chat, matchmaking and game traffic go through the bypass too.":
        "Голосовой чат, подбор игр и игровой трафик тоже идут через обход.",
    "Off — only web ports are filtered. Turn on if games or voice chat lag.":
        "Выключен — фильтруются только веб-порты. Включите, если лагают игры или голосовой чат.",
    "Widens the filter to the game port range (1024-65535).":
        "Расширяет фильтр на игровой диапазон портов (1024-65535).",
    "Applying the new filter…": "Применяем новый фильтр…",
    # --- settings: general
    "General": "Общие",
    "Startup": "Запуск",
    "When and how Unlock itself starts.": "Когда и как запускается сам Unlock.",
    "Launch Unlock when Windows starts": "Запускать вместе с Windows",
    "Adds Unlock to the Windows startup entries for your account.":
        "Добавляет Unlock в автозапуск Windows для вашей учётной записи.",
    "Start minimised to tray": "Запускать свёрнутым в трей",
    "No window on launch — Unlock waits in the notification area.":
        "Окно не открывается — Unlock ждёт в области уведомлений.",
    "Connect automatically on launch": "Подключаться автоматически при запуске",
    "Turn the bypass on automatically": "Включать обход автоматически",
    "Presses the Home button for you as soon as Unlock is up.":
        "Нажимает кнопку на «Главной» сразу после запуска.",
    "Turn my VPN on automatically": "Включать мой VPN автоматически",
    "Brings up the selected server on the VPN tab at launch.":
        "Поднимает выбранный на вкладке «VPN» сервер при запуске.",
    "Play a sound on connect and disconnect":
        "Звук при подключении и отключении",
    "Automatic re-test": "Автоматическая перепроверка",
    "Every %d days": "Каждые %d дн.",
    "Never": "Никогда",
    # --- settings: appearance
    "Appearance": "Оформление",
    "Theme": "Тема",
    "Accent": "Акцент",
    "Language": "Язык",
    "Follow Windows": "Как в Windows",
    "Dark": "Тёмная",
    "Light": "Светлая",
    "blue": "Синий",
    "green": "Зелёный",
    "purple": "Фиолетовый",
    "orange": "Оранжевый",
    "rose": "Розовый",
    # --- settings: engines
    "Bypass engines": "Движки обхода",
    "What the Home button starts": "Что включает кнопка на «Главной»",
    "Pick the engines the main button turns on. Both can run together; "
    "with both off the button has nothing to do.":
        "Выберите движки, которые включает главная кнопка. Можно оба сразу; "
        "если выключены оба — кнопке нечего запускать.",
    "DPI bypass for YouTube, Discord and HTTPS sites":
        "Обход DPI для YouTube, Discord и HTTPS-сайтов",
    "Runs winws with the chosen strategy. Needs Administrator rights.":
        "Запускает winws с выбранной конфигурацией. Нужны права администратора.",
    "WebSocket bridge for Telegram": "WebSocket-мост для Telegram",
    "A local MTProto proxy that carries Telegram over WebSocket.":
        "Локальный MTProto-прокси, который ведёт Telegram через WebSocket.",
    "Hand the proxy to Telegram automatically":
        "Передавать прокси в Telegram автоматически",
    "On connect, a running Telegram client is asked to adopt the local proxy.":
        "При подключении запущенному Telegram предлагается включить локальный прокси.",
    "Watches for Telegram and offers it the local proxy, including after a restart.":
        "Следит за Telegram и передаёт ему локальный прокси, в том числе после перезапуска.",
    "Disguise the Telegram proxy as HTTPS": "Маскировать прокси Telegram под HTTPS",
    "Fake TLS: the handshake looks like an ordinary HTTPS session, and "
    "anything else that connects to the port sees a real website.":
        "Fake TLS: рукопожатие выглядит как обычная HTTPS-сессия, а всё "
        "остальное, что подключится к порту, увидит настоящий сайт.",
    " · disguised as HTTPS": " · под видом HTTPS",
    "Telegram proxy updated — confirm the new prompt":
        "Прокси Telegram обновлён — подтвердите новый запрос",
    "Telegram is configured for you: while the bypass is on, the proxy is "
    "offered to the client as soon as it is running — confirm the prompt once.":
        "Telegram настраивается сам: пока обход включён, прокси предлагается "
        "клиенту сразу после запуска — достаточно подтвердить один раз.",
    "DPI strategy": "Конфигурация DPI",
    "Auto (benchmark result)": "Авто (по результатам теста)",
    "Route traffic through my own VPN": "Пускать трафик через свой VPN",
    "Start my VPN when Unlock launches": "Запускать мой VPN вместе с Unlock",
    "The VPN has its own button on the VPN tab — this only preselects it.":
        "У VPN своя кнопка на вкладке «VPN» — здесь только автозапуск.",
    "Point the Windows proxy at the VPN": "Направить системный прокси в VPN",
    "Route every app through the VPN (TUN)":
        "Направить все приложения через VPN (TUN)",
    "Creates a virtual network adapter. Needs Administrator rights.":
        "Создаёт виртуальный сетевой адаптер. Нужны права администратора.",
    "On: a virtual adapter carries all traffic, so apps that ignore the "
    "Windows proxy — Telegram, games, anything on UDP — still go through "
    "the VPN. This is how WireSock and similar clients work.":
        "Включено: виртуальный адаптер несёт весь трафик, поэтому приложения, "
        "игнорирующие системный прокси — Telegram, игры, всё на UDP — тоже "
        "идут через VPN. Так работают WireSock и подобные клиенты.",
    "Used when TUN is off: Windows sends every app's traffic to the local "
    "port the tunnel listens on, but apps with their own proxy setting "
    "ignore it.":
        "Работает, когда TUN выключен: Windows направляет трафик приложений "
        "на локальный порт туннеля, но приложения со своими настройками "
        "прокси это игнорируют.",
    "Ordinary apps follow the tunnel; the setting is restored on disconnect.":
        "Обычные приложения пойдут через туннель; при отключении настройка вернётся.",
    "The VPN has its own button on the VPN tab and runs independently of "
    "the bypass.":
        "У VPN своя кнопка на вкладке «VPN», он работает независимо от обхода.",
    # --- vpn tab
    "VPN off": "VPN выключен",
    "VPN on": "VPN включён",
    "Connect VPN": "Подключить VPN",
    "Disconnect VPN": "Отключить VPN",
    "%s · SOCKS 127.0.0.1:%d": "%s · SOCKS 127.0.0.1:%d",
    "%s · every app is routed through the tunnel":
        "%s · весь трафик идёт через туннель",
    # --- live tunnel stats
    "Time": "Время",
    "Upload": "Передача",
    "Download": "Получение",
    "Quality": "Качество",
    "Now": "Сейчас",
    "Total sent": "Всего отправлено",
    "Total received": "Всего получено",
    "Ping": "Ping",
    "Packet loss": "Потери пакетов",
    "Starting the tunnel": "Запуск туннеля",
    "Stopping the tunnel": "Остановка туннеля",
    "Ready: %s": "Готов: %s",
    "Add a server below, then press the button.":
        "Добавьте сервер ниже и нажмите кнопку.",
    "Add a server, then press the button.":
        "Добавьте сервер и нажмите кнопку.",
    "Add your own VPN": "Добавить свой VPN",
    "Connect or disconnect VPN": "Подключить или отключить VPN",
    "Частный туннель / управление VPN": "Частный туннель / управление VPN",
    "Нажмите на орбиту для подключения": "Нажмите на орбиту для подключения",
    "Выбранный маршрут": "Выбранный маршрут",
    "Сервер не выбран": "Сервер не выбран",
    "Ожидание": "Ожидание",
    "Туннель активен": "Туннель активен",
    "Подключение": "Подключение",
    "Отключение": "Отключение",
    "Ошибка подключения": "Ошибка подключения",
    # --- add-servers dialog
    "Add servers": "Добавить серверы",
    "Paste one link per line — vless, vmess, trojan, ss, hysteria2, "
    "an Amnezia vpn:// link, or a subscription URL. Everything you paste "
    "and drop is imported together.":
        "Вставьте по одной ссылке в строке — vless, vmess, trojan, ss, hysteria2, "
        "ссылку Amnezia vpn:// или адрес подписки. Всё вставленное и перетащенное "
        "импортируется разом.",
    "Drop config files or QR images here":
        "Перетащите сюда файлы конфигурации или QR-коды",
    "…or click to browse. Several files at once are fine.":
        "…или нажмите для выбора. Можно сразу несколько файлов.",
    "Queued files: %s": "Файлы в очереди: %s",
    "Browse…": "Обзор…",
    "Cancel": "Отмена",
    "Import": "Импортировать",
    "Close": "Закрыть",
    "Paste a link or add a file first.":
        "Сначала вставьте ссылку или добавьте файл.",
    "Nothing importable was found.": "Не найдено ничего для импорта.",
    "Imported %d, skipped %d:": "Импортировано: %d, пропущено: %d:",
    "No servers yet — press Add, or drop a config here.":
        "Серверов пока нет — нажмите «Добавить» или перетащите сюда конфигурацию.",
    "Paste a vless/vmess/trojan/ss/hysteria2 link, a subscription URL "
    "or an Amnezia vpn:// link — or import a WireGuard/AmneziaWG .conf, "
    "a config file or a QR screenshot.":
        "Вставьте ссылку vless/vmess/trojan/ss/hysteria2, адрес подписки "
        "или ссылку Amnezia vpn:// — либо импортируйте .conf WireGuard/AmneziaWG, "
        "файл конфигурации или скриншот QR-кода.",
    "Add": "Добавить",
    "From file": "Из файла",
    "From QR image": "Из QR-кода",
    "Your servers": "Ваши серверы",
    "No servers yet.": "Серверов пока нет.",
    "Remove": "Удалить",
    "Importing…": "Импорт…",
    "Added %d server(s)": "Добавлено серверов: %d",
    "Those servers are already saved": "Эти серверы уже сохранены",
    "Import a VPN config": "Импорт конфигурации VPN",
    "Import a QR code": "Импорт QR-кода",
    "Configs and QR images (*.conf *.txt *.json *.yaml *.yml *.png *.jpg *.jpeg);;All files (*)":
        "Конфигурации и QR-коды (*.conf *.txt *.json *.yaml *.yml *.png *.jpg *.jpeg);;Все файлы (*)",
    "Images (*.png *.jpg *.jpeg *.bmp *.webp)":
        "Изображения (*.png *.jpg *.jpeg *.bmp *.webp)",
    "%s is missing from this install — servers can be saved now, "
    "but the tunnel will not start. Reinstall Unlock.":
        "В установке нет %s — серверы сохранятся, но туннель не запустится. "
        "Переустановите Unlock.",
    "Selected: %s": "Выбран: %s",
    "Not configured": "Не настроен",
    # --- settings: files
    "Files": "Файлы",
    # --- logs
    "Clear view": "Очистить",
    # --- tray
    "Connect": "Подключить",
    "Disconnect": "Отключить",
    "Show window": "Показать окно",
    "Re-test strategies": "Перетестировать",
    "Quit": "Выход",
    "Still running in the tray. Use Quit to exit completely.":
        "Приложение свёрнуто в трей. Для полного выхода нажмите «Выход».",
    # --- benchmark dialog
    "Finding the best configuration": "Поиск лучшей конфигурации",
    "Benchmarking bypass strategies": "Тестирование конфигураций обхода",
    "First launch: Unlock tests every bypass strategy against YouTube, "
    "Discord and Telegram, then keeps the fastest one that works fully.":
        "Первый запуск: приложение проверит каждую конфигурацию на YouTube, "
        "Discord и Telegram и оставит самую быструю из полностью рабочих.",
    "Re-testing every strategy. The fastest fully-working configuration "
    "will replace the current one.":
        "Повторная проверка всех конфигураций. Текущую заменит самая быстрая "
        "из полностью рабочих.",
    "Preparing…": "Подготовка…",
    "Hide": "Скрыть",
    "Finish": "Завершить",
    "Press the button to reopen the test window":
        "Нажмите кнопку, чтобы вернуться к окну проверки",
    "Done": "Готово",
    "Testing cancelled — pick a strategy in Settings":
        "Тестирование отменено — выберите конфигурацию в настройках",
    "No config unblocked anything. Try again on a different network, "
    "or update the bundled zapret build.":
        "Ни одна конфигурация ничего не разблокировала. Попробуйте другую сеть "
        "или обновите встроенную сборку zapret.",
    # --- evolution dialog
    "Evolving a strategy": "Эволюция стратегии",
    "Evolving a strategy for your provider": "Эволюция стратегии под ваш провайдер",
    "Instead of picking the best of the bundled configs, Unlock breeds new "
    "ones: it starts from those configs, keeps whatever works best against "
    "your connection and recombines them. This takes a while — the app "
    "cannot protect you until it finishes.":
        "Вместо выбора лучшей из встроенных конфигураций Unlock выводит новые: "
        "берёт существующие как основу, скрещивает их и оставляет то, что лучше "
        "всего работает на вашем соединении. Это занимает время — до окончания "
        "поиска обход не будет активен.",
    "Stop and keep best": "Остановить и сохранить лучшее",
    "Ends the search after the running test. Whatever it has already "
    "found is kept — it is never worse than the bundled configs.":
        "Завершает поиск после текущего теста. Найденное сохраняется — "
        "результат не хуже встроенных конфигураций.",
    "Nothing worked on this connection. Try again on a different "
    "network, or update the bundled zapret build.":
        "Ничего не сработало на этом соединении. Попробуйте другую сеть "
        "или обновите встроенную сборку zapret.",
    "Evolve a strategy for my provider": "Подобрать стратегию под провайдера",
    "Breeds new configurations from the bundled ones and keeps what works "
    "best on your connection. Slower than a benchmark, but it can beat "
    "every preset.":
        "Создаёт новые конфигурации на основе встроенных и оставляет ту, что "
        "лучше всего работает на вашем соединении. Медленнее теста, но может "
        "обойти любой пресет.",
    "Evolve a strategy": "Подобрать стратегию",
    # --- errors
    "Could not update the Windows startup entry.":
        "Не удалось изменить автозапуск Windows.",
    "Testing Telegram bridge": "Проверка моста Telegram",
    "Both DPI bypass and Telegram proxy are disabled in Settings.":
        "В настройках отключены и обход DPI, и прокси Telegram.",
    "Every bypass engine is disabled in Settings.":
        "В настройках отключены все движки обхода.",
    "No VPN server selected — add one in the VPN tab.":
        "Не выбран VPN-сервер — добавьте его во вкладке «VPN».",
    "Restart Unlock as Administrator — WinDivert needs elevation.":
        "Перезапустите от имени администратора — WinDivert требует прав.",
    "Still finishing the cancelled test — try again in a moment.":
        "Отменённая проверка ещё завершается — повторите через мгновение.",
    # --- sidebar misc
    "Tunneling": "Туннелирование",
    "Search": "Поиск",
    # --- split tunneling tab
    "Split Tunneling": "Раздельное туннелирование",
    "Enable": "Включить",
    "Disable": "Выключить",
    "Control which apps, websites, or IPs go through the VPN. "
    "Blacklist: everything tunnelled except chosen. "
    "Whitelist: only chosen goes through the VPN.":
        "Выберите приложения, сайты или IP, которые пойдут через VPN. "
        "Блоклист: всё идёт через VPN, кроме выбранных. "
        "Белый список: через VPN идут только выбранные.",
    "Mode": "Режим",
    "Blacklist": "Блоклист",
    "Whitelist": "Белый список",
    "Apps": "Приложения",
    "Domains": "Домены",
    "IPs": "IP-адреса",
    "+ Add application": "+ Добавить приложение",
    "example.com or *.example.com": "example.com или *.example.com",
    "192.168.1.0/24 or 1.2.3.4": "192.168.1.0/24 или 1.2.3.4",
    "Select application": "Выбрать приложение",
    "Executables (*.exe);;All files (*)": "Исполняемые файлы (*.exe);;Все файлы (*)",
    "Split tunneling works in TUN mode only. "
    "Changes take effect after reconnecting the VPN.":
        "Раздельное туннелирование работает только в режиме TUN. "
        "Изменения применяются после переподключения VPN.",
    # --- site / IP lists
    "Lists": "Списки",
    "Sites and IP": "Сайты и IP",
    "Manage addresses that go through the DPI bypass":
        "Управляйте адресами, которые проходят через обход DPI",
    "AI sites": "AI-сайты",
    "Add AI websites through DPI bypass": "Добавить AI-сайты через обход DPI",
    "AI services": "AI-сервисы",
    "Enable AI services through DPI bypass and hosts mappings":
        "Включить AI-сервисы через DPI-обход и hosts-сопоставления",
    "Update AI services": "Обновить AI-сервисы",
    "enable": "Включить",
    "disable": "Выключить",
    "AI services mode downloads current AI-only mappings from the Zapret-GUI "
    "sources, sends their domains through DPI bypass, and writes only Unlock's "
    "separate block in the Windows hosts file. Administrator confirmation may be "
    "requested. %s it?":
        "Режим AI-сервисов загружает актуальные сопоставления только для AI из источников "
        "Zapret-GUI, направляет их домены через DPI-обход и записывает в Windows hosts только "
        "отдельный блок Unlock. Может потребоваться подтверждение администратора. %s?",
    "Search sites or IPs": "Поиск сайтов или IP",
    "All types": "Все типы",
    "Domain": "Домен",
    "Subnet": "Подсеть",
    "Import": "Импорт",
    "Refresh AI sites": "Обновить AI-сайты",
    "Delete selected": "Удалить выбранные",
    "Enable all": "Включить все",
    "Disable all": "Выключить все",
    "No rules yet": "Правил пока нет",
    "Add a site, IP address or subnet to include it in the DPI bypass.":
        "Добавьте сайт, IP-адрес или подсеть, чтобы включить их в обход DPI.",
    "Add first rule": "Добавить первую запись",
    "Included": "В обходе",
    "Disabled": "Выключено",
    "Include this rule in the DPI bypass": "Включить это правило в обход DPI",
    "User": "Пользователь",
    "Delete": "Удалить",
    "Add addresses": "Добавить адреса",
    "Add sites, IPs or subnets": "Добавить сайты, IP или подсети",
    "One value per line. Domains, wildcard domains, IPv4/IPv6 and CIDR "
    "subnets are accepted. Empty lines and # comments are ignored.":
        "По одному значению в строке. Поддерживаются домены, wildcard-домены, "
        "IPv4/IPv6 и подсети CIDR. Пустые строки и комментарии с # игнорируются.",
    "Import list": "Импорт списка",
    "Text files (*.txt);;All files (*)": "Текстовые файлы (*.txt);;Все файлы (*)",
    "Remove AI sites": "Удалить AI-сайты",
    "AI-site entries are managed as a group. Remove %d selected entry(s)?":
        "AI-сайты управляются как группа. Удалить выбранные записи: %d?",
    "Rule added": "Правило добавлено",
    "List imported: %d rules": "Импортировано правил: %d",
    "AI sites list updated": "Список AI-сайтов обновлён",
    "AI services list updated": "Список AI-сервисов обновлён",
    "AI sites updated": "AI-сайты обновлены",
    "AI services updated": "AI-сервисы обновлены",
    "AI services updated from cache": "AI-сервисы обновлены из локального кэша",
    "AI services list updated; hosts mapping was unavailable":
        "Список AI-сервисов обновлён, но сопоставления hosts сейчас недоступны",
    "List saved": "Список сохранён",
    "No valid new rules": "Нет новых корректных правил",
    "Rules already exist": "Такие правила уже есть",
    "Hosts override (experimental)": "Переопределение hosts (экспериментально)",
    "Manual domain → IP mappings. This is separate from normal DPI bypass rules.":
        "Ручные сопоставления «домен → IP». Это отдельный режим, не обычные правила обхода DPI.",
    "Experimental: applying this changes the Windows hosts file and asks for UAC "
    "administrator confirmation. Antivirus software may react. It is not needed "
    "for ordinary zapret site rules.":
        "Экспериментально: применение меняет системный файл hosts и запрашивает "
        "подтверждение UAC. Антивирус может отреагировать. Для обычных правил zapret это не нужно.",
    "Add mapping": "Добавить сопоставление",
    "Apply hosts changes": "Применить изменения hosts",
    "No hosts mappings. Add one only when a service explicitly gives you an IP.":
        "Сопоставлений hosts нет. Добавляйте их только если сервис явно дал IP-адрес.",
    "Add hosts override": "Добавить переопределение hosts",
    "Map one concrete domain to an IPv4 or IPv6 address.":
        "Сопоставьте один конкретный домен с IPv4- или IPv6-адресом.",
    "Save mapping": "Сохранить сопоставление",
    "Enter a valid domain and IP address": "Введите корректные домен и IP-адрес",
    "Hosts mapping saved": "Сопоставление hosts сохранено",
    "Add a hosts mapping first": "Сначала добавьте сопоставление hosts",
    "apply": "применить",
    "remove": "удалить",
    "To %s hosts overrides, Unlock will request UAC administrator rights and edit "
    "the system hosts file only between its own markers. Antivirus software may react. "
    "This is not required for ordinary zapret site rules. Continue?":
        "Чтобы %s переопределения hosts, Unlock запросит права администратора через UAC "
        "и изменит системный файл hosts только внутри собственных маркеров. Антивирус может "
        "отреагировать. Для обычных правил zapret это не нужно. Продолжить?",
    "UAC confirmation requested — hosts change will apply shortly":
        "Запрошено подтверждение UAC — изменение hosts скоро применится",
    "UAC confirmation requested — AI hosts change will apply shortly":
        "Запрошено подтверждение UAC — изменение AI-блока hosts скоро применится",
    "DPI restarted — changes applied": "DPI перезапущен, изменения применены",
    "List saved — applies at next bypass start":
        "Список сохранён — применится при следующем запуске обхода",
}

_CATALOGUES = {EN: {}, RU: _RU}


def system_language() -> str:
    """Windows UI language mapped onto a supported code; English otherwise."""
    if sys.platform == "win32":
        try:
            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, 85):
                return RU if buffer.value.lower().startswith("ru") else EN
        except Exception:                          # noqa: BLE001 - ctypes surface
            pass
    try:
        code = locale.getlocale()[0] or ""
    except ValueError:
        return EN
    return RU if code.lower().startswith(("ru", "russian")) else EN


def resolve(preference: str) -> str:
    if preference in _CATALOGUES:
        return preference
    return system_language()


def set_language(preference: str = SYSTEM) -> str:
    global _current
    _current = resolve(preference)
    return _current


def current() -> str:
    return _current


def tr(text: str) -> str:
    return _CATALOGUES[_current].get(text, text)
