"""
CassyController - Klasse zur Steuerung des Power-CASSY
Unterstützt: Dreieck, Sinus, Gleichstrom und benutzerdefinierte Formeln

SensorCassyController - Unterstützt:
  - Box524013: Standard-Spannungseingang (±10V)
  - Box524040: µV-Box für Induktionsspannungen

Verwendung:
    cassys = find_cassys(DLL_PATH)
    power  = CassyController(DLL_PATH, cassy=cassys['power'])
    sensor = SensorCassyController(DLL_PATH, box_type='microvolt', cassy=cassys['sensor'])
"""

import clr
import time
from System import Enum
import numpy as np
from math import pi, sin, cos, tan, exp, log, sqrt


# --------------------------------------------------
# Gemeinsamer Scan
# --------------------------------------------------

def find_cassys(dll_path):
    """
    Scannt alle angeschlossenen CASSY-Geräte einmalig und gibt sie als Dict zurück.
    Muss VOR der Instanziierung von CassyController / SensorCassyController
    aufgerufen werden, wenn beide Geräte gleichzeitig verwendet werden.

    Args:
        dll_path (str): Pfad zur LD.Api.dll

    Returns:
        dict: {'power': <PowerCASSY oder None>, 'sensor': <SensorCASSY oder None>}
    """
    clr.AddReference(dll_path)
    from LD.Api import CASSYs, CASSYTypes

    print("🔍 Suche CASSY-Geräte...")
    cassys_list = CASSYs()
    cassys_list.Scan()

    if cassys_list.Count == 0:
        raise RuntimeError("Kein CASSY-Gerät gefunden.")

    result = {'power': None, 'sensor': None}

    for cassy in cassys_list:
        print(f"  Gefunden: {cassy.Text} (Typ: {cassy.CASSYType})")
        if cassy.CASSYType == CASSYTypes.Power:
            result['power'] = cassy
        elif cassy.CASSYType == CASSYTypes.Sensor:
            result['sensor'] = cassy

    return result


# --------------------------------------------------
# Power-CASSY Controller
# --------------------------------------------------

class CassyController:
    """
    Controller für Power-CASSY Stromsteuerung.

    Wellenformen:
    - 0: DC (Gleichstrom)
    - 1: Sinus
    - 2: Rechteck (±Amplitude)
    - 3: Rechteck (0 bis Amplitude)
    - 4: Dreieck (±Amplitude)
    - 5: Dreieck (0 bis Amplitude)
    - 6: Benutzerdefiniert (Formula)
    """

    WAVEFORM_DC          = 0
    WAVEFORM_SINE        = 1
    WAVEFORM_SQUARE      = 2
    WAVEFORM_SQUARE_UP   = 3
    WAVEFORM_TRIANGLE    = 4
    WAVEFORM_TRIANGLE_UP = 5
    WAVEFORM_USER        = 6

    def __init__(self, dll_path, cassy=None):
        """
        Args:
            dll_path (str):  Pfad zur LD.Api.dll
            cassy:           Optional: bereits gefundenes Power-CASSY Objekt
                             aus find_cassys(). Falls None, wird selbst gescannt.
        """
        self.dll_path = dll_path
        self._cassy_device = cassy
        self.power_cassy = None
        self.cassyios = None
        self.io = None
        self.quantityI = None
        self.quantityU = None
        self.is_running = False
        self.is_available = False

        self.current_waveform  = self.WAVEFORM_DC
        self.current_amplitude = 0.0
        self.current_frequency = 0.05
        self.current_offset    = 0.0
        self.current_ratio     = 50
        self.current_formula   = ""

        try:
            self._initialize()
            self.is_available = True
        except Exception as e:
            print(f"⚠️ Power-CASSY nicht verfügbar: {e}")
            self.is_available = False

    # --------------------------------------------------
    # Initialisierung
    # --------------------------------------------------

    def _initialize(self):
        """Initialisiert Power-CASSY und IO."""
        clr.AddReference(self.dll_path)

        from LD.Api import CASSYs, CASSYTypes
        from LD.Api.IOs import CASSYIOs, Box524011, ScanMode

        self.CASSYs     = CASSYs
        self.CASSYTypes = CASSYTypes
        self.CASSYIOs   = CASSYIOs
        self.Box524011  = Box524011
        self.ScanMode   = ScanMode

        if self._cassy_device is not None:
            self.power_cassy = self._cassy_device
            print(f"✅ Power-CASSY übernommen: {self.power_cassy.Text}")
        else:
            print("🔍 Suche Power-CASSY...")
            cassys_list = CASSYs()
            cassys_list.Scan()
            for cassy in cassys_list:
                if cassy.CASSYType == CASSYTypes.Power:
                    self.power_cassy = cassy
                    break

        if self.power_cassy is None:
            raise RuntimeError("Kein Power-CASSY gefunden.")

        self.power_cassy.Open()

        if not self.power_cassy.PowerGood:
            raise RuntimeError("Power-CASSY nicht an externer Versorgung!")

        self.cassyios = CASSYIOs()
        self.cassyios.AutoDefaults = True
        self.io = Box524011(self.power_cassy)
        self.cassyios.Add(self.io)
        self.cassyios.Scan(ScanMode.ScanOnly)

        self.quantityI = self.io.QuantityOutputI
        self.quantityU = self.io.QuantityInputU

        self.quantityI.Selected  = True
        self.quantityU.Selected  = True
        self.quantityI.SingleShot = True

        print("⚡ Power-CASSY bereit.")

    # --------------------------------------------------
    # Wellenform-Konfiguration
    # --------------------------------------------------

    def configure_waveform(self, waveform_type, amplitude=1.0, frequency=0.05,
                           offset=0.0, ratio=50, formula=None):
        """Konfiguriert die Wellenform des Stromausgangs."""
        if not self.is_available:
            return False

        self.current_waveform  = waveform_type
        self.current_amplitude = amplitude
        self.current_frequency = frequency
        self.current_offset    = offset
        self.current_ratio     = ratio
        if formula:
            self.current_formula = formula

        WaveformType = self.quantityI.Waveform.GetType()

        if waveform_type == self.WAVEFORM_USER and formula is not None:
            self.set_formula(formula)
        else:
            self.quantityI.Waveform = Enum.ToObject(WaveformType, waveform_type)
            self.quantityI.FrequencyParser.Value = frequency
            self.quantityI.AmplitudeParser.Value = amplitude
            self.quantityI.OffsetParser.Value    = offset
            self.quantityI.RatioParser.Value     = ratio

    def configure_dc(self, current=1.0):
        """Konfiguriert Gleichstrom."""
        self.configure_waveform(
            waveform_type=self.WAVEFORM_DC,
            amplitude=0.0, frequency=0.0, offset=current, ratio=50
        )

    def configure_sine(self, amplitude=1.0, frequency=0.05, offset=0.0):
        """Konfiguriert Sinusstrom."""
        self.configure_waveform(
            waveform_type=self.WAVEFORM_SINE,
            amplitude=amplitude, frequency=frequency, offset=offset, ratio=50
        )

    def configure_triangle(self, amplitude=1.0, frequency=0.05,
                           offset=0.0, ratio=0.5):
        """Konfiguriert Dreiecksstrom."""
        self.configure_waveform(
            waveform_type=self.WAVEFORM_TRIANGLE,
            amplitude=amplitude, frequency=frequency, offset=offset, ratio=ratio
        )

    def set_formula(self, formula):
        """
        Setzt eine benutzerdefinierte Wellenform basierend auf einer Formel.

        Args:
            formula (str): Python-Ausdruck mit 'x' als Variable (0 bis 1).
                           Beispiele: "sin(2*pi*x)", "x**2", "abs(sin(10*pi*x))"

        WICHTIG: Die Formel definiert nur die FORM (normalisiert -1 bis 1).
                 Amplitude und Offset werden SEPARAT über die Parser-Properties gesetzt.
        """
        if not self.is_available:
            return False

        try:
            WaveformType = self.quantityI.Waveform.GetType()
            self.quantityI.Waveform = Enum.ToObject(WaveformType, self.WAVEFORM_USER)

            num_points   = 4000
            userWaveForm = []

            for j in range(num_points):
                x = j / num_points
                try:
                    value = eval(formula, {"__builtins__": {}}, {
                        'x': x, 'pi': pi, 'sin': sin, 'cos': cos,
                        'tan': tan, 'exp': exp, 'log': log,
                        'sqrt': sqrt, 'abs': abs, 'np': np
                    })
                    userWaveForm.append(float(value))
                except Exception as e:
                    raise ValueError(f"Fehler in Formel bei x={x}: {e}")

            from System import Array, Double
            self.quantityI.WaveformParser.SetWaveform(Array[Double](userWaveForm))

            self.quantityI.AmplitudeParser.Value = self.current_amplitude
            self.quantityI.OffsetParser.Value    = self.current_offset
            self.quantityI.FrequencyParser.Value = self.current_frequency
            self.quantityI.RatioParser.Value     = self.current_ratio

            self.current_formula = formula
            print(f"✅ Benutzerdefinierte Wellenform gesetzt: {formula}")
            print(f"   {num_points} Punkte | Amplitude: {self.current_amplitude}A "
                  f"| Offset: {self.current_offset}A | Frequenz: {self.current_frequency}Hz")

            return np.array(userWaveForm)

        except Exception as e:
            print(f"❌ Fehler beim Setzen der Wellenform: {e}")
            import traceback
            traceback.print_exc()
            return None

    # --------------------------------------------------
    # Start / Stop / Toggle
    # --------------------------------------------------

    def toggle(self):
        """Schaltet Generator ein/aus."""
        if not self.is_available:
            return False
        if self.is_running:
            self.stop()
            return False
        else:
            self.start_continuous()
            return True

    def start_continuous(self):
        """Startet den Funktionsgenerator kontinuierlich."""
        if not self.is_available:
            return False
        if self.is_running:
            print("⚠️ Generator läuft bereits!")
            return

        try:
            WaveformType = self.quantityI.Waveform.GetType()
            self.quantityI.Waveform = Enum.ToObject(WaveformType, self.current_waveform)
            self.quantityI.FrequencyParser.Value = self.current_frequency
            self.quantityI.AmplitudeParser.Value = self.current_amplitude
            self.quantityI.OffsetParser.Value    = self.current_offset
            self.quantityI.RatioParser.Value     = self.current_ratio
            self.quantityI.SingleShot            = False

            self.cassyios.OscilloscopeInterval = 0.1
            self.cassyios.OscilloscopeCount    = 10
            self.cassyios.DoOscilloscope()

            self.is_running = True
            print("▶️ Generator gestartet (kontinuierlich)")

        except Exception as e:
            print(f"❌ Fehler beim Starten: {e}")
            raise

    def start_with_measurement(self, interval=0.1, duration=20, callback=None):
        """Startet Generator mit Messwerterfassung."""
        if not self.is_available:
            return False
        if self.is_running:
            print("⚠️ Generator läuft bereits!")
            return None

        self.cassyios.OscilloscopeInterval = interval
        self.cassyios.OscilloscopeCount    = int(duration / interval) + 1

        print(f"▶️ Starte Messung ({duration}s, dt={interval}s)...")

        times, currents, voltages = [], [], []
        self.is_running = True

        try:
            i = 0
            while not self.cassyios.DoOscilloscope():
                for j in range(i, min(self.quantityI.Values.Count,
                                      self.quantityU.Values.Count)):
                    t = self.cassyios.Times[j]
                    I = self.quantityI.Values[j]
                    U = self.quantityU.Values[j]
                    times.append(t)
                    currents.append(I)
                    voltages.append(U)
                    if callback:
                        callback(t, I, U)
                    i = j + 1

            print("✅ Messung abgeschlossen.")
            return {'times': times, 'currents': currents, 'voltages': voltages}

        except Exception as e:
            print(f"❌ Fehler während Messung: {e}")
            raise
        finally:
            self.is_running = False

    def stop(self):
        """Stoppt den Funktionsgenerator."""
        if not self.is_running:
            print("⚠️ Generator läuft nicht.")
            return

        try:
            WaveformType = self.quantityI.Waveform.GetType()
            self.quantityI.Waveform = Enum.ToObject(WaveformType, self.WAVEFORM_DC)
            self.quantityI.SingleShot            = True
            self.quantityI.OffsetParser.Value    = 0.0
            self.quantityI.AmplitudeParser.Value = 0.0
            self.cassyios.StopOscilloscope()
            self.is_running = False
            print("⏹️ Generator gestoppt.")
        except Exception as e:
            print("❌ Fehler beim Stoppen:", e)

    # --------------------------------------------------
    # Messwerte abfragen
    # --------------------------------------------------

    def get_current_values(self):
        """Liest aktuelle Strom- und Spannungswerte aus."""
        if not self.is_available:
            return False
        try:
            self.cassyios.DoSingleMeasurement()
            return {
                'current': self.quantityI.Value,
                'voltage': self.quantityU.Value
            }
        except Exception as e:
            print(f"❌ Fehler beim Auslesen: {e}")
            return None

    # --------------------------------------------------
    # Status
    # --------------------------------------------------

    def get_status(self):
        """Gibt den aktuellen Status zurück."""
        return {
            'is_running':    self.is_running,
            'is_open':       self.power_cassy.IsOpen if self.power_cassy else False,
            'power_good':    self.power_cassy.PowerGood if self.power_cassy else False,
            'serial_number': self.power_cassy.SerialNumber if self.power_cassy else None,
            'waveform':      self.current_waveform,
            'amplitude':     self.current_amplitude,
            'frequency':     self.current_frequency,
            'offset':        self.current_offset,
            'ratio':         self.current_ratio,
            'formula':       self.current_formula,
        }

    def is_ready(self):
        """Prüft, ob CASSY bereit ist."""
        return (self.power_cassy is not None and
                self.power_cassy.IsOpen and
                self.power_cassy.PowerGood)

    # --------------------------------------------------
    # Cleanup
    # --------------------------------------------------

    def close(self):
        """Schließt alle Verbindungen und gibt Ressourcen frei."""
        print("🔌 Schließe Power-CASSY...")
        if self.is_running:
            self.stop()
        try:
            if self.cassyios:
                self.cassyios.Dispose()
        except Exception:
            pass
        try:
            if self.power_cassy:
                self.power_cassy.Close()
        except Exception:
            pass
        print("✅ Power-CASSY geschlossen.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# --------------------------------------------------
# Sensor-CASSY Controller
# --------------------------------------------------

class SensorCassyController:
    """
    Controller zum Auslesen von Sensoreingängen am Sensor-CASSY.

    Unterstützte Box-Typen:
      'voltage'   – Box524013: Standard-Spannungseingang (±10V), input_index = 0 (A) oder 1 (B)
      'microvolt' – Box524040: µV-Box für Induktionsspannungen
    """

    def __init__(self, dll_path, box_type='voltage', input_index=0, cassy=None):
        """
        Args:
            dll_path (str):    Pfad zur LD.Api.dll
            box_type (str):    'voltage' für Box524013, 'microvolt' für Box524040
            input_index (int): Eingangsindex für Box524013 (0=A, 1=B); für Box524040 ignoriert
            cassy:             Optional: bereits gefundenes Sensor-CASSY Objekt
                               aus find_cassys(). Falls None, wird selbst gescannt.
        """
        self.dll_path      = dll_path
        self.box_type      = box_type
        self.input_index   = input_index
        self._cassy_device = cassy
        self.sensor_cassy  = None
        self.cassyios      = None
        self.box           = None
        self.quantityU     = None
        self.is_available  = False

        try:
            self._initialize()
            self.is_available = True
        except Exception as e:
            print(f"⚠️ Sensor-CASSY nicht verfügbar: {e}")
            self.is_available = False

    def _initialize(self):
        """Initialisiert Sensor-CASSY mit der gewählten Box."""
        clr.AddReference(self.dll_path)

        from LD.Api import CASSYs, CASSYTypes
        from LD.Api.IOs import CASSYIOs, Box524013, Box524040, ScanMode

        self.ScanMode = ScanMode

        if self._cassy_device is not None:
            self.sensor_cassy = self._cassy_device
            print(f"✅ Sensor-CASSY übernommen: {self.sensor_cassy.Text}")
        else:
            print("🔍 Suche Sensor-CASSY...")
            cassys_list = CASSYs()
            cassys_list.Scan()
            
            if cassys_list.Count == 0:
                raise RuntimeError("Kein CASSY-Gerät gefunden.")
            
            for cassy in cassys_list:
                print(f"  Gefunden: {cassy.Text} (Typ: {cassy.CASSYType})")
                if cassy.CASSYType == CASSYTypes.Sensor:
                    self.sensor_cassy = cassy
                    break

        if self.sensor_cassy is None:
            raise RuntimeError("Kein Sensor-CASSY gefunden.")

        self.sensor_cassy.Open()

        self.cassyios = CASSYIOs()
        self.cassyios.AutoDefaults = True

        if self.box_type == 'microvolt':
            self.box = Box524040(self.sensor_cassy, 0)
            self.cassyios.Add(self.box)
            self.cassyios.Scan(ScanMode.ScanOnly)
            self.quantityU = self.box.QuantityU
            self.quantityU.Selected = True
            self.quantityU.SingleShot = True
        else:
            self.box = Box524013(self.sensor_cassy, self.input_index)
            self.cassyios.Add(self.box)
            self.cassyios.Scan(ScanMode.ScanOnly)
            self.quantityU = self.box.QuantityU
            self.quantityU.Selected  = True
            self.quantityU.SingleShot = True

        print(f"   Box: {self.box.SensorBoxName} | Gültig: {self.box.SensorBoxValid}")
        try:
            print(f"   Einheit: {self.quantityU.ValueUnitString}")
        except Exception:
            pass

    def read_voltage(self):
        """Liest einen einzelnen Spannungswert."""
        if not self.is_available:
            return None
        try:
            self.cassyios.Scan(self.ScanMode.ScanOnly)
            self.cassyios.DoSingleMeasurement()
            return self._to_float(self.quantityU.Value)
        except Exception as e:
            print(f"❌ Fehler beim Auslesen: {e}")
            return None

    def voltage_unit_string(self):
        """Gibt die Einheit der gemessenen Spannung zurück."""
        if not self.is_available:
            return "nicht verfügbar"
        try:
            return str(self.quantityU.ValueUnitString)
        except Exception:
            return "µV" if self.box_type == 'microvolt' else "V"

    def close(self):
        """Schließt alle Verbindungen."""
        print("🔌 Schließe Sensor-CASSY...")
        try:
            if self.cassyios:
                self.cassyios.Dispose()
        except Exception:
            pass
        try:
            if self.sensor_cassy:
                self.sensor_cassy.Close()
        except Exception:
            pass
        print("✅ Sensor-CASSY geschlossen.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def _to_float(value):
        if hasattr(value, "HasValue") and hasattr(value, "Value"):
            if not value.HasValue:
                return None
            value = value.Value
        try:
            v = float(value)
            return None if np.isnan(v) else v
        except Exception:
            return None