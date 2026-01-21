# Quick Start Guide

Get meg2bids up and running in 5 minutes!

## Install

```bash
# Option 1: From PyPI (once published)
pip install meg2bids

# Option 2: From source
git clone https://github.com/ln2t/meg2bids.git
cd meg2bids
pip install -e .
```

## Set Up Your Data

```bash
# Create directory structure
mkdir -p sourcedata/mystudy-sourcedata/{meg,configs}

# Organize your MEG files
sourcedata/mystudy-sourcedata/meg/
  meg_1001/         # Your MEG subject ID
    250207/         # Session date (YYMMDD)
      rest1.fif
      visual1.fif
```

## Create Configuration

Create `sourcedata/mystudy-sourcedata/configs/meg2bids.json`:

```json
{
  "file_patterns": [
    {"pattern": "*rest*.fif", "task": "rest"},
    {"pattern": "*visual*.fif", "task": "visual"}
  ],
  "calibration": {"system": "triux", "auto_detect": true},
  "derivatives": {"pipeline_name": "maxfilter"}
}
```

## Create Participants File

Create `sourcedata/mystudy-sourcedata/participants_complete.tsv`:

```
participant_id	meg_id
sub-01	1001
```

## Run Conversion

```bash
# Check configuration
python meg2bids.py --dataset mystudy --check-config

# Convert
python meg2bids.py --dataset mystudy --subject sub-01

# Validate BIDS
python meg2bids.py --dataset mystudy --subject sub-01 --validate
```

## Output

Your BIDS data will be in:
```
rawdata/mystudy-rawdata/
  sub-01/
    ses-01/
      meg/
        sub-01_ses-01_task-rest_meg.fif
        sub-01_ses-01_task-visual_meg.fif
```

## Need Help?

- 📖 [Full Tutorial](docs/tutorial.md)
- ⚙️ [Configuration Guide](docs/configuration.md)
- 🚀 [Advanced Usage](docs/advanced.md)
- ❓ Questions? Post on [Neurostars](https://neurostars.org/) with `meg2bids` tag
- 🐛 Found a bug? [Open an issue](https://github.com/ln2t/meg2bids/issues)

---

**That's it!** You've converted your MEG data to BIDS format. 🎉
