# -*- coding: utf-8 -*-
"""Locate + LEFT-click the "Unlock" system-tray icon on Windows 11 (24H2+,
XAML tray) via UIAutomation (comtypes). Enumerates buttons in Shell_TrayWnd /
Shell_SecondaryTrayWnd / NotifyIconOverflowWindow, prints all button names
for diagnostics, finds Name starting with "Unlock", clicks it with pyautogui,
then verifies UnlockDiag.exe state. Up to N attempts.
"""
import subprocess
import sys
import time

import pyautogui
import comtypes
import comtypes.client

# Get IUIAutomation with typeinfo (typelib guid for UIAutomationCore)
uia_ini = comtypes.client.GetModule(("{944DE083-8FB8-45CF-BCB7-C477ACB2F897}", 1, 0))
IUIA = comtypes.client.CreateObject(
    "{FF48DBA4-60EF-4201-AA87-54103EEF594E}",
    interface=uia_ini.IUIAutomation)

TreeScope_Subtree = 0x7
UIA_ControlTypePropertyId = 30003
UIA_NamePropertyId = 30005
UIA_ButtonControlTypeId = 50000

user32 = __import__("ctypes").windll.user32


def tray_roots():
    roots = []
    for cls in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow"):
        h = 0
        while True:
            h = user32.FindWindowExW(None, h, cls, None)
            if not h:
                break
            roots.append((cls, h))
    return roots


def list_tray_buttons():
    out = []
    for cls, hwnd in tray_roots():
        try:
            root = IUIA.ElementFromHandle(hwnd)
        except Exception as ex:
            print(f"{cls} hwnd={hwnd}: ElementFromHandle failed: {ex}")
            continue
        cond = IUIA.CreatePropertyCondition(UIA_ControlTypePropertyId,
                                            UIA_ButtonControlTypeId)
        arr = root.FindAll(TreeScope_Subtree, cond)
        n = arr.Length
        print(f"{cls} hwnd={hwnd}: {n} buttons")
        for i in range(n):
            e = arr.GetElement(i)
            try:
                name = e.CurrentName
            except Exception:
                name = ""
            try:
                r = e.CurrentBoundingRectangle
                rect = (r.left, r.top, r.right, r.bottom)
            except Exception:
                rect = None
            print(f"  [{cls}][{i}] name={name!r} rect(l,t,r,b)={rect}")
            out.append((cls, e, name, rect))
    return out


def process_alive(name):
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}"],
                         capture_output=True, text=True).stdout
    return name.lower() in out.lower()


if __name__ == "__main__":
    proc_name = sys.argv[3] if len(sys.argv) > 3 else "UnlockDiag.exe"
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    target_name = sys.argv[2] if len(sys.argv) > 2 else "Unlock"
    crash = False
    for attempt in range(1, attempts + 1):
        print(f"=== attempt {attempt} ===")
        buttons = list_tray_buttons()
        target = None
        for cls, e, name, rect in buttons:
            if name and name.strip().startswith(target_name):
                target = (cls, e, name, rect)
                break
        if not target:
            print(f"{target_name} tray button NOT found via UIA; "
                  f"checking overflow flyout...")
            # click the chevron to open overflow, then re-scan
            for cls, e, name, rect in buttons:
                if name and ("overflow" in name.lower() or "chevron" in name.lower()
                             or "notification" in name.lower()):
                    r = rect
                    if r:
                        pyautogui.click((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)
                        time.sleep(1.5)
                        buttons = list_tray_buttons()
                        for cls2, e2, name2, rect2 in buttons:
                            if name2 and name2.strip().startswith(target_name):
                                target = (cls2, e2, name2, rect2)
                                break
                    break
        if not target:
            print(f"{target_name} icon not found on this attempt")
        else:
            cls, e, name, rect = target
            print(f"found: {name!r} in {cls} rect={rect}")
            if rect:
                cx = (rect[0] + rect[2]) // 2
                cy = (rect[1] + rect[3]) // 2
                print(f"clicking at ({cx}, {cy})")
                pyautogui.moveTo(cx, cy, duration=0.2)
                time.sleep(0.3)
                pyautogui.click(cx, cy, button="left")
            else:
                try:
                    e.GetCurrentPattern(10000).Invoke()
                except Exception as ex:
                    print("invoke failed:", ex)
        time.sleep(3)
        alive = process_alive(proc_name)
        print(f"{proc_name} alive: {alive}")
        if not alive:
            print(f"{proc_name} is NOT alive after click -> crashed/exited")
            crash = True
            break
    print(f"RESULT: target={'found' if target else 'NOT found'}, "
          f"crash={crash}")
    sys.exit(2 if crash else (1 if not target else 0))
