import gi
import sys
import threading
import time

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject, GLib

import numpy as np
import cv2

Gst.init(None)

class GStreamerPipeline:
    def __init__(self, pipeline_desc):
        self.pipeline = Gst.parse_launch(pipeline_desc)
        self.loop = GLib.MainLoop()
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self.on_message)
        self.thread = threading.Thread(target=self.run_pipeline)
        self.last_frame = None  # Aquí guardamos el último frame recibido
        self.stop_stream = False

        # Appsink setup
        self.appsink = self.pipeline.get_by_name("mysink")
        self.appsink.set_property("emit-signals", True)
        self.appsink.connect("new-sample", self.on_new_sample)

    def on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS or t == Gst.MessageType.ERROR:
            err, debug = (message.parse_error() if t == Gst.MessageType.ERROR else (None, None))
            print(f"\n[GStreamer] Stream detenido. ERROR: {err if err else 'EOS'}")
            self.stop()
        return True

    def on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        caps = sample.get_caps()
        width = caps.get_structure(0).get_value("width")
        height = caps.get_structure(0).get_value("height")
        success, map_info = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.ERROR
        try:
            frame = np.ndarray(
                (height, width, 3),
                dtype=np.uint8,
                buffer=map_info.data
            )
            self.last_frame = frame.copy() # Guardamos la última imagen recibida
            cv2.imshow("Stream", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('s'):
                fname = f"frame_{int(time.time())}.png"
                cv2.imwrite(fname, frame)
                print(f"Frame guardado como {fname}")
            if key == ord('q'):
                self.stop()
        finally:
            buf.unmap(map_info)
        return Gst.FlowReturn.OK

    def run_pipeline(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        self.loop.run()

    def start(self):
        print("▶️ Iniciando reproducción en hilo separado...")
        self.thread.start()

    def stop(self):
        if self.loop.is_running():
            self.loop.quit()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        cv2.destroyAllWindows()
        self.stop_stream = True

# --- Ejecución Principal ---
if __name__ == "__main__":
    PIPELINE_DESCRIPTION = (
        "udpsrc port=5000 caps=\"application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96\" "
        "! rtph264depay ! h264parse ! decodebin ! videoconvert ! video/x-raw,format=BGR "
        "! appsink sync=false max-buffers=1 drop=true name=mysink"
    )

    client = GStreamerPipeline(PIPELINE_DESCRIPTION)
    client.start()

    print("✅ Cliente iniciado. Presiona 's' para guardar un frame como PNG o 'q' para salir.")
    
    try:
        while client.thread.is_alive() and not client.stop_stream:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[Ctrl+C detectado] Enviando señal de detención al GStreamer...")
    finally:
        client.stop()
        if client.thread.is_alive():
            client.thread.join()
    print("Programa finalizado y recursos liberados.")