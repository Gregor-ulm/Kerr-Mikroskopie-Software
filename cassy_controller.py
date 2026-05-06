"""
CassyController - Klasse zur Steuerung des Power-CASSY
Unterstützt: Dreieck, Sinus, Gleichstrom und benutzerdefinierte Formeln
"""

import clr
import time
from System import Enum
import numpy as np
from math import pi, sin, cos, tan, exp, log, sqrt



class CassyController:
    """
    Controller für Power-CASSY Stromsteuerung
    
    Wellenformen:
    - 0: DC (Gleichstrom)
    - 1: Sinus
    - 2: Rechteck (±Amplitude)
    - 3: Rechteck (0 bis Amplitude)
    - 4: Dreieck (±Amplitude)
    - 5: Dreieck (0 bis Amplitude)
    - 6: Benutzerdefiniert (Formula)
    """
    
    # Wellenform-Konstanten
    WAVEFORM_DC = 0
    WAVEFORM_SINE = 1
    WAVEFORM_SQUARE = 2
    WAVEFORM_SQUARE_UP = 3
    WAVEFORM_TRIANGLE = 4
    WAVEFORM_TRIANGLE_UP = 5
    WAVEFORM_USER = 6
    
    def __init__(self, dll_path):
        self.dll_path = dll_path
        self.power_cassy = None
        self.cassyios = None
        self.io = None
        self.quantityI = None
        self.quantityU = None
        self.is_running = False
        self.is_available = False
        
        # Aktuelle Parameter speichern
        self.current_waveform = self.WAVEFORM_DC
        self.current_amplitude = 0.0
        self.current_frequency = 0.05
        self.current_offset = 0.0
        self.current_ratio = 50
        self.current_formula = ""
        
        try:
            self._initialize()
            self.is_available = True
        except Exception as e:
            print(f"⚠️ CASSY nicht verfügbar: {e}")
            self.is_available = False
    
    # --------------------------------------------------
    # Initialisierung
    # --------------------------------------------------
    
    def _initialize(self):
        """Initialisiert Power-CASSY und IO"""
        clr.AddReference(self.dll_path)
        
        from LD.Api import CASSYs, CASSYTypes
        from LD.Api.IOs import CASSYIOs, Box524011, ScanMode
        
        self.CASSYs = CASSYs
        self.CASSYTypes = CASSYTypes
        self.CASSYIOs = CASSYIOs
        self.Box524011 = Box524011
        self.ScanMode = ScanMode
        
        print("🔍 Suche Power-CASSY...")
        
        cassys_list = self.CASSYs()
        cassys_list.Scan()
        
        if cassys_list.Count == 0:
            raise RuntimeError("Kein CASSY-Gerät gefunden.")
        
        for cassy in cassys_list:
            if cassy.CASSYType == self.CASSYTypes.Power:
                self.power_cassy = cassy
                break
        
        if self.power_cassy is None:
            raise RuntimeError("Kein Power-CASSY gefunden.")
        
        print(f"✅ Power-CASSY: {self.power_cassy.Text}")
        
        self.power_cassy.Open()
        
        if not self.power_cassy.PowerGood:
            raise RuntimeError("Power-CASSY nicht an externer Versorgung!")
        
        # IO Setup
        self.cassyios = self.CASSYIOs()
        self.cassyios.AutoDefaults = True
        
        self.io = self.Box524011(self.power_cassy)
        self.cassyios.Add(self.io)
        self.cassyios.Scan(self.ScanMode.ScanOnly)
        
        self.quantityI = self.io.QuantityOutputI
        self.quantityU = self.io.QuantityInputU
        
        self.quantityI.Selected = True
        self.quantityU.Selected = True
        self.quantityI.SingleShot = True
        
        print("⚡ CASSY bereit.")
    
    # --------------------------------------------------
    # Wellenform-Konfiguration (Hauptmethode)
    # --------------------------------------------------
    
    def configure_waveform(self, waveform_type, amplitude=1.0, frequency=0.05,
                      offset=0.0, ratio=50, formula=None):
        """
        Konfiguriert die Wellenform des Stromausgangs
        """
        if not self.is_available:
            return False
        
        # Parameter ZUERST speichern (wichtig für set_formula!)
        self.current_waveform = waveform_type
        self.current_amplitude = amplitude
        self.current_frequency = frequency
        self.current_offset = offset
        self.current_ratio = ratio
        if formula:
            self.current_formula = formula
        
        WaveformType = self.quantityI.Waveform.GetType()
        
        # Bei benutzerdefinierten Wellenformen: ZUERST Formel setzen
        if waveform_type == self.WAVEFORM_USER and formula is not None:
            # set_formula verwendet self.current_* Werte!
            self.set_formula(formula)
        else:
            # Normale Wellenform setzen
            self.quantityI.Waveform = Enum.ToObject(WaveformType, waveform_type)
            
            # Parameter setzen
            self.quantityI.FrequencyParser.Value = frequency
            self.quantityI.AmplitudeParser.Value = amplitude
            self.quantityI.OffsetParser.Value = offset
            self.quantityI.RatioParser.Value = ratio
        
        waveform_names = {
            0: "Gleichstrom (DC)",
            1: "Sinus",
            2: "Rechteck (±A)",
            3: "Rechteck (0-A)",
            4: "Dreieck (±A)",
            5: "Dreieck (0-A)",
            6: "Benutzerdefiniert"
        }
        """
        print(f"⚙️ Wellenform konfiguriert: {waveform_names.get(waveform_type, 'Unbekannt')}")
        print(f"   Amplitude: {amplitude} A")
        print(f"   Frequenz:  {frequency} Hz")
        print(f"   Offset:    {offset} A")
        print(f"   Ratio:     {ratio}%")
        if formula:
            print(f"   Formel:    {formula}")
        """
    # --------------------------------------------------
    # Spezielle Konfigurationsmethoden
    # --------------------------------------------------
    
    def configure_dc(self, current=1.0):
        """Konfiguriert Gleichstrom"""
        self.configure_waveform(
            waveform_type=self.WAVEFORM_DC,
            amplitude=0.0,
            frequency=0.0,
            offset=current,
            ratio=50
        )
    
    def configure_sine(self, amplitude=1.0, frequency=0.05, offset=0.0):
        """Konfiguriert Sinusstrom"""
        self.configure_waveform(
            waveform_type=self.WAVEFORM_SINE,
            amplitude=amplitude,
            frequency=frequency,
            offset=offset,
            ratio=50
        )
    
    def configure_triangle(self, amplitude=1.0, frequency=0.05, 
                          offset=0.0, ratio=.5, zero_based=False):
        """Konfiguriert Dreiecksstrom"""
        waveform = self.WAVEFORM_TRIANGLE
        self.configure_waveform(
            waveform_type=waveform,
            amplitude=amplitude,
            frequency=frequency,
            offset=offset,
            ratio=ratio
        )
    
    def set_formula(self, formula):
        """
        Setzt eine benutzerdefinierte Wellenform basierend auf einer Formel
        
        Args:
            formula (str): Python-Ausdruck mit 'x' als Variable (0 bis 1)
                          Beispiele: "sin(2*pi*x)", "x**2", "abs(sin(10*pi*x))"
        
        WICHTIG: Die Formel definiert nur die FORM (normalisiert -1 bis 1).
                Amplitude und Offset werden SEPARAT über die Parser-Properties gesetzt!
        """
        if not self.is_available:
            return False
        
        try:
            # Wellenform auf User setzen
            WaveformType = self.quantityI.Waveform.GetType()
            self.quantityI.Waveform = Enum.ToObject(WaveformType, self.WAVEFORM_USER)
            
            # Array mit 4000 Werten erstellen
            num_points = 4000
            userWaveForm = []
            
            # Formel für jeden Punkt auswerten (x von 0 bis 1)
            for j in range(num_points):
                x = j / num_points  # x läuft von 0 bis ~1 (eine Periode)
                
                try:
                    # Formel auswerten → sollte Werte zwischen -1 und 1 liefern
                    value = eval(formula, {"__builtins__": {}}, {
                        'x': x, 'pi': pi, 'sin': sin, 'cos': cos, 
                        'tan': tan, 'exp': exp, 'log': log, 
                        'sqrt': sqrt, 'abs': abs, 'np': np
                    })
                    userWaveForm.append(float(value))
                except Exception as e:
                    raise ValueError(f"Fehler in Formel bei x={x}: {e}")
            
            # .NET Array erstellen
            from System import Array, Double
            dotnet_array = Array[Double](userWaveForm)
            
            # Wellenform setzen über WaveformParser
            self.quantityI.WaveformParser.SetWaveform(dotnet_array)
            
            # WICHTIG: Amplitude, Offset, Frequenz NACH SetWaveform setzen!
            # Diese Parameter skalieren/verschieben die definierte Wellenform
            self.quantityI.AmplitudeParser.Value = self.current_amplitude
            self.quantityI.OffsetParser.Value = self.current_offset
            self.quantityI.FrequencyParser.Value = self.current_frequency
            self.quantityI.RatioParser.Value = self.current_ratio
            
            self.current_formula = formula
            print(f"✅ Benutzerdefinierte Wellenform gesetzt: {formula}")
            print(f"   {num_points} Punkte generiert")
            print(f"   Amplitude: {self.current_amplitude}A, Offset: {self.current_offset}A")
            print(f"   Frequenz: {self.current_frequency}Hz")
            
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
        """Schaltet Generator ein/aus"""
        if not self.is_available:
            return False
        if self.is_running:
            self.stop()
            return False
        else:
            self.start_continuous()
            return True
    
    def start_continuous(self):
        """Startet den Funktionsgenerator kontinuierlich"""
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
            self.quantityI.OffsetParser.Value = self.current_offset
            self.quantityI.RatioParser.Value = self.current_ratio
            
            
            self.quantityI.SingleShot = False
            # Minimale Oszilloskop-Konfiguration für kontinuierlichen Betrieb
            self.cassyios.OscilloscopeInterval = 0.1
            self.cassyios.OscilloscopeCount = 10
            
            # Starten (blockiert NICHT!)
            self.cassyios.DoOscilloscope()
            
            self.is_running = True
            print("▶️ Generator gestartet (kontinuierlich)")
            
        except Exception as e:
            print(f"❌ Fehler beim Starten: {e}")
            raise
    
    def start_with_measurement(self, interval=0.1, duration=20, callback=None):
        """Startet Generator mit Messwerterfassung"""
        if not self.is_available:
            return False
        if self.is_running:
            print("⚠️ Generator läuft bereits!")
            return None
        
        self.cassyios.OscilloscopeInterval = interval
        self.cassyios.OscilloscopeCount = int(duration / interval) + 1
        
        print(f"▶️ Starte Messung ({duration}s, dt={interval}s)...")
        
        times = []
        currents = []
        voltages = []
        
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
            
            return {
                'times': times,
                'currents': currents,
                'voltages': voltages
            }
            
        except Exception as e:
            print(f"❌ Fehler während Messung: {e}")
            raise
        finally:
            self.is_running = False
    
    def stop(self):
        """Stoppt den Funktionsgenerator"""
        if not self.is_running:
            print("⚠️ Generator läuft nicht.")
            return
        
        try:
            # Generator deaktivieren
            WaveformType = self.quantityI.Waveform.GetType()
            self.quantityI.Waveform = Enum.ToObject(WaveformType, self.WAVEFORM_DC)
            self.quantityI.SingleShot = True
            self.quantityI.OffsetParser.Value = 0.0
            self.quantityI.AmplitudeParser.Value = 0.0
            #self.configure_dc(0.0)
            self.cassyios.StopOscilloscope()
            self.is_running = False
            print("⏹️ Generator gestoppt.")
            

        except Exception as e:
            print("❌ Fehler beim Stoppen:", e)
    
    # --------------------------------------------------
    # Messwerte abfragen
    # --------------------------------------------------
    
    def get_current_values(self):
        """Liest aktuelle Strom- und Spannungswerte aus"""
        if not self.is_available:
            return False
        try:
            self.cassyios.DoSingleMeasurement()
            """
            if self.quantityI.Value.HasValue and self.quantityU.Value.HasValue:
                return {
                    'current': float(self.quantityI.Value.Value),
                    'voltage': float(self.quantityU.Value.Value)
                }
            else:
                return None
            """
            return {'current': self.quantityI.Value,
             'voltage': self.quantityU.Value}

        except Exception as e:
            print(f"❌ Fehler beim Auslesen: {e}")
            return None
    
    # --------------------------------------------------
    # Status-Abfragen
    # --------------------------------------------------
    
    def get_status(self):
        """Gibt den aktuellen Status zurück"""
        return {
            'is_running': self.is_running,
            'is_open': self.power_cassy.IsOpen if self.power_cassy else False,
            'power_good': self.power_cassy.PowerGood if self.power_cassy else False,
            'serial_number': self.power_cassy.SerialNumber if self.power_cassy else None,
            'waveform': self.current_waveform,
            'amplitude': self.current_amplitude,
            'frequency': self.current_frequency,
            'offset': self.current_offset,
            'ratio': self.current_ratio,
            'formula': self.current_formula
        }
    
    def is_ready(self):
        """Prüft, ob CASSY bereit ist"""
        return (self.power_cassy is not None and 
                self.power_cassy.IsOpen and 
                self.power_cassy.PowerGood)
    
    # --------------------------------------------------
    # Cleanup
    # --------------------------------------------------
    
    def close(self):
        """Schließt alle Verbindungen und gibt Ressourcen frei"""
        print("🔌 Schließe CASSY...")
        
        if self.is_running:
            self.stop()
        
        try:
            if self.cassyios:
                self.cassyios.Dispose()
        except:
            pass
        
        try:
            if self.power_cassy:
                self.power_cassy.Close()
        except:
            pass
        
        print("✅ CASSY geschlossen.")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class SensorCassyController:
    """Minimaler Controller zum Auslesen der Spannung am Sensor-CASSY 2."""

    def __init__(self, dll_path, input_index=0):
        self.dll_path = dll_path
        self.input_index = input_index
        self.sensor_cassy = None
        self.cassyios = None
        self.input = None
        self.quantityU = None
        self.is_available = False

        try:
            self._initialize()
            self.is_available = True
        except Exception as e:
            print(f"Sensor-CASSY nicht verfuegbar: {e}")
            self.is_available = False

    def _initialize(self):
        """Initialisiert Sensor-CASSY 2 mit Spannungseingang U."""
        clr.AddReference(self.dll_path)

        from LD.Api import SensorCASSY2
        from LD.Api.IOs import CASSYIOs, Box524013, ScanMode

        self.ScanMode = ScanMode
        self.sensor_cassy = SensorCASSY2()
        self.sensor_cassy.Open()

        self.cassyios = CASSYIOs()
        self.cassyios.AutoDefaults = True
        self.input = Box524013(self.sensor_cassy, self.input_index)
        self.cassyios.Add(self.input)
        self.cassyios.Scan(self.ScanMode.ScanOnly)

        self.quantityU = self.input.QuantityU
        self.quantityU.Selected = True
        self.quantityU.SingleShot = True

        print(f"Sensor-CASSY bereit: {self.sensor_cassy.Text}")

    def read_voltage(self):
        """Liest einen einzelnen Spannungswert mit den aktuell am CASSY gesetzten Einstellungen."""
        if not self.is_available:
            return None

        self.cassyios.Scan(self.ScanMode.ScanOnly)
        self.cassyios.DoSingleMeasurement()
        voltage = self._to_float(self.quantityU.Value)
        if voltage is None or np.isnan(voltage):
            return None
        return voltage

    def voltage_unit_string(self):
        if not self.is_available:
            return "nicht verfuegbar"
        try:
            return str(self.quantityU.ValueUnitString)
        except Exception:
            return ""

    def close(self):
        print("Schliesse Sensor-CASSY...")

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

    @staticmethod
    def _to_float(value):
        if hasattr(value, "HasValue") and hasattr(value, "Value"):
            if not value.HasValue:
                return None
            value = value.Value
        return float(value)
