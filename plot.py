from PySide6.QtWidgets import QWidget, QVBoxLayout
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import numpy as np


class WaveformPlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.figure = Figure(figsize=(5, 3), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self.ax = self.figure.add_subplot(111)
        self.ax.set_title("Benutzerdefinierte Wellenform")
        self.ax.set_xlabel(r"$x \in (0,1)$, ")
        self.ax.set_ylabel("Amplitude")

    def plot_waveform(self, values, amplitude=1.0, offset=0.0, frequency = 0.1):
        """
        Plottet die Wellenform mit Berücksichtigung von Amplitude und Offset
        
        Args:
            values: numpy array mit Wellenform-Werten (bereits skaliert!)
            amplitude: Nur für Anzeige (falls values noch nicht skaliert)
            offset: Nur für Anzeige
        """
        self.ax.clear()

        x = np.linspace(0, 1, len(values))
        self.ax.plot(x, values, linewidth=2)

        # Titel mit Parametern
        self.ax.set_title(f"Benutzerdefinierte Wellenform\nA={amplitude:.2f}A, Offset={offset:.2f}A")
        self.ax.set_xlabel(r"$x \in (0,1)$, " + f"{1/frequency:.2f} s")
        self.ax.set_ylabel("Strom (A)")
        
        # Grid und Y-Achsen-Limits
        self.ax.grid(True, alpha=0.3)
        
        # Y-Achse dynamisch anpassen
        y_min = values.min()
        y_max = values.max()
        margin = (y_max - y_min) * 0.1  # 10% Rand
        self.ax.set_ylim(y_min - margin, y_max + margin)
        
        # Nulllinie einzeichnen
        self.ax.axhline(y=0, color='k', linestyle='--', linewidth=0.5, alpha=0.5)

        self.figure.tight_layout()
        self.canvas.draw()

