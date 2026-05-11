# main.py
import sys
import ctypes
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget, QLabel, QVBoxLayout, QScrollArea, QFileDialog, QStyleFactory
from PySide6.QtCore import QTimer, QOperatingSystemVersion
from PySide6.QtGui import QImage, QPixmap
from PySide6 import QtCore, QtGui, QtWidgets
import cv2 as cv
import numpy as np
import glob
import os
from datetime import datetime


#local imports
from gui import MainWindow
from vision import VisionWorker
from settings import SettingsDialog
from camera_adapters import IDSAdapter, WebcamAdapter
from ids_camera import IDSCamera
from cassy_controller import CassyController, SensorCassyController
from plot import WaveformPlotWidget
from amperemeter import AmpereMeter
from sensor_measurement_dialog import SensorMeasurementDialog
from app_config import AppConfig
import resources_rc



os.chdir(os.path.dirname(os.path.abspath(__file__)))

class App:
    def __init__(self):
        # Initialparameter setzen
        self.diffbild = False
        self.diff_gain = 1 
        self.analog_gain = 1 
        self.digital_gain = 1
        self.series_count = 30
        self.series_time = 30000 # milliseconds
        # Informationen für Bildaufnahme
        self.save_path = os.path.join(f"{os.getcwd()}\\Aufnahmen\\{datetime.today().strftime('%d%m')}")
        self.name = "Bild"
        self.single_name = self.name
        self.single_image_counter = 0
        self.cassy_trigger = False
        self.trigger_mode = 'rising'
        self.trigger_value = 0.0
        self.step_trigger = False
        self.trigger_step = 0.1
        self.next_trigger_value = 0.0
        self.active_capture_request = False
        self.statusbar_percentage = 0.0

        # Deaktiviere Windows Darkmode für die Titelzeile
        if QOperatingSystemVersion.current() >= QOperatingSystemVersion.Windows10:
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            ctypes.windll.dwmapi.DwmSetWindowAttribute(0, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(ctypes.c_int(0)), 4)

        self.app = QApplication(sys.argv)
        self.app.setStyle(QStyleFactory.create("Fusion"))
        self.app.setStyleSheet("""
            QWidget {
                background-color: white;
                color: black;
            }
            QMenuBar {
                background-color: #f0f0f0;
                color: black;
            }
            QMenuBar::item {
                background-color: transparent;
                color: black;
            }
            QMenuBar::item:selected {
                background-color: #e0e0e0;
            }
        """)

        self.window = MainWindow()
        self.config = AppConfig()
        self.dll_path = self.resolve_cassy_dll_path()
        self.measurement_window_size_mm = (
            self.config.get("hardware", "measurement_window", "width_mm", default=1.0),
            self.config.get("hardware", "measurement_window", "height_mm", default=1.0)
        )

        #==============================
        # Hardware-Setup
        #==============================
        # IDS-Kamera initialisieren, falls vorhanden, ansonsten Webcam
        try:
            ids_cam = IDSCamera()
            camera_adapter = IDSAdapter(ids_cam)
            print("IDS-Kamera verwendet")
        except Exception as e:
            print("Keine IDS-Kamera, nutze Systemkamera:", e)
            QMessageBox.warning(
                    None, 
                    "IDS-Kamera nicht verfügbar",
                    "Die IDS-Kamera konnte nicht initialisiert werden.\n"
                    "Die Anwendung nutzt die Webcam."
                )
            camera_adapter = WebcamAdapter(0)

        #CASSY initialisieren
        self.cassy = None
        self.sensor_cassy = None
        try:
            if not self.dll_path:
                raise RuntimeError("Keine CASSY-DLL ausgewaehlt.")
            
            # ✅ WICHTIG: Zuerst EINEN gemeinsamen Scan durchführen
            from cassy_controller import find_cassys
            cassys = find_cassys(self.dll_path)
            
            # Dann die Controller mit den gefundenen Geräten initialisieren
            if cassys['power']:
                self.cassy = CassyController(self.dll_path, cassy=cassys['power'])
                if not self.cassy.is_available:
                    QMessageBox.warning(
                        None, 
                        "CASSY nicht verfügbar",
                        "Power-CASSY konnte nicht initialisiert werden.\n"
                        "Die Anwendung läuft ohne CASSY-Steuerung weiter."
                    )
                    self.window.ui.actioncassy.setEnabled(False)
            else:
                raise RuntimeError("Kein Power-CASSY gefunden.")
            
            if cassys['sensor']:
                self.sensor_cassy = SensorCassyController(self.dll_path, box_type='microvolt', cassy=cassys['sensor'])
            
        except Exception as e:
            QMessageBox.warning(
                None,
                "CASSY-Fehler", 
                f"CASSY konnte nicht initialisiert werden:\n{str(e)}\n\n"
                "Die Anwendung läuft ohne CASSY-Steuerung weiter."
            )
            self.cassy = None
            self.sensor_cassy = None
        
        

        # VisionWorker starten
        self.vision = VisionWorker(camera_adapter)
        self.vision.frame_ready.connect(self.process_frame_slot)
        self.vision.start()


        #=============================================================
        #UI elements and connections
        self.diff_button = self.window.ui.action_diffbild
        self.brightness_label = self.window.ui.lbl_diff_brightness
        self.analog_gain_label = self.window.ui.lbl_analog_gain
        self.digital_gain_line_edit = self.window.ui.lineEdit_digital_gain
        self.analog_gain_line_edit = self.window.ui.lineEdit_analog_gain
        self.status_label = self.window.ui.lbl_status
        self.histogram_label = self.window.ui.lbl_histogram
        self.background_mix_button = self.window.ui.action_background_mix
        self.statusbar = self.window.ui.progressBar
        self.statusbar.setVisible(False)
        self.status_label.setText("Bereit")
        self.status_label.setContentsMargins(6, 0, 6, 0)
        self.cassy_info_label = self.window.ui.lbl_cassy_info
        self.set_plot_btn = self.window.ui.btn_set_formula
        self.stabilizer_btn = self.window.ui.actionstabilize
        self.frequenz_lbl = self.window.ui.lbl_frequenz

        self.waveform_plot = WaveformPlotWidget()
        self.window.ui.verticalLayout_3.addWidget(self.waveform_plot)


        #Settings button

        self.save_settings_button = self.window.ui.actionsettings
        self.roi_button = self.window.ui.actionroi
        self.roi_reset_button = self.window.ui.actionreset
        self.cassy_button = self.window.ui.actioncassy
        self.sensor_cassy_action = self.window.ui.actionMessung
        self.sensor_cassy_action.setEnabled(bool(self.sensor_cassy and self.sensor_cassy.is_available))
        self.measure_action = self.window.ui.actionmeasure
        self.window.set_measurement_window_size(*self.measurement_window_size_mm)
        
        # Camera settings (ms)
        self.exposure_slider = self.window.ui.slider_exposure
        self.exposure_slider.setMinimum(1)       
        self.exposure_slider.setMaximum(100)    
        self.exposure_slider.setValue(10)       
        self.exposure_lineEdit = self.window.ui.lineEdit_exposure

        #UI connections
        self.window.ui.actionbackground.triggered.connect(lambda: self.vision.request_single_capture(background=True))
        self.window.ui.action_save_single.triggered.connect(self.request_single_capture)
        self.window.ui.action_diffbild.triggered.connect(self.switch_diffbild)
        self.window.ui.slider_diff_brightness.valueChanged.connect(self.set_diff_gain)
        self.window.ui.slider_analog_gain.valueChanged.connect(self.set_analog_gain)
        self.window.ui.slider_digital_gain.valueChanged.connect(self.set_digital_gain)
        self.window.ui.action_show_background.triggered.connect(self.show_background_image)
        self.save_settings_button.triggered.connect(self.open_settings_dialog)
        self.window.ui.action_save_series.triggered.connect(self.save_image_series)
        self.exposure_slider.valueChanged.connect(self.on_exposure_slider_changed)
        self.window.ui.lineEdit_exposure.editingFinished.connect(self.on_exposure_text_changed)
        self.exposure_lineEdit.editingFinished.connect(self.on_exposure_text_changed)
        self.digital_gain_line_edit.editingFinished.connect(lambda: self.set_digital_gain(int(self.digital_gain_line_edit.text())*10))
        self.analog_gain_line_edit.editingFinished.connect(lambda: self.set_analog_gain(float(self.analog_gain_line_edit.text())*10))
        self.window.ui.spinBox_mean_ref_offset.valueChanged.connect(self.vision.set_mean_offset)
        self.window.ui.checkBox_kontrast.toggled.connect(lambda checked: setattr(self.vision, 'improve_contrast', checked))
        self.window.ui.slider_kontrast.valueChanged.connect(lambda value: setattr(self.vision, 'clip_limit', value))
        self.window.ui.checkBox_fix_mean.toggled.connect(self.vision.fix_mean)
        self.window.ui.checkBox_neutralisation.toggled.connect(lambda checked: setattr(self.vision, 'neutralisation', checked))


        self.roi_reset_button.triggered.connect(self.reset_roi)
        self.background_mix_button.triggered.connect(self.create_background_from_files)
        self.set_plot_btn.clicked.connect(lambda: self.update_cassy_params(setzen=True))
        self.stabilizer_btn.triggered.connect(self.toggle_stabilizer)
        #Cassy controls
        self.cassy_button.triggered.connect(self.cassy_toggle)
        self.sensor_cassy_action.triggered.connect(self.open_sensor_measurement_dialog)
        self.measure_action.triggered.connect(self.toggle_measurement_mode)
        self.window.ui.SpinBox_frequenz.valueChanged.connect(self.update_cassy_params)
        self.window.ui.SpinBox_amplitude.valueChanged.connect(self.update_cassy_params)
        self.window.ui.SpinBox_offset.valueChanged.connect(self.update_cassy_params)
        self.window.ui.SpinBox_ratio.valueChanged.connect(self.update_cassy_params)
        self.window.ui.radioButton_user.toggled.connect(lambda: self.update_cassy_params(switch=True))
        self.window.ui.radioButton_dc.toggled.connect(lambda: self.update_cassy_params(switch=True))
        self.window.ui.radioButton_dreieck.toggled.connect(lambda: self.update_cassy_params(switch=True))
        self.window.ui.radioButton_sin.toggled.connect(lambda: self.update_cassy_params(switch=True))
        self.cassy_status_label = self.window.ui.lbl_cassy_status
        #Signal connections
        self.window.roi_set.connect(self.on_roi_set)
        self.window.measurement_finished.connect(self.on_measurement_finished)
        self.vision.save_image_ready.connect(self.save_single_image)
        self.vision.progress_changed.connect(self.update_progress)
        self.vision.task_started.connect(self.on_task_started)
        self.vision.task_finished.connect(self.on_task_finished)
        self.vision.status_message.connect(self.update_status_message)
        self.vision.stats_ready.connect(self.update_stats_display)
        self.vision.background_ready.connect(self.update_buttons)


        #=================================================================================

        # CASSY Status im GUI anzeigen
        if self.cassy and self.cassy.is_available:
            self.cassy_timer = QTimer()
            self.cassy_timer.timeout.connect(self.update_cassy_status)
            self.cassy_timer.start(200)  
        else:
            # Einmalig "Nicht verfügbar" anzeigen
            self.cassy_status_label.setText("❌ CASSY nicht verfügbar")
            self.cassy_status_label.setStyleSheet("color: gray;")

        self.ampere_meter = AmpereMeter(self.window.ui.widget_amperemeter)
        self.window.ui.verticalLayout_3.insertWidget(0, self.ampere_meter)
        layout = QtWidgets.QVBoxLayout(self.window.ui.widget_amperemeter)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.ampere_meter)
        self.set_status_ready()
        
        self.digital_gain_line_edit.setText(f"{self.digital_gain:.1f}")
        self.analog_gain_line_edit.setText(f"{self.analog_gain:.1f}")
        self.exposure_lineEdit.setText(f"{self.exposure_slider.value()*10:.2f}")  # ms
        print("Showing window...")
        self.window.showMaximized()

    def resolve_cassy_dll_path(self):
        dll_path = self.config.get("cassy", "dll_path", default="")
        if dll_path and os.path.exists(dll_path):
            return dll_path

        QMessageBox.warning(
            self.window,
            "CASSY-DLL nicht gefunden",
            "Die in viewer_config.json eingetragene CASSY-DLL wurde nicht gefunden.\n"
            "Bitte waehle die Datei LD.Api.dll aus."
        )
        selected_path, _ = QFileDialog.getOpenFileName(
            self.window,
            "CASSY-DLL auswaehlen",
            os.path.dirname(dll_path) if dll_path else os.getcwd(),
            "DLL-Dateien (*.dll);;Alle Dateien (*)"
        )

        if not selected_path:
            return None

        self.config.set("cassy", "dll_path", value=selected_path)
        self.config.save()
        return selected_path


    @QtCore.Slot(np.ndarray)
    def process_frame(self, frame):
        """ Gain anwenden (übernimmt ab jetzt der worker)
        if self.diffbild:
            frame = cv.convertScaleAbs(frame, alpha=self.diff_gain*self.digital_gain)
        else:
            frame = cv.convertScaleAbs(frame, alpha=self.digital_gain)
        """

        self.window.current_frame = frame
        self.window.display_frame()
        
        fps = self.vision.get_fps()
        self.window.ui.lbl_fps.setText(f"{fps:.1f} FPS")

        self.update_histogram(frame)

    def switch_diffbild(self): #Umschalten zwischen Original- und Diffbild
        if self.vision.background is None:
            QMessageBox.warning(self.window, "Warnung", "Kein Hintergrundbild vorhanden. Bitte zuerst Hintergrund erfassen.")
            return
        self.diffbild = not self.diffbild
        self.vision.diff_enabled = self.diffbild
        print("Diffbild mode:", self.diffbild)

        # Buttons anpassen
        if self.diffbild:
            self.diff_button.checked = True
            self.roi_button.setEnabled(False)
        else:
            self.diff_button.checked = False
            self.roi_button.setEnabled(True)

    #Update der gain Werte über die Slider
    def set_diff_gain(self, value):
        self.diff_gain = value / 10  
        self.brightness_label.setText(f"Helligkeit: {self.diff_gain:.1f}")
        self.vision.diff_gain = self.diff_gain

    def set_analog_gain(self, value):
        self.analog_gain = value / 10 
        self.analog_gain_line_edit.setText(f"{self.analog_gain:.1f}")
        self.vision.camera.set_gain(self.analog_gain)
        
    def set_digital_gain(self, value):
        self.digital_gain = value / 10
        self.digital_gain_line_edit.setText(f"{self.digital_gain:.1f}")
        self.vision.set_digital_gain(self.digital_gain)

    #Todo: Hintergrundbild abspeichern
    def show_background_image(self):
        if self.vision.background is None:
            QMessageBox.warning(self.window, "Warnung", "Kein Hintergrundbild vorhanden.")
            return

        self.back_window = QWidget()
        self.back_window.setWindowTitle("Hintergrundbild")

        layout = QVBoxLayout()
        self.back_window.setLayout(layout)

        scroll = QScrollArea()
        layout.addWidget(scroll)

        label = QLabel()
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)

        # Numpy-Array vorbereiten: contiguous + uint8
        img = self.vision.background
        img = np.ascontiguousarray(img, dtype=np.uint8)  

        h, w = img.shape

        # QImage erstellen: bytesPerLine = Breite
        qimg = QImage(img.data, w, h, w, QImage.Format_Grayscale8)

        # Pixmap und Label
        pix = QPixmap.fromImage(qimg)
        label.setPixmap(pix)
        label.setScaledContents(True)

        # Fenstergröße passend setzen
        self.back_window.resize(min(w, 800), min(h, 600))
        self.back_window.show()

    # Öffnet den Einstellungsdialog für die Bilderserie
    def open_settings_dialog(self):
        dlg = SettingsDialog(
            parent=self.window, 
            name=self.name, 
            count=self.series_count, 
            duration=self.series_time // 1000, 
            path=self.save_path,
            cassy_trigger=self.cassy_trigger,
            trigger_mode=self.trigger_mode,
            trigger_value=self.trigger_value,
            step_trigger=self.step_trigger,
            trigger_step=self.trigger_step,
            next_trigger_value=self.next_trigger_value,
            single_target = self.vision._single_target) #Laden der aktuellen Einstellungen in das Fenster
        if dlg.exec():  
            self.series_count = dlg.spin_count.value()
            self.save_path = dlg.line_path.text()
            self.series_time = dlg.spinBox_time.value() * 1000  
            self.name = dlg.line_name.text()
            self.vision.series_name = dlg.line_name.text()
            self.cassy_trigger = dlg.cassy_trigger_checkbox.isChecked()
            self.trigger_mode = 'rising' if dlg.ui.radioButton_geq.isChecked() else 'falling'
            #self.trigger_mode = dlg.trigger_geq_spinbox.text()
            self.trigger_value = dlg.trigger_geq_spinbox.value()
            self.step_trigger = dlg.trigger_step_checkbox.isChecked()
            self.trigger_step = dlg.trigger_step_spinbox.value()
            self.next_trigger_value = dlg.trigger_leq_spinbox.value()
            self.vision._single_target = dlg.single_target_spin.value()
            print(f"Neue Einstellungen übernommen.")
        else:
            print("Dialog abgebrochen")

    def save_image_series(self):
        os.makedirs(self.save_path, exist_ok=True)
        print(f"Capture starten mit Pfad: {self.save_path}")
        self.vision.request_series_capture(
            self.series_count,
            self.series_time
        )

    def request_single_capture(self, background=False): 
        self.vision.request_single_capture(background=background)

    def save_single_image(self, image, mode="single", counter=0):
        os.makedirs(self.save_path, exist_ok=True)
        number = self.single_image_counter if mode=="single" else counter
        if self.cassy and self.cassy.is_running:
            try:
                status = self.cassy.get_status()
                if status['is_running']:
                    values = self.cassy.get_current_values()
                    if values:
                        current = values['current']
                        filename = f"{self.name}_{current:.2f}A_{number:02d}.png"
            except Exception as e:
                filename = f"{self.name}_{number:02d}.png"
        else:
            filename = f"{self.name}_{number:02d}.png"

        filepath = os.path.join(self.save_path, filename)

        cv.imwrite(filepath, image)

        self.single_image_counter += 1

        print(f"Bild gespeichert: {filename}")
        if mode == "single":
            self.active_capture_request = False
        elif mode == "serie" and counter >= self.series_count:
            self.active_capture_request = False


    def update_histogram(self, frame):
        total_h = self.histogram_label.height()
        total_w = self.histogram_label.width()

        margin_x = 50
        margin_y = 40

        hist_h = max(10, total_h - margin_y)
        hist_w = max(10, total_w - margin_x)

        hist_img = self.calculate_histogram(frame, hist_w, hist_h, margin_x, margin_y)
        h, w = hist_img.shape
        qimg = QImage(hist_img.data, w, h, w, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimg)
        self.histogram_label.setPixmap(pixmap)

    def calculate_histogram(self, frame, hist_width=512, hist_height=200, margin_x=50, margin_y=40):
        if frame is None:
            return np.zeros((hist_height + margin_y, hist_width + margin_x), dtype=np.uint8)
        
        if frame.dtype != np.uint8:
            frame = cv.convertScaleAbs(frame)
        
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            frame = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)

        hist = cv.calcHist([frame], [0], None, [256], [0, 256])
        hist = cv.normalize(hist, hist, 0, hist_height, cv.NORM_MINMAX).flatten()

        #Histogrammbild erstellen mit Rand
        img_height = hist_height + margin_y
        img_width  = hist_width + margin_x
        hist_img = np.zeros((img_height, img_width), dtype=np.uint8)

        # Histogrammlinien zeichnen
        for x in range(256):
            x_pos = int(x * hist_width / 256) + margin_x
            y_top = hist_height - int(hist[x])
            cv.line(hist_img, (x_pos, hist_height), (x_pos, y_top), 255, 1)

        # X-Achse (Graustufen) unten
        for gray in [0, 128, 255]:
            x_pos = int(gray * hist_width / 256) + margin_x -int(margin_x*(gray/256)/2)
            y_pos = hist_height + margin_y - 10
            cv.putText(hist_img, str(gray), (x_pos-10, y_pos),
                        cv.FONT_HERSHEY_SIMPLEX, 0.5, 255, 1, cv.LINE_AA)

        # Y-Achse (%) links
        for y_val in [0, 50, 100]:
            y_pos = hist_height - int(y_val * hist_height / 100)
            y_pos = max(y_pos, 10)  
            cv.putText(hist_img, str(y_val), (5, y_pos+5),
                        cv.FONT_HERSHEY_SIMPLEX, 0.5, 255, 1, cv.LINE_AA)

        return hist_img

    def update_image_overlay(self):
        if self.current_frame is None:
            return

        # Kopie des Frames zum Zeichnen
        img_copy = self.current_frame.copy()

        # ROI-Rechteck zeichnen
        if self.roi_rect:
            x, y, w, h = self.roi_rect
            # cv.rectangle(img, top-left, bottom-right, color, thickness)
            cv.rectangle(img_copy, (x, y), (x + w, y + h), 255, 1)

        # Bild anzeigen
        self.show_image(img_copy)


    def reset_roi(self):
        print("Reset ROI")
        self.roi_rect = None
        self.show_full_image = True
        self.vision.reset_roi()
    
    def on_exposure_slider_changed(self, slider_val):
        exposure_us = self.slider_to_exposure(slider_val, min_exp=20000, max_exp=1000000)
        self.vision.set_exposure(exposure_us)

        # FPS wieder auf Maximalwert
        self.vision.set_dynamic_fps(exposure_us)

        self.window.ui.lineEdit_exposure.setText(f"{exposure_us/1000:.2f}")  # ms

    
    def on_exposure_text_changed(self):
        try:
            value_ms = float(self.window.ui.lineEdit_exposure.text())
        except ValueError:
            return

        # Min/Max Werte für Slider umrechnen
        value_ms = np.clip(value_ms, 20, 1000)  # µs 20k–1M µs
        slider_val = int(self.exposure_to_slider(value_ms*1000))
        self.window.ui.slider_exposure.setValue(slider_val)

        # Belichtung setzen
        self.vision.set_exposure(value_ms * 1000.0)
        # FPS dynamisch anpassen
        self.vision.set_dynamic_fps(value_ms * 1000.0)


    def slider_to_exposure(self, slider_value, min_exp=20000, max_exp=1000000):
        """
        slider_value: 0-100
        min_exp, max_exp: µs
        """
        exp = min_exp * (max_exp / min_exp) ** (slider_value / 100)
        return exp

    def exposure_to_slider(self, exposure, min_exp=20000, max_exp=1000000):
        """
        Rückrechnung für LineEdit oder initialen Slider
        """
        slider_val = 100 * np.log(exposure / min_exp) / np.log(max_exp / min_exp)
        slider_val = np.clip(slider_val, 0, 100)
        return slider_val
        
    @QtCore.Slot(np.ndarray)
    def process_frame_slot(self, frame):
        """Wrapper: Frame anzeigen und Worker informieren, dass Frame verarbeitet wurde"""
        try:
            self.process_frame(frame)
        except Exception as e:
            print("Fehler beim Verarbeiten des Frames:", e)
        finally:
            # Worker informieren, dass GUI Frame verarbeitet hat → nächstes Frame kann gesendet werden
            self.vision.mark_frame_processed()


    def on_roi_set(self, roi_rect):
        """
        Wird aufgerufen, sobald der Nutzer ein ROI fertig gezeichnet hat.
        - roi_rect: (x, y, w, h)
        """
        print("ROI erhalten in App:", roi_rect)

        # Worker informieren → hardware ROI setzen (falls IDS)
        self.vision.set_roi(*roi_rect)
        
        # Optional: GUI-Status setzen, falls noch nötig
        self.window.show_full_image = False

    # In deiner App-Klasse - Füge diese Funktionen hinzu:

    def toggle_measurement_mode(self, checked=False):
        if checked:
            self.window.start_measurement_mode()
            self.status_label.setText("Messung: Startpunkt setzen")
        else:
            self.window.cancel_measurement_mode()
            self.status_label.setText("Messung abgebrochen")

    def on_measurement_finished(self, start, end):
        self.measure_action.setChecked(False)
        length_label = self.window.format_measurement_length(start, end)

        msg = QMessageBox(self.window)
        msg.setWindowTitle("Strecke gemessen")
        msg.setIcon(QMessageBox.Information)
        msg.setText(f"Gemessene Strecke: {length_label}")
        save_button = msg.addButton("Save", QMessageBox.AcceptRole)
        ok_button = msg.addButton("OK", QMessageBox.RejectRole)
        msg.setDefaultButton(ok_button)
        msg.exec()

        if msg.clickedButton() == save_button:
            self.save_measurement_image(start, end)

        self.window.clear_measurement()

    def save_measurement_image(self, start, end):
        image = self.window.image_with_measurement_overlay(start, end)
        if image is None:
            QMessageBox.warning(self.window, "Speichern fehlgeschlagen", "Kein aktuelles Bild verfuegbar.")
            return

        os.makedirs(self.save_path, exist_ok=True)
        timestamp = datetime.now().strftime("%H%M%S_%f")
        filepath = os.path.join(self.save_path, f"{self.name}_messung_{timestamp}.png")
        if cv.imwrite(filepath, image):
            QMessageBox.information(self.window, "Gespeichert", f"Messbild gespeichert:\n{filepath}")
        else:
            QMessageBox.warning(self.window, "Speichern fehlgeschlagen", f"Datei konnte nicht geschrieben werden:\n{filepath}")

    def open_sensor_measurement_dialog(self):
        if not self.sensor_cassy or not self.sensor_cassy.is_available:
            QMessageBox.warning(
                self.window,
                "Sensor-CASSY nicht verfuegbar",
                "Sensor-CASSY konnte nicht initialisiert werden."
            )
            return

        if not hasattr(self, "sensor_measurement_dialog"):
            self.sensor_measurement_dialog = None

        if self.sensor_measurement_dialog is None:
            self.sensor_measurement_dialog = SensorMeasurementDialog(
                self.sensor_cassy,
                power_cassy=self.cassy,
                parent=self.window
            )
            self.sensor_measurement_dialog.finished.connect(
                lambda: setattr(self, "sensor_measurement_dialog", None)
            )

        self.sensor_measurement_dialog.show()
        self.sensor_measurement_dialog.raise_()
        self.sensor_measurement_dialog.activateWindow()

    def cassy_toggle(self):
        """Schaltet CASSY ein/aus und aktualisiert Button-Icon"""
        if not self.cassy or not self.cassy.is_available:
            QMessageBox.warning(self.window, "CASSY nicht verfuegbar", "Power-CASSY ist nicht verfuegbar.")
            return

        try:
            if self.cassy.is_running and hasattr(self, "single_cycle_timer"):
                self.single_cycle_timer.stop()

            if (
                not self.cassy.is_running
                and self.window.ui.radioButton_user.isChecked()
            ):
                if self.window.ui.SpinBox_frequenz.value() <= 0:
                    self.cassy_info_label.setText("Frequenz fuer Einmal-Zyklus muss > 0 sein")
                    return
                if not self.window.ui.lineEdit_user.text():
                    self.cassy_info_label.setText("Bitte Formel fuer Einmal-Zyklus eingeben")
                    return
                self.update_cassy_params(setzen=True)

            self.cassy.is_running = self.cassy.toggle()
            
            # Button-Icon ändern
            if self.cassy.is_running:
                self.actioncassy_red()
                self._schedule_single_cycle_stop()
                print("✅ CASSY gestartet")
            else:
                self.actioncassy_green()
                print("⏹️ CASSY gestoppt")
                
        except Exception as e:
            QMessageBox.critical(self.window, "Fehler", f"CASSY-Fehler: {str(e)}")

    def _schedule_single_cycle_stop(self):
        if not self.window.ui.radioButton_user.isChecked():
            return

        frequency = self.window.ui.SpinBox_frequenz.value()
        if frequency <= 0:
            self.cassy_info_label.setText("Frequenz fuer Einmal-Zyklus muss > 0 sein")
            return

        duration_ms = int(round(1000 / frequency))
        if not hasattr(self, "single_cycle_timer"):
            self.single_cycle_timer = QTimer()
            self.single_cycle_timer.setSingleShot(True)
            self.single_cycle_timer.timeout.connect(self.stop_single_cycle)

        self.single_cycle_timer.start(duration_ms)
        self.cassy_info_label.setText(f"Einmal-Zyklus gestartet: {duration_ms / 1000:.2f}s")

    def stop_single_cycle(self):
        if not self.cassy or not self.cassy.is_running:
            return

        try:
            self.cassy.stop()
            self.actioncassy_green()
            self.cassy_info_label.setText("Einmal-Zyklus beendet")
        except Exception as e:
            QMessageBox.critical(self.window, "Fehler", f"CASSY-Stop fehlgeschlagen: {str(e)}")

    def update_cassy_params(self, value=0.0, switch=False, setzen=False):
        """Aktualisiert CASSY-Parameter basierend auf GUI-Werten"""
        if not self.cassy or not self.cassy.is_available:
            return

        if switch:
            if self.cassy.is_running:
                print(f"Toggled because of switch: {switch}")
                self.cassy.toggle()
                self.actioncassy_green()
        
        try:
            # Parameter aus SpinBoxes auslesen
            frequency = self.window.ui.SpinBox_frequenz.value()
            self.frequenz_lbl.setText(f"Hz         T= {1/frequency:.2f}s" if frequency > 0 else "Hz      ---")
            amplitude = self.window.ui.SpinBox_amplitude.value()
            offset = self.window.ui.SpinBox_offset.value()
            ratio = self.window.ui.SpinBox_ratio.value()
            
            
            self.set_plot_btn.setEnabled(False)
            
            # Welche Wellenform ist ausgewählt?
            if self.window.ui.radioButton_dc.isChecked():
                self.cassy.configure_dc(current=amplitude)
                
            elif self.window.ui.radioButton_sin.isChecked():
                if frequency == 0.0:
                    self.cassy_info_label.setText("⚠️ Frequenz einstellen")
                    return
                    
                self.cassy.configure_sine(
                    amplitude=amplitude,
                    frequency=frequency,
                    offset=offset
                )
                
            elif self.window.ui.radioButton_dreieck.isChecked():
                if frequency == 0.0:
                    self.cassy_info_label.setText("⚠️ Frequenz einstellen")
                    return
                self.cassy.configure_triangle(
                    amplitude=amplitude,
                    frequency=frequency,
                    offset=offset,
                    ratio=ratio
                )
                
            elif self.window.ui.radioButton_user.isChecked():
                self.set_plot_btn.setEnabled(True)
                if not setzen:
                    return
                if frequency == 0.0:
                    self.cassy_info_label.setText("⚠️ Frequenz einstellen")
                    return
                if not self.window.ui.lineEdit_user.text():
                    self.cassy_info_label.setText("⚠️ Bitte Formel eingeben")
                    return
                
                formula = self.window.ui.lineEdit_user.text()
                
                # WICHTIG: configure_waveform mit ALLEN Parametern aufrufen!
                self.cassy.configure_waveform(
                    waveform_type=self.cassy.WAVEFORM_USER,
                    amplitude=amplitude,
                    frequency=frequency,
                    offset=offset,
                    ratio=ratio,
                    formula=formula
                )
                
                # Für Plot: Normalisierte Werte
                values = self.cassy.set_formula(formula)
                if values is not None:
                    try:
                        self.waveform_plot.plot_waveform(values, amplitude=amplitude, offset=offset, frequency=frequency)
                        self.cassy_info_label.setText(
                            f"✅ Formel gesetzt | A={amplitude}A, f={frequency}Hz, Offset={offset}A"
                        )
                    except Exception as e:
                        self.cassy_info_label.setText(f"⚠️ Plot-Fehler: {e}")
            """
            # Wenn CASSY läuft, neu starten mit neuen Parametern
            if self.cassy.is_running:
                print("Neustart...")
                self.cassy.stop()
                self.cassy.start_continuous()
            """
            self.update_buttons()
        except Exception as e:
            QMessageBox.warning(self.window, "Warnung", 
                              f"Parameter-Update fehlgeschlagen: {str(e)}")

    def update_cassy_status(self):
        """Aktualisiert CASSY-Status und Anzeige"""
        if not self.cassy or not self.cassy.is_available:
            return
        
        try:
            status = self.cassy.get_status()
            
            if not status['power_good']:
                self.cassy_status_label.setText("⚠️ Nicht an Stromversorgung")
                self.cassy_status_label.setStyleSheet("color: orange; font-weight: bold;")
                self.ampere_meter.setCurrent(0.0)
                
            elif status['is_running']:
                values = self.cassy.get_current_values()
                if values:
                    current = values['current']
                    voltage = values['voltage']
                    if self.cassy_trigger and not self.active_capture_request:
                        self._check_trigger(current)
                    elif self.cassy_trigger and self.active_capture_request:
                        print("Konflikt: Aktive Aufnahme läuft noch!")
                    
                    # Status-Label aktualisieren
                    self.cassy_status_label.setText(
                        f"▶️ Aktiv | I={current:.2f}A | U={voltage:.2f}V"
                    )
                    self.cassy_status_label.setStyleSheet("color: green; font-weight: bold;")
                    self.ampere_meter.setCurrent(current)
                    
                else:
                    self.cassy_status_label.setText("▶️ Aktiv (keine Messwerte)")
                    self.cassy_status_label.setStyleSheet("color: green;")
                    
            else:
                self.cassy_status_label.setText("⏸️ Bereit")
                self.cassy_status_label.setStyleSheet("color: blue; font-weight: bold;")
                self.ampere_meter.setCurrent(0.0)
            self.update_buttons()
                
        except Exception as e:
            self.cassy_status_label.setText(f"⚠️ Fehler: {str(e)}")
            self.cassy_status_label.setStyleSheet("color: red;")

    def _check_trigger(self, current):
        """Trigger-Logik"""
        
        if self.trigger_mode == 'rising':
            # Rising Edge: Trigger wenn current >= trigger_value
            if current >= self.trigger_value:
                
                if self.step_trigger:
                    # Step-Trigger: Mehrere Aufnahmen in Schritten
                    if current >= self.next_trigger_value:
                        print(f"✅ TRIGGER bei {current:.3f}A (nächster: {self.next_trigger_value + self.trigger_step:.3f}A)")
                        
                        # Aufnahme starten
                        self.capture_in_progress = True  # ← WICHTIG!
                        self.single_name = f"{self.name}_{current:.3f}A"
                        self.vision.request_single_capture()
                        
                        # Nächsten Trigger-Wert berechnen
                        self.next_trigger_value += self.trigger_step
                        
                        # Ende erreicht?
                        if self.next_trigger_value >= self.cassy.current_amplitude:
                            print("🏁 Trigger-Sequenz abgeschlossen")
                            self.cassy_trigger = False
                            self.next_trigger_value = self.trigger_value  # Reset für nächstes Mal
                
                else:
                    # Einmalige Serie bei Trigger
                    print(f"✅ TRIGGER bei {current:.3f}A - starte Serie")
                    self.capture_in_progress = True
                    self.cassy_trigger = False
                    self.vision.request_series_capture(
                        self.series_count, 
                        self.series_time, 
                        self.save_path, 
                        self.name
                    )
        
        elif self.trigger_mode == 'falling':
            # Falling Edge: Trigger wenn current <= trigger_value
            if current <= self.trigger_value:
                
                if self.step_trigger:
                    # TODO: Implementierung für falling step trigger
                    if current <= self.next_trigger_value:
                        print(f"✅ TRIGGER bei {current:.3f}A (fallend)")
                        
                        self.capture_in_progress = True
                        self.single_name = f"{self.name}_{current:.3f}A"
                        self.vision.request_single_capture()
                        
                        self.next_trigger_value -= self.trigger_step
                        
                        if self.next_trigger_value < 0:
                            print("🏁 Trigger-Sequenz abgeschlossen")
                            self.cassy_trigger = False
                            self.next_trigger_value = self.trigger_value
                else:
                    print(f"✅ TRIGGER bei {current:.3f}A (fallend) - starte Serie")
                    self.capture_in_progress = True
                    self.cassy_trigger = False
                    self.vision.request_series_capture(
                        self.series_count, 
                        self.series_time, 
                        self.save_path, 
                        self.name
                    )

    def toggle_stabilizer(self):
        self.vision.brightness_stabilization = not self.vision.brightness_stabilization
        if self.vision.brightness_stabilization:
            print("Stabilizer aktiviert")
            self.stabilizer_btn.checked = True
            self.window.ui.checkBox_fix_mean.setEnabled(True)
        else:
            print("Stabilizer deaktiviert")
            self.stabilizer_btn.checked = False
            self.window.ui.checkBox_fix_mean.setEnabled(False)
            
    def actioncassy_green(self):
        self.cassy_button.setIcon(QtGui.QIcon(r'res\power-button_on.png'))
        self.cassy_button.checked = False     
        print("Grün gesetzt und unchecked")

    def actioncassy_red(self):
        self.cassy_button.setIcon(QtGui.QIcon(r'res\power-button.png'))
        self.cassy_button.checked = True

    def browse_folder(self):
        files, _ = QFileDialog.getOpenFileNames(None, "Bilder für Hintergrund nauswählen","","All Files (*)")
        if files:
            return files
        return None
        
    def create_background_from_files(self):
        file_list = self.browse_folder()
        if not file_list:
            return
        self.vision.reset_acc()
        try:
            for file in file_list:
                self.vision.accumulate_frame(cv.imread(file, cv.IMREAD_GRAYSCALE))
            
            background = (self.vision._acc / len(file_list)).astype(np.uint8)
            self.vision.set_background(background)
            QMessageBox.information(self.window, "Fertig", "Hintergrund aus ausgewählten Bildern erstellt.")
        except Exception as e:
            QMessageBox.critical(self.window, "Fehler", f"Hintergrunderstellung fehlgeschlagen: {str(e)}")

    @QtCore.Slot(float, float, float)
    def update_stats_display(self, mean, mean_ref, gain):
        self.window.ui.lbl_brightness_stabilizer.setText(f"Gain: {gain:.1f}")
        self.window.ui.lbl_mean_ref.setText(f"{mean_ref:.1f}")
        self.window.ui.progressBar_mean_current.setValue(int(mean))
        if abs(mean-mean_ref) >5:
            self.window.ui.lbl_stabilizer_info.setText(f"⚠️ Helligkeitsabweichung!")
        else:
            self.window.ui.lbl_stabilizer_info.setText(f"🟢")
            

    def on_task_started(self, text):
        self.statusbar.setVisible(True)
        self.statusbar.setValue(0)
        self.set_status_working(text)

    def update_progress(self, value):
        self.statusbar.setValue(value)

    def update_status_message(self, text):
        self.status_label.setText(f"🔴 {text}")
        self.update_buttons()
    
    def update_buttons(self):
        bg = self.vision.background
        diff = self.vision.diff_enabled
        self.diff_button.checked = diff
        self.cassy_button.checked = bool(self.cassy and self.cassy.is_running)
        if bg is None:
            self.diff_button.setEnabled(False)
        else:
            self.diff_button.setEnabled(True)


    def on_task_finished(self, text):
        self.statusbar.setValue(100)
        self.set_status_ready(text=text)
        QTimer.singleShot(800, lambda: self.statusbar.setVisible(False))
        self.update_buttons()


    def set_status_ready(self, text ="Bereit"):
        self.status_label.setText(f"🟢  {text}")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        QTimer.singleShot(2000, lambda: self.status_label.setText(f"🟢  Bereit"))

    def set_status_working(self, text="Arbeitet..."):
        self.status_label.setText(f"🔴  {text}")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")

    def closeEvent(self, event):
        self.vision.stop()
        event.accept()

if __name__ == "__main__":
    app =App()
    try:
        sys.exit(app.app.exec())
    finally:
        app.vision.stop()
        if app.cassy:
            app.cassy.close()
        if app.sensor_cassy:
            app.sensor_cassy.close()
