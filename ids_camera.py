# ids_camera.py

from ids_peak import ids_peak
from ids_peak import ids_peak_ipl_extension
from ids_peak_ipl import ids_peak_ipl
import numpy as np
import cv2


class IDSCamera:
    def __init__(self):
        ids_peak.Library.Initialize()

        self.device_manager = ids_peak.DeviceManager.Instance()
        self.device_manager.Update()

        if self.device_manager.Devices().empty():
            raise RuntimeError("Keine IDS Kamera gefunden")

        self.device = self.device_manager.Devices()[0].OpenDevice(
            ids_peak.DeviceAccessType_Control
        )

        self.remote_nodemap = self.device.RemoteDevice().NodeMaps()[0]
        # Default Settings laden
        self.remote_nodemap.FindNode("UserSetSelector").SetCurrentEntry("Default")
        self.remote_nodemap.FindNode("UserSetLoad").Execute()
        self.remote_nodemap.FindNode("UserSetLoad").WaitUntilDone()

        # Continuous Mode
        self.remote_nodemap.FindNode("AcquisitionMode").SetCurrentEntry("Continuous")

        # DataStream
        self.data_stream = self.device.DataStreams()[0].OpenDataStream()
        payload_size = self.remote_nodemap.FindNode("PayloadSize").Value()
        buffer_count = self.data_stream.NumBuffersAnnouncedMinRequired()

        for _ in range(buffer_count):
            buffer = self.data_stream.AllocAndAnnounceBuffer(payload_size)
            self.data_stream.QueueBuffer(buffer)

        self.remote_nodemap.FindNode("TLParamsLocked").SetValue(1)

        self.data_stream.StartAcquisition()
        self.remote_nodemap.FindNode("AcquisitionStart").Execute()
        self.remote_nodemap.FindNode("AcquisitionStart").WaitUntilDone()

        self.running = True

    # --------------------------------------------------
    def get_frame(self, timeout_ms=2000, discard_old=False):
        """
        Holt Frame von der Kamera (mit Fehlerbehandlung)
        """
        try:
            # Alte Frames verwerfen
            if discard_old:
                self._clear_buffer_queue()
            
            # Frame holen mit Timeout
            buffer = self.data_stream.WaitForFinishedBuffer(timeout_ms)
            
            # Zu Numpy konvertieren
            img_ids = ids_peak_ipl_extension.BufferToImage(buffer)
            frame = self._convert_to_numpy(img_ids)
            
            # Buffer zurückgeben
            self.data_stream.QueueBuffer(buffer)
            
            return frame
            
        except Exception as e:
            error_msg = str(e)
            
            # Timeout ist normal nach ROI-Änderung
            if "TIMEOUT" in error_msg or "timeout" in error_msg.lower():
                print("⏱️ Frame-Timeout (normal nach ROI-Änderung)")
                # Bei Timeout: Nächster Frame-Request wird funktionieren
                return None
            else:
                print(f"❌ Fehler beim Holen des Frames: {e}")
                return None


    # --------------------------------------------------

    def _convert_to_numpy(self, img_ids):
        width = img_ids.Width()
        height = img_ids.Height()
        pixel_format = img_ids.PixelFormat()

        np_array = np.frombuffer(img_ids.get_numpy_1D(), dtype=np.uint8)

        if pixel_format == ids_peak_ipl.PixelFormatName_Mono8:
            img = np_array.reshape((height, width))

        elif pixel_format == ids_peak_ipl.PixelFormatName_Mono16:
            np_array = np.frombuffer(img_ids.get_numpy_1D(), dtype=np.uint16)
            img = np_array.reshape((height, width))
            img = (img / 256).astype(np.uint8)

        elif pixel_format == ids_peak_ipl.PixelFormatName_BGR8:
            img = np_array.reshape((height, width, 3))
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        elif pixel_format == ids_peak_ipl.PixelFormatName_RGB8:
            img = np_array.reshape((height, width, 3))
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        else:
            img_converted = img_ids.ConvertTo(ids_peak_ipl.PixelFormatName_Mono8)
            np_array = np.frombuffer(img_converted.get_numpy_1D(), dtype=np.uint8)
            img = np_array.reshape((height, width))

        return img

    #Einstellungen und Parameter müssen über die sogenannte Nodemap der Kamera gesetzt werden:
    def set_exposure(self, exposure_us: float):
        try:
            node = self.remote_nodemap.FindNode("ExposureTime")
            exposure_us = max(node.Minimum(), min(exposure_us, node.Maximum()))
            node.SetValue(exposure_us)
        except Exception as e:
            print("Exposure setzen fehlgeschlagen:", e)
    
    def get_exposure(self):
        try:
            node = self.remote_nodemap.FindNode("ExposureTime")
            return node.Value()
        except Exception as e:
            print("Exposure setzen fehlgeschlagen:", e)

    def set_gain(self, gain_value: float):
        try:
            selector = self.remote_nodemap.FindNode("GainSelector")
            selector.SetCurrentEntry("AnalogAll")
        except:
            pass

        try:
            gain_node = self.remote_nodemap.FindNode("Gain")
            gain_value = max(gain_node.Minimum(), min(gain_value, gain_node.Maximum()))
            gain_node.SetValue(gain_value)
        except Exception as e:
            print("Gain setzen fehlgeschlagen:", e)
    
    def set_roi(self, x, y, width, height):
        try:
            node_map = self.remote_nodemap

            # --- Acquisition stoppen ---
            node_map.FindNode("AcquisitionStop").Execute()
            node_map.FindNode("AcquisitionStop").WaitUntilDone()
            
            width = (width//2)*2 #2 wegen inc=2 der Kamera!! In y ist inc=1, dewegen keine Korrektur nötig
            x = (x//2)*2
            tl = node_map.FindNode("TLParamsLocked")
            if tl and tl.Value() == 1:
                tl.SetValue(0)

            width_node = node_map.FindNode("Width")
            height_node = node_map.FindNode("Height")
            offset_x_node = node_map.FindNode("OffsetX")
            offset_y_node = node_map.FindNode("OffsetY")

            # Erst ROI vollständig resetten

            offset_x_node.SetValue(0)
            offset_y_node.SetValue(0)

            width_node.SetValue(width_node.Maximum())
            height_node.SetValue(height_node.Maximum())

            # Neue Größe setzen
            width = max(width_node.Minimum(),
                        min(width, width_node.Maximum()))
            height = max(height_node.Minimum(),
                         min(height, height_node.Maximum()))

            width_node.SetValue(width)
            height_node.SetValue(height)

            # Offsets setzen
            x = max(offset_x_node.Minimum(),
                    min(x, offset_x_node.Maximum()))
            y = max(offset_y_node.Minimum(),
                    min(y, offset_y_node.Maximum()))

            offset_x_node.SetValue(x)
            offset_y_node.SetValue(y)

            # --- TL wieder locken ---
            if tl:
                tl.SetValue(1)

            # --- Acquisition starten ---
            node_map.FindNode("AcquisitionStart").Execute()
            node_map.FindNode("AcquisitionStart").WaitUntilDone()

            print("ROI erfolgreich gesetzt")
            return True

        except Exception as e:
            print("ROI Fehler:", e)
            return False



    def reset_roi(self):
        try:
            node_map = self.remote_nodemap

            # Stop
            node_map.FindNode("AcquisitionStop").Execute()
            node_map.FindNode("AcquisitionStop").WaitUntilDone()

            tl = node_map.FindNode("TLParamsLocked")
            if tl and tl.Value() == 1:
                tl.SetValue(0)

            width_node = node_map.FindNode("Width")
            height_node = node_map.FindNode("Height")
            offset_x_node = node_map.FindNode("OffsetX")
            offset_y_node = node_map.FindNode("OffsetY")

            # Offsets zuerst auf 0
            offset_x_node.SetValue(0)
            offset_y_node.SetValue(0)

            # Dann maximale Größe
            width_node.SetValue(width_node.Maximum())
            height_node.SetValue(height_node.Maximum())

            # TL wieder locken
            if tl:
                tl.SetValue(1)

            # Restart
            node_map.FindNode("AcquisitionStart").Execute()
            node_map.FindNode("AcquisitionStart").WaitUntilDone()

            print("ROI Reset erfolgreich")

        except Exception as e:
            print("ROI Reset Fehler:", e)

                
                # Recovery
        try:
            self.remote_nodemap.FindNode("TLParamsLocked").SetValue(1)
            self.data_stream.StartAcquisition()
            self.remote_nodemap.FindNode("AcquisitionStart").Execute()
            self.remote_nodemap.FindNode("AcquisitionStart").WaitUntilDone()
        except:
            pass

    def has_pending_frames(self):
        """
        Prüft, ob noch alte Buffers in der Queue fertig sind.
        Damit werden alte Frames verworfen, um Ruckeln zu vermeiden.
        """
        try:
            return self.data_stream.NumFinishedBuffers() > 0
        except:
            return False


    # --------------------------------------------------

    def close(self):
        if not self.running:
            return

        self.running = False

        try:
            self.remote_nodemap.FindNode("AcquisitionStop").Execute()
            self.remote_nodemap.FindNode("AcquisitionStop").WaitUntilDone()
        except:
            pass

        try:
            self.data_stream.StopAcquisition(
                ids_peak.AcquisitionStopMode_Default
            )
            self.data_stream.Flush(
                ids_peak.DataStreamFlushMode_DiscardAll
            )
        except:
            pass

        for buffer in self.data_stream.AnnouncedBuffers():
            self.data_stream.RevokeBuffer(buffer)

        try:
            self.remote_nodemap.FindNode("TLParamsLocked").SetValue(0)
        except:
            pass

        ids_peak.Library.Close()
