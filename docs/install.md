# Installation Guide

## Requirements

- Python 3.8 or higher
- pip or conda package manager

## Method 1: Install from PyPI (Recommended)

Once meg2bids is published to PyPI, you can install it with:

```bash
pip install meg2bids
```

## Method 2: Install from Source

### Using pip

```bash
# Clone the repository
git clone https://github.com/ln2t/meg2bids.git
cd meg2bids

# Install in editable mode
pip install -e .

# Or install normally
pip install .
```

### Using conda

```bash
# Create a new environment
conda create -n meg2bids python=3.10
conda activate meg2bids

# Clone and install
git clone https://github.com/ln2t/meg2bids.git
cd meg2bids
pip install -e .
```

## Development Installation

If you want to contribute to meg2bids:

```bash
# Clone the repository
git clone https://github.com/ln2t/meg2bids.git
cd meg2bids

# Install with development dependencies
pip install -e ".[dev]"

# Verify installation
pytest tests/
```

## Verify Installation

```bash
# Check version
python -c "import meg2bids; print(meg2bids.__version__)"

# Run help
python meg2bids.py --help
```

## Dependencies

meg2bids automatically installs:
- `mne>=1.0` - MEG/EEG analysis
- `mne-bids>=0.13` - BIDS integration
- `numpy>=1.20` - Numerical computing

## Optional: BIDS Validator

To validate your BIDS output:

```bash
# Using npm
npm install -g bids-validator

# Or use npx (no installation needed)
npx bids-validator your_bids_directory/
```

## Troubleshooting

### ImportError: No module named 'mne'

```bash
pip install mne mne-bids
```

### Permission Denied

On Linux/macOS, you may need:
```bash
pip install --user meg2bids
```

Or use a virtual environment (recommended):
```bash
python -m venv meg2bids-env
source meg2bids-env/bin/activate  # On Windows: meg2bids-env\Scripts\activate
pip install meg2bids
```

### Python Version Issues

Check your Python version:
```bash
python --version
```

If you have multiple Python versions, use:
```bash
python3.10 -m pip install meg2bids
```

## Next Steps

- Read the [Tutorial](tutorial.md) to get started
- Check [Configuration Guide](configuration.md) for setup details
- See [Examples](../examples/) for sample configurations
