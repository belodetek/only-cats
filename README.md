# onlyCat(s)

## train

	python3 -m venv .venv
	source .venv/bin/activate

	pip install --upgrade pip
	pip install ultralytics torch torchvision

	python -c "import torch; print('MPS Available:', torch.backends.mps.is_available())"

	# https://universe.roboflow.com/flappie/prey-detection
	unzip -q Prey-detection.v1i.yolov11.zip -d prey_dataset

	echo "path: ./prey_dataset" >> prey_dataset/data.json

	python train.py
