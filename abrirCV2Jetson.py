#!/usr/bin/env python3
# Captura UDP/H264 con GStreamer + appsink (PyGObject) y muestra con OpenCV.
# Requiere: python3-gi, gir1.2-gstreamer-1.0, gstreamer1.0-plugins-good/bad/ugly/libav, python3-opencv
#
# Ejemplo de uso:
#   python3 captura_gst_appsink.py
#
# Nota: si tienes hardware decoder (nvv4l2decoder) puedes reemplazar "avdec_h264" por "nvv4l2decoder"
# en la variable PIPELINE.

import sys
import cv2
import numpy as np
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

Gst.init(None)

# Cambia puerto/caps según emisor. Aquí uso avdec_h264 (software) para máxima compatibilidad.
PIPELINE = (
    'udpsrc port=5000 caps="application/x-rtp, media=video, '
    'clock-rate=90000, encoding-name=H264, payload=96" '
    '! rtpjitterbuffer ! rtph264depay ! h264parse ! avdec_h264 '
    '! videoconvert ! video/x-raw,format=BGR ! appsink name=sink emit-signals=true '
    'max-buffers=2 drop=true sync=false'
)

def on_message(bus, message, loop):
    t = message.type
    if t == Gst.MessageType.EOS:
        print("End-Of-Stream")
        loop.quit()
    elif t == Gst.MessageType.ERROR:
        err, dbg = message.parse_error()
        print("GStreamer Error:", err, dbg)
        loop.quit()

def new_sample(sink, data):
    sample = sink.emit('pull-sample')
    if not sample:
        return Gst.FlowReturn.EOS
    buf = sample.get_buffer()
    caps = sample.get_caps()
    # Obtener info de imagen
    structure = caps.get_structure(0)
    width = structure.get_value('width')
    height = structure.get_value('height')
    # Map buffer y convertir a numpy array
    result, mapinfo = buf.map(Gst.MapFlags.READ)
    if not result:
        return Gst.FlowReturn.ERROR
    try:
        arr = np.frombuffer(mapinfo.data, dtype=np.uint8)
        # El formato es BGR packed (height * width * 3)
        frame = arr.reshape((height, width, 3))
        # Mostrar con OpenCV
        cv2.imshow('stream-gst-appsink', frame)
        k = cv2.waitKey(1) & 0xFF
        if k == ord('q'):
            data['loop'].quit()
    except Exception as e:
        print("Error procesando frame:", e)
    finally:
        buf.unmap(mapinfo)
    return Gst.FlowReturn.OK

def main():
    print("Pipeline usada:")
    print(PIPELINE)
    pipeline = Gst.parse_launch(PIPELINE)
    sink = pipeline.get_by_name('sink')
    if not sink:
        print("No se encontró appsink en la pipeline.")
        return 1

    loop = GLib.MainLoop()
    data = {'loop': loop}

    # Connect signal to receive frames
    sink.connect('new-sample', new_sample, data)

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_message, loop)

    pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    pipeline.set_state(Gst.State.NULL)
    cv2.destroyAllWindows()
    return 0

if __name__ == '__main__':
    sys.exit(main())