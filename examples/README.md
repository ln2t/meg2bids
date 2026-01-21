# meg2bids Example Configuration Files

This directory contains example configuration files to help you get started with meg2bids.

## Files

### `config_basic.json`
Basic configuration example with common MEG tasks:
- Resting state
- Visual task
- Auditory task
- Motor task

### `participants_complete.tsv`
Example participant mapping file showing how to map MEG subject IDs to BIDS subject identifiers.

## Usage

1. Copy the example config to your sourcedata directory:
```bash
cp examples/config_basic.json sourcedata/mystudy-sourcedata/configs/meg2bids.json
```

2. Copy the participants file:
```bash
cp examples/participants_complete.tsv sourcedata/mystudy-sourcedata/
```

3. Edit both files to match your data:
   - Update file patterns to match your MEG file names
   - Update task names
   - Add your subject mappings

4. Test your configuration:
```bash
python meg2bids.py --dataset mystudy --check-config
```

## Directory Structure

Your complete setup should look like:

```
project/
├── sourcedata/
│   └── mystudy-sourcedata/
│       ├── configs/
│       │   └── meg2bids.json          # Configuration
│       ├── participants_complete.tsv  # Subject mapping
│       └── meg/
│           ├── meg_1001/              # MEG subject folders
│           │   └── 250207/            # Session date
│           │       ├── rest1.fif
│           │       └── visual1.fif
│           └── meg_1002/
│               └── 250208/
│                   ├── rest1.fif
│                   └── visual1.fif
├── MEG/                               # Optional: calibration files
│   └── maxfilter/
│       ├── ctc/
│       │   └── ct_sparse_triux2.fif
│       └── sss/
│           ├── sss_cal_XXXX_241201.dat
│           └── sss_cal_XXXX_250101.dat
└── meg2bids.py                        # The conversion script
```

## Configuration Options

### File Patterns

File patterns use glob-style matching:
- `*rest*.fif` - Matches any file containing "rest"
- `chessboard*.fif` - Matches files starting with "chessboard"
- `*_task1_*.fif` - Matches files with "_task1_" anywhere in the name

### Run Extraction

- `"last_digits"` - Extract run number from last digits in filename
- `"none"` - Don't extract run numbers (single-run tasks)

### Calibration Systems

- `"triux"` - Elekta Neuromag Triux system (uses ct_sparse_triux2.fif)
- `"vectorview"` - Elekta Neuromag VectorView system (uses ct_sparse_vectorview.fif)

## Need Help?

See the main documentation:
- [Configuration Guide](../docs/configuration.md)
- [Tutorial](../docs/tutorial.md)
- [README](../README.md)
