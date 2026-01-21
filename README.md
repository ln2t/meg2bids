# meg2bids

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

Your friendly MEG to BIDS converter.

`meg2bids` reorganizes MEG FIF files into the [Brain Imaging Data Structure](https://bids-specification.readthedocs.io/en/stable/) (BIDS) format using [MNE-Python](https://mne.tools/) and [mne-bids](https://mne.tools/mne-bids/).

## 🎯 Scope

`meg2bids` is designed specifically for **Neuromag/Elekta/MEGIN MEG systems** that produce FIF (`.fif`) files. It handles:

- ✅ Raw MEG FIF files conversion to BIDS
- ✅ Automatic MaxFilter derivative detection and organization
- ✅ Split file support (files > 2GB)
- ✅ Calibration file management (crosstalk and fine-calibration)
- ✅ Session auto-detection
- ✅ Multi-subject batch processing

**Note**: Currently supports only FIF format from Neuromag/Elekta/MEGIN systems. Support for other MEG manufacturers (CTF, BTI/4D, KIT/Yokogawa) may be added in future releases.

## 📋 Requirements

- Python 3.8 or higher
- MNE-Python >= 1.0
- mne-bids >= 0.13

## 🚀 Installation

### From PyPI (when published)

```bash
pip install meg2bids
```

### From source

```bash
git clone https://github.com/ln2t/meg2bids.git
cd meg2bids
pip install -e .
```

### Using conda/mamba

```bash
conda create -n meg2bids python=3.10
conda activate meg2bids
pip install -e .
```

## 📖 Quick Start

### 1. Organize Your Data

Your source data should follow this structure:

```
sourcedata/
  <dataset>-sourcedata/
    meg/
      meg_XXXX/          # MEG subject folders
        YYMMDD/          # Session date folders
          *.fif          # MEG FIF files
    configs/
      meg2bids.json      # Configuration file
    participants_complete.tsv  # Subject mapping
```

### 2. Create Configuration File

Create `meg2bids.json` in your configs directory:

```json
{
  "dataset": {
    "dataset_name": "MyStudy",
    "datatype": "meg"
  },
  "file_patterns": [
    {
      "pattern": "*rest*.fif",
      "task": "rest",
      "run_extraction": "last_digits",
      "description": "Resting state"
    },
    {
      "pattern": "*chessboard*.fif",
      "task": "visual",
      "run_extraction": "last_digits",
      "description": "Visual task"
    }
  ],
  "calibration": {
    "system": "triux",
    "auto_detect": true,
    "maxfilter_root": "MEG/maxfilter"
  },
  "derivatives": {
    "pipeline_name": "maxfilter",
    "maxfilter_version": "v2.2.20"
  },
  "options": {
    "allow_maxshield": true,
    "overwrite": true
  }
}
```

### 3. Create Participants Mapping

Create `participants_complete.tsv`:

```tsv
participant_id	meg_id
sub-01	1001
sub-02	1002
```

### 4. Run Conversion

```bash
# Check configuration first
python meg2bids.py --dataset mydataset --check-config

# Convert all subjects
python meg2bids.py --dataset mydataset

# Convert single subject
python meg2bids.py --dataset mydataset --subject sub-01

# With BIDS validation
python meg2bids.py --dataset mydataset --subject sub-01 --validate
```

## 📚 Documentation

- [Installation Guide](docs/install.md)
- [Configuration Guide](docs/configuration.md)
- [Tutorial: First Steps](docs/tutorial.md)
- [Advanced Usage](docs/advanced.md)
- [API Reference](docs/api.md)

## 🔧 Key Features

### Automatic Derivative Detection

`meg2bids` automatically detects MaxFilter derivatives by recognizing standard suffixes:

- `_sss`, `_tsss` → Signal Space Separation
- `_mc` → Movement compensation
- `_trans`, `_quat` → Head position
- `_av`, `_ave` → Averaged data

Example: `restingstate_mc_ave.fif` → `sub-01_task-rest_proc-mc-ave_meg.fif`

### Calibration File Management

Automatically detects and copies calibration files:
- **Crosstalk**: `ct_sparse_triux2.fif` (Triux) or `ct_sparse_vectorview.fif` (VectorView)
- **Fine-calibration**: `sss_cal_XXXX_*.dat` (date-matched) or `sss_cal_vectorview.dat`

### Split File Handling

Handles large files automatically split by the acquisition system:
- `filename.fif`, `filename-1.fif`, `filename-2.fif` → Single BIDS entry

## 🗂️ Output Structure

```
rawdata/
  <dataset>-rawdata/
    sub-01/
      ses-01/
        meg/
          sub-01_ses-01_task-rest_meg.fif
          sub-01_ses-01_task-rest_meg.json
          sub-01_ses-01_task-rest_channels.tsv
          sub-01_ses-01_acq-crosstalk_meg.fif
          sub-01_ses-01_acq-calibration_meg.dat

derivatives/
  <dataset>-derivatives/
    maxfilter_v2.2.20/
      sub-01/
        ses-01/
          meg/
            sub-01_ses-01_task-rest_proc-sss_meg.fif
```

## 🛠️ Command-Line Interface

```bash
python meg2bids.py --dataset DATASET [OPTIONS]

Required Arguments:
  --dataset DATASET     Dataset name (e.g., 'mystudy')

Optional Arguments:
  --subject SUBJECT     Process single subject (sub-01, 01, or meg_id)
  -b, --validate        Run BIDS validation after conversion
  --check-config        Validate config without conversion

Paths (auto-constructed from dataset):
  sourcedata/<dataset>-sourcedata/meg/
  rawdata/<dataset>-rawdata/
  derivatives/<dataset>-derivatives/
```

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup

```bash
git clone https://github.com/ln2t/meg2bids.git
cd meg2bids
pip install -e ".[dev]"
pytest tests/
```

## 📄 License

This project is licensed under the GNU General Public License v3.0 - see [LICENSE](LICENSE) for details.

## 📖 Citation

If you use `meg2bids` in your research, please cite:

```bibtex
@software{meg2bids,
  author = {Your Name},
  title = {meg2bids: MEG to BIDS Converter},
  year = {2026},
  url = {https://github.com/ln2t/meg2bids}
}
```

## 🙏 Acknowledgments

- Inspired by [dcm2bids](https://github.com/UNFmontreal/Dcm2Bids)
- Built with [MNE-Python](https://mne.tools/) and [mne-bids](https://mne.tools/mne-bids/)
- Follows [BIDS specification](https://bids-specification.readthedocs.io/)

## ❓ Issues and Questions

- **Usage questions**: Post on [Neurostars](https://neurostars.org/) with the `meg2bids` tag
- **Bug reports**: Open an issue on [GitHub](https://github.com/ln2t/meg2bids/issues)
- **Feature requests**: Open an issue with the `enhancement` label

## 🔗 Related Projects

- [dcm2bids](https://github.com/UNFmontreal/Dcm2Bids) - DICOM to BIDS converter
- [mne-bids](https://mne.tools/mne-bids/) - MNE-Python BIDS integration
- [bidscoin](https://github.com/Donders-Institute/bidscoin) - Multi-modal BIDS converter
