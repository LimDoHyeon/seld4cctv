# [SELD4CCTV] Audio-Guided Smart CCTV for Public Safety
2026 GIST C&S Project (Team A)

## Usage

Prepare the spatial CCTV dataset under `Dataset/`. The current SELDnet adapter expects:

```text
Dataset/spatial-mic-array/train.csv
Dataset/spatial-mic-array/test.csv
Dataset/spatial-mic-array/seldnet/wav_ov1_split1_0db/*.wav
```

Audio files should be 16 kHz, 4-channel wav files. Then run:

```powershell
cd seld-net
pip install -r requirements.txt
wandb login
python batch_feature_extraction.py
python seld.py
```

Training logs are sent to the `seld4cctv` Weights & Biases project by default. Set `WANDB_MODE=offline` or `use_wandb=False` in `seld-net/parameter.py` to disable online logging.

Training uses TensorFlow `MirroredStrategy` automatically when more than one GPU is visible. Limit or select GPUs with `CUDA_VISIBLE_DEVICES`, for example:

```bash
CUDA_VISIBLE_DEVICES=0,1 python seld.py
```

Training checkpoints are saved under `seld-net/models/` as `<run_name>_best.keras` and `<run_name>_last.keras`.
Validation runs every 10 epochs by default; change `validation_interval` in `seld-net/parameter.py` if needed.

Generated features, labels, models, and dataset files are ignored by git.
Extracted feature and label files are organized under class-name subdirectories.
