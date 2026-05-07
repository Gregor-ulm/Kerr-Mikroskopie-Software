#vision.py
from PySide6 import QtCore
from PySide6.QtCore import QTimer
import cv2 as cv
import numpy as np
from camera_adapters import IDSAdapter, WebcamAdapter
import time
import os

class VisionWorker(QtCore.QThread):
    frame_ready = QtCore.Signal(np.ndarray)
    progress_changed = QtCore.Signal(int)   # 0–100
    task_started = QtCore.Signal(str)       # z.B. "Hintergrundaufnahme..."
    task_finished = QtCore.Signal(str)
    status_message = QtCore.Signal(str)
    stats_ready = QtCore.Signal(float, float, float)
    background_ready = QtCore.Signal(bool)
    save_image_ready = QtCore.Signal(np.ndarray, str, int)  # (filename, image)


    def __init__(self, camera_adapter, parent=None):
        super().__init__(parent)
        self.camera = camera_adapter
        self.running = True
        self._last_time = time.time()
        self._fps = 0
        self.digital_gain = 1.0
        self.diff_gain = 1.0
        self.improve_contrast = False
        self.clip_limit = 2.0
        
        # Helligkeitsstabilisierung
        self.brightness_stabilization = False
        self._mean_ref = None
        self._alpha = 0.02   # Reaktionsgeschwindigkeit (klein = sehr träge)
        self._max_gain = 5.0 # Sicherheitslimit
        self.mean_ref_offset = 0.0
        self.is_mean_fixed = False

        #Matching
        self.roi_size = 600              # Größe des Ausschnitts
        self.match_interval = 3          # alle N Frames neu berechnen
        self.frame_counter = 0

        self.cached_shift = (0.0, 0.0)
        self.match_quality = 1.0



        self.background = None
        self.diff_enabled = False
        self._roi = None

        # Single capture
        self._single_request = False
        self.background_requested = False
        self._single_count = 0
        self.acc = None
        self._single_target = 5
        self.captured_image = None

        # Series capture
        self._series_request = False
        self._series_count = 0
        self._series_saved = 0
        self._series_interval = 0
        self._series_last_time = 0
        self._series_path = ""
        self.series_name = ""

        # Frame-Puffer für GUI
        self._latest_frame = None
        self._frame_pending = False

    def run(self):
        while self.running:
            frame = self.camera.get_frame()
            if frame is None:
                self.msleep(10)
                continue
                        
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
            else:
                gray = frame
                
            if self.brightness_stabilization:
                gray = self.stabilize_brightness(gray)
            #LOG für Analyse
            if self.series_name == "stat":
                mean_val = float(np.mean(gray))
                timestamp = time.time()
                with open("brightness_log.txt", "a") as f:
                    f.write(f"{timestamp},{mean_val}\n")
            # FPS berechnen
            now = time.time()
            dt = now - self._last_time
            if dt > 0:
                self._fps = 1.0 / dt
            self._last_time = now


            # Diff-Bild
            if self.diff_enabled and self.background is not None:
                if gray.shape != self.background.shape:
                    # ROI oder Auflösung geändert -> Hintergrund passt nicht mehr
                    self.status_message.emit("Diff deaktiviert: Hintergrundgröße passt nicht zum Frame.")
                    self.background = None
                    self.diff_enabled = False
                else:
                    aligned, dx, dy, quality = self.align_frame(gray)

                    # Diff
                    gray = cv.absdiff(aligned, self.background)

                    # Feedback
                    if quality < 0.2:
                        self.status_message.emit(f"⚠️ Schlechtes Matching ({quality:.2f})")

                    # Optional Logging
                    #print(f"Shift: dx={dx:.2f}, dy={dy:.2f}, Q={quality:.2f}")
            img = None
            if self.background_requested:   
                img = gray.copy()
            gray = cv.convertScaleAbs(gray, alpha=self.digital_gain*self.diff_gain if self.diff_enabled else self.digital_gain)

            if self.improve_contrast:
                clahe = cv.createCLAHE(clipLimit=self.clip_limit, tileGridSize=(8,8))
                gray = clahe.apply(gray)

            
            # Background Capture
            if self._single_request:
                current_frame = img if self.background_requested else gray
                if current_frame is None:
                    print("Warnung: Frame ist None!")
                    continue
                self.process_image_capture(current_frame, background=self.background_requested)
            # Series Capture
            if self._series_request:
                self._process_series_capture(gray)

            # Frame für GUI
            self._latest_frame = gray
            if not self._frame_pending:
                self.frame_ready.emit(self._latest_frame.copy())
                self._frame_pending = True

            # Alte Frames verwerfen (nur IDS)
            try:
                while self.camera.has_pending_frames():
                    _ = self.camera.get_frame(discard_old=True)
            except:
                pass

            self.msleep(1)



    # ================= BACKGROUND =================
    def request_single_capture(self, background=False):
        self._single_request = True
        self._single_count = 0
        self._acc = None
        if background:
            self.task_started.emit("Hintergrundaufnahme läuft...")
            self.background_requested = True
            

    def process_image_capture(self, frame, background=False): 
        single_target = 30 if background else self._single_target
        self.accumulate_frame(frame)
        progress = int(100 * self._single_count / single_target)
        self.progress_changed.emit(progress)
        
        if background:
            self.status_message.emit(f"Hintergrundaufnahme: {self._single_count}/{single_target} Bilder gesammelt")
        else:       
            self.status_message.emit(f"Einzelaufnahme: {self._single_count}/{single_target} Bilder gesammelt")
        #print(f"{self._single_count} Bilder gesammelt von {single_target}, BG: {background}")
        if self._single_count >= single_target:
            self.status_message.emit("Aufnahme abgeschlossen. Vearbeitung...")
            avg = self.finalize_average(single_target)
            if background:
                self.set_background(avg)
                self.background_requested = False
            else:
                self.save_image_ready.emit(avg, "single", 1)
            print("Wird ausgeführt")
            self.task_finished.emit("Hintergrundaufnahme abgeschlossen." if background else "Einzelaufnahme abgeschlossen.")
            self._single_request = False

    

    # ================= SERIES =================

    def request_series_capture(self, count, total_time_ms):
        #os.makedirs(save_path, exist_ok=True)
        self.task_started.emit("Serienaufnahme läuft...")

        self._series_count = count
        self._series_saved = 0
        self._series_interval = total_time_ms / count / 1000.0
        self._series_last_time = 0
        self._series_request = True
    
    def _process_series_capture(self, frame):
        now = time.time()

        if self._series_saved == 0 or (now - self._series_last_time) >= self._series_interval:
            self.save_image_ready.emit(frame, "serie", self._series_saved + 1)
            """
            filename = os.path.join(
                self._series_path,
                f"{self.series_name}_{self._series_saved + 1:02d}.png"
            )
            cv.imwrite(filename, frame)
            """
            self._series_last_time = now
            self._series_saved += 1
            progress = int(100 * self._series_saved / self._series_count)
            self.progress_changed.emit(progress)
            self.status_message.emit(f"Serienaufnahme: {self._series_saved}/{self._series_count} Bilder gespeichert")


            if self._series_saved >= self._series_count:
                self._series_request = False
                self.task_finished.emit("Serienaufnahme abgeschlossen.")


    # ================= CONTROL =================
    def mark_frame_processed(self):
        self._frame_pending = False
        
    def set_diff_enabled(self, enabled: bool):
        self.diff_enabled = enabled
        
    def set_exposure(self, exposure_us: float):
        try:
            self.camera.set_exposure(exposure_us)
        except Exception as e:
            print("Exposure setzen fehlgeschlagen:", e)

    def get_exposure(self):
        try:
            node = self.camera.remote_nodemap.FindNode("ExposureTime")
            return node.Value()
        except:
            return None
            
    def get_fps(self):
        return self._fps

    def set_dynamic_fps(self, exposure_us):
        """
        FPS automatisch an Belichtungszeit anpassen.
        FPS = min(FPS_Hardware_Max, 1 / ExposureTime)
        """
        try:
            node = self.camera.camera.remote_nodemap.FindNode("AcquisitionFrameRate")
            if node is None:
                return
            max_fps = node.Maximum()
            # Exposure in Sekunden umrechnen
            fps = min(max_fps, 1.0 / (exposure_us / 1e6))
            node.SetValue(fps)
        except Exception as e:  
            print("FPS setzen fehlgeschlagen:", e)

    # ROI setzen
    def set_roi(self, x, y, w, h):
        """
        Setzt die Region-of-Interest.
        IDS: Hardware-ROI
        Webcam: Software-ROI über Adapter
        """
        if hasattr(self.camera, 'set_roi'):
            self.camera.set_roi(x, y, w, h)
        self._roi = (x, y, w, h)
        if self.background is not None:
            # Hintergrund an ROI anpassen (falls vorhanden)
            try:
                bg_h, bg_w = self.background.shape[:2]
                if 0 <= x < bg_w and 0 <= y < bg_h and x + w <= bg_w and y + h <= bg_h:
                    self.background = self.background[y:y + h, x:x + w]
                else:
                    # ROI passt nicht zum vorhandenen Hintergrund -> neu aufnehmen
                    self.background = None
            except Exception:
                self.background = None

    def reset_acc(self):
        self._acc = None

    def accumulate_frame(self, frame):
        if frame is None:
            print("Warnung: accumulate_frame erhielt None")
            return
        if self._acc is None:
            self._acc = frame.astype(np.float32)
        else:
            self._acc += frame.astype(np.float32)
        self._single_count += 1

    def finalize_average(self,n):
        avg = self._acc / n
        self.reset_acc()
        self._single_count = 0
        return avg.astype(np.uint8)

    def set_background(self, background):
        self.background = background
        self.background_ready.emit(True)
        
        
    # ROI zurücksetzen
    def reset_roi(self):
        if hasattr(self.camera, 'reset_roi'):
            self.camera.reset_roi()
        self._roi = None
        # Hintergrund zurücksetzen, da Framegröße wieder anders ist
        self.background = None

    def set_digital_gain(self, value: float):
        self.digital_gain = value
        
        
    def stabilize_brightness(self, frame: np.ndarray):
        """
        Stabilisiert globale Helligkeit durch EMA-Normierung.
        """
        mean_current = float(np.mean(frame))

        # Initialisierung
        if self._mean_ref is None:
            self._mean_ref = mean_current
            return frame

        # EMA Update
        if not self.is_mean_fixed:
            self._mean_ref = (1 - self._alpha) * self._mean_ref + self._alpha * mean_current

        # Gain berechnen
        if mean_current > 1e-6:
            gain = (self._mean_ref+self.mean_ref_offset) / mean_current
        else:
            gain = 1.0

        # Sicherheitsbegrenzung
        gain = max(1/self._max_gain, min(self._max_gain, gain))

        # Anwenden
        frame_corrected = cv.convertScaleAbs(frame, alpha=gain)
        self.stats_ready.emit(mean_current,
                      self._mean_ref,
                      gain)

        return frame_corrected

    def set_mean_offset(self, value):
        self.mean_ref_offset = value
    
    def fix_mean(self):
        self.is_mean_fixed = not self.is_mean_fixed
    
    def stop(self):
        self.running = False
        self.wait()
        self.camera.close()
        #self.cap.release()

    def extract_roi(self, img):
        h, w = img.shape
        cx, cy = w // 2, h // 2
        half = self.roi_size // 2

        return img[cy-half:cy+half, cx-half:cx+half]
    
    def compute_shift(self, img, template):
        roi_img = self.extract_roi(img)
        roi_template = self.extract_roi(template)

        # float32 nötig!
        roi_img_f = np.float32(roi_img)
        roi_template_f = np.float32(roi_template)

        shift, response = cv.phaseCorrelate(roi_template_f, roi_img_f)

        dx, dy = shift  # Achtung: Reihenfolge (x, y)

        return dx, dy, response

    def apply_shift(self, img, dx, dy):
        h, w = img.shape

        M = np.float32([
            [1, 0, dx],
            [0, 1, dy]
        ])

        shifted = cv.warpAffine(img, M, (w, h))

        return shifted, M
    
    def mark_borders(self, img, dx, dy):
        h, w = img.shape
        mask = np.ones((h, w), dtype=np.uint8) * 255

        dx_i = int(round(dx))
        dy_i = int(round(dy))

        # Ungültige Bereiche markieren
        if dx_i > 0:
            mask[:, :dx_i] = 0
        elif dx_i < 0:
            mask[:, dx_i:] = 0

        if dy_i > 0:
            mask[:dy_i, :] = 0
        elif dy_i < 0:
            mask[dy_i:, :] = 0

        # Rand abdunkeln
        img_marked = img.copy()
        img_marked[mask == 0] = 30  # dunkelgrau

        return img_marked

    def align_frame(self, gray):
        self.frame_counter += 1

        # -----------------------------
        # Shift neu berechnen?
        # -----------------------------
        if (
            self.frame_counter % self.match_interval == 0
            or self.cached_shift is None
        ):
            dx, dy, response = self.compute_shift(gray, self.background)

            self.cached_shift = (dx, dy)
            self.match_quality = response
        else:
            dx, dy = self.cached_shift

        # -----------------------------
        # Shift anwenden
        # -----------------------------
        aligned, _ = self.apply_shift(gray, dx, dy)

        # -----------------------------
        # Rand markieren
        # -----------------------------
        aligned = self.mark_borders(aligned, dx, dy)

        return aligned, dx, dy, self.match_quality