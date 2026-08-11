"""Offscreen smoke/render check for the lighthouse redesign."""
from __future__ import annotations
import os, pathlib, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from unlock import config as config_module
from unlock.controller import Controller
from unlock.ui.main_window import MainWindow
from unlock.ui.vpn_add_dialog import AddServersDialog

app = QApplication(sys.argv)
config_module.CONFIG_PATH = pathlib.Path(tempfile.mkdtemp()) / "config.json"
controller = Controller()
window = MainWindow(controller)
window.resize(1024, 572)
window.show()
app.processEvents()
assert window._power.grab().save("lighthouse_v4_off.png")
window._power._set_mix(1.0)
app.processEvents()
assert window._power.grab().save("lighthouse_v4_on.png")
for index in range(window._pages.count()):
    window._set_nav_page(index)
    app.processEvents()
dialog = AddServersDialog(window)
dialog.show(); app.processEvents(); dialog.close()
window.close()
print("offscreen smoke OK; lighthouse_v4_off.png and lighthouse_v4_on.png written")
