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
python batch_feature_extraction.py
python seld.py
```

Generated features, labels, models, and dataset files are ignored by git.
