import gi
import sys # Asegúrate de que sys esté importado para sys.exit()
import threading # Necesario para el hilo
import time 

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject, GLib

Gst.init(None)

# ... (El PIPELINE_DESCRIPTION va aquí) ...

class GStreamerPipeline:
    def __init__(self, pipeline_desc):
        self.pipeline = Gst.parse_launch(pipeline_desc)
        self.loop = GLib.MainLoop()
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self.on_message)
        self.thread = threading.Thread(target=self.run_pipeline)

    def on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS or t == Gst.MessageType.ERROR:
            err, debug = (message.parse_error() if t == Gst.MessageType.ERROR else (None, None))
            print(f"\n[GStreamer] Stream detenido. ERROR: {err if err else 'EOS'}")
            self.stop()
        return True

    def run_pipeline(self):
        # El loop.run() se ejecuta en el hilo separado
        self.pipeline.set_state(Gst.State.PLAYING)
        self.loop.run()

    def start(self):
        print("▶️ Iniciando reproducción en hilo separado...")
        self.thread.start()

    def stop(self):
        # Función para detener el loop y liberar recursos
        if self.loop.is_running():
            self.loop.quit()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)

# --- Ejecución Principal ---
if __name__ == "__main__":
    
    # Define la descripción de tu pipeline aquí para que sea más fácil de usar
    PIPELINE_DESCRIPTION = (
        "udpsrc port=5000 caps=\"application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96\" "
        "! rtph264depay ! h264parse ! decodebin ! videoconvert ! autovideosink"
    )

    client = GStreamerPipeline(PIPELINE_DESCRIPTION)
    client.start()

    print("✅ Cliente iniciado. Presiona Ctrl+C para detener el proceso principal.")
    
    try:
        # El hilo principal se queda aquí esperando.
        while client.thread.is_alive():
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        # El Ctrl+C se captura aquí, donde es seguro
        print("\n[Ctrl+C detectado] Enviando señal de detención al GStreamer...")
    
    finally:
        # Asegúrate de detener el pipeline cuando el script finalice
        client.stop()
        if client.thread.is_alive():
            client.thread.join() # Espera a que el hilo termine

    print("Programa finalizado y recursos liberados.")