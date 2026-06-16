# camera_adapters.py
import cv2
import numpy as np

"""
Adapter-Klassen für IDS-Kamera und Webcam. Sie bieten eine einheitliche Schnittstelle für die Worker/GUI, 
damit diese nicht direkt mit den spezifischen Kamerabibliotheken arbeiten müssen. So können die Worker/GUI unabhängig von der 
Kameratechnologie implementiert werden, und die Adapter kümmern sich um die Details der jeweiligen Kamera.
Wird eine andere Kamera verwendet, muss hier ein Adapter erstellt werden, der eine entsprechende Schnittstelle bereitstellt. 
Die Worker/GUI können dann unverändert bleiben, solange sie die Methoden der Adapter verwenden.
Die Kommunikation mit der Kamera erfolgt über eine eigene Klasse, hier ids_camera.py
Die Kommunikation mit der Webcam erfolgt direkt über OpenCV in diesem Adapter. 
"""
# --- IDS Adapter ---
class IDSAdapter:
    def __init__(self, ids_camera):
        self.camera = ids_camera
        self._roi = None  # Optional für Worker/GUI

    def get_frame(self, discard_old=False):
        frame = self.camera.get_frame(discard_old=discard_old)
        if frame is None:
            return None
        # IDS: Hardware-ROI liefert bereits zugeschnittenes Bild
        return frame


    def has_pending_frames(self):
        return self.camera.has_pending_frames()

    def set_exposure(self, exposure_us: float):
        self.camera.set_exposure(exposure_us)

    def set_dynamic_fps(self, exposure_us: float):
        try:
            node = self.camera.remote_nodemap.FindNode("AcquisitionFrameRate")
            if node is None:
                return
            max_fps = node.Maximum()
            fps = min(max_fps, 1.0 / (exposure_us / 1e6))
            node.SetValue(fps)
        except Exception as e:
            print("FPS setzen fehlgeschlagen (IDSAdapter):", e)

    def set_gain(self, gain_value: float):
        self.camera.set_gain(gain_value)
        

    def set_roi(self, x, y, w, h):
        try:
            # Direkt die Hardware-ROI Methode in IDSCamera aufrufen
            self.camera.set_roi(x, y, w, h)
            self._roi = (x, y, w, h)
            print("IDSAdapter: ROI gesetzt:", self._roi)
        except Exception as e:
            print("IDSAdapter: IDS ROI setzen im Adapter fehlgeschlagen:", e)

    def reset_roi(self):
        try:
            self.camera.reset_roi()
            self._roi = None
        except Exception as e:
            print("IDS ROI Reset fehlgeschlagen:", e)

    def close(self):
        self.camera.close()



# --- Webcam Adapter ---
class WebcamAdapter:
    def __init__(self, cam_id=0):
        self.cap = cv2.VideoCapture(cam_id, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError("Webcam konnte nicht geöffnet werden")
        self._fps = 30
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FPS, self._fps)
        self._roi = None

    def get_frame(self, discard_old=False):
        if discard_old:
            while self.cap.grab():
                pass
        ret, frame = self.cap.read()
        if not ret:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self._roi:
            x, y, w, h = self._roi
            gray = gray[y:y+h, x:x+w]
        return gray

    def has_pending_frames(self):
        return False

    def set_exposure(self, exposure_us: float):
        self.cap.set(cv2.CAP_PROP_EXPOSURE, float(exposure_us) / 1000)  # ms

    def set_dynamic_fps(self, exposure_us: float):
        pass  # nicht nötig

    def set_gain(self, gain_value: float):
        self.cap.set(cv2.CAP_PROP_GAIN, gain_value)

    def set_roi(self, x, y, w, h):
        self._roi = (x, y, w, h)  # Software-ROI

    def reset_roi(self):
        self._roi = None

    def close(self):
        self.cap.release()

