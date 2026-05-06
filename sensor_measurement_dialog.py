import time

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6 import QtCore, QtWidgets


class SensorMeasurementDialog(QtWidgets.QDialog):
    def __init__(self, sensor_cassy, power_cassy=None, parent=None):
        super().__init__(parent)

        self.sensor_cassy = sensor_cassy
        self.power_cassy = power_cassy
        self.times = []
        self.voltages = []
        self.currents = []
        self.integrated_voltages = []
        self._start_time = None
        self._started_power_cassy = False

        self.setWindowTitle("Sensor-CASSY Spannungsmessung")
        self.resize(900, 600)

        self.figure = Figure(figsize=(7, 4), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)

        self.integrate_checkbox = QtWidgets.QCheckBox("Spannung integrieren")
        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(20, 5000)
        self.interval_spin.setValue(100)
        self.interval_spin.setSuffix(" ms")

        self.start_button = QtWidgets.QPushButton("Messung starten")
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.clear_button = QtWidgets.QPushButton("Zuruecksetzen")
        self.export_button = QtWidgets.QPushButton("Export")
        self.status_label = QtWidgets.QLabel("Bereit")

        self.stop_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.start_button.setEnabled(bool(sensor_cassy and sensor_cassy.is_available))
        if not self.start_button.isEnabled():
            self.status_label.setText("Sensor-CASSY nicht verfuegbar")

        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(self.integrate_checkbox)
        controls.addWidget(QtWidgets.QLabel("Intervall"))
        controls.addWidget(self.interval_spin)
        controls.addStretch(1)
        controls.addWidget(self.status_label)
        controls.addWidget(self.clear_button)
        controls.addWidget(self.export_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.start_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.canvas, stretch=1)
        layout.addLayout(controls)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._poll_voltage)

        self.start_button.clicked.connect(self.start_measurement)
        self.stop_button.clicked.connect(self.stop_measurement)
        self.clear_button.clicked.connect(self.clear_measurement)
        self.export_button.clicked.connect(self.export_measurement)
        self.integrate_checkbox.toggled.connect(self._redraw)

        self._redraw()

    def start_measurement(self):
        if not self.sensor_cassy or not self.sensor_cassy.is_available:
            self.status_label.setText("Sensor-CASSY nicht verfuegbar")
            return

        if self.power_cassy and self.power_cassy.is_available and not self.power_cassy.is_running:
            try:
                self.power_cassy.start_continuous()
                self._started_power_cassy = True
                self.status_label.setText("Power-CASSY gestartet")
            except Exception as e:
                self.status_label.setText(f"CASSY Startfehler: {e}")
                return

        self.clear_measurement()
        self._start_time = time.monotonic()
        self.timer.start(self.interval_spin.value())
        self.interval_spin.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Messung laeuft")

    def stop_measurement(self):
        self.timer.stop()
        self.interval_spin.setEnabled(True)
        self.start_button.setEnabled(bool(self.sensor_cassy and self.sensor_cassy.is_available))
        self.stop_button.setEnabled(False)
        self.status_label.setText(f"{len(self.times)} Messwerte")

        if self._started_power_cassy and self.power_cassy and self.power_cassy.is_available and self.power_cassy.is_running:
            try:
                self.power_cassy.stop()
            except Exception:
                pass
            self._started_power_cassy = False

    def clear_measurement(self):
        self.times.clear()
        self.voltages.clear()
        self.currents.clear()
        self.integrated_voltages.clear()
        self.export_button.setEnabled(False)
        self._redraw()

    def export_measurement(self):
        if not self.times:
            self.status_label.setText("Keine Messwerte zum Export")
            return

        filepath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Messwerte exportieren",
            "sensor_cassy_messung.txt",
            "Textdateien (*.txt);;Alle Dateien (*)"
        )
        if not filepath:
            return

        try:
            self._write_measurement_file(filepath)
            self.status_label.setText(f"Exportiert: {filepath}")
        except Exception as e:
            self.status_label.setText(f"Exportfehler: {e}")

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)

    def _poll_voltage(self):
        try:
            voltage = self.sensor_cassy.read_voltage()
        except Exception as e:
            self.stop_measurement()
            self.status_label.setText(f"Messfehler: {e}")
            return

        if voltage is None or np.isnan(voltage):
            self.status_label.setText("Kein Messwert")
            return

        elapsed = time.monotonic() - self._start_time
        current = self._read_current()

        self.times.append(elapsed)
        self.voltages.append(voltage)
        self.currents.append(current)
        self.integrated_voltages.append(self._integral_value())
        self.export_button.setEnabled(True)

        self.status_label.setText(f"U = {voltage:.5g} V")
        self._redraw()

    def _write_measurement_file(self, filepath):
        with open(filepath, "w", encoding="utf-8") as file:
            file.write("# Sensor-CASSY Messwerte\n")
            file.write("# Spalten: t_s\tU_V\tI_A\tint_U_Vs\n")
            file.write("t_s\tU_V\tI_A\tint_U_Vs\n")
            for t, u, i, integral in zip(
                self.times,
                self.voltages,
                self.currents,
                self.integrated_voltages
            ):
                voltage = "" if u is None or np.isnan(u) else f"{u:.10g}"
                current = "" if i is None or np.isnan(i) else f"{i:.10g}"
                integration = "" if integral is None or np.isnan(integral) else f"{integral:.10g}"
                file.write(f"{t:.10g}\t{voltage}\t{current}\t{integration}\n")

    def _read_current(self):
        if not self.power_cassy or not self.power_cassy.is_available or not self.power_cassy.is_running:
            return None

        values = self.power_cassy.get_current_values()
        if not values:
            return None

        current = float(values["current"])
        if np.isnan(current):
            return None
        return current

    def _integral_value(self):
        if len(self.times) < 2:
            return 0.0

        dt = self.times[-1] - self.times[-2]
        area = 0.5 * (self.voltages[-1] + self.voltages[-2]) * dt
        return self.integrated_voltages[-1] + area

    def _redraw(self):
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)

        if self.integrate_checkbox.isChecked():
            usable = [(i, y) for i, y in zip(self.currents, self.integrated_voltages) if i is not None]
            if usable:
                x_values, y_values = zip(*usable)
                self.ax.plot(x_values, y_values, linewidth=1.8)
                self.ax.set_xlabel("Strom I (A)")
                self.ax.set_ylabel("Integral der Spannung (V s)")
                self.ax.set_title("Hysteresekurve")
            else:
                self.ax.plot(self.times, self.integrated_voltages, linewidth=1.8)
                self.ax.set_xlabel("Zeit (s)")
                self.ax.set_ylabel("Integral der Spannung (V s)")
                self.ax.set_title("Integrierte Spannung")
        else:
            self.ax.plot(self.times, self.voltages, linewidth=1.8)
            self.ax.set_xlabel("Zeit (s)")
            self.ax.set_ylabel("Spannung U (V)")
            self.ax.set_title("Sensor-CASSY Spannung")

        if self.times:
            self.ax.relim()
            self.ax.autoscale_view()
        else:
            self.ax.set_xlim(0, 1)
            self.ax.set_ylim(-1, 1)

        self.figure.tight_layout()
        self.canvas.draw_idle()
