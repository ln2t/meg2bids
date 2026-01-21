# Configuration Guide

Complete reference for meg2bids configuration options.

## Configuration File Format

meg2bids uses JSON configuration files. Place your config at:
```
sourcedata/<dataset>-sourcedata/configs/meg2bids.json
```

## Complete Example

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
      "description": "Resting state recording"
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

## Configuration Sections

### 1. Dataset

```json
"dataset": {
  "dataset_name": "MyStudy",
  "datatype": "meg"
}
```

- `dataset_name`: Name of your study (used in folder names)
- `datatype`: Must be "meg"

### 2. File Patterns

```json
"file_patterns": [
  {
    "pattern": "*rest*.fif",
    "task": "rest",
    "run_extraction": "last_digits",
    "description": "Resting state"
  }
]
```

**Required fields:**
- `pattern`: Glob pattern to match files (case-insensitive)
- `task`: BIDS task name

**Optional fields:**
- `run_extraction`: How to extract run numbers
  - `"last_digits"` - Use last digits in filename (default)
  - `"none"` - No run numbers (single-run tasks)
- `description`: Human-readable description

**Pattern matching rules:**

Patterns are evaluated in order. First match wins.

✅ **Good patterns** (specific):
```json
{"pattern": "rest_baseline_*.fif", "task": "rest"},
{"pattern": "visual_checkerboard_*.fif", "task": "visual"}
```

⚠️ **Ambiguous patterns** (will cause errors):
```json
{"pattern": "*rest*.fif", "task": "rest"},
{"pattern": "*_rest_*.fif", "task": "rest"}  // Both match "test_rest_1.fif"!
```

**Pattern examples:**

| Pattern | Matches | Doesn't Match |
|---------|---------|---------------|
| `*rest*.fif` | rest1.fif, baseline_rest.fif | visual1.fif |
| `rest_*.fif` | rest_1.fif, rest_baseline.fif | baseline_rest.fif |
| `*_1.fif` | rest_1.fif, visual_1.fif | rest_2.fif |
| `chessboard*.fif` | chessboard1.fif, chessboard_run1.fif | visual_chessboard.fif |

### 3. Calibration

```json
"calibration": {
  "system": "triux",
  "auto_detect": true,
  "maxfilter_root": "MEG/maxfilter"
}
```

**Fields:**
- `system`: MEG system type
  - `"triux"` - Elekta Neuromag Triux (default)
  - `"vectorview"` - Elekta Neuromag VectorView
- `auto_detect`: Automatically find calibration files (default: true)
- `maxfilter_root`: Path to MEG/maxfilter directory (optional)

**Calibration files by system:**

| System | Crosstalk File | Fine-Cal File |
|--------|----------------|---------------|
| Triux | `ct_sparse_triux2.fif` | `sss_cal_XXXX_*.dat` (date-matched) |
| VectorView | `ct_sparse_vectorview.fif` | `sss_cal_vectorview.dat` |

**Auto-detection logic:**

1. If `maxfilter_root` specified → Look in MEG/maxfilter/{ctc,sss}
2. Otherwise → Look in session folders
3. For Triux fine-cal → Match calibration date ≤ session date

### 4. Derivatives

```json
"derivatives": {
  "pipeline_name": "maxfilter",
  "maxfilter_version": "v2.2.20"
}
```

- `pipeline_name`: Processing pipeline name (appears in derivatives folder)
- `maxfilter_version`: Version string (optional, appended to pipeline name)

**Output structure:**
```
derivatives/
  <dataset>-derivatives/
    maxfilter_v2.2.20/
      sub-01/
        ses-01/
          meg/
            sub-01_ses-01_task-rest_proc-sss_meg.fif
```

**Derivative detection:**

meg2bids automatically detects MaxFilter derivatives by suffix:

| Suffix | Processing | BIDS Label |
|--------|------------|------------|
| `_sss` | Signal Space Separation | `proc-sss` |
| `_tsss` | Temporal SSS | `proc-tsss` |
| `_mc` | Movement compensation | `proc-mc` |
| `_trans`, `_quat` | Head position | `proc-trans`, `proc-quat` |
| `_av`, `_ave` | Averaged | `proc-ave` |

**Multi-suffix support:**
- `rest_mc_ave.fif` → `sub-01_task-rest_proc-mc-ave_meg.fif`
- `visual_tsss_mc.fif` → `sub-01_task-visual_proc-tsss-mc_meg.fif`

### 5. Options

```json
"options": {
  "allow_maxshield": true,
  "overwrite": true
}
```

- `allow_maxshield`: Allow MaxShield (pre-SSS) data (default: true)
- `overwrite`: Overwrite existing BIDS files (default: true)

## Participants File

Create `participants_complete.tsv` in sourcedata directory:

```tsv
participant_id	meg_id	age	sex	group
sub-01	1001	25	F	control
sub-02	1002	28	M	patient
```

**Required columns:**
- `participant_id`: BIDS subject identifier (e.g., sub-01)
- `meg_id`: MEG system ID (4 digits, matches meg_XXXX folder)

**Optional columns:**
- Any BIDS-valid participant metadata (age, sex, group, etc.)

## Directory Structure

Your complete project structure:

```
project/
├── sourcedata/
│   └── <dataset>-sourcedata/
│       ├── configs/
│       │   └── meg2bids.json       # Configuration file
│       ├── participants_complete.tsv  # Subject mapping
│       └── meg/
│           └── meg_XXXX/           # MEG subject folders
│               └── YYMMDD/         # Session folders (date)
│                   ├── *.fif       # Raw MEG files
│                   ├── *_sss.fif   # Derivative files (optional)
│                   └── *.dat       # Calibration files (optional)
│
├── MEG/                            # Optional: shared calibration files
│   └── maxfilter/
│       ├── ctc/
│       │   ├── ct_sparse_triux2.fif
│       │   └── ct_sparse_vectorview.fif
│       └── sss/
│           ├── sss_cal_XXXX_241201.dat
│           └── sss_cal_XXXX_250101.dat
│
├── rawdata/                        # Output: BIDS raw data
│   └── <dataset>-rawdata/
│       └── sub-01/
│           └── ses-01/
│               └── meg/
│
└── derivatives/                    # Output: BIDS derivatives
    └── <dataset>-derivatives/
        └── maxfilter_v2.2.20/
            └── sub-01/
```

## Validation

Always validate your configuration before running:

```bash
python meg2bids.py --dataset mydataset --check-config
```

This checks:
- ✅ File pattern matching
- ✅ Subject mapping
- ✅ Calibration file detection
- ⚠️ Ambiguous patterns
- ⚠️ Unmatched files

## Common Configurations

### Single-session study

```json
{
  "dataset": {"dataset_name": "SingleSession", "datatype": "meg"},
  "file_patterns": [
    {"pattern": "*task1*.fif", "task": "memory", "run_extraction": "none"},
    {"pattern": "*task2*.fif", "task": "attention", "run_extraction": "none"}
  ]
}
```

### Multi-session study

Organize data with date folders (YYMMDD). Sessions are auto-detected:
```
meg_1001/
  250207/  → ses-01
    rest1.fif
  250214/  → ses-02
    rest1.fif
```

### Complex task naming

```json
"file_patterns": [
  {"pattern": "baseline_rest_*.fif", "task": "restbaseline"},
  {"pattern": "posttest_rest_*.fif", "task": "restpost"},
  {"pattern": "visual_checkerboard_*.fif", "task": "visual"},
  {"pattern": "auditory_oddball_*.fif", "task": "auditory"}
]
```

### No calibration files

```json
"calibration": {
  "system": "triux",
  "auto_detect": false
}
```

## Troubleshooting

### "File matches multiple patterns"

**Cause:** Overlapping patterns
**Solution:** Make patterns more specific or reorder them

### "No matching pattern"

**Cause:** Filename doesn't match any pattern
**Solution:** Add pattern for this file type or rename file

### "Calibration files not found"

**Solutions:**
1. Place files in session folders
2. Set `maxfilter_root` in config
3. Set `auto_detect: false` to skip calibration

### "Subject not in participants file"

**Solution:** Add mapping to `participants_complete.tsv`:
```tsv
participant_id	meg_id
sub-03	1003
```

## Best Practices

1. **Test first**: Always use `--check-config` before conversion
2. **Single subject test**: Use `--subject` to test one subject first
3. **Specific patterns**: Make patterns as specific as possible
4. **Version control**: Keep your config in git
5. **Document tasks**: Use descriptive task names and descriptions
6. **Backup data**: Keep original sourcedata separate

## See Also

- [Tutorial](tutorial.md) - Getting started guide
- [Examples](../examples/) - Sample configurations
- [Advanced Usage](advanced.md) - Complex scenarios
