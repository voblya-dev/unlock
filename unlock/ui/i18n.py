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
    # --- window / tabs
    "Home": "Главная",
    "Settings": "Настройки",
    "Logs": "Журнал",
    "NETWORK CONTROL": "УПРАВЛЕНИЕ СЕТЬЮ",
    # --- title bar
    "Minimise": "Свернуть",
    "Close": "Закрыть",
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
    "DPI bypass": "Обход DPI",
    "Latency": "Задержка",
    "Click to offer the proxy to Telegram again.":
        "Нажмите, чтобы снова предложить прокси в Telegram.",
    "Offered the proxy to Telegram.": "Прокси предложен в Telegram.",
    "Start the bypass first — the bridge is not running.":
        "Сначала включите обход — мост не запущен.",
    "Telegram bridge": "Мост Telegram",
    "Not running": "Не запущен",
    "Copy proxy link": "Скопировать ссылку на прокси",
    "Copies the tg:// proxy link, for pasting into Telegram by hand "
    "or sending to someone else on this network.":
        "Копирует ссылку tg:// — её можно вставить в Telegram вручную "
        "или отправить другому человеку в этой сети.",
    "Proxy link copied to the clipboard.": "Ссылка на прокси скопирована.",
    "No proxy link yet — start the bypass first.":
        "Ссылки пока нет — сначала включите обход.",
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
    "Startup": "Запуск",
    "When and how Unlock itself starts.": "Когда и как запускается сам Unlock.",
    "Start minimised to tray": "Запускать свёрнутым в трей",
    "No window on launch — Unlock waits in the notification area.":
        "Окно не открывается — Unlock ждёт в области уведомлений.",
    "Turn the bypass on automatically": "Включать обход автоматически",
    "Launch with Windows": "Запускать вместе с Windows",
    "Starts Unlock minimised to the notification area after you sign in.":
        "Запускает Unlock свёрнутым в область уведомлений после входа в систему.",
    "Presses the Home button for you as soon as Unlock is up.":
        "Нажимает кнопку на «Главной» сразу после запуска.",
    "Play a sound on connect and disconnect":
        "Звук при подключении и отключении",
    "Automatic re-test": "Автоматическая перепроверка",
    "Every %d days": "Каждые %d дн.",
    "Never": "Никогда",
    # --- settings: appearance
    "Appearance": "Оформление",
    "Theme": "Тема",
    "Language": "Язык",
    "Follow Windows": "Как в Windows",
    "Dark": "Тёмная",
    "Light": "Светлая",
    "Signal tone": "Яркость сигнала",
    "High contrast": "Высокий контраст",
    "Balanced": "Сбалансированная",
    "Dimmed": "Приглушённая",
    # --- settings: engines
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
    "Re-test": "Перепроверить",
    "Times every shipped strategy and keeps the fastest one.":
        "Замеряет все входящие в сборку конфигурации и оставляет самую быструю.",
    # --- settings: updates
    "Updates": "Обновления",
    "Installed version: %s": "Установленная версия: %s",
    "Check for a newer Unlock on startup":
        "Проверять обновления Unlock при запуске",
    "Asks GitHub for the latest release tag. Nothing is downloaded or "
    "installed without you.":
        "Запрашивает у GitHub номер последнего релиза. Ничего не скачивается "
        "и не устанавливается без вашего участия.",
    "Version %s is available.": "Доступна версия %s.",
    "Open the release page": "Открыть страницу релиза",
    # --- settings: files
    "Files": "Файлы",
    # --- logs
    "Clear view": "Очистить",
    # --- tray
    "Connect": "Подключить",
    "Disconnect": "Отключить",
    "Show window": "Показать окно",
    "Re-test strategies": "Перетестировать",
    "DPI profile": "Профиль DPI",
    "Quit": "Выход",
    "Still running in the tray. Use Quit to exit completely.":
        "Приложение свёрнуто в трей. Для полного выхода нажмите «Выход».",
    # --- tray notifications
    #
    # The engine label ("winws", "Telegram bridge") is substituted, so the
    # sentence has to read correctly with a proper noun in front of it.
    "%s stopped unexpectedly": "%s неожиданно остановлен",
    "Restarting it now.": "Перезапускаем.",
    "%s is running again": "%s снова работает",
    "Protection restored.": "Защита восстановлена.",
    "%s could not be restarted": "Не удалось перезапустить: %s",
    "Turn the bypass off and on again, or see the Logs tab.":
        "Выключите и включите обход или посмотрите вкладку «Журнал».",
    "Some services are still unreachable": "Некоторые сервисы всё ещё недоступны",
    "Not answering: %s": "Не отвечают: %s",
    "Unlock %s is available": "Доступна версия Unlock %s",
    "Open Settings for the release page.":
        "Ссылка на релиз — в настройках.",
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
    "%d/%d endpoints, %s ms": "%d/%d адресов, %s мс",
    "Selected %s — %s ms": "Выбрана %s — %s мс",
    "No config passed everything. Best partial: %s (%d/%d endpoints)":
        "Ни одна конфигурация не прошла всё. Лучшая частичная: %s (%d/%d адресов)",
    "Testing cancelled — pick a strategy in Settings":
        "Тестирование отменено — выберите конфигурацию в настройках",
    "No config unblocked anything. Try again on a different network, "
    "or update the bundled zapret build.":
        "Ни одна конфигурация ничего не разблокировала. Попробуйте другую сеть "
        "или обновите встроенную сборку zapret.",
    "Testing failed: %s": "Проверка не удалась: %s",
    # --- errors
    "Could not update the Windows startup entry.":
        "Не удалось изменить автозапуск Windows.",
    "Testing Telegram bridge": "Проверка моста Telegram",
    "Restart Unlock as Administrator — WinDivert needs elevation.":
        "Перезапустите от имени администратора — WinDivert требует прав.",
    "Still finishing the cancelled test — try again in a moment.":
        "Отменённая проверка ещё завершается — повторите через мгновение.",
    "Both bypass engines are disabled in Settings.":
        "Оба движка обхода выключены в настройках.",
    "Failed to start": "Не удалось запустить",
    # --- status line
    #
    # Only the messages the controllers emit as plain literals. The ones built
    # with an f-string cannot be keyed and fall back to English by design.
    "Starting bypass…": "Запуск обхода…",
    "Stopping bypass…": "Остановка обхода…",
    "Bypass stopped": "Обход остановлен",
    "Disconnected": "Отключено",
    "Updating the zapret pack…": "Обновление сборки zapret…",
    "No working DPI strategy found": "Рабочая конфигурация DPI не найдена",
    "DPI profile saved — applies at next bypass start":
        "Профиль DPI сохранён — применится при следующем запуске обхода",
    "Restored the system proxy left by a previous run":
        "Системный прокси, оставшийся от прошлого запуска, восстановлен",
    # --- site / IP lists
    "Lists": "Списки",
    "Sites and IP": "Сайты и IP",
    "Manage addresses that go through the DPI bypass":
        "Управляйте адресами, которые проходят через обход DPI",
    "AI services": "AI-сервисы",
    "Enable AI services with Zapret-GUI-compatible hosts mappings":
        "Включить AI-сервисы через hosts-сопоставления, совместимые с Zapret-GUI",
    "Update AI services": "Обновить AI-сервисы",
    "enable": "Включить",
    "disable": "Выключить",
    "AI services mode uses the complete hosts bundle and DNS resolvers from Zapret-GUI, "
    "including its non-AI and ad-block entries. It stays separate from your "
    "zapret domain/IP lists; your current DNS is saved and restored when disabled. "
    "Administrator confirmation may be requested. %s it?":
        "Режим AI-сервисов использует полный набор hosts-записей и DNS-серверов из "
        "Zapret-GUI, включая записи, не связанные с AI, и блокировку рекламы. Он "
        "работает отдельно от ваших списков доменов и IP для zapret; текущие DNS "
        "сохраняются и восстанавливаются при выключении. Может потребоваться "
        "подтверждение администратора. %s?",
    "Add": "Добавить",
    "Search sites or IPs": "Поиск сайтов или IP",
    "All types": "Все типы",
    "Domain": "Домен",
    "Subnet": "Подсеть",
    "Import": "Импорт",
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
    "Rule added": "Правило добавлено",
    "List imported: %d rules": "Импортировано правил: %d",
    "AI services list updated": "Список AI-сервисов обновлён",
    "AI services updated": "AI-сервисы обновлены",
    "AI services updated from cache": "AI-сервисы обновлены из локального кэша",
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
