# training
> needs a GPU

	python3.12 -m venv .venv
	source .venv/bin/activate

	pip install --upgrade pip
	pip install ultralytics torch torchvision numpy

	# https://universe.roboflow.com/flappie/prey-detection
	unzip -q Prey-detection.v1i.yolov11.zip -d training/prey_dataset
	# training
	# ├── prey_dataset
	# │   ├── data.yaml
	# │   ├── README.dataset.txt
	# │   ├── README.roboflow.txt
	# │   ├── test
	# │   │   ├── images
	# │   │   └── labels
	# │   ├── train
	# │   │   ├── images
	# │   │   └── labels
	# │   └── valid
	# │       ├── images
	# │       └── labels
	# └── train.py

    pushd training

	cp prey_data.yaml prey_dataset/data.yaml

	python train.py

	# find the last generated weights
	find ../runs -type f -name best.pt | xargs -I{} cp {} ../prey_runs/yolo11_prey/weights
