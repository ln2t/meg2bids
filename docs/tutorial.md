# Tutorial: First Steps with meg2bids

This tutorial will guide you through your first MEG to BIDS conversion.

## Prerequisites

- meg2bids installed ([Installation Guide](install.md))
- MEG FIF files from a Neuromag/Elekta/MEGIN system
- Basic familiarity with command line

## Step 1: Organize Your Data

Create the following directory structure:

```bash
mkdir -p sourcedata/mystudy-sourcedata/meg
mkdir -p sourcedata/mystudy-sourcedata/configs
```

Move your MEG data into meg folders:
```
sourcedata/
  mystudy-sourcedata/
    meg/
      meg_1001/          # Subject 1
        250207/          # Session date (YYMMDD)
          rest1.fif
          rest2.fif
          visual1.fif
      meg_1002/          # Subject 2
        250208/
          rest1.fif
          visual1.fif
```

**Folder naming:**
- MEG subject folders: `meg_XXXX` (where XXXX is your MEG system ID)
- Session folders: `YYMMDD` (date format: 250207 = Feb 7, 2025)

## Step 2: Create Participants File

Create `sourcedata/mystudy-sourcedata/participants_complete.tsv`:

```tsv
participant_id	meg_id
sub-01	1001
sub-02	1002
```

**Format:**
- Tab-separated values (TSV)
- `participant_id`: BIDS subject identifier (e.g., sub-01)
- `meg_id`: MEG system ID (4 digits, matches meg_XXXX folder)

## Step 3: Create Configuration File

Create `sourcedata/mystudy-sourcedata/configs/meg2bids.json`:

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
      "pattern": "*visual*.fif",
      "task": "visual",
      "run_extraction": "last_digits",
      "description": "Visual task"
    }
  ],
  "calibration": {
    "system": "triux",
    "auto_detect": true
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

**Key settings:**
- `file_patterns`: Match your FIF filenames to BIDS tasks
- `calibration.system`: "triux" or "vectorview"
- `run_extraction`: "last_digits" extracts run numbers from filenames

## Step 4: Validate Configuration

Before converting, check your configuration:

```bash
cd "your/project/directory"
python meg2bids.py --dataset mystudy --check-config
```

This will show you:
- ✅ How many files were found
- ✅ How each file will be matched to a task
- ✅ Subject mapping validation
- ⚠️ Any warnings or errors

**Example output:**
```
═══════════════════════════════════════════════════════════════════
CONFIG CHECK SUMMARY
═══════════════════════════════════════════════════════════════════
Subjects discovered: 2
Subjects mapped:     2
Sessions:            2
Files:               raw=5, derivatives=0

✓ Config check PASSED - ready to convert
```

## Step 5: Convert Single Subject (Test)

Test conversion on a single subject first:

```bash
python meg2bids.py --dataset mystudy --subject sub-01
```

**Alternative subject formats:**
```bash
python meg2bids.py --dataset mystudy --subject 01      # Without 'sub-' prefix
python meg2bids.py --dataset mystudy --subject 1001    # Using MEG ID
```

## Step 6: Review Output

Check the BIDS output:

```bash
ls rawdata/mystudy-rawdata/sub-01/ses-01/meg/
```

You should see:
```
sub-01_ses-01_task-rest_run-01_meg.fif
sub-01_ses-01_task-rest_run-01_meg.json
sub-01_ses-01_task-rest_run-01_channels.tsv
sub-01_ses-01_task-rest_run-02_meg.fif
...
sub-01_ses-01_task-visual_run-01_meg.fif
...
```

## Step 7: Convert All Subjects

Once you're satisfied with the test:

```bash
python meg2bids.py --dataset mystudy
```

This will process all subjects found in your MEG data directory.

## Step 8: Validate BIDS

Run the BIDS validator to ensure compliance:

```bash
python meg2bids.py --dataset mystudy --validate
```

Or use the official BIDS validator:
```bash
bids-validator rawdata/mystudy-rawdata/
# or
npx bids-validator rawdata/mystudy-rawdata/
```

## Common Issues

### "No session folders found"

**Problem:** Session folders not detected.
**Solution:** Ensure folders are named with dates (YYMMDD format, e.g., 250207).

### "File matches multiple patterns"

**Problem:** Ambiguous file pattern matching.
**Solution:** Make patterns more specific in your config:
```json
{
  "pattern": "rest_*.fif",     // More specific
  "task": "rest"
}
```

### "Subject not found in participants file"

**Problem:** MEG ID not mapped to BIDS subject.
**Solution:** Add mapping to `participants_complete.tsv`:
```tsv
participant_id	meg_id
sub-03	1003
```

### "Calibration files not found"

**Problem:** Auto-detection can't find calibration files.
**Solution:** Either:
1. Place calibration files in session folders, or
2. Specify `maxfilter_root` in config to point to MEG/maxfilter directory

## Next Steps

- Learn about [Advanced Usage](advanced.md)
- Read the [Configuration Guide](configuration.md) for all options
- Check out [Examples](../examples/) for more patterns

## Getting Help

- **Questions**: Post on [Neurostars](https://neurostars.org/) with `meg2bids` tag
- **Bugs**: Report on [GitHub Issues](https://github.com/ln2t/meg2bids/issues)
- **Documentation**: See [README](../README.md)
