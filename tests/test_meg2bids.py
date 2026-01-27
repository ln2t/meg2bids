"""
Tests for meg2bids

Run with: pytest tests/
"""

import pytest
from pathlib import Path
import json


def test_import():
    """Test that meg2bids can be imported."""
    import meg2bids
    assert meg2bids.__version__ == "1.0.0"


def test_bids_config_validation(tmp_path):
    """Test BIDSConfig validation."""
    from meg2bids.meg2bids import BIDSConfig
    
    # Create a minimal valid config
    config_data = {
        "file_patterns": [
            {
                "pattern": "*rest*.fif",
                "task": "rest"
            }
        ]
    }
    
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config_data))
    
    config = BIDSConfig(config_file)
    assert config.get_datatype() == "meg"
    patterns = config.get_file_patterns()
    assert len(patterns) == 1
    assert patterns[0]["task"] == "rest"


def test_derivative_detection():
    """Test MaxFilter derivative detection."""
    from meg2bids.meg2bids import extract_derivative_info
    
    # Test single suffix
    result = extract_derivative_info("rest_sss.fif")
    assert result == ("rest.fif", "sss")
    
    # Test multiple suffixes
    result = extract_derivative_info("rest_mc_ave.fif")
    assert result == ("rest.fif", "mc-ave")
    
    # Test raw file (no derivative)
    result = extract_derivative_info("rest.fif")
    assert result is None


def test_split_file_detection():
    """Test split file detection."""
    from meg2bids.meg2bids import detect_split_files
    
    # Mock file paths
    files = [
        Path("/data/rest.fif"),
        Path("/data/rest-1.fif"),
        Path("/data/rest-2.fif"),
        Path("/data/visual.fif"),
    ]
    
    split_groups = detect_split_files(files)
    
    # rest.fif should be grouped with its parts
    primary = Path("/data/rest.fif")
    assert primary in split_groups
    assert len(split_groups[primary]) == 3
    assert Path("/data/rest.fif") in split_groups[primary]
    assert Path("/data/rest-1.fif") in split_groups[primary]
    assert Path("/data/rest-2.fif") in split_groups[primary]
    
    # visual.fif should not be in split_groups (single file)
    assert Path("/data/visual.fif") not in split_groups


def test_run_extraction():
    """Test run number extraction from filenames."""
    from meg2bids.meg2bids import extract_run_from_filename
    
    # Test last digits extraction
    assert extract_run_from_filename("rest1.fif", "last_digits") == 1
    assert extract_run_from_filename("task_run_2.fif", "last_digits") == 2
    assert extract_run_from_filename("baseline_3.fif", "last_digits") == 3
    
    # Test no extraction
    assert extract_run_from_filename("rest.fif", "none") is None
    
    # Test split file (should extract run from base, not split index)
    assert extract_run_from_filename("rest2-1.fif", "last_digits") == 2


def test_eeg_detection():
    """Test EEG channel detection from FIF file."""
    import mne
    import numpy as np
    from meg2bids.meg2bids import extract_eeg_information
    
    # Create a mock raw object with EEG channels
    info = mne.create_info(
        ch_names=['MEG0111', 'MEG0112', 'EEG001', 'EEG002', 'EEG003'],
        sfreq=250,
        ch_types=['grad', 'grad', 'eeg', 'eeg', 'eeg']
    )
    
    # Set channel locations
    info['chs'][2]['loc'][:3] = [0.001, 0.002, 0.003]  # EEG001
    info['chs'][3]['loc'][:3] = [-0.001, 0.002, 0.003]  # EEG002
    info['chs'][4]['loc'][:3] = [0.000, -0.002, 0.003]  # EEG003
    
    raw = mne.io.RawArray(np.zeros((5, 1000)), info)
    
    # Test EEG detection
    eeg_data = extract_eeg_information(raw)
    
    assert eeg_data is not None
    assert len(eeg_data['name']) == 3
    assert eeg_data['name'] == ['EEG001', 'EEG002', 'EEG003']
    assert len(eeg_data['x']) == 3
    assert len(eeg_data['y']) == 3
    assert len(eeg_data['z']) == 3
    assert len(eeg_data['size']) == 3
    
    # Check coordinate values
    assert np.isclose(eeg_data['x'][0], 0.001)
    assert np.isclose(eeg_data['y'][0], 0.002)
    assert np.isclose(eeg_data['z'][0], 0.003)


def test_eeg_not_detected():
    """Test behavior when no EEG channels are present."""
    import mne
    import numpy as np
    from meg2bids.meg2bids import extract_eeg_information
    
    # Create a mock raw object with only MEG channels
    info = mne.create_info(
        ch_names=['MEG0111', 'MEG0112', 'MEG0113'],
        sfreq=250,
        ch_types=['grad', 'grad', 'grad']
    )
    
    raw = mne.io.RawArray(np.zeros((3, 1000)), info)
    
    # Test that no EEG data is returned
    eeg_data = extract_eeg_information(raw)
    assert eeg_data is None


def test_electrodes_tsv_creation(tmp_path):
    """Test electrodes.tsv file creation with proper BIDS naming."""
    from meg2bids.meg2bids import write_electrodes_tsv
    import csv
    
    # Create mock EEG data
    eeg_data = {
        'name': ['EEG001', 'EEG002', 'EEG003'],
        'x': [0.001, -0.001, 0.000],
        'y': [0.002, 0.002, -0.002],
        'z': [0.003, 0.003, 0.003],
        'size': [0.005, 0.005, 0.005]
    }
    
    bids_root = tmp_path / "bids"
    
    # Test without session
    write_electrodes_tsv(eeg_data, '01', None, bids_root)
    
    electrodes_file = bids_root / "sub-01" / "meg" / "sub-01_electrodes.tsv"
    assert electrodes_file.exists()
    
    # Read and verify TSV content
    with open(electrodes_file, 'r') as f:
        reader = csv.DictReader(f, delimiter='\t')
        rows = list(reader)
    
    assert len(rows) == 3
    assert rows[0]['name'] == 'EEG001'
    assert float(rows[0]['x']) == 0.001
    assert float(rows[0]['y']) == 0.002
    assert float(rows[0]['z']) == 0.003
    
    # Test with session
    write_electrodes_tsv(eeg_data, '02', '01', bids_root)
    
    electrodes_file_session = bids_root / "sub-02" / "ses-01" / "meg" / "sub-02_ses-01_electrodes.tsv"
    assert electrodes_file_session.exists()


def test_eeg_montage_fallback_head_to_device():
    """Ensure montage positions are used when locs are zero and transformed to device coords if possible."""
    import mne
    import numpy as np
    from meg2bids.meg2bids import extract_eeg_information
    
    # Create raw with EEG channels but zero locs
    info = mne.create_info(
        ch_names=['EEG004', 'EEG006'],
        sfreq=250,
        ch_types=['eeg', 'eeg']
    )
    
    # Zero locs (default)
    for ch in info['chs']:
        ch['loc'][:3] = [0.0, 0.0, 0.0]
    
    raw = mne.io.RawArray(np.zeros((2, 1000)), info)
    
    # Build a simple montage with head coords
    ch_pos = {
        'EEG004': np.array([0.001, 0.0, 0.0]),
        'EEG006': np.array([0.0, -0.001, 0.0]),
    }
    montage = mne.channels.make_dig_montage(ch_pos=ch_pos)
    raw.set_montage(montage)
    
    # Create a simple dev->head transform (identity scaled)
    # For test, set dev_head_t to identity so head==device
    trans = np.eye(4)
    raw.info['dev_head_t'] = {'from': mne.io.constants.FIFF.FIFFV_COORD_DEVICE,
                              'to': mne.io.constants.FIFF.FIFFV_COORD_HEAD,
                              'trans': trans}
    
    eeg_data = extract_eeg_information(raw)
    assert eeg_data is not None
    
    # With identity transform, device coords == head coords
    assert np.isclose(eeg_data['x'][0], 0.001)
    assert np.isclose(eeg_data['y'][0], 0.0)
    assert np.isclose(eeg_data['z'][0], 0.0)


def test_split_file_derivative_matching():
    """Test derivative matching for split files with both naming patterns."""
    from meg2bids.meg2bids import find_matching_raw_file
    from pathlib import Path
    
    # Mock raw files with split structure
    raw_files = [
        Path("/data/rest.fif"),
        Path("/data/rest-1.fif"),
        Path("/data/rest-2.fif"),
    ]
    
    # Mock split file groups
    split_file_groups = {
        Path("/data/rest.fif"): [
            Path("/data/rest.fif"),
            Path("/data/rest-1.fif"),
            Path("/data/rest-2.fif"),
        ]
    }
    
    # Test derivative matching for primary file
    result = find_matching_raw_file("rest_mc.fif", raw_files, split_file_groups)
    assert result is not None
    assert result[0].name == "rest.fif"
    assert result[1] == 0  # Primary file
    
    # Test pattern: file-1_mc.fif (split first, then processing)
    result = find_matching_raw_file("rest-1_mc.fif", raw_files, split_file_groups)
    assert result is not None
    assert result[0].name == "rest.fif"  # Returns primary file
    assert result[1] == 1  # Split index 1 (which is split-02 in BIDS)
    
    # Test pattern: file_mc-1.fif (processing first, then split)
    result = find_matching_raw_file("rest_mc-1.fif", raw_files, split_file_groups)
    assert result is not None
    assert result[0].name == "rest.fif"  # Returns primary file
    assert result[1] == 1  # Split index 1 (which is split-02 in BIDS)
    
    # Test split part -2 with both patterns
    result = find_matching_raw_file("rest-2_mc.fif", raw_files, split_file_groups)
    assert result is not None
    assert result[0].name == "rest.fif"
    assert result[1] == 2  # Split index 2 (which is split-03 in BIDS)
    
    result = find_matching_raw_file("rest_mc-2.fif", raw_files, split_file_groups)
    assert result is not None
    assert result[0].name == "rest.fif"
    assert result[1] == 2  # Split index 2 (which is split-03 in BIDS)


def test_pattern_matching():
    """Test file pattern matching."""
    from meg2bids.meg2bids import match_file_pattern
    
    patterns = [
        {"pattern": "*rest*.fif", "task": "rest"},
        {"pattern": "*visual*.fif", "task": "visual"},
    ]
    
    # Test matching
    result = match_file_pattern("baseline_rest_1.fif", patterns)
    assert result is not None
    assert result["task"] == "rest"
    
    result = match_file_pattern("visual_checkerboard.fif", patterns)
    assert result is not None
    assert result["task"] == "visual"
    
    # Test no match
    result = match_file_pattern("unknown_task.fif", patterns)
    assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
