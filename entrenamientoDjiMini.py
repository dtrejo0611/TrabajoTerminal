from ultralytics import YOLO

if __name__ == "__main__":

    modelo = YOLO("yolov8m.pt")
    #Conforme realize los entrenamientos debo cambiar las epocas y el batch hasta que me de un resultado optimo
    modelo.train(data="./datasets/djimini/data.yaml", epochs=50, batch=8, 
                 optimizer='Adam', lr0=0.0001, pretrained=True)
