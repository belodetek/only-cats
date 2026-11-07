# training
> needs a GPU

	python3.12 -m venv .venv
	source .venv/bin/activate

	pip install --upgrade pip
	pip install -r requirements.txt

	# https://universe.roboflow.com/flappie/prey-detection
	unzip -q Prey-detection.v1i.yolov11.zip -d prey_dataset
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
	# ├── prey_data.yaml
	# └── train.py

	cp prey_data.yaml prey_dataset/data.yaml

	python train.py

	# find the last generated weights and copy to build context
	find runs -type f -name best.pt -exec stat -f "%m %N" {} + \
	  | sort -rn \
	  | head -n 1 \
	  | cut -d' ' -f2- | xargs -I{} cp {} ../prey_runs/yolo11_prey/weights
