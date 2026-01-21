# Advanced Usage

Advanced features and use cases for meg2bids.

## Batch Processing

### Process All Subjects

```bash
# Convert all discovered subjects
python meg2bids.py --dataset mystudy
```

### Process Specific Subjects

```bash
# Using BIDS subject ID
python meg2bids.py --dataset mystudy --subject sub-01

# Using subject label (without 'sub-' prefix)
python meg2bids.py --dataset mystudy --subject 01

# Using MEG system ID
python meg2bids.py --dataset mystudy --subject 1001
```

### Process Multiple Subjects with Shell Script

```bash
#!/bin/bash
# process_subjects.sh

DATASET="mystudy"
SUBJECTS=("sub-01" "sub-02" "sub-03" "sub-04")

for subject in "${SUBJECTS[@]}"; do
    echo "Processing $subject..."
    python meg2bids.py --dataset $DATASET --subject $subject
    
    if [ $? -eq 0 ]; then
        echo "✓ $subject completed"
    else
        echo "✗ $subject failed"
    fi
done
```

## Split File Handling

meg2bids automatically handles split files (files > 2GB):

**Input files:**
```
meg_1001/250207/
  rest.fif       # Primary file
  rest-1.fif     # Split part 1
  rest-2.fif     # Split part 2
```

**What happens:**
1. meg2bids detects split files automatically
2. MNE reads all parts transparently
3. BIDS output may be split if data is large

**BIDS output:**
```
sub-01/ses-01/meg/
  sub-01_ses-01_task-rest_meg.fif
  sub-01_ses-01_task-rest_split-01_meg.fif
  sub-01_ses-01_task-rest_split-02_meg.fif
```

## MaxFilter Derivatives

### Automatic Detection

meg2bids detects MaxFilter derivatives by suffix:

```python
# Single suffix
rest_sss.fif → proc-sss

# Multiple suffixes
rest_mc_ave.fif → proc-mc-ave
visual_tsss_mc.fif → proc-tsss-mc
```

### Derivative Output Structure

```
derivatives/<dataset>-derivatives/
  maxfilter_v2.2.20/
    sub-01/
      ses-01/
        meg/
          sub-01_ses-01_task-rest_proc-sss_meg.fif
          sub-01_ses-01_task-rest_proc-mc_meg.fif
          sub-01_ses-01_task-rest_proc-mc-ave_meg.fif
```

### Matching Derivatives to Raw Files

Derivatives are matched to raw files by base filename:

```
Raw file:       rest1.fif           → sub-01_task-rest_run-01_meg.fif
Derivative:     rest1_sss.fif       → sub-01_task-rest_run-01_proc-sss_meg.fif
Derivative:     rest1_mc_ave.fif    → sub-01_task-rest_run-01_proc-mc-ave_meg.fif
```

**Important**: Derivatives without matching raw files are skipped with a warning.

## Calibration File Management

### Triux System (Date-Matched)

For Triux systems, fine-calibration files are matched by date:

```
MEG/maxfilter/sss/
  sss_cal_XXXX_241201.dat  # Dec 1, 2024
  sss_cal_XXXX_250101.dat  # Jan 1, 2025
  sss_cal_XXXX_250301.dat  # Mar 1, 2025

Session: meg_1001/250207/ (Feb 7, 2025)
→ Uses sss_cal_XXXX_250101.dat (most recent ≤ session date)
```

**Logic:**
1. Extract session date from folder name (YYMMDD)
2. Find all `sss_cal_XXXX_*.dat` files
3. Select most recent calibration with date ≤ session date

### VectorView System

VectorView uses fixed calibration files (no date matching):

```json
"calibration": {
  "system": "vectorview",
  "auto_detect": true
}
```

Files used:
- Crosstalk: `ct_sparse_vectorview.fif`
- Fine-cal: `sss_cal_vectorview.dat`

### Custom Calibration Location

```json
"calibration": {
  "system": "triux",
  "auto_detect": true,
  "maxfilter_root": "/path/to/MEG/maxfilter"
}
```

### Disable Calibration

```json
"calibration": {
  "auto_detect": false
}
```

## Run Number Assignment

### Automatic Run Numbering

By default, meg2bids extracts run numbers from filenames:

```
rest1.fif → run-01
rest2.fif → run-02
rest3.fif → run-03
```

**Extraction patterns:**
- Last digits: `rest1.fif`, `task_2.fif`, `baseline_run_3.fif`
- Ignores split suffixes: `rest-1.fif` (split file, not run number)

### No Run Numbers

For single-run tasks:

```json
{
  "pattern": "*baseline*.fif",
  "task": "baseline",
  "run_extraction": "none"
}
```

Output: `sub-01_task-baseline_meg.fif` (no run entity)

### Multiple Runs with Same Name

If multiple files match the same task without distinct run numbers:

```
Input:
  task1.fif
  task2.fif
  task3.fif

Output:
  sub-01_task-memory_run-01_meg.fif
  sub-01_task-memory_run-02_meg.fif
  sub-01_task-memory_run-03_meg.fif
```

Runs are assigned based on alphabetical order of filenames.

## Session Handling

### Single Session

One date folder per subject:
```
meg_1001/
  250207/
    rest1.fif
```

Output: `sub-01/meg/sub-01_task-rest_meg.fif` (no session entity)

### Multiple Sessions

Multiple date folders per subject:
```
meg_1001/
  250207/  # First session
    rest1.fif
  250214/  # Second session
    rest1.fif
  250221/  # Third session
    rest1.fif
```

Output:
```
sub-01/
  ses-01/meg/sub-01_ses-01_task-rest_meg.fif
  ses-02/meg/sub-01_ses-02_task-rest_meg.fif
  ses-03/meg/sub-01_ses-03_task-rest_meg.fif
```

Sessions numbered sequentially by folder name (alphabetical order).

## Configuration Validation

### Pre-flight Check

Always validate before converting:

```bash
python meg2bids.py --dataset mystudy --check-config
```

**Checks performed:**
- ✅ File pattern matching
- ✅ Subject mapping validation
- ✅ Calibration file detection
- ⚠️ Ambiguous patterns
- ⚠️ Unmatched files
- ⚠️ Missing subjects

### Subject-Specific Check

```bash
python meg2bids.py --dataset mystudy --subject sub-01 --check-config
```

Shows detailed file-by-file matching for a single subject.

### Dataset Summary Check

```bash
python meg2bids.py --dataset mystudy --check-config
```

Without `--subject`, shows compact summary for all subjects:
- Subject counts
- File counts
- Task distribution
- Issues per subject

## BIDS Validation

### Built-in Validation

```bash
python meg2bids.py --dataset mystudy --validate
```

Runs conversion followed by BIDS validation.

### Manual Validation

```bash
# Using npm package
bids-validator rawdata/mystudy-rawdata/

# Using npx (no installation)
npx bids-validator rawdata/mystudy-rawdata/
```

## Error Handling

### Ambiguous File Matching

**Problem:** File matches multiple patterns with different tasks

```
ERROR: Ambiguous filename detected
File: rest_baseline.fif
Matches 2 patterns:
  1. Pattern: *rest*.fif → task=rest
  2. Pattern: *baseline*.fif → task=baseline
```

**Solutions:**
1. Make patterns more specific:
```json
{"pattern": "rest_baseline_*.fif", "task": "restbaseline"},
{"pattern": "rest_*.fif", "task": "rest"},
{"pattern": "baseline_*.fif", "task": "baseline"}
```

2. Reorder patterns (first match wins)

### Unmatched Files

**Warning:** `No matching pattern for: unknown_task.fif`

**Solution:** Add pattern to config:
```json
{"pattern": "unknown_task*.fif", "task": "newtask"}
```

### Missing Raw File for Derivative

**Warning:** `rest_sss.fif: No corresponding raw file found (skipped)`

**Cause:** Derivative exists but `rest.fif` doesn't

**Solutions:**
1. Ensure raw file exists
2. Accept that derivative will be skipped

## Integration with Analysis Pipelines

### Output for MNE-Python

```python
import mne
from mne_bids import BIDSPath, read_raw_bids

# Read BIDS data
bids_path = BIDSPath(
    subject='01',
    session='01',
    task='rest',
    run=1,
    datatype='meg',
    root='rawdata/mystudy-rawdata'
)

raw = read_raw_bids(bids_path)
```

### Output for FieldTrip

```matlab
% In MATLAB with FieldTrip
cfg = [];
cfg.dataset = 'rawdata/mystudy-rawdata/sub-01/ses-01/meg/sub-01_ses-01_task-rest_meg.fif';
data = ft_preprocessing(cfg);
```

### Output for MNE-BIDS-Pipeline

meg2bids output is compatible with [MNE-BIDS-Pipeline](https://mne.tools/mne-bids-pipeline/):

```python
# config.py
study_name = 'mystudy'
bids_root = 'rawdata/mystudy-rawdata'
deriv_root = 'derivatives/mystudy-derivatives'

subjects = ['01', '02', '03']
sessions = ['01']
task = 'rest'
```

## Performance Tips

### Large Datasets

For datasets with many subjects:

```bash
# Process in parallel (GNU parallel)
parallel -j 4 python meg2bids.py --dataset mystudy --subject {} ::: sub-01 sub-02 sub-03 sub-04

# Or use a job scheduler (SLURM)
sbatch --array=1-10 process_subjects.sh
```

### Skip Validation

Skip validation for faster processing:

```bash
# Without BIDS validation
python meg2bids.py --dataset mystudy
```

Run validation separately after all conversions:
```bash
bids-validator rawdata/mystudy-rawdata/
```

## Troubleshooting

### Memory Issues

For very large files:

```python
# meg2bids uses preload=False by default
# Data is loaded lazily when needed
```

### Permission Errors

```bash
# Ensure write permissions
chmod -R u+w rawdata/ derivatives/
```

### Python Version Issues

```bash
# Check Python version (requires 3.8+)
python --version

# Use specific Python version
python3.10 meg2bids.py --dataset mystudy
```

## See Also

- [Configuration Guide](configuration.md)
- [Tutorial](tutorial.md)
- [Examples](../examples/)
- [BIDS Specification](https://bids-specification.readthedocs.io/en/stable/)
- [MNE-BIDS Documentation](https://mne.tools/mne-bids/)
