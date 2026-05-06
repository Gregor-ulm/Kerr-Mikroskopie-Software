from PySide6.QtWidgets import QDialog, QVBoxLayout, QFileDialog, QSpinBox, QLineEdit, QToolButton, QLabel, QVBoxLayout
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile
from PySide6 import QtCore, QtWidgets

class SettingsDialog(QDialog):
    def __init__(self, 
                 count=30, 
                 duration=30, 
                 path="", 
                 name="", 
                 cassy_trigger=False, 
                 trigger_mode='rising', 
                 trigger_value=0.0, 
                 step_trigger=False, 
                 trigger_step=0.1, 
                 next_trigger_value=0.0, 
                 single_target=2,
                 parent=None):
        super().__init__(parent)
        
        loader = QUiLoader()
        ui_file = QFile("settings_dialog.ui")
        ui_file.open(QFile.ReadOnly)
        self.ui = loader.load(ui_file)
        self.ui.setWindowFlags(QtCore.Qt.Widget)
        ui_file.close()
        try:
            self.spin_count = self.ui.spinBox_img_count
            self.spinBox_time = self.ui.spinBox_time
            self.line_path = self.ui.lineEdit_save_path
            self.btn_browse = self.ui.toolButton_save_path
            self.fps_lbl = self.ui.lbl_fps
            self.path_lbl = self.ui.lbl_save_path
            self.line_name = self.ui.line_name
            self.single_target_spin = self.ui.spinBox_single_target
            self.cassy_trigger_checkbox = self.ui.checkBox_cassy_trigger
            self.trigger_geq_spinbox = self.ui.SpinBox_trigger_geq
            self.trigger_leq_spinbox = self.ui.SpinBox_trigger_leq
            self.trigger_step_checkbox = self.ui.checkBox_value_trigger
            self.trigger_step_spinbox = self.ui.SpinBox_value_trigger

            # Connect signals
            self.btn_browse.clicked.connect(self.browse_folder)
            self.spin_count.valueChanged.connect(self.update_fps)
            self.spinBox_time.valueChanged.connect(self.update_fps)
            self.btn_browse.clicked.connect(self.browse_folder)
            self.trigger_step_checkbox.toggled.connect(lambda checked: self.trigger_step_spinbox.setEnabled(checked))

            # ... other connections
            self.ui.accepted.connect(self.accept)
            self.ui.rejected.connect(self.reject)
        except AttributeError as e:
            print(f"Error: A widget name in the .ui file does not match: {e}")
        
        main_layout = QtWidgets.QVBoxLayout(self) 
        main_layout.addWidget(self.ui)
        main_layout.setContentsMargins(0, 0, 0, 0) # Optional: removes whitespace
        self.resize(self.ui.sizeHint()) 

        #Setzen der aktuellen Werte
        self.line_path.setText(path)
        self.spin_count.setValue(count)
        self.spinBox_time.setValue(duration)
        self.line_name.setText(name)
        self.cassy_trigger_checkbox.setChecked(cassy_trigger)
        self.trigger_geq_spinbox.setValue(trigger_value)   
        self.trigger_leq_spinbox.setValue(next_trigger_value)
        self.trigger_step_checkbox.setChecked(step_trigger)
        self.trigger_step_spinbox.setValue(trigger_step)
        self.single_target_spin.setValue(single_target)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Ordner auswählen", self.line_path.text())
        if folder:
            self.line_path.setText(folder)

    def update_fps(self):
        if not hasattr(self, 'spin_count') or not self.spin_count:
            return
        count = self.spin_count.value()
        duration = self.spinBox_time.value()
        if duration > 0:
            fps = count / duration
            self.fps_lbl.setText(f"≈ {fps:.1f} Bilder/Sekunde")
        else:
            self.fps_lbl.setText("Dauer muss > 0 sein")
            self.spinBox_time.setValue(1)

    