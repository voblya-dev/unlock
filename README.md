# Unlock 2

Unlock 2 — Windows-приложение для двух задач:

- обход DPI через актуальный `zapret` / `winws`;
- локальный Telegram MTProto → WebSocket bridge (`tg-ws-proxy`) на `127.0.0.1:1443`.

VPN-вкладка и VPN-бинарники удалены. Остальной привычный интерфейс приложения сохранён: главная страница, маршруты, списки, настройки и журнал.

## Запуск

При каждом запуске Unlock:

1. гарантирует рабочую локальную копию Zapret;
2. проверяет последний релиз [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube/releases/latest);
3. скачивает и заменяет пакет только если ZIP корректен и содержит `winws.exe`, списки и `general*.bat` пресеты;
4. автоматически запускает Zapret и Telegram bridge.

Если GitHub недоступен или загрузка не проходит проверку, используется предыдущая рабочая копия. Она хранится в `%APPDATA%\Unlock\zapret`; пользовательские домены/IP — в `%APPDATA%\Unlock\zapret-lists`.

`winws` использует WinDivert, поэтому приложение запускается с правами администратора. Это необходимо для автоматического старта обхода DPI.

## Управление

В приложении доступны:

- включение/остановка обхода DPI и Telegram bridge;
- выбор актуального пресета Zapret и Game mode;
- список доменов, IP и CIDR, который добавляется к рабочим zapret-спискам;
- AI mode: актуальный hosts-пакет `dns.malw.link` с дополнением Goida-AI-Unlocker;
- автоматическая передача `tg://proxy` Telegram Desktop и ручное копирование ссылки;
- настройки запуска и журнал работы.

AI mode меняет исключительно блок `# Unlock AI services BEGIN/END` в Windows `hosts`. При включении список обновляется и применяется автоматически; без уже выданных прав администратора Windows покажет UAC-подтверждение только для этой операции.

## Сборка

```powershell
py -m pip install -r requirements.txt pyinstaller
py -m PyInstaller unlock.spec --noconfirm
```

В сборку включён только fallback-пакет Zapret и код Telegram bridge. Никакие VPN-бинарники не упаковываются.
