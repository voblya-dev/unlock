"""Small system-language catalogue for the bootstrap installer."""

from __future__ import annotations

import ctypes
import locale
import sys


_RU = {
    "bootstrap installer": "установщик",
    "installer": "установщик",
    "Unlock bootstrap installer": "Установщик Unlock",
    "Unlock installer": "Установщик Unlock",
    "UNLOCK FOR WINDOWS": "UNLOCK ДЛЯ WINDOWS",
    "Install\nUnlock": "Установить\nUnlock",
    "A simple setup for your network tools.": "Простая установка сетевых инструментов.",
    "Install Unlock": "Установить Unlock",
    "Version %s": "Версия %s",
    "Install location": "Папка установки",
    "Browse": "Обзор",
    "Options": "Параметры",
    "Create a desktop shortcut": "Создать ярлык на рабочем столе",
    "Add a Start Menu shortcut": "Добавить ярлык в меню «Пуск»",
    "Launch Unlock when you sign in": "Запускать Unlock при входе в Windows",
    "Launch Unlock after install": "Запустить Unlock после установки",
    "Ready to install": "Готово к установке",
    "Cancel": "Отмена",
    "Install": "Установить",
    "Remove": "Удалить",
    "Select install folder": "Выберите папку установки",
    "Reinstall latest": "Переустановить последнюю версию",
    "Removing…": "Удаление…",
    "Installing…": "Установка…",
    "Choose a folder": "Выберите папку",
    "Choose an install folder first.": "Сначала выберите папку установки.",
    "Reinstall latest Unlock": "Переустановить последнюю версию Unlock",
    "The latest available release will replace the current app files. Your settings and VPN profiles will be kept. Continue?":
        "Последний релиз заменит файлы приложения. Настройки и VPN-профили сохранятся. Продолжить?",
    "Unlock is not installed": "Unlock не установлен",
    "No Unlock installation was found in this folder.": "В этой папке не найдена установленная копия Unlock.",
    "Remove Unlock": "Удалить Unlock",
    "Remove Unlock, its shortcuts and its startup entry?\n\nYour settings, VPN profiles and logs will be kept.":
        "Удалить Unlock, его ярлыки и запись автозапуска?\n\nНастройки, VPN-профили и журналы сохранятся.",
    "Unlock is installed": "Unlock установлен",
    "You can close the installer.": "Теперь установщик можно закрыть.",
    "Installation complete": "Установка завершена",
    "Close": "Закрыть",
    "Installation failed": "Ошибка установки",
    "Fix the problem and try again": "Исправьте проблему и повторите попытку",
    "Installation cancelled": "Установка отменена",
    "Change the options and start again when ready.": "Измените параметры и запустите установку снова.",
    "Cancelled": "Отменено",
    "Unlock was removed": "Unlock удалён",
    "Your settings and VPN profiles were kept.": "Настройки и VPN-профили сохранены.",
    "Removal complete": "Удаление завершено",
    "Removal failed": "Ошибка удаления",
    "Close Unlock and try again": "Закройте Unlock и повторите попытку",
    "Cancelling…": "Отмена…",
    "Installation in progress": "Установка выполняется",
    "Cancel the installation first or wait for it to finish.": "Сначала отмените установку или дождитесь её завершения.",
    "Downloading release package": "Загрузка пакета релиза",
    "Target": "Папка",
    "Deleting": "Удаление",
    "Verifying package": "Проверка пакета",
    "Checking integrity before install": "Проверка целостности перед установкой",
    "Computing SHA-256": "Вычисление SHA-256",
    "Package verified": "Пакет проверен",
    "Package downloaded": "Пакет загружен",
    "Package staged": "Пакет подготовлен",
    "Installing Unlock": "Установка Unlock",
    "Preparing folders": "Подготовка папок",
    "Deploying files": "Копирование файлов",
    "Creating shortcuts": "Создание ярлыков",
    "Configuring startup": "Настройка автозапуска",
    "Finishing up": "Завершение установки",
    "Ready": "Готово",
    "Removing shortcuts": "Удаление ярлыков",
    "Removing application files": "Удаление файлов приложения",
    "Unlock removed": "Unlock удалён",
    "Removing Unlock": "Удаление Unlock",
    "Removing shortcuts and startup entry": "Удаление ярлыков и записи автозапуска",
    "Integrity check failed. Expected %s, got %s.": "Проверка целостности не пройдена. Ожидалось %s, получено %s.",
    "Archive payload is missing %s": "В архиве отсутствует %s",
    "No %s installation was found in %s.": "Установленная копия %s не найдена в папке %s.",
    "Could not remove all Unlock files. Close Unlock and try again.": "Не удалось удалить все файлы Unlock. Закройте Unlock и повторите попытку.",
    "Could not replace the old Unlock folder. Close Unlock and try again.": "Не удалось заменить старую папку Unlock. Закройте Unlock и повторите попытку.",
}


def is_russian() -> bool:
    if sys.platform == "win32":
        try:
            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                return buffer.value.lower().startswith("ru")
        except Exception:
            pass
    try:
        code = locale.getlocale()[0] or ""
    except ValueError:
        code = ""
    return code.lower().startswith(("ru", "russian"))


def tr(text: str) -> str:
    """Russian on Russian Windows; English is the fallback for all others."""
    return _RU.get(text, text) if is_russian() else text
