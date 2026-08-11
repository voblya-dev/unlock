# -*- coding: utf-8 -*-
"""Locate + LEFT-click the "Unlock" system-tray icon on Windows 11 (24H2+,
XAML tray) using raw-ctypes UIAutomation: enumerate descendants of
Shell_TrayWnd / Shell_SecondaryTrayWnd / NotifyIconOverflowWindow, print all
leaf names for diagnostics, find the Name starting with "Unlock", click it,
then verify the target process state.
"""
import ctypes
from ctypes import wintypes
import subprocess
import sys
import time

import pyautogui

CLSID_CUIAutomation = "{FF48DBA4-60EF-4201-AA87-54103EEF594E}"
IID_IUIAutomation = "{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}"
TreeScope_Subtree = 7
ControlType_Button = 50000
UIA_NamePropertyId = 30005
UIA_InvokePatternId = 10000
UIA_BoundingRectanglePropertyId = 30001

ole32 = ctypes.OleDLL("ole32")
oleaut32 = ctypes.OleDLL("oleaut32")


def guid_from_str(s):
    g = (ctypes.c_byte * 16)()
    ole32.CLSIDFromString(ctypes.c_wchar_p(s), g)
    return g


def com_vtbl(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0],
                       ctypes.POINTER(ctypes.c_void_p))
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn


ole32.CoInitializeEx(None, 0)  # COINIT_APARTMENTTHREADED
uap = ctypes.c_void_p()
hr = ole32.CoCreateInstance(guid_from_str(CLSID_CUIAutomation), None, 1,
                            guid_from_str(IID_IUIAutomation), ctypes.byref(uap))
if hr != 0:
    print("CoCreateInstance failed", hex(hr & 0xFFFFFFFF)); sys.exit(1)

# CUIAutomation vtable (IUnknown: 0..2)
# 3 CompareRuntimeIds, 4 GetRootElement, 5 ElementFromHandle, ...,
CreateAndCondition = com_vtbl(uap, 23, ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
CreatePropertyCondition = com_vtbl(uap, 21, ctypes.HRESULT, ctypes.c_int, wintypes.VARIANT, ctypes.POINTER(ctypes.c_void_p))
CreateTrueCondition = com_vtbl(uap, 20, ctypes.HRESULT, ctypes.POINTER(ctypes.c_void_p))
ElementFromHandle = com_vtbl(uap, 5, ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))


def elem_FindAll(elem, cond_ptr, tree_scope=TreeScope_Subtree):
    FindAll = com_vtbl(elem, 23, ctypes.HRESULT, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    arr = ctypes.c_void_p()
    hr = FindAll(elem, tree_scope, cond_ptr, ctypes.byref(arr))
    if hr != 0:
        return None
    return arr


def arr_get(arr, i):
    GetElement = com_vtbl(arr, 5, ctypes.HRESULT, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
    e = ctypes.c_void_p()
    if GetElement(arr, i, ctypes.byref(e)) != 0:
        return None
    return e


def arr_len(arr):
    get_len = com_vtbl(arr, 3, ctypes.HRESULT, ctypes.POINTER(ctypes.c_int))
    n = ctypes.c_int()
    get_len(arr, ctypes.byref(n))
    return n.value


def elem_prop_bstr(elem, propid):
    GetPropertyValue = com_vtbl(elem, 15, ctypes.HRESULT, ctypes.c_int, wintypes.VARIANT)
    v = wintypes.VARIANT()
    GetPropertyValue(elem, propid, v)
    try:
        return v.value
    except Exception:
        return ""


def elem_prop_rect(elem):
    GetPropertyValue = com_vtbl(elem, 15, ctypes.HRESULT, ctypes.c_int, wintypes.VARIANT)
    v = wintypes.VARIANT()
    GetPropertyValue(elem, UIA_BoundingRectanglePropertyId, v)
    try:
        return tuple(v)  # (l,t,w,h)
    except Exception:
        return None


def elem_ctrltype(elem):
    GetPropertyValue = com_vtbl(elem, 15, ctypes.HRESULT, ctypes.c_int, wintypes.VARIANT)
    v = wintypes.VARIANT()
    GetPropertyValue(elem, 30003, v)  # UIA_ControlTypePropertyId == 30003
    return int(v) if v.value is not None else -1


def elem_invoke(elem):
    GetPattern = com_vtpl_invoke = com_vtbl(elem, 19, ctypes.HRESULT, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
    pat = ctypes.c_void_p()
    if GetPattern(UIA_InvokePatternId, ctypes.byref(pat)) != 0 or not pat:
        return False
    Invoke = com_vtbl(pat, 3, ctypes.HRESULT)
    return Invoke(pat) == 0


def make_int_variant(val):
    v = wintypes.VARIANT()
    v.vt = 3  # VT_I4
    v.value = val
    return v


def find_tray_elements():
    user32 = ctypes.windll.user32
    roots = []
    for cls in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow"):
        h = 0
        while True:
            h = user32.FindWindowExW(None, h, cls, None)
            if not h:
                break
            roots.append((cls, h))
    results = []
    for cls, h in roots:
        root = ctypes.c_void_p()
        if ElementFromHandle(h, ctypes.byref(root)) != 0 or not root:
            print(f"{cls} hwnd={h}: ElementFromHandle failed")
            continue
        # condition: ControlType == Button
        cond = ctypes.c_void_p()
        CreatePropertyCondition(30003, make_int_variant(ControlType_Button), ctypes.byref(cond))
        arr = elem_FindAll(root, cond)
        if not arr:
            print(f"{cls}: no buttons")
            continue
        n = arr_len(arr)
        print(f"{cls} hwnd={h}: {n} buttons")
        for i in range(n):
            e = arr_get(arr, i)
            if not e:
                continue
            name = elem_prop_bstr(e, UIA_NamePropertyId) or ""
            rect = elem_prop_rect(e)
            results.append((cls, e, name, rect))
            print(f"  [{cls}][{i}] name={name!r} rect(l,t,w,h)={rect}")
    return results


def process_alive(name):
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}"],
                         capture_output=True, text=True).stdout
    return name.lower() in out.lower()


if __name__ == "__main__":
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    for attempt in range(1, attempts + 1):
        print(f"=== attempt {attempt} ===")
        elems = find_tray_elements()
        target = None
        for cls, e, name, rect in elems:
            if name and name.strip().startswith("Unlock"):
                target = (cls, e, name, rect)
                break
        if not target:
            print("Unlock tray button NOT found via UIA")
        else:
            cls, e, name, rect = target
            print(f"found: {name!r} in {cls} rect={rect}")
            if rect and rect[2] > 0:
                cx = int(rect[0] + rect[2] / 2)
                cy = int(rect[1] + rect[3] / 2)
                print(f"clicking at ({cx}, {cy})")
                pyautogui.moveTo(cx, cy, duration=0.2)
                time.sleep(0.3)
                pyautogui.click(cx, cy, button="left")
            else:
                print("no rect; trying Invoke pattern")
                elem_invoke(e)
        time.sleep(3)
        if not process_alive("UnlockDiag.exe"):
            print("UnlockDiag.exe is NOT alive after click -> crashed")
            sys.exit(2)
        print("UnlockDiag.exe still alive")
    print("done: no crash after all attempts")
