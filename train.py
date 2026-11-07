"""train the model"""

# pylint: disable=import-error,unused-import
from ultralytics import YOLO

# pylint: enable=import-error,unused-import


def main():
    """main()"""
    # load the base YOLO11 nano model
    model = YOLO("yolo11n.pt")

    # train on Apple M1 Pro GPU using Metal Performance Shaders (device='mps')
    results = model.train(
        data="prey_dataset/data.yaml",
        epochs=50,  # 50 epochs is standard; adjust as needed
        imgsz=640,
        batch=16,  # if unified memory is constrained, drop to 8
        device="mps",  # explicitly enables Apple Silicon GPU
        workers=2,  # lower workers avoid macOS multiprocessing locks
        plots=True,
        project="prey_runs",
        name="yolo11_prey",
    )
    print(f"{ results = }")

    model = YOLO("prey_runs/yolo11_prey/weights/best.pt")
    print("OK")


if __name__ == "__main__":
    main()
