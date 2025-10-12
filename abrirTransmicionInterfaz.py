#!/usr/bin/env python3
# abrirTransmicionInterfaz.py
# Muestra la transmisión UDP/H264 en displayCam1 usando appsink y decodebin (no requiere avdec_h264)

import sys
import gi
import time
from PyQt5 import QtWidgets, QtCore, QtGui

gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)

from interfaz import Ui_MainWindow


class GstVideoReceiver(QtCore.QObject):
    frameReceived = QtCore.pyqtSignal(QtGui.QPixmap)

    def __init__(self, port=5000, width=1920, height=1080, parent=None):
        super().__init__(parent)
        self.port = port
        self.width = width
        self.height = height
        self.pipeline = None
        self.appsink = None

    def start(self):
        # Usamos decodebin en lugar de avdec_h264 para evitar dependencia explícita
        pipeline_str = (
            f'udpsrc port={self.port} caps="application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96" '
            f'! rtph264depay ! h264parse ! decodebin ! videoconvert ! video/x-raw,format=RGB,width={self.width},height={self.height} '
            f'! appsink name=sink emit-signals=true sync=false max-buffers=1 drop=true'
        )

        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            print(f"[GstVideoReceiver] Error al crear pipeline: {e}")
            return

        self.appsink = self.pipeline.get_by_name("sink")
        if not self.appsink:
            print("[GstVideoReceiver] No se encontró appsink en el pipeline")
            return

        # conectar callback para nuevas muestras
        self.appsink.connect("new-sample", self.on_new_sample)

        self.pipeline.set_state(Gst.State.PLAYING)
        print(f"[GstVideoReceiver] Pipeline iniciado en puerto {self.port}")

    def stop(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            print("[GstVideoReceiver] Pipeline detenido")

    def on_new_sample(self, sink) -> Gst.FlowReturn:
        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.ERROR
    
        buf = sample.get_buffer()
        caps = sample.get_caps()
        if not caps:
            return Gst.FlowReturn.ERROR
    
        s = caps.get_structure(0)
    
        # Obtener ancho/alto desde las caps si están disponibles
        try:
            width = s.get_value("width")
            height = s.get_value("height")
        except Exception:
            width = self.width
            height = self.height
    
        # Intentar leer stride/bytes_per_line si la caps lo reporta (evita corrupción)
        bytes_per_line = None
        try:
            # claves comunes: "stride", "stride0" o "pstride" (varía)
            if s.has_field("stride"):
                bytes_per_line = s.get_value("stride")
            elif s.has_field("stride0"):
                bytes_per_line = s.get_value("stride0")
            elif s.has_field("pstride"):
                bytes_per_line = s.get_value("pstride")
        except Exception:
            bytes_per_line = None
    
        if not bytes_per_line:
            # asunción por defecto: RGB (3 bytes por píxel)
            bytes_per_line = width * 3
    
        success, mapinfo = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.ERROR
    
        try:
            data = mapinfo.data  # bytes
            # Crear QImage usando stride correcto
            qimg = QtGui.QImage(data, width, height, bytes_per_line, QtGui.QImage.Format_RGB888).copy()
            pix = QtGui.QPixmap.fromImage(qimg)
            self.frameReceived.emit(pix)
        finally:
            buf.unmap(mapinfo)
    
        return Gst.FlowReturn.OK


class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self, gst_port=5000, gst_width=1920, gst_height=1080):
        super().__init__()
        self.setupUi(self)

        self.displayCam1.setScaledContents(False)
        self.displayCam1.setText("Esperando transmisión...")

        self.receiver = GstVideoReceiver(port=gst_port, width=gst_width, height=gst_height)
        self.receiver.frameReceived.connect(self.on_frame_received)
        self.receiver.start()

        app = QtWidgets.QApplication.instance()
        app.aboutToQuit.connect(self.cleanup)

    def on_frame_received(self, pixmap: QtGui.QPixmap):
        label = self.displayCam1
        if label.width() <= 0 or label.height() <= 0:
            return
        scaled = pixmap.scaled(label.width(), label.height(), QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
        label.setPixmap(scaled)

    def cleanup(self):
        self.receiver.stop()


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(gst_port=5000, gst_width=1920, gst_height=1080)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()