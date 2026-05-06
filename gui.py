# gui.py
from PySide6.QtWidgets import QMainWindow, QToolBar
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt, QEvent, Signal
from PySide6 import QtCore, QtGui
import cv2 as cv
import numpy as np

MIN_ROI_WIDTH = 256   # IDS-Kamera Minimum
MIN_ROI_HEIGHT = 1

class MainWindow(QMainWindow):
    roi_set = Signal(tuple)  # (x, y, w, h)
    measurement_finished = Signal(tuple, tuple)
    
    def __init__(self):
        super().__init__()
        self.current_frame = None
        
        # UI laden
        loader = QUiLoader()
        file = QFile("menubar_new.ui")  # ← GEÄNDERT: neue UI-Datei
        file.open(QFile.ReadOnly)
        
        # WICHTIG: Bei QMainWindow wird das UI direkt als self geladen
        # NICHT: self.ui = loader.load(file, self)
        # SONDERN: komplettes Window ersetzen
        loaded_ui = loader.load(file, None)  # ← parent=None!
        file.close()
        
        # Alle Widgets aus dem geladenen UI übernehmen
        self.ui = loaded_ui
        
        # Central Widget, MenuBar, ToolBar vom geladenen UI übernehmen
        self.setCentralWidget(loaded_ui.centralWidget())
        self.setMenuBar(loaded_ui.menuBar())
        
        # Falls ToolBars vorhanden:
        for toolbar in loaded_ui.findChildren(QToolBar):
            self.addToolBar(toolbar)
        
        # Fenster-Eigenschaften übernehmen
        self.setWindowTitle(loaded_ui.windowTitle())
        self.resize(loaded_ui.size())
        
        # ROI-Variablen
        self.roi = False
        self.roi_start = None
        self.roi_rect = None  # (x, y, w, h)
        self.show_full_image = True  # Flag für ROI vs. Full Frame
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._first_display = True
        self.measurement_active = False
        self.measurement_start = None
        self.measurement_current = None
        self.measurement_finished_points = None
        self.measurement_window_width_mm = 1.0
        self.measurement_window_height_mm = 1.0

        # Widgets referenzieren (Namen sollten gleich geblieben sein)
        self.img_label = self.ui.lbl_image
        self.hbox_layout = self.ui.horizontalLayout
        self.img_label.setMouseTracking(True)
        self.img_label.installEventFilter(self)
        
        self.btn_roi = self.ui.actionroi
        self.btn_roi_reset = self.ui.actionreset

        # Connections
        self.btn_roi.triggered.connect(lambda: setattr(self, 'roi', True))
        self.btn_roi_reset.triggered.connect(self.reset_roi)
        
        # ENTFERNEN: self.setCentralWidget(self.ui)
        # Das wurde schon oben gemacht!

    
    def eventFilter(self, obj, event):
        if obj == self.img_label:
            if event.type() == QEvent.MouseButtonPress:
                if self.measurement_active:
                    self.manage_measurement(event)
                    return True
                self.manage_roi(event)
                return True

            elif event.type() == QEvent.MouseMove:
                if self.measurement_active:
                    self.update_measurement(event)
                    return True
                self.update_roi(event)
                return True

            elif event.type() == QEvent.Resize:
                if self.current_frame is not None:
                    self.display_frame()
                    self.hbox_layout.setContentsMargins(
                        int(self.offset_x), 0, 0, 0
                    )
                return False

        return False

    def display_frame(self):
        """
        Zentrale, einzige Renderfunktion für das Kamerabild.
        Kümmert sich um:
        - ROI-only oder Vollbild
        - Skalierung mit AspectRatio
        - korrektes ROI-Overlay
        """
        if self.current_frame is None:
            return

        frame = self.current_frame

        # Sicherstellen, dass Bild zusammenhängend im Speicher liegt
        frame_to_show = np.ascontiguousarray(frame)
        img_h, img_w = frame_to_show.shape
        lbl_w = self.img_label.width()
        lbl_h = self.img_label.height()

        if img_w == 0 or img_h == 0:
            return

        self.scale = min(lbl_w / img_w, lbl_h / img_h)
        pix_w = round(img_w * self.scale)
        pix_h = round(img_h * self.scale)

        self.offset_x = (lbl_w - pix_w) / 2
        self.offset_y = (lbl_h - pix_h) / 2

        qimg = QImage(frame_to_show.data, img_w, img_h, img_w, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimg).scaled(
            pix_w, pix_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        # ROI Overlay nur in Vollbildansicht
        if self.roi_rect and self.show_full_image:
            x, y, w, h = self.roi_rect

            scale_x = pix_w / img_w
            scale_y = pix_h / img_h
            if w < MIN_ROI_WIDTH:
                w = MIN_ROI_WIDTH
            elif h < MIN_ROI_HEIGHT:
                h = MIN_ROI_HEIGHT
            x_s = round(x * self.scale)
            y_s = round(y * self.scale)
            w_s = round(w * self.scale)
            h_s = round(h * self.scale)

            painter = QtGui.QPainter(pixmap)
            pen = QtGui.QPen(Qt.red)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(x_s, y_s, w_s, h_s)
            painter.end()

        self.draw_measurement_overlay(pixmap, img_w, img_h)

        self.img_label.setPixmap(pixmap)

    def set_measurement_window_size(self, width_mm, height_mm):
        self.measurement_window_width_mm = float(width_mm)
        self.measurement_window_height_mm = float(height_mm)

    def start_measurement_mode(self):
        self.measurement_active = True
        self.measurement_start = None
        self.measurement_current = None
        self.measurement_finished_points = None
        self.roi = False
        self.roi_start = None
        self.display_frame()

    def cancel_measurement_mode(self):
        self.measurement_active = False
        self.measurement_start = None
        self.measurement_current = None
        self.measurement_finished_points = None
        self.display_frame()

    def clear_measurement(self):
        self.measurement_active = False
        self.measurement_start = None
        self.measurement_current = None
        self.measurement_finished_points = None
        self.display_frame()

    def manage_measurement(self, event):
        img_pos = self.label_to_image_coords(event.position().toPoint())
        if img_pos is None:
            return

        if self.measurement_start is None:
            self.measurement_start = img_pos
            self.measurement_current = img_pos
            self.measurement_finished_points = None
            self.display_frame()
            return

        self.measurement_current = img_pos
        self.measurement_finished_points = (self.measurement_start, img_pos)
        self.measurement_active = False
        self.measurement_finished.emit(self.measurement_start, img_pos)
        self.display_frame()

    def update_measurement(self, event):
        if self.measurement_start is None:
            return

        img_pos = self.label_to_image_coords(event.position().toPoint())
        if img_pos is None:
            return

        self.measurement_current = img_pos
        self.display_frame()

    def draw_measurement_overlay(self, pixmap, img_w, img_h):
        points = self.measurement_finished_points
        if points is None and self.measurement_start and self.measurement_current:
            points = (self.measurement_start, self.measurement_current)
        if points is None:
            return

        start, end = points
        x0, y0 = start
        x1, y1 = end
        x0_s = round(x0 * self.scale)
        y0_s = round(y0 * self.scale)
        x1_s = round(x1 * self.scale)
        y1_s = round(y1 * self.scale)
        label = self.format_measurement_length(start, end, img_w, img_h)

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(40, 220, 80))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(x0_s, y0_s, x1_s, y1_s)
        painter.setBrush(QtGui.QColor(40, 220, 80))
        painter.drawEllipse(QtCore.QPointF(x0_s, y0_s), 4, 4)
        painter.drawEllipse(QtCore.QPointF(x1_s, y1_s), 4, 4)

        text_x = int((x0_s + x1_s) / 2) + 8
        text_y = int((y0_s + y1_s) / 2) - 8
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        rect = metrics.boundingRect(label).adjusted(-5, -3, 5, 3)
        rect.moveTopLeft(QtCore.QPoint(text_x, text_y - rect.height()))
        painter.fillRect(rect, QtGui.QColor(0, 0, 0, 170))
        painter.setPen(QtGui.QPen(Qt.white))
        painter.drawText(rect, Qt.AlignCenter, label)
        painter.end()

    def manage_roi(self, event):
        """ROI-Verwaltung mit Mindestgrößen-Validierung"""
        
        img_pos = self.label_to_image_coords(event.position().toPoint())
        if img_pos is None:
            return
        
        if self.roi and self.roi_start is None:
            # Erster Klick - Startpunkt setzen
            self.roi_start = img_pos
            print("ROI start:", self.roi_start)
            
        elif self.roi and self.roi_start:
            # Zweiter Klick - ROI finalisieren
            x0, y0 = self.roi_start
            x1, y1 = img_pos
            
            # ROI berechnen
            x = min(x0, x1)
            y = min(y0, y1)
            w = abs(x1 - x0)
            h = abs(y1 - y0)
            
            # ROI auf Mindestgröße erweitern
            if w < MIN_ROI_WIDTH:
                diff = MIN_ROI_WIDTH - w
                if x0 < x1:
                    w = MIN_ROI_WIDTH
                else:
                    x = max(0, x - diff)
                    w = MIN_ROI_WIDTH
            
            if h < MIN_ROI_HEIGHT:
                diff = MIN_ROI_HEIGHT - h
                if y0 < y1:
                    h = MIN_ROI_HEIGHT
                else:
                    y = max(0, y - diff)
                    h = MIN_ROI_HEIGHT
            
            # Prüfen ob ROI im Bildbereich liegt
            if hasattr(self, 'current_frame') and self.current_frame is not None:
                img_height, img_width = self.current_frame.shape[:2]
                
                if x + w > img_width:
                    x = max(0, img_width - w)
                    if w > img_width:
                        w = img_width
                
                if y + h > img_height:
                    y = max(0, img_height - h)
                    if h > img_height:
                        h = img_height
                
                x = max(0, x)
                y = max(0, y)
            
            # ROI setzen
            self.roi_rect = (x, y, w, h)
            self.show_full_image = False
            self.roi_start = None
            self.roi = False
            
            print(f"✅ ROI gesetzt: x={x}, y={y}, w={w}, h={h}")
            
            self.roi_set.emit(self.roi_rect)
            self.display_frame()

    def update_roi(self, event):
        if self.roi_start is None:
            return

        img_pos = self.label_to_image_coords(event.position().toPoint())
        if img_pos is None:
            return

        x0, y0 = self.roi_start
        x1, y1 = img_pos

        x = min(x0, x1)
        y = min(y0, y1)
        w = abs(x1 - x0)
        h = abs(y1 - y0)

        self.roi_rect = (x, y, w, h)
        self.display_frame()

    def reset_roi(self):
        """Setzt ROI zurück → Anzeige wieder Vollbild"""
        self.roi = False
        self.roi_rect = None
        self.roi_start = None
        self.show_full_image = True
        self.display_frame()

    def measurement_length_mm(self, start, end, img_w=None, img_h=None):
        if self.current_frame is None and (img_w is None or img_h is None):
            return 0.0

        if img_w is None or img_h is None:
            img_h, img_w = self.current_frame.shape[:2]

        x0, y0 = start
        x1, y1 = end
        px_w = self.measurement_window_width_mm / max(img_w - 1, 1)
        px_h = self.measurement_window_height_mm / max(img_h - 1, 1)
        dx_mm = (x1 - x0) * px_w
        dy_mm = (y1 - y0) * px_h
        return float(np.hypot(dx_mm, dy_mm))

    def format_measurement_length(self, start, end, img_w=None, img_h=None):
        length_mm = self.measurement_length_mm(start, end, img_w, img_h)
        if length_mm >= 10:
            return f"{length_mm / 10:.3f} cm"
        return f"{length_mm:.3f} mm"

    def image_with_measurement_overlay(self, start, end):
        if self.current_frame is None:
            return None

        frame = np.ascontiguousarray(self.current_frame)
        if frame.ndim == 2:
            output = cv.cvtColor(frame, cv.COLOR_GRAY2BGR)
        else:
            output = frame.copy()

        img_h, img_w = output.shape[:2]
        x0, y0 = start
        x1, y1 = end
        label = self.format_measurement_length(start, end, img_w, img_h)

        cv.line(output, (x0, y0), (x1, y1), (40, 220, 80), 2, cv.LINE_AA)
        cv.circle(output, (x0, y0), 5, (40, 220, 80), -1, cv.LINE_AA)
        cv.circle(output, (x1, y1), 5, (40, 220, 80), -1, cv.LINE_AA)

        mid_x = int((x0 + x1) / 2)
        mid_y = int((y0 + y1) / 2)
        font = cv.FONT_HERSHEY_SIMPLEX
        font_scale = max(0.5, min(img_w, img_h) / 1200)
        thickness = 1
        (text_w, text_h), baseline = cv.getTextSize(label, font, font_scale, thickness)
        text_x = int(np.clip(mid_x + 8, 0, max(img_w - text_w - 8, 0)))
        text_y = int(np.clip(mid_y - 8, text_h + 8, img_h - baseline - 8))
        cv.rectangle(
            output,
            (text_x - 5, text_y - text_h - 5),
            (text_x + text_w + 5, text_y + baseline + 5),
            (0, 0, 0),
            -1
        )
        cv.putText(output, label, (text_x, text_y), font, font_scale, (255, 255, 255), thickness, cv.LINE_AA)
        return output

    def label_to_image_coords(self, pos):
        """Wandelt QLabel-Mausposition in Bildkoordinaten um"""
        if self.current_frame is None:
            return None

        if not hasattr(self, "scale"):
            return None

        img_h, img_w = self.current_frame.shape

        scale = self.scale
        offset_x = self.offset_x
        offset_y = self.offset_y

        x = (pos.x() - offset_x) / scale
        y = (pos.y() - offset_y) / scale

        x = int(np.clip(x, 0, img_w - 1))
        y = int(np.clip(y, 0, img_h - 1))

        return x, y
