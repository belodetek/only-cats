# training
> needs a GPU

## base weights

	python3 -m venv .venv
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

## tuning
> [scp-uuid] in your own training images, generate draft labels, verify and fine tune the
  base model

    cd tune

    # scp in your own training images from live runtime
    scp-uuid -r {{uuid}}.balena:/mnt/data/docker/volumes/{{volume-id}}_resin-data/_data/images tune/

    # beware overwriting manually generated labels
    scp-uuid -r {{uuid}}.balena:/mnt/data/docker/volumes/{{volume-id}}_resin-data/_data/labels tune/

    # .. or download dataset export from the Web UI and unpack to tune/

    # generate draft labels (prey coordinates in image)
    python predict.py

    # .. and verify
    python verify.py

    # fine tune the base weights
    python tune.py


[scp-uuid]: https://github.com/pdcastro/ssh-uuid#file-transfer-with-scp
