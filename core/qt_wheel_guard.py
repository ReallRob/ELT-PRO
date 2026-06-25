"""Qt interaction guards shared by desktop entry points."""

from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import QAbstractScrollArea, QApplication, QComboBox, QWidget


class ComboBoxWheelGuard(QObject):
    """Prevent accidental QComboBox value changes from hover-wheel events."""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return False

        combo = self._find_combo(obj)
        if combo is None:
            return False

        view = combo.view()
        if view is not None and view.isVisible():
            return False

        self._scroll_nearest_area(combo, event)
        return True

    def _find_combo(self, obj):
        widget = obj if isinstance(obj, QWidget) else None
        while widget is not None:
            if isinstance(widget, QComboBox):
                return widget
            widget = widget.parentWidget()
        return None

    def _scroll_nearest_area(self, widget, event):
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                delta = event.angleDelta().y()
                if not delta:
                    return
                bar = parent.verticalScrollBar()
                step = bar.singleStep() or 20
                units = delta / 120 if abs(delta) >= 120 else delta / abs(delta)
                bar.setValue(bar.value() - int(units * step * 3))
                return
            parent = parent.parentWidget()


def install_combo_wheel_guard(app=None):
    app = app or QApplication.instance()
    if app is None or getattr(app, "_combo_wheel_guard", None) is not None:
        return
    guard = ComboBoxWheelGuard(app)
    app.installEventFilter(guard)
    app._combo_wheel_guard = guard
