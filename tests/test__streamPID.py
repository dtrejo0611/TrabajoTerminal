import pytest
from src.camaras.streamPID import ServoController, ServoTracker, ControlServer

# 1. El Fixture: Prepara la clase antes de cada prueba
@pytest.fixture
def servo_ctrl():
    """Instancia la clase ServoController en modo mock (sin hardware real)."""
    controlador = ServoController()
    return controlador

@pytest.mark.parametrize("canal_valido", [
    0,
    7,
    15
])
def test_set_angle_canales_validos(servo_ctrl, canal_valido):
    # Intentamos mover el servo a 90 grados
    resultado = servo_ctrl.set_angle(canal_valido, 90.0)
    
    # La función debe retornar True indicando éxito
    assert resultado is True

@pytest.mark.parametrize("canal_invalido", [
    -1,
    16,
    99
])
def test_set_angle_canales_invalidos(servo_ctrl, canal_invalido):
    # Intentamos mover el servo en un canal que no existe
    resultado = servo_ctrl.set_angle(canal_invalido, 90.0)
    
    # La función debe abortar y retornar False para proteger el sistema
    assert resultado is False

@pytest.mark.parametrize("angulo_valido", [
    0.0,
    95.0,
    180.0
])
def test_set_angle_angulos_validos(servo_ctrl, angulo_valido):
    #Movemos el servo a un ángulo válido
    resultado = servo_ctrl.set_angle(0, angulo_valido)

    #La funcion debe retornar True indicando éxito
    assert resultado is True

@pytest.mark.parametrize("angulo_invalido", [
    -10.0,
    -50.0,
    270.0
])
def test_set_angle_angulos_invalidos(servo_ctrl, angulo_invalido):
    #Movemos el servo a un ángulo inválido
    resultado = servo_ctrl.set_angle(0, angulo_invalido)

    #La funcion debe retornar True por la funcion safe_angle que ajusta el ángulo a un valor seguro
    assert resultado is True

#Siguen las pruebas para la clase ServoTracker, que depende de ServoController

@pytest.fixture
def servo_seg(servo_ctrl):
    """Instancia la clase ServoController en modo mock (sin hardware real)."""
    seg = ServoTracker(servo_ctrl)
    return seg

def test_zona_muerta_no_altera_angulos(servo_seg):
    # El centro perfecto es (320, 180).
    # Le mandamos una coordenada ligeramente movida: (335, 195).
    # Esto genera un error de 15 píxeles en X y 15 en Y.
    # Como 15 es menor que la deadzone (20), el sistema NO debe reaccionar.
    
    servo_seg.update_target(335.0, 195.0)
    
    # Afirmamos que los ángulos de los servos se quedaron intactos en el centro
    assert servo_seg.pan_angle == 90.0
    assert servo_seg.tilt_angle == 90.0
    
    # Afirmamos que la memoria del PID (integral) se reseteó correctamente
    assert servo_seg.integral_x == 0.0
    assert servo_seg.integral_y == 0.0

def test_zona_muerta_altera_angulos(servo_seg):
    # El centro perfecto es (320, 180).
    # Le mandamos una coordenada ligeramente movida: (335, 195).
    # Esto genera un error de 15 píxeles en X y 15 en Y.
    # Como 15 es menor que la deadzone (20), el sistema NO debe reaccionar.
    
    servo_seg.update_target(400.0, 300.0)
    
    # Afirmamos que los ángulos de los servos se quedaron intactos en el centro
    assert servo_seg.pan_angle != 90.0
    assert servo_seg.tilt_angle != 90.0
    
    # Afirmamos que la memoria del PID (integral) se reseteó correctamente
    assert servo_seg.integral_x != 0.0
    assert servo_seg.integral_y != 0.0

def test_limite_inferior_tilt(servo_seg):
    # El centro perfecto es (320, 180).
    # Le mandamos una coordenada ligeramente movida: (335, 195).
    # Esto genera un error de 15 píxeles en X y 15 en Y.
    # Como 15 es menor que la deadzone (20), el sistema NO debe reaccionar.
    for i in range (1000):
        servo_seg.last_update -= 0.2
        servo_seg.update_target(1.0, 1.0)
    
    # Afirmamos que los ángulos de los servos se quedaron intactos en el centro
    assert servo_seg.tilt_angle == 45.0

def test_limite_superior_tilt(servo_seg):
    # El centro perfecto es (320, 180).
    # Le mandamos una coordenada ligeramente movida: (335, 195).
    # Esto genera un error de 15 píxeles en X y 15 en Y.
    # Como 15 es menor que la deadzone (20), el sistema NO debe reaccionar.
    for i in range (1000):
        servo_seg.last_update -= 0.2
        servo_seg.update_target(639.0, 359.0)
    
    # Afirmamos que los ángulos de los servos se quedaron intactos en el centro
    assert servo_seg.tilt_angle == 135.0

def test_idle_sweep(servo_seg):
    
    for i in range(91):
        servo_seg.idle_sweep()

    assert servo_seg.tilt_angle == 70.0
    assert servo_seg.pan_angle == 179.0
    assert servo_seg.pan_sweep_dir == -1

#Siguen las pruebas para la clase ServoTracker, que depende de ServoController

@pytest.fixture
def servidor(servo_ctrl, servo_seg):
    ser = ControlServer("0.0.0.0", 6000, servo_ctrl, servo_seg)
    return ser

@pytest.mark.parametrize("comandos_validos", [
    "SERVO 1 90",
    "TARGET 320 240",
    "COORD 100 100",
    "LOST"
])

def test_comandos_validos(servidor, comandos_validos):
    resultado = servidor.handle_command(comandos_validos)

    assert resultado is not False

@pytest.mark.parametrize("comandos_invalidos", [
    "SERVO 1",
    "TARGET cx cy",
    "COORD 100",
    "",
    "TRES DOS UNO"
])

def test_comandos_invalidos(servidor, comandos_invalidos):
    resultado = servidor.handle_command(comandos_invalidos)

    assert resultado is False