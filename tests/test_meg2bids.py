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
