#!/usr/bin/env python3
"""
MEG FIF → BIDS Converter with Automatic MaxFilter Derivative Detection

Converts MEG FIF files into a BIDS dataset using mne-bids. Automatically detects
and processes MaxFilter derivative files (suffixes: _SSS, _tSSS, _mc, _av, _ave, 
_trans, _quat) by matching them to raw file counterparts and inheriting metadata.

Key Features:
- Automatic derivative detection (no config needed)
- Multi-suffix support (e.g., chessboard2_mc_ave.fif → proc-mc-ave)
- Strict pattern validation (fail on ambiguity)
- Calibration file auto-detection
- Split file support

Usage:
  python meg2bids.py --source <SOURCE_DIR> --bids-root <OUTPUT_DIR> --subject <ID>
  python meg2bids.py --source <SOURCE_DIR> --bids-root <OUTPUT_DIR> --subject <ID> -b

See README_MEG2BIDS.md for detailed documentation.
"""

from pathlib import Path
import argparse
import re
import sys
import json
import logging
from typing import Optional, Dict, List, Any, Tuple, Set
from datetime import datetime, date, timezone
import subprocess
import shutil
import fnmatch
from collections import defaultdict
import numpy as np
import warnings

import mne
from mne.transforms import apply_trans
from mne_bids import write_raw_bids, BIDSPath

# Suppress mne and mne_bids verbose output
mne.set_log_level('ERROR')
logging.getLogger('mne_bids').setLevel(logging.ERROR)
logging.getLogger('mne').setLevel(logging.ERROR)
warnings.filterwarnings('ignore', category=DeprecationWarning, module='mne')
warnings.filterwarnings('ignore', message='.*headshape.*', category=UserWarning)
warnings.filterwarnings('ignore', message='.*does not conform to MNE naming conventions.*')
warnings.filterwarnings('ignore', message='.*raw Internal Active Shielding data.*')
warnings.filterwarnings('ignore', message='.*No events found or provided.*')


def setup_logging() -> logging.Logger:
    """Configure logging to console only with clear formatting."""
    logger = logging.getLogger("MEG2BIDS")
    logger.setLevel(logging.DEBUG)
    
    # Clear any existing handlers
    logger.handlers = []
    
    # Console handler - clean format, INFO and above
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(console_handler)
    
    return logger


logger: logging.Logger = logging.getLogger("MEG2BIDS")


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


class ConversionStats:
    """Track conversion statistics."""
    def __init__(self):
        self.total_files = 0
        self.converted = 0
        self.skipped = 0
        self.excluded = 0
        self.failed = 0
        self.task_counts = defaultdict(int)
        self.failed_files = []
        self.subjects_processed = 0
        self.subjects_skipped = 0
    
    def add_file(self, task: str, status: str, filename: str = ""):
        """Record a file conversion."""
        self.total_files += 1
        if status == 'converted':
            self.converted += 1
            self.task_counts[task] += 1
        elif status == 'skipped':
            self.skipped += 1
        elif status == 'excluded':
            self.excluded += 1
        elif status == 'failed':
            self.failed += 1
            if filename:
                self.failed_files.append(filename)
    
    def summary(self) -> str:
        """Return a summary of conversion statistics."""
        lines = []
        lines.append("")
        lines.append("═" * 70)
        lines.append("CONVERSION SUMMARY")
        lines.append("═" * 70)
        lines.append(f"  Subjects processed:  {self.subjects_processed}")
        if self.subjects_skipped > 0:
            lines.append(f"  Subjects skipped:    {self.subjects_skipped} (existing MEG data)")
        lines.append("")
        lines.append(f"  Total files:    {self.total_files}")
        lines.append(f"  ✓ Converted:    {self.converted}")
        lines.append(f"  ⊘ Skipped:      {self.skipped}")
        if self.excluded > 0:
            lines.append(f"  ⊗ Excluded:     {self.excluded}")
        if self.failed > 0:
            lines.append(f"  ✗ Failed:       {self.failed}")
        
        if self.task_counts:
            lines.append("")
            lines.append("Files by task:")
            for task in sorted(self.task_counts.keys()):
                count = self.task_counts[task]
                lines.append(f"  • task-{task}: {count} file(s)")
        
        if self.failed_files:
            lines.append("")
            lines.append("Failed files:")
            for filename in self.failed_files:
                lines.append(f"  ✗ {filename}")
        
        lines.append("═" * 70)
        return "\n".join(lines)


conversion_stats: Optional['ConversionStats'] = None


class BIDSConfig:
    """Parse and validate configuration from JSON file.
    
    Expected structure:
    {
      "dataset": {"dataset_name": "...", "datatype": "meg"},
      "file_patterns": [{pattern, task, run_extraction, description}, ...],
      "derivatives": {write_derivatives, pipeline_name, pipeline_version},
      "calibration_files": {auto_detect, crosstalk_file, calibration_file},
      "options": {allow_maxshield, extract_metadata_from_fif, overwrite}
    }
    """
    
    def __init__(self, config_path: Path):
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        self._validate()
    
    def _validate(self):
        """Basic validation of required fields."""
        required = ['file_patterns']
        for key in required:
            if key not in self.config:
                raise ValueError(f"Missing required config section: {key}")
        if 'exclude_patterns' not in self.config:
            self.config['exclude_patterns'] = []
        elif not isinstance(self.config['exclude_patterns'], list):
            raise ValueError("'exclude_patterns' must be a list of wildcard patterns")    
    def get_datatype(self) -> str:
        return self.config.get('dataset', {}).get('datatype', 'meg')
    
    def get_file_patterns(self) -> List[Dict[str, Any]]:
        """Return list of file pattern rules in order (for raw files only)."""
        patterns = self.config['file_patterns']
        # Filter out derivative patterns (is_processed, is_averaged)
        return [p for p in patterns if not (p.get('is_processed') or p.get('is_averaged'))]
    
    def get_option(self, key: str, default=None):
        """Get an option from the options section."""
        return self.config.get('options', {}).get(key, default)
    
    def get_calibration_settings(self) -> Dict[str, Any]:
        """Get calibration settings from config (calibration.system, calibration.auto_detect)."""
        calib = self.config.get('calibration', {})
        # Backwards compatibility: allow old top-level fields
        if not calib and 'calibration_system' in self.config:
            calib = {
                'system': self.config.get('calibration_system'),
                'auto_detect': self.config.get('calibration_files', {}).get('auto_detect', True)
            }
        return calib
    
    def get_calibration_system(self) -> str:
        """Get calibration system: 'triux' (default) or 'vectorview'."""
        return self.get_calibration_settings().get('system', 'triux').lower()
    
    def get_calibration_auto_detect(self) -> bool:
        """Return whether calibration auto-detect is enabled (default: True)."""
        return bool(self.get_calibration_settings().get('auto_detect', True))
    
    def get_maxfilter_root(self) -> Optional[Path]:
        """Get the path to MEG/maxfilter directory for calibration files."""
        maxfilter_path = self.get_calibration_settings().get('maxfilter_root')
        if maxfilter_path:
            path = Path(maxfilter_path)
            return path if path.exists() else None
        return None
    
    def get_pipeline_name(self) -> Optional[str]:
        """Get pipeline name for derivatives folder. Returns None if set to 'none'.
        
        If maxfilter_version is specified in derivatives config, appends it to the pipeline name
        (e.g., 'maxfilter' → 'maxfilter_3.0.0').
        """
        pipeline = self.config.get('derivatives', {}).get('pipeline_name')
        if pipeline and pipeline.lower() != 'none':
            # Check for maxfilter_version and append if present
            version = self.config.get('derivatives', {}).get('maxfilter_version')
            if version:
                return f"{pipeline}_{version}"
            return pipeline
        return None
    
    def get_maxfilter_version(self) -> Optional[str]:
        """Get maxfilter version from derivatives config."""
        return self.config.get('derivatives', {}).get('maxfilter_version')

    def get_exclude_patterns(self) -> List[str]:
        """Return list of file exclusion wildcard patterns."""
        return self.config.get('exclude_patterns', [])


def _extract_base_name_and_suffix(filename: str, with_proc: bool = False) -> Tuple[str, Optional[str]]:
    """Extract base name and optional proc suffix from a FIF filename.

    Used by split detection and derivative detection to group files by their
    base name and processing label.

    Args:
        filename: FIF filename
        with_proc: If True, also extract proc label (e.g., 'tsss-mc').
                   If False, strip split suffixes only.

    Returns:
        (base_name, proc_label) where proc_label is None if with_proc=False
        or no proc suffix found.
    """
    stem = Path(filename).stem

    # FIRST: Remove trailing split suffix if present (e.g., _sss-2)
    # This is for Pattern 2: base_sss-2.fif
    split_after_proc = re.match(r'^(.+)-\d+$', stem)
    if split_after_proc:
        stem = split_after_proc.group(1)

    if not with_proc:
        # Also remove leading split suffix if present (e.g., -1_sss becomes just sss part)
        # This is for Pattern 1: base-1_sss.fif
        split_before_proc = re.match(r'^(.+?)-\d+(.*)$', stem)
        if split_before_proc:
            stem = split_before_proc.group(1) + split_before_proc.group(2)
        return (stem, None)

    # Extract proc label
    derivative_suffixes = [
        ('_tsss', 'tsss'),
        ('_sss', 'sss'),
        ('_mc', 'mc'),
        ('_quat', 'quat'),
        ('_trans', 'trans'),
        ('_ave', 'ave'),
        ('_av', 'ave'),
    ]

    current_stem = stem
    found_suffixes = []

    while True:
        found_match = False
        for suffix, label in derivative_suffixes:
            if current_stem.lower().endswith(suffix):
                found_suffixes.insert(0, label)
                current_stem = current_stem[:-len(suffix)]
                found_match = True
                break
        if not found_match:
            break

    # FINALLY: Remove any remaining leading split suffix (e.g., -1 or -2)
    # This is for Pattern 1: base-1_sss.fif where base_name is extracted after removing _sss
    split_before_proc = re.match(r'^(.+?)-\d+$', current_stem)
    if split_before_proc:
        current_stem = split_before_proc.group(1)

    if found_suffixes:
        unique_labels = []
        for label in found_suffixes:
            if label not in unique_labels:
                unique_labels.append(label)
        proc_label = '-'.join(unique_labels)
        return (current_stem, proc_label)

    return (stem, None)


def should_exclude_file(filename: str, exclude_patterns: List[str]) -> Optional[str]:
    """Check if a file should be excluded based on configured patterns.

    Performs case-insensitive wildcard matching against exclude patterns.

    Args:
        filename: FIF filename to check
        exclude_patterns: List of wildcard patterns (e.g., '*test*', '*demo*')

    Returns:
        Matched pattern if file should be excluded, None otherwise
    """
    if not exclude_patterns:
        return None

    filename_lower = filename.lower()
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(filename_lower, pattern.lower()):
            return pattern

    return None


def get_fif_header_info(file_path: Path) -> Optional[Dict[str, Any]]:
    """Extract metadata from FIF file header without loading full data.

    Reads only the FIF header to extract recording fingerprint info.

    Args:
        file_path: Path to FIF file

    Returns:
        Dict with 'file_id', 'meas_date', 'first_samps', 'is_primary', 'n_parts'
        or None if read failed.
    """
    try:
        raw = mne.io.read_raw_fif(file_path, preload=False, allow_maxshield=True, verbose=False)

        file_id = raw.info.get('file_id', {})
        meas_date = raw.info.get('meas_date')

        meas_date_str = None
        if meas_date:
            if isinstance(meas_date, datetime):
                meas_date_str = meas_date.isoformat()
            elif isinstance(meas_date, date):
                meas_date_str = meas_date.isoformat()

        first_samps = getattr(raw, '_first_samps', None)
        last_samps = getattr(raw, '_last_samps', None)

        return {
            'file_id': file_id,
            'meas_date': meas_date_str,
            'n_samples': raw.n_times,
            'sfreq': raw.info.get('sfreq'),
            'n_channels': len(raw.ch_names),
            'duration_sec': raw.times[-1] if len(raw.times) > 0 else 0,
            'first_samps': first_samps,
            'last_samps': last_samps,
            'is_primary': first_samps is not None and len(first_samps) > 1,
            'n_parts': len(first_samps) if first_samps is not None else 1,
        }
    except Exception as e:
        logger.warning(f"Failed to read FIF header from {file_path.name}: {e}")
        return None


def inspect_fif_header(fif_path: Path, verbose: bool = True) -> Optional[Dict[str, Any]]:
    """Inspect and display detailed FIF header information for debugging.

    Args:
        fif_path: Path to FIF file
        verbose: If True, log detailed information

    Returns:
        Dict with detailed header information, or None if read failed
    """
    try:
        raw = mne.io.read_raw_fif(fif_path, preload=False, allow_maxshield=True, verbose=False)

        file_id = raw.info.get('file_id', {})
        meas_date = raw.info.get('meas_date')

        result = {
            'filename': fif_path.name,
            'meas_date': str(meas_date) if meas_date else None,
            'duration_sec': raw.times[-1] if len(raw.times) > 0 else 0,
            'n_samples': raw.n_times,
            'n_channels': len(raw.ch_names),
            'sfreq': raw.info.get('sfreq'),
            'file_id': file_id,
        }

        if verbose:
            logger.info(f"FIF Header: {fif_path.name}")
            logger.info(f"  Meas date: {result['meas_date']}")
            logger.info(f"  Duration: {result['duration_sec']:.1f}s")
            logger.info(f"  Samples: {result['n_samples']:,}")
            logger.info(f"  Channels: {result['n_channels']}")
            logger.info(f"  Sfreq: {result['sfreq']} Hz")

            if file_id:
                logger.info(f"  File ID:")
                for key, value in file_id.items():
                    logger.info(f"    {key}: {value}")

            if hasattr(raw, '_first_samps') and hasattr(raw, '_last_samps'):
                logger.info(f"  Split info (internal):")
                logger.info(f"    First samples: {raw._first_samps}")
                logger.info(f"    Last samples: {raw._last_samps}")

        return result
    except Exception as e:
        if verbose:
            logger.warning(f"Failed to inspect FIF header from {fif_path.name}: {e}")
        return None


def prompt_user_for_duplicate(files: List[Path]) -> Path:
    """Prompt user to choose between duplicate files.

    Only prompts if stdin is a TTY (interactive environment).
    Falls back silently to first file if not interactive.

    Args:
        files: List of duplicate file paths (should have 2+ files)

    Returns:
        The file chosen by the user, or first file if non-interactive
    """
    if not sys.stdin.isatty():
        logger.debug(f"Non-interactive environment: silently choosing {files[0].name}")
        return files[0]

    print(f"\n⚠  Duplicate files with same preference level found:")
    for idx, fpath in enumerate(files, 1):
        print(f"  {idx}. {fpath.name}")

    while True:
        try:
            response = input(f"\nWhich file to keep? Enter 1-{len(files)}: ").strip()
            choice = int(response)
            if 1 <= choice <= len(files):
                selected = files[choice - 1]
                print(f"✓ Selected: {selected.name}\n")
                return selected
            else:
                print(f"Invalid choice. Please enter 1-{len(files)}.")
        except ValueError:
            print(f"Invalid input. Please enter a number 1-{len(files)}.")


def has_fif_files_in_folder(folder: Path) -> bool:
    """Check if FIF files exist directly in a folder (non-recursive).

    Used to detect legacy MEG data without session subdirectories.

    Args:
        folder: Path to folder to check

    Returns:
        True if one or more .fif files found directly in folder
    """
    if not folder.exists():
        return False
    return len(list(folder.glob("*.fif"))) > 0


def extract_measurement_date_from_fif(fif_file: Path) -> Optional[str]:
    """Extract measurement date from a FIF file and convert to YYMMDD format.

    Used as fallback for calibration file matching when session folder
    doesn't contain a date.

    Args:
        fif_file: Path to raw FIF file

    Returns:
        Date string in YYMMDD format, or None if extraction failed
    """
    if not fif_file.exists():
        return None

    try:
        raw = mne.io.read_raw_fif(fif_file, preload=False, allow_maxshield=True, verbose=False)
        meas_date = raw.info.get('meas_date')

        if isinstance(meas_date, datetime):
            return meas_date.strftime('%y%m%d')
        elif isinstance(meas_date, date):
            return meas_date.strftime('%y%m%d')

        return None
    except Exception as e:
        logger.debug(f"Could not extract measurement date from {fif_file.name}: {e}")
        return None


def extract_derivative_info(filename: str) -> Optional[Tuple[str, str]]:
    """
    Detect and extract MaxFilter processing information from filename.

    Strips recognized suffixes and builds the base filename. Handles multiple
    suffixes (e.g., chessboard2_mc_ave.fif -> chessboard2.fif, "mc-ave").
    Also handles split file suffixes (e.g., file_tsss_mc-1.fif, file-1_tsss_mc.fif).

    Returns:
      (base_filename, proc_label) if derivative detected, None if raw file
      Example: chessboard2_mc_ave.fif -> ("chessboard2.fif", "mc-ave")
    """
    base_name, proc_label = _extract_base_name_and_suffix(filename, with_proc=True)

    if proc_label is None:
        return None

    base_filename = base_name + '.fif'
    return (base_filename, proc_label)


def find_matching_raw_file(derivative_filename: str, raw_files: List[Path], split_file_groups: Dict[Path, List[Path]]) -> Optional[Tuple[Path, Optional[int]]]:
    """
    Find the raw file that corresponds to a derivative file.
    
    Handles both split naming patterns:
    - file-1_mc.fif (split first, then processing)
    - file_mc-1.fif (processing first, then split)
    
    Args:
        derivative_filename: Name of the derivative file (e.g., 'chessboard1_mc.fif', 'file_mc-1.fif', 'file-1_mc.fif')
        raw_files: List of raw FIF file paths in the session
        split_file_groups: Dict mapping primary file → list of all split parts
    
    Returns:
        Tuple of (matching_raw_path, split_index) where:
        - matching_raw_path: Path to the raw file (primary file if split)
        - split_index: Index if derivative is a split part (0=primary, 1=first split, etc), None if not split
        Returns None if no match found
    """
    stem = Path(derivative_filename).stem
    
    # First, check if there's a split suffix at the end (e.g., file_mc-1 or file-1_mc)
    split_match = re.match(r'^(.+?)-(\d+)$', stem)
    split_num = None
    base_stem_with_proc = stem
    
    if split_match:
        # Has a split suffix: extract it
        base_stem_with_proc = split_match.group(1)  # e.g., "file_mc" or "file"
        split_num = int(split_match.group(2))        # e.g., 1, 2, 3
    
    # Now extract derivative info from the (possibly split-stripped) stem
    # Reconstruct filename for derivative extraction
    temp_filename = base_stem_with_proc + '.fif'
    deriv_info = extract_derivative_info(temp_filename)
    
    if not deriv_info:
        # Not a derivative file
        return None
    
    base_filename_stem, _ = deriv_info  # e.g., 'file.fif' → 'file'
    base_filename_stem = Path(base_filename_stem).stem
    
    # Now we have the base stem and possibly a split number
    if split_num is not None:
        # Derivative is for a split part (e.g., 'file_mc-1.fif' or 'file-1_mc.fif')
        primary_filename = f"{base_filename_stem}.fif"
        
        # Find the primary raw file
        for raw_path in raw_files:
            if raw_path.name == primary_filename:
                # Verify this is actually a split file group
                if raw_path in split_file_groups:
                    return (raw_path, split_num)  # split_num matches the -N suffix
                break
    else:
        # Derivative is for primary file (e.g., 'file_mc.fif')
        primary_filename = f"{base_filename_stem}.fif"
        for raw_path in raw_files:
            if raw_path.name == primary_filename:
                # Check if this raw file is part of a split group
                if raw_path in split_file_groups:
                    return (raw_path, 0)  # 0 = primary file
                else:
                    return (raw_path, None)  # Not a split file
    
    return None


def infer_task_from_basename(base_filename: str, file_patterns: List[Dict[str, Any]]) -> Optional[str]:
    """
    Try to infer task from base filename by matching against patterns.
    Used for derivatives when the raw file doesn't exist.
    
    Args:
        base_filename: Base filename without derivative suffix (e.g., 'chessboard1.fif')
        file_patterns: List of pattern rules from config
    
    Returns:
        Task name if pattern matches, None otherwise
    """
    matches = find_matching_patterns(base_filename, file_patterns)
    if matches:
        return matches[0][1].get('task', None)
    return None


def find_matching_patterns(filename: str, patterns: List[Dict[str, Any]]) -> List[Tuple[int, Dict[str, Any]]]:
    """
    Find ALL patterns that match a filename.
    Returns list of (pattern_index, pattern_rule) tuples.
    """
    matches = []
    for idx, pattern_rule in enumerate(patterns):
        pattern = pattern_rule['pattern']
        if fnmatch.fnmatch(filename.lower(), pattern.lower()):
            matches.append((idx, pattern_rule))
    return matches


def match_file_pattern(filename: str, patterns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Match a filename against configured patterns with strict validation.
    
    Ensures each file matches exactly one pattern. If multiple patterns match with
    different task assignments, raises ValidationError to prevent silent misclassification.
    
    Returns: Matched pattern rule dictionary, or None if no match found
    Raises: ValidationError if multiple patterns match with different tasks
    """
    matches = find_matching_patterns(filename, patterns)
    
    if len(matches) == 0:
        return None
    
    if len(matches) == 1:
        return matches[0][1]
    
    # Multiple matches - check if they all assign the same task
    tasks = set(rule.get('task', 'unknown') for _, rule in matches)
    
    if len(tasks) == 1:
        logger.debug(f"  ℹ {filename}: matches {len(matches)} patterns (all assign task={list(tasks)[0]}, using first)")
        return matches[0][1]
    
    # Multiple matches with different tasks - ambiguous!
    error_msg = [
        f"",
        f"{'='*70}",
        f"ERROR: Ambiguous filename detected",
        f"{'='*70}",
        f"File: {filename}",
        f"Matches {len(matches)} patterns:",
        f""
    ]
    for idx, (pattern_idx, rule) in enumerate(matches, 1):
        pattern = rule.get('pattern', 'unknown')
        task = rule.get('task', 'unknown')
        error_msg.append(f"  {idx}. Pattern: {pattern} → task={task}")
    
    error_msg.extend([
        f"",
        f"Resolution:",
        f"  1. Make patterns more specific (reorder in config.json)",
        f"  2. Rename the file to match only one pattern",
        f"",
        f"Run 'python meg_validate_config.py' to check your configuration.",
        f"{'='*70}",
    ])
    
    raise ValidationError('\n'.join(error_msg))


def validate_all_files(fif_files: List[Path], file_patterns: List[Dict[str, Any]]) -> Dict[Path, Dict[str, Any]]:
    """
    Pre-flight validation: check all files can be uniquely matched.
    
    Returns:
        Dict mapping file paths to their matched pattern rules
    
    Raises:
        ValidationError: If any file cannot be uniquely matched
    """
    file_pattern_map = {}
    validation_errors = []
    
    logger.info("\n" + "─"*70)
    logger.info("PRE-FLIGHT VALIDATION")
    logger.info("─"*70)
    logger.info(f"Validating {len(fif_files)} file(s)...")
    
    for fif_path in fif_files:
        try:
            pattern_rule = match_file_pattern(fif_path.name, file_patterns)
            if pattern_rule is None:
                validation_errors.append(f"  ✗ {fif_path.name}: No matching pattern")
            else:
                file_pattern_map[fif_path] = pattern_rule
                task = pattern_rule.get('task', 'unknown')
                logger.debug(f"  ✓ {fif_path.name} → task={task}")
        except ValidationError as e:
            raise
    
    if validation_errors:
        logger.error("\nValidation failed:")
        for err in validation_errors:
            logger.error(err)
        raise ValidationError("Pre-flight validation failed. Fix configuration.")
    
    logger.info(f"✓ Validation complete: {len(file_pattern_map)}/{len(fif_files)} files matched")
    
    return file_pattern_map


def extract_run_from_filename(filename: str, extraction_method: str = "last_digits", meg_id: Optional[str] = None) -> Optional[int]:
    """
    Extract run number from filename.
    
    NOTE: Excludes split file patterns (e.g., -1.fif, -2.fif) which indicate
    file splits, not run numbers. Rejects if the extracted number matches meg_id.
    """
    if extraction_method == "none":
        return None
    
    # Check if this is a split file (ends with -N.fif pattern)
    # If so, remove the split suffix before extracting run number
    stem = Path(filename).stem
    
    # Remove split suffix if present (e.g., "filename-1" -> "filename")
    split_match = re.match(r'^(.+?)-(\d+)$', stem)
    if split_match:
        stem = split_match.group(1)  # Use base name without split number
    
    matches = re.findall(r'\d+', stem)
    if not matches:
        return None
    
    if extraction_method == "first_digits":
        candidate = int(matches[0])
    else:  # "last_digits" or default
        candidate = int(matches[-1])
    
    # Reject if it matches the MEG ID (not a run number)
    if meg_id is not None:
        try:
            if candidate == int(meg_id):
                return None
        except (ValueError, TypeError):
            pass
    
    return candidate


def group_files_by_task(file_pattern_map: Dict[Path, Dict[str, Any]], meg_id: Optional[str] = None) -> Dict[str, List[Tuple[Path, Dict[str, Any], Optional[int]]]]:
    """Group files by task and extract run numbers."""
    task_files = defaultdict(list)
    
    for fif_path, pattern_rule in file_pattern_map.items():
        task = pattern_rule.get('task', 'unknown')
        run_from_filename = extract_run_from_filename(
            fif_path.name,
            pattern_rule.get('run_extraction', 'last_digits'),
            meg_id=meg_id
        )
        task_files[task].append((fif_path, pattern_rule, run_from_filename))
    
    return task_files


def assign_run_numbers(task_files: Dict[str, List[Tuple[Path, Dict[str, Any], Optional[int]]]]) -> Dict[Path, Tuple[str, Optional[int], Dict[str, Any]]]:
    """Assign run numbers based on task grouping."""
    file_mapping = {}
    
    for task, files in task_files.items():
        raw_files = [f for f in files if not (f[1].get('is_processed') or f[1].get('is_averaged'))]
        
        if len(raw_files) == 0:
            for fif_path, pattern_rule, run_from_filename in files:
                file_mapping[fif_path] = (task, run_from_filename, pattern_rule)
            continue
        elif len(raw_files) == 1:
            fif_path, pattern_rule, _ = raw_files[0]
            file_mapping[fif_path] = (task, None, pattern_rule)
        else:
            sorted_raw = sorted(raw_files, key=lambda x: (x[2] if x[2] is not None else float('inf'), x[0].name))
            for idx, (fif_path, pattern_rule, run_from_filename) in enumerate(sorted_raw, start=1):
                file_mapping[fif_path] = (task, idx, pattern_rule)
    
    return file_mapping


def find_fine_calibration_file(meg_maxfilter_root: Path, session_date: Optional[str], calibration_system: str = 'triux') -> Optional[Path]:
    """
    Find the appropriate fine-calibration file based on session date.
    
    For Triux (default):
      - Looks for sss_cal_XXXX_*.dat files
      - Selects file with date <= session date
      - Returns full path and logs the selection with dates
    
    For VectorView:
      - Returns sss_cal_vectorview.dat (single file, no date matching)
    
    Args:
        meg_maxfilter_root: Path to MEG/maxfilter directory
        session_date: Date string in format 'YYMMDD' from session folder name
        calibration_system: 'triux' or 'vectorview' to determine which calibration files to use
    
    Returns:
        Path to calibration file or None if not found
    """
    sss_dir = meg_maxfilter_root / 'sss'
    
    if not sss_dir.exists():
        logger.warning(f"  ⚠ SSS directory not found: {sss_dir}")
        return None
    
    if calibration_system == 'vectorview':
        # VectorView: single file, no date matching needed
        vectorview_file = sss_dir / 'sss_cal_erasme_enm.dat'
        if vectorview_file.exists():
            logger.info(f"  ✓ Fine-calibration: {vectorview_file.name} (VectorView)")
            return vectorview_file
        else:
            logger.warning(f"  ⚠ VectorView calibration not found: {vectorview_file}")
            return None
    else:
        # Triux (default): find calibration file with date <= session date
        if not session_date:
            logger.error(f"  ✗ Could not extract session date - cannot match calibration file")
            return None
        
        from datetime import datetime
        try:
            # Parse YYMMDD format from session folder
            yy = int(session_date[:2])
            mm = int(session_date[2:4])
            dd = int(session_date[4:6])
            # Assume 20YY for years 00-50, 19YY for 50-99
            yyyy = 2000 + yy if yy <= 50 else 1900 + yy
            session_dt = datetime(yyyy, mm, dd)
        except (ValueError, IndexError) as e:
            logger.error(f"  ✗ Could not parse session date '{session_date}': {e}")
            return None
        
        # Find all sss_cal_XXXX_*.dat files
        import re
        
        cal_files = []
        for f in sss_dir.glob('sss_cal_XXXX_*.dat'):
            # Extract date from filename (format: YYMMDD)
            match = re.search(r'sss_cal_XXXX_(\d{6})\.dat', f.name)
            if match:
                date_str = match.group(1)
                try:
                    # Parse YYMMDD format
                    yy = int(date_str[:2])
                    mm = int(date_str[2:4])
                    dd = int(date_str[4:6])
                    # Assume 20YY for years 00-50, 19YY for 50-99
                    yyyy = 2000 + yy if yy <= 50 else 1900 + yy
                    cal_date = datetime(yyyy, mm, dd)
                    cal_files.append((cal_date, f))
                except (ValueError, IndexError) as e:
                    logger.debug(f"Could not parse date from {f.name}: {e}")
        
        if not cal_files:
            logger.error(f"  ✗ No fine-calibration files found matching pattern sss_cal_XXXX_*.dat")
            return None
        
        # Sort by date
        cal_files.sort(key=lambda x: x[0])
        
        # Find the most recent calibration file with date <= session date
        selected_file = None
        selected_date = None
        
        for cal_date, f in cal_files:
            if cal_date <= session_dt:
                selected_file = f
                selected_date = cal_date
        
        if selected_file and selected_date:
            logger.info(f"  ✓ Fine-calibration: {selected_file.name} (cal date: {selected_date.strftime('%Y-%m-%d')}, session date: {session_dt.strftime('%Y-%m-%d')})")
            return selected_file
        else:
            logger.error(f"  ✗ No calibration file with date <= {session_dt.strftime('%Y-%m-%d')} found in {sss_dir}")
            return None


def detect_calibration_files(source_dir: Path, session_folder: Optional[str] = None, meg_maxfilter_root: Optional[Path] = None, calibration_system: str = 'triux', raw_fif_files: Optional[List[Path]] = None) -> Dict[str, Optional[Path]]:
    """Auto-detect Neuromag/Elekta/MEGIN calibration files.
    
    If meg_maxfilter_root is provided, looks for calibration files in:
      - Crosstalk: MEG/maxfilter/ctc/ct_sparse_triux2.fif (triux) or ct_sparse_erasme_enm.fif (vectorview)
      - Fine-cal: MEG/maxfilter/sss/sss_cal_XXXX_*.dat (date-matched to session date for triux) or sss_cal_erasme_enm.dat (vectorview)
    
    Session date is extracted from session_folder name (YYMMDD format).
    If folder name has no date and raw_fif_files is provided, falls back to
    extracting measurement date from the first FIF file.
    Falls back to searching the session directory if meg_maxfilter_root not found.
    """
    calibration_files: Dict[str, Optional[Path]] = {'crosstalk': None, 'calibration': None}
    
    # If meg_maxfilter_root provided, use it first
    if meg_maxfilter_root and meg_maxfilter_root.exists():
        ctc_dir = meg_maxfilter_root / 'ctc'
        
        if calibration_system == 'vectorview':
            # VectorView crosstalk
            crosstalk_file = ctc_dir / 'ct_sparse_erasme_enm.fif'
            if crosstalk_file.exists():
                calibration_files['crosstalk'] = crosstalk_file
                logger.debug(f"  Found cross-talk file (VectorView): {crosstalk_file.name}")
            else:
                logger.warning(f"  ⚠ VectorView crosstalk not found: {crosstalk_file}")
        else:
            # Triux (default) crosstalk
            crosstalk_file = ctc_dir / 'ct_sparse_triux2.fif'
            if crosstalk_file.exists():
                calibration_files['crosstalk'] = crosstalk_file
                logger.debug(f"  Found cross-talk file (Triux): {crosstalk_file.name}")
            else:
                logger.warning(f"  ⚠ Triux crosstalk not found: {crosstalk_file}")
        
        # Extract session date from folder name (format: YYMMDD)
        session_date = None
        if session_folder:
            # Try to extract YYMMDD from session folder name
            import re
            match = re.search(r'(\d{6})', session_folder)
            if match:
                session_date = match.group(1)
        
        # Fallback: extract measurement date from FIF file if folder name has no date
        if not session_date and raw_fif_files and len(raw_fif_files) > 0:
            session_date = extract_measurement_date_from_fif(raw_fif_files[0])
            if session_date:
                logger.debug(f"  Extracted session date from FIF header: {session_date}")
        
        # Find calibration file based on session date
        calibration_files['calibration'] = find_fine_calibration_file(meg_maxfilter_root, session_date, calibration_system)
    
    # Fallback: search in session directory if meg_maxfilter_root not used or files not found
    if not calibration_files['crosstalk'] or not calibration_files['calibration']:
        search_dir = source_dir / session_folder if session_folder else source_dir
        
        if not calibration_files['crosstalk']:
            for pattern in ['*crosstalk*.fif', '*cross_talk*.fif', '*sst*.fif']:
                matches = list(search_dir.glob(pattern))
                if matches:
                    calibration_files['crosstalk'] = matches[0]
                    logger.debug(f"  Found cross-talk file (fallback): {matches[0].name}")
                    break
        
        if not calibration_files['calibration']:
            for pattern in ['*calibration*.dat', '*sss*.dat']:
                matches = list(search_dir.glob(pattern))
                if matches:
                    calibration_files['calibration'] = matches[0]
                    logger.debug(f"  Found calibration file (fallback): {matches[0].name}")
                    break
    
    return calibration_files


def copy_calibration_files(source_calib_files: Dict[str, Optional[Path]], subject: str, session: Optional[str], bids_root: Path, datatype: str = 'meg') -> None:
    """Copy cross-talk and fine-calibration files to BIDS directory."""
    if session:
        target_dir = bids_root / f"sub-{subject}" / f"ses-{session}" / datatype
    else:
        target_dir = bids_root / f"sub-{subject}" / datatype
    
    target_dir.mkdir(parents=True, exist_ok=True)
    
    if source_calib_files['crosstalk']:
        if session:
            target_name = f"sub-{subject}_ses-{session}_acq-crosstalk_meg.fif"
        else:
            target_name = f"sub-{subject}_acq-crosstalk_meg.fif"
        
        target_path = target_dir / target_name
        shutil.copy2(source_calib_files['crosstalk'], target_path)
        logger.info(f"  ✓ Copied cross-talk file: {target_name}")
    
    if source_calib_files['calibration']:
        if session:
            target_name = f"sub-{subject}_ses-{session}_acq-calibration_meg.dat"
        else:
            target_name = f"sub-{subject}_acq-calibration_meg.dat"
        
        target_path = target_dir / target_name
        shutil.copy2(source_calib_files['calibration'], target_path)
        logger.info(f"  ✓ Copied calibration file: {target_name}")


def detect_split_files(fif_files: List[Path]) -> Dict[Path, List[Path]]:
    """
    Detect and group multi-part FIFF files (files > 2GB split across multiple files).
    
    Large FIF files automatically split into parts named: filename.fif, filename-1.fif,
    filename-2.fif, etc. This function groups them back together.
    
    Returns: Dict mapping primary file → list of all parts in order
    """
    split_groups = {}
    processed = set()
    fif_files_set = set(fif_files)
    
    for fif_path in sorted(fif_files):
        if fif_path in processed:
            continue

        base_name, _ = _extract_base_name_and_suffix(fif_path.name, with_proc=False)
        parent_dir = fif_path.parent
        base_file = parent_dir / f"{base_name}.fif"
        
        # Prefer the unsuffixed base file as the primary if it exists
        if base_file in fif_files_set:
            primary = base_file
        else:
            primary = fif_path
        
        # Collect parts starting from primary, then -1, -2, ...
        parts = [primary]
        idx = 1
        while True:
            next_part = parent_dir / f"{base_name}-{idx}.fif"
            if next_part in fif_files_set:
                parts.append(next_part)
                processed.add(next_part)
                idx += 1
            else:
                break
        
        if len(parts) > 1:
            split_groups[primary] = parts
            processed.update(parts)
            logger.debug(f"  Detected split file: {base_name} ({len(parts)} parts)")
    
    return split_groups


def detect_derivative_split_files(deriv_files: List[Path]) -> Tuple[Dict[Path, List[Path]], set]:
    """Detect and group multi-part derivative FIFF files.

    Groups derivatives by (base_name, proc_label) and detects split patterns.

    Handles both patterns:
    - NAP-1_tsss_mc.fif, NAP-2_tsss_mc.fif (split before proc)
    - NAP_tsss_mc-1.fif, NAP_tsss_mc-2.fif (split after proc)

    Args:
        deriv_files: List of derivative FIF file paths

    Returns:
        (split_groups, processed_set) where split_groups maps primary file to
        list of all parts in order, and processed_set contains all files in
        any split group.
    """
    split_groups: Dict[Path, List[Path]] = {}
    processed: set = set()
    deriv_files_set = set(deriv_files)

    # Group derivatives by (base_name, proc_label)
    deriv_groups: Dict[Tuple[str, str], List[Path]] = defaultdict(list)
    for deriv_file in deriv_files:
        base_name, proc_label = _extract_base_name_and_suffix(deriv_file.name, with_proc=True)
        if proc_label is None:
            continue
        deriv_groups[(base_name, proc_label)].append(deriv_file)

    # For each group, detect splits
    for (base_name, proc_label), files in deriv_groups.items():
        if len(files) <= 1:
            continue

        proc_suffix = proc_label.replace('-', '_')
        parent_dir = files[0].parent
        parts: List[Path] = []

        # Try pattern 1: base_proc.fif, base-1_proc.fif, base-2_proc.fif (split BEFORE proc)
        base_file = parent_dir / f"{base_name}_{proc_suffix}.fif"
        pattern1_parts: List[Path] = []
        if base_file in deriv_files_set:
            pattern1_parts.append(base_file)

        # Look for split parts (-1, -2, etc.)
        idx = 1
        while True:
            next_part = parent_dir / f"{base_name}-{idx}_{proc_suffix}.fif"
            if next_part in deriv_files_set:
                pattern1_parts.append(next_part)
                idx += 1
            else:
                break

        if len(pattern1_parts) > 1:
            parts = pattern1_parts

        # If pattern 1 didn't find splits, try pattern 2: base_proc-1.fif, base_proc-2.fif
        if not parts:
            base_file_p2 = parent_dir / f"{base_name}_{proc_suffix}-1.fif"
            if base_file_p2 in deriv_files_set:
                pattern2_parts: List[Path] = []
                # Check if there's also a base file without split suffix
                base_without_split = parent_dir / f"{base_name}_{proc_suffix}.fif"
                if base_without_split in deriv_files_set:
                    pattern2_parts.append(base_without_split)

                idx = 1
                while True:
                    next_part = parent_dir / f"{base_name}_{proc_suffix}-{idx}.fif"
                    if next_part in deriv_files_set:
                        pattern2_parts.append(next_part)
                        idx += 1
                    else:
                        break

                if len(pattern2_parts) > 1:
                    parts = pattern2_parts

        # Create split group if we found parts
        if len(parts) > 1:
            split_groups[parts[0]] = parts
            # Mark ALL files in this (base_name, proc_label) group as processed
            processed.update(files)

    return split_groups, processed


def identify_primary_files(fif_files: List[Path], interactive: bool = False) -> Tuple[List[Path], int]:
    """Identify and filter FIF files by separating duplicates.

    Uses FIF header fingerprints to deduplicate files that represent the same
    recording (e.g., renamed copies, redundant split parts).

    Algorithm:
    - PHASE 1: Classify by split structure (PRIMARY: len(first_samps)>1, OTHER: ==1)
    - PHASE 2: Deduplicate PRIMARYs by fingerprint (meas_date, first_samps[0])
    - PHASE 3: Link OTHER files to kept PRIMARYs; remainder are STANDALONEs
    - PHASE 4: Deduplicate STANDALONEs by fingerprint

    Args:
        fif_files: List of FIF file paths
        interactive: If True, prompt user when duplicates have same preference level

    Returns:
        (files_to_keep, split_group_count) where split_group_count is the number
        of multi-part recordings detected.
    """
    if not fif_files:
        return [], 0

    logger.info("Identifying duplicate files...")

    # Read headers for all files
    file_headers: Dict[Path, Optional[Dict]] = {}
    for fif_file in fif_files:
        header_info = get_fif_header_info(fif_file)
        file_headers[fif_file] = header_info  # may be None

    # Helper: filename preference score (underscore=0, dash=1, none=2)
    def get_preference_level(file_path: Path) -> int:
        stem = file_path.stem
        if re.search(r'^.+_\d+$', stem):
            return 0  # underscore suffix: base_N
        if re.search(r'^.+?-\d+$', stem):
            return 1  # dash suffix: base-N
        return 2     # no numeric suffix

    # Helper: create fingerprint
    def get_fingerprint(file_path: Path) -> tuple:
        hdr = file_headers.get(file_path)
        if not hdr:
            return ('unknown', file_path.name)
        first_samps = hdr['first_samps']
        first_samp_tuple = tuple(int(s) for s in first_samps) if first_samps is not None else ()
        meas_date = hdr['meas_date'] or 'unknown'
        return (meas_date, first_samp_tuple)

    # Helper: select best from duplicate group
    def process_duplicate_group(files_in_group: List[Path], interactive: bool = False) -> Path:
        if len(files_in_group) == 1:
            return files_in_group[0]
        files_sorted = sorted(files_in_group, key=lambda f: (get_preference_level(f), f.name))
        if len(files_sorted) >= 2:
            level_1 = get_preference_level(files_sorted[0])
            level_2 = get_preference_level(files_sorted[1])
            if level_1 == level_2 and interactive:
                canonical = prompt_user_for_duplicate(files_sorted)
                logger.info(f"  → (user selected) {canonical.name} from {len(files_sorted)} duplicate(s)")
                return canonical
        canonical = files_sorted[0]
        if len(files_sorted) > 1:
            kept = files_sorted[0].name
            for excluded_file in files_sorted[1:]:
                logger.info(f"  → {kept} <-> {excluded_file.name}")
        return canonical

    # Helper: parse filename to get (base, number, separator)
    def parse_filename_with_number(filename: str) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        stem = filename[:-4] if filename.endswith('.fif') else filename
        match = re.search(r'^(.+)_(\d+)$', stem)
        if match:
            return (match.group(1), int(match.group(2)), '_')
        match = re.search(r'^(.+?)-([\d]+)$', stem)
        if match:
            return (match.group(1), int(match.group(2)), '-')
        return (None, None, None)

    # ========== PHASE 1: Classify ==========
    primary_files: List[Path] = []
    other_files: List[Path] = []

    for fif_file in sorted(fif_files):
        hdr = file_headers.get(fif_file)
        if hdr and hdr['first_samps'] is not None and len(hdr['first_samps']) > 1:
            primary_files.append(fif_file)
        else:
            other_files.append(fif_file)

    # ========== PHASE 2: Deduplicate PRIMARYs ==========
    primary_by_fp: Dict[Tuple, List[Path]] = defaultdict(list)
    for fif_file in primary_files:
        hdr = file_headers.get(fif_file)
        if hdr and hdr['first_samps'] is not None and len(hdr['first_samps']) > 0 and hdr['meas_date']:
            first_samp = int(hdr['first_samps'][0])
            fp: tuple = (hdr['meas_date'], first_samp)
        else:
            fp = ('unknown', fif_file.name)
        primary_by_fp[fp].append(fif_file)

    kept_primary_files: set = set()
    excluded_primary_files: set = set()

    for fp, files_in_group in primary_by_fp.items():
        canonical = process_duplicate_group(files_in_group, interactive=interactive)
        kept_primary_files.add(canonical)
        for fif_file in files_in_group:
            if fif_file != canonical:
                excluded_primary_files.add(fif_file)

    # ========== PHASE 3: Link SECONDARY files to KEPT PRIMARYs ==========
    kept_primary_map: Dict[str, str] = {}
    for kept_primary in kept_primary_files:
        hdr = file_headers.get(kept_primary)
        if hdr and hdr['meas_date']:
            stem = kept_primary.name[:-4]
            kept_primary_map[stem] = hdr['meas_date']

    secondary_files: List[Path] = []
    standalone_files: List[Path] = []
    kept_secondaries: set = set()

    # First pass: identify SECONDARY files linked to kept PRIMARY
    for fif_file in other_files:
        hdr = file_headers.get(fif_file)
        is_secondary_candidate = (
            hdr and hdr['meas_date'] and
            hdr['first_samps'] is not None and
            len(hdr['first_samps']) == 1
        )
        if not is_secondary_candidate:
            standalone_files.append(fif_file)
            continue

        matched_to_kept = False
        base_file, num_file, sep_file = parse_filename_with_number(fif_file.name)
        if base_file and sep_file == '-':
            for primary_stem, primary_meas_date in kept_primary_map.items():
                primary_base, primary_num, primary_sep = parse_filename_with_number(primary_stem + ".fif")
                if (base_file == primary_base and
                        primary_sep == '_' and
                        hdr and hdr['meas_date'] == primary_meas_date):
                    secondary_files.append(fif_file)
                    logger.debug(f"  SECONDARY (kept): {fif_file.name} -> linked to {primary_stem}.fif")
                    matched_to_kept = True
                    break

        if not matched_to_kept:
            standalone_files.append(fif_file)

    # Second pass: among standalones, find duplicates of kept SECONDARY files
    for fif_file in list(standalone_files):
        hdr = file_headers.get(fif_file)
        is_secondary_candidate = (
            hdr and hdr['meas_date'] and
            hdr['first_samps'] is not None and
            len(hdr['first_samps']) == 1
        )
        if not is_secondary_candidate or not hdr:
            continue

        first_samp = int(hdr['first_samps'][0])
        meas_date = hdr['meas_date']
        candidate_fp = (first_samp, meas_date)

        is_duplicate = False
        for kept_sec in secondary_files:
            kept_hdr = file_headers.get(kept_sec)
            if kept_hdr and kept_hdr['first_samps'] is not None and len(kept_hdr['first_samps']) == 1:
                kept_fp = (int(kept_hdr['first_samps'][0]), kept_hdr['meas_date'])
                if candidate_fp == kept_fp:
                    is_duplicate = True
                    break

        if is_duplicate:
            standalone_files.remove(fif_file)
            logger.debug(f"  SECONDARY (excluded - duplicate): {fif_file.name}")

    # ========== PHASE 4: Deduplicate STANDALONEs ==========
    standalone_by_fp: Dict[tuple, List[Path]] = defaultdict(list)
    for fif_file in standalone_files:
        fp = get_fingerprint(fif_file)
        standalone_by_fp[fp].append(fif_file)

    kept_standalone_files: List[Path] = []
    for fp, files_in_group in standalone_by_fp.items():
        canonical = process_duplicate_group(files_in_group, interactive=interactive)
        kept_standalone_files.append(canonical)

    # ========== Combine results ==========
    files_to_keep = list(kept_primary_files) + kept_standalone_files

    split_group_count = sum(
        1 for kp in kept_primary_files
        if (file_headers.get(kp) or {}).get('first_samps') is not None
        and len((file_headers.get(kp) or {}).get('first_samps', [])) > 1
    )

    return files_to_keep, split_group_count


def ensure_derivatives_description(deriv_root: Path, pipeline_name: str, pipeline_version: Optional[str]) -> None:
    """Create derivatives/dataset_description.json if missing."""
    deriv_root.mkdir(parents=True, exist_ok=True)
    dd = deriv_root / "dataset_description.json"
    if dd.exists():
        return
    
    payload = {
        "Name": f"Derivatives - {pipeline_name}",
        "BIDSVersion": "1.10.0",
        "DatasetType": "derivative",
        "GeneratedBy": [{"Name": pipeline_name, "Version": pipeline_version if pipeline_version else "unknown"}]
    }
    dd.write_text(json.dumps(payload, indent=2))


def extract_eeg_information(raw: mne.io.BaseRaw) -> Optional[Dict[str, List[Any]]]:
    """
    Extract EEG channel information from FIF file for electrodes.tsv.
    
    Returns a dictionary with lists of electrode information:
    {
        'name': [...],      # EEG channel names
        'x': [...],         # X coordinates (in meters, MEG device frame)
        'y': [...],         # Y coordinates
        'z': [...],         # Z coordinates
        'size': [...]       # Electrode size (optional, in meters)
    }
    
    Returns None if no EEG channels found.
    """
    # Get EEG channel indices
    eeg_indices = mne.pick_types(raw.info, eeg=True, exclude=[])  # type: ignore[arg-type]
    
    if len(eeg_indices) == 0:
        return None
    
    eeg_data = {
        'name': [],
        'x': [],
        'y': [],
        'z': [],
        'size': []
    }
    
    for idx in eeg_indices:
        ch_info = raw.info['chs'][idx]
        ch_name = ch_info['ch_name']
        
        # Channel name
        eeg_data['name'].append(ch_name)
        
        # Primary: try channel loc in device coordinates (meters)
        loc = np.array(ch_info['loc'][:3], dtype=float)
        use_fallback = (not np.any(np.isfinite(loc))) or np.allclose(loc, 0.0)

        if use_fallback:
            # Fallback: try montage positions (typically in head coordinates)
            montage = raw.get_montage()
            if montage is not None:
                try:
                    positions = montage.get_positions()
                    ch_pos = positions.get('ch_pos') or {}
                    if ch_name in ch_pos and ch_pos[ch_name] is not None:
                        head_pos = np.array(ch_pos[ch_name], dtype=float)
                        # Convert head → device if dev_head_t is available
                        dev_head_t = raw.info.get('dev_head_t')
                        if dev_head_t and 'trans' in dev_head_t and dev_head_t['trans'] is not None:
                            try:
                                loc = apply_trans(np.linalg.inv(dev_head_t['trans']), head_pos)
                            except Exception:
                                # If transform fails, keep head coordinates
                                loc = head_pos
                                logger.debug(f"    ⚠ Using head coords for {ch_name} (dev_head_t transform failed)")
                        else:
                            # No device-head transform available; use head coordinates
                            loc = head_pos
                            logger.debug(f"    ⚠ Using head coords for {ch_name} (missing dev_head_t)")
                    else:
                        logger.debug(f"    ⚠ No montage position for {ch_name}; coordinates remain zero")
                except Exception as e:
                    logger.debug(f"    ⚠ Montage fallback failed for {ch_name}: {e}")
            else:
                logger.debug(f"    ⚠ No montage found; coordinates for {ch_name} may be zero")

        eeg_data['x'].append(float(loc[0]))
        eeg_data['y'].append(float(loc[1]))
        eeg_data['z'].append(float(loc[2]))
        
        # Electrode size (optional, in meters)
        size = ch_info.get('size', 0.005)  # Default 5mm if not specified
        eeg_data['size'].append(float(size))
    
    return eeg_data


def write_electrodes_tsv(eeg_data: Dict[str, List[Any]], subject: str, session: Optional[str], bids_root: Path, datatype: str = 'meg') -> None:
    """
    Write electrodes.tsv file for simultaneous MEG/EEG recording.
    
    BIDS naming: sub-<label>[_ses-<label>]_electrodes.tsv
    Location: sub-<label>[_ses-<label>]/meg/
    
    The electrodes are stored in MEG device coordinates (device frame).
    
    Args:
        eeg_data: Dictionary with 'name', 'x', 'y', 'z', 'size' lists
        subject: Subject label (e.g., '01', 'HC01')
        session: Session label (e.g., '01') or None
        bids_root: Root BIDS directory
        datatype: Data type directory (default 'meg')
    """
    import csv
    
    # Determine the MEG directory
    if session:
        meg_dir = bids_root / f"sub-{subject}" / f"ses-{session}" / datatype
    else:
        meg_dir = bids_root / f"sub-{subject}" / datatype
    
    meg_dir.mkdir(parents=True, exist_ok=True)
    
    # Build filename: sub-<label>[_ses-<label>]_electrodes.tsv
    fname_parts = [f"sub-{subject}"]
    if session:
        fname_parts.append(f"ses-{session}")
    fname_parts.append("electrodes.tsv")
    filename = "_".join(fname_parts)
    
    electrodes_file = meg_dir / filename
    
    # Write TSV file with proper formatting
    # BIDS required columns: name, x, y, z
    # Optional column: size
    with open(electrodes_file, 'w', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['name', 'x', 'y', 'z', 'size'],
            delimiter='\t',
            lineterminator='\n'
        )
        writer.writeheader()
        
        for i in range(len(eeg_data['name'])):
            writer.writerow({
                'name': eeg_data['name'][i],
                'x': f"{eeg_data['x'][i]:.6f}",
                'y': f"{eeg_data['y'][i]:.6f}",
                'z': f"{eeg_data['z'][i]:.6f}",
                'size': f"{eeg_data['size'][i]:.6f}"
            })
    
    logger.info(f"    → Created electrodes.tsv: {filename} ({len(eeg_data['name'])} EEG channels)")


def normalize_raw_info(raw: mne.io.BaseRaw) -> None:
    """Normalize raw.info fields for BIDS compatibility."""
    md = raw.info.get('meas_date')
    if isinstance(md, date) and not isinstance(md, datetime):
        raw.set_meas_date(datetime(md.year, md.month, md.day, tzinfo=timezone.utc))
    elif isinstance(md, datetime) and md.tzinfo is None:
        raw.set_meas_date(md.replace(tzinfo=timezone.utc))
    
    si = raw.info.get('subject_info')
    if isinstance(si, dict) and 'birthday' in si:
        si['birthday'] = None


def write_derivative_raw(raw: mne.io.BaseRaw, subject: str, session: Optional[str], task: str, run: Optional[int], processing: str, derivatives_root: Path, pipeline_name: str, pipeline_version: Optional[str], datatype: str, overwrite: bool = True) -> None:
    """Write processed raw to derivatives with BIDS naming.
    
    Args:
        derivatives_root: Root derivatives directory (e.g., derivatives/<dataset>_derivatives/)
    """
    deriv_root = derivatives_root / pipeline_name
    ensure_derivatives_description(deriv_root, pipeline_name, pipeline_version)
    
    # For multi-label processing (e.g., mc-ave), build filename manually to avoid BIDSPath validation issues
    if '-' in processing:
        # Build BIDS path manually for multi-label processing
        if session:
            subdir = deriv_root / f"sub-{subject}" / f"ses-{session}" / datatype
        else:
            subdir = deriv_root / f"sub-{subject}" / datatype
        
        subdir.mkdir(parents=True, exist_ok=True)
        
        # Build filename: sub-<label>_task-<label>[_run-<index>]_proc-<label>_meg.fif
        fname_parts = [f"sub-{subject}"]
        if session:
            fname_parts.append(f"ses-{session}")
        fname_parts.append(f"task-{task}")
        if run is not None:
            fname_parts.append(f"run-{run:02d}")
        fname_parts.append(f"proc-{processing}")
        fname_parts.append("meg.fif")
        
        filename = "_".join(fname_parts)
        filepath = subdir / filename
        
        raw.save(filepath, overwrite=overwrite)
        logger.info(f"    → Saved to derivatives: {filepath.relative_to(deriv_root)}")
    else:
        # Single-label processing - use BIDSPath
        bp = BIDSPath(
            subject=subject,
            session=session,
            task=task,
            run=run,
            processing=processing,
            datatype=datatype,
            root=deriv_root,
            suffix="meg",
            extension=".fif"
        )
        bp.fpath.parent.mkdir(parents=True, exist_ok=True)
        raw.save(bp.fpath, overwrite=overwrite)
        logger.info(f"    → Saved to derivatives: {bp.fpath.relative_to(deriv_root)}")


def convert_raw_file(fif_path: Path, subject: str, session: Optional[str], task: str, run: Optional[int], config: BIDSConfig, pattern_rule: Dict[str, Any], bids_root: Path, split_parts: Optional[List[Path]] = None) -> None:
    """Convert a single raw FIF file to BIDS."""
    datatype = config.get_datatype()
    allow_maxshield = config.get_option('allow_maxshield', True)
    
    run_str = f" (run {run})" if run is not None else ""
    split_str = f" ({len(split_parts)} parts)" if split_parts and len(split_parts) > 1 else ""
    logger.info(f"  ✓ Converting: {fif_path.name}{run_str}{split_str} → task={task}")
    
    try:
        # For split files, mne.io.read_raw_fif automatically handles reading all parts
        # when you pass the first file (the one without -1, -2, etc.)
        # MNE automatically detects and reads split files like file.fif, file-1.fif, file-2.fif
        raw = mne.io.read_raw_fif(fif_path, preload=False, allow_maxshield=allow_maxshield, verbose=False)
        # Check actual split structure from header
        actual_first_samps = getattr(raw, '_first_samps', None)
        if actual_first_samps is not None and len(actual_first_samps) > 1 and not split_str:
            logger.debug(f"    ({len(actual_first_samps)} parts detected from header)")
        normalize_raw_info(raw)
        
        bids_path = BIDSPath(
            subject=subject,
            session=session,
            task=task,
            run=run,
            datatype=datatype,
            root=bids_root
        )
        
        # write_raw_bids will automatically create split files if the data is too large
        write_raw_bids(raw, bids_path, overwrite=config.get_option('overwrite', True), verbose=False)
        
        if split_parts and len(split_parts) > 1:
            logger.debug(f"    → Saved BIDS file with {len(split_parts)} split parts")
        else:
            logger.debug(f"    → Saved BIDS file: {bids_path.basename}")
        
        conversion_stats.add_file(task, 'converted', fif_path.name)  # type: ignore[union-attr]
        
    except Exception as err:
        logger.error(f"  ✗ Conversion failed for {fif_path.name}: {err}")
        conversion_stats.add_file(task, 'failed', fif_path.name)  # type: ignore[union-attr]


def copy_derivative_file_with_proc(deriv_path: Path, subject: str, session: Optional[str], task: str, run: Optional[int], processing_label: str, derivatives_root: Path, acq: Optional[str] = None, pipeline_name: str = 'maxfilter') -> None:
    """
    Copy a derivative file to BIDS derivatives with proc label.

    Uses standard BIDS naming:
    - Single file: sub-<label>[_ses-<label>]_task-<label>[_acq-<label>][_run-<label>]_proc-<label>_meg.fif
    - Split part: sub-<label>[_ses-<label>]_task-<label>[_acq-<label>][_run-<label>]_split-<index>_proc-<label>_meg.fif

    Split index is determined internally from the source filename pattern.

    Args:
        derivatives_root: Root derivatives directory (e.g., derivatives/<dataset>_derivatives/)
        acq: Optional acquisition label
    """
    deriv_root = derivatives_root / pipeline_name
    ensure_derivatives_description(deriv_root, pipeline_name, None)

    if session:
        subdir = deriv_root / f"sub-{subject}" / f"ses-{session}" / 'meg'
    else:
        subdir = deriv_root / f"sub-{subject}" / 'meg'

    subdir.mkdir(parents=True, exist_ok=True)

    # Determine split index from source filename
    stem = deriv_path.stem
    split_index = None

    # Pattern 1: base-N_proc.fif -> split N+1 (e.g., -1 becomes split-02)
    split_before_match = re.search(r'^(.+)-(\d+)_[a-zA-Z]', stem)
    if split_before_match:
        split_index = int(split_before_match.group(2)) + 1
    else:
        # Pattern 2: base_proc-N.fif -> split N+1
        split_after_match = re.search(r'_[a-zA-Z][a-zA-Z_]*-(\d+)$', stem)
        if split_after_match:
            split_index = int(split_after_match.group(1)) + 1

    # Build filename
    fname_parts = [f"sub-{subject}"]
    if session:
        fname_parts.append(f"ses-{session}")
    fname_parts.append(f"task-{task}")
    if acq is not None:
        fname_parts.append(f"acq-{acq}")
    if run is not None:
        fname_parts.append(f"run-{run:02d}")
    if split_index is not None:
        fname_parts.append(f"split-{split_index:02d}")
    fname_parts.append(f"proc-{processing_label}")
    fname_parts.append("meg.fif")

    filename = "_".join(fname_parts)
    filepath = subdir / filename

    shutil.copy2(deriv_path, filepath)
    logger.info(f"    → Copied to derivatives: {filepath.relative_to(deriv_root)}")


def convert_derivative_file(deriv_path: Path, subject: str, session: Optional[str], task: str, run: Optional[int], config: BIDSConfig, processing_label: str, derivatives_root: Path, raw_files: List[Path], split_file_groups: Dict[Path, List[Path]]) -> None:
    """
    Convert MaxFilter derivative to BIDS derivatives directory.
    
    Strategy: Copy derivative with standard BIDS naming, inheriting split structure
    from corresponding raw file. If raw file is not found, skip with warning.
    
    Args:
        derivatives_root: Root derivatives directory (e.g., derivatives/<dataset>_derivatives/)
    """
    # Use get_pipeline_name() which includes version if specified
    pipeline_name = config.get_pipeline_name()
    if not pipeline_name:
        pipeline_name = 'maxfilter'
    
    logger.info(f"  ✓ Converting derivative: {deriv_path.name} → task={task} (proc-{processing_label})")
    
    try:
        # Find matching raw file and check if it's a split part
        raw_match_result = find_matching_raw_file(deriv_path.name, raw_files, split_file_groups)
        
        if raw_match_result is None:
            logger.warning(f"  ⚠ {deriv_path.name}: No corresponding raw file found (skipped)")
            return
        
        raw_path, split_idx = raw_match_result
        
        # Copy derivative with standard BIDS naming (including split index if applicable)
        copy_derivative_file_with_proc(deriv_path, subject, session, task, run, processing_label, derivatives_root, pipeline_name=pipeline_name)
        if conversion_stats is not None:
            conversion_stats.add_file(task, 'converted', deriv_path.name)
        
    except Exception as err:
        logger.error(f"  ✗ Conversion failed for {deriv_path.name}: {err}")
        if conversion_stats is not None:
            conversion_stats.add_file(task, 'failed', deriv_path.name)


def auto_detect_sessions(source_dir: Path) -> List[Tuple[str, Optional[str]]]:
    """
    Auto-detect sessions from date-named folders in source directory.
    
    Folder naming convention: Usually dates (YYYYMMDD, e.g., 250207)
    Returns: List of (folder_name, session_id) tuples
    - Single session: session_id = None
    - Multiple sessions: session_id = "01", "02", etc.
    """
    session_folders = sorted([p for p in source_dir.iterdir() if p.is_dir()])
    
    if not session_folders:
        return []
    
    if len(session_folders) == 1:
        return [(session_folders[0].name, None)]
    
    sessions = []
    for idx, folder in enumerate(session_folders, start=1):
        session_id = f"{idx:02d}"
        sessions.append((folder.name, session_id))
    
    return sessions


def load_participants_mapping(participants_file: Path) -> Dict[str, str]:
    """
    Load participants_complete.tsv and create mapping of meg_id -> bids_subject.
    
    Expected columns:
    - participant_id: BIDS subject (e.g., 'sub-01')
    - meg_id: MEG identifier (e.g., 'meg_1001', 'MEG-1001', or '1001')
    
    Returns: Dict mapping meg_id_digits -> bids_subject
    (e.g., '1001' -> 'sub-01')
    """
    mapping = {}
    with open(participants_file, 'r') as f:
        lines = f.readlines()
    
    if not lines:
        raise ValueError("Participants file is empty")
    
    # Parse header
    header = lines[0].strip().split('\t')
    try:
        participant_idx = header.index('participant_id')
        meg_id_idx = header.index('meg_id')
    except ValueError as e:
        raise ValueError(f"Missing required column in participants file: {e}")
    
    # Parse rows
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.strip().split('\t')
        if len(parts) <= max(participant_idx, meg_id_idx):
            continue
        
        bids_subject = parts[participant_idx].strip()
        meg_id_raw = parts[meg_id_idx].strip()
        
        # Extract 4 digits from meg_id (e.g., '1001' from 'meg_1001' or 'MEG-1001')
        digits = re.findall(r'\d{4}', meg_id_raw)
        if digits:
            meg_id = digits[0]
            mapping[meg_id] = bids_subject
            logger.debug(f"  Mapped meg_id {meg_id} ({meg_id_raw}) -> {bids_subject}")
    
    if not mapping:
        raise ValueError("No valid meg_id mappings found in participants file")
    
    return mapping


def auto_discover_meg_folders(source_dir: Path) -> List[str]:
    """
    Auto-discover all meg_XXXX folders in source directory.
    
    Returns: List of meg_id strings (e.g., ['1001', '1002'])
    """
    meg_folders = []
    for item in source_dir.iterdir():
        if item.is_dir() and item.name.lower().startswith('meg_'):
            # Extract digits from folder name
            digits = re.findall(r'\d{4}', item.name)
            if digits:
                meg_folders.append(digits[0])
    
    return sorted(meg_folders)


def lookup_meg_id_from_subject(bids_subject: str, participants_map: Dict[str, str]) -> Optional[str]:
    """
    Look up meg_id for a given BIDS subject.
    
    Args:
        bids_subject: BIDS subject identifier (e.g., 'sub-01')
        participants_map: Dict mapping meg_id -> bids_subject
    
    Returns: meg_id (4 digits) or None if not found
    """
    for meg_id, subject in participants_map.items():
        if subject == bids_subject or subject == f"sub-{bids_subject}":
            return meg_id
    return None


def lookup_subject_from_meg_id(meg_id: str, participants_map: Dict[str, str]) -> Optional[str]:
    """
    Look up BIDS subject for a given meg_id.
    
    Args:
        meg_id: MEG ID (4 digits)
        participants_map: Dict mapping meg_id -> bids_subject
    
    Returns: BIDS subject (e.g., 'sub-01') or None if not found
    """
    return participants_map.get(meg_id)


def normalize_subject_input(subject_input: str, participants_map: Dict[str, str]) -> Optional[str]:
    """
    Normalize subject input to BIDS subject format.
    
    Accepts three input formats:
    1. BIDS subject: 'sub-HC01' → 'sub-HC01'
    2. Subject label: 'HC01' → 'sub-HC01'
    3. MEG ID (4 digits): '2473' → 'sub-HC01' (via participants lookup)
    
    Args:
        subject_input: Subject identifier in any of the three formats
        participants_map: Dict mapping meg_id -> bids_subject
    
    Returns: 
        BIDS subject (e.g., 'sub-HC01') or None if not found
    """
    # Check if input is a 4-digit meg_id
    if subject_input.isdigit() and len(subject_input) == 4:
        # Treat as meg_id, look it up in participants file
        return lookup_subject_from_meg_id(subject_input, participants_map)
    
    # Otherwise treat as BIDS subject label
    if subject_input.startswith('sub-'):
        return subject_input
    else:
        return f"sub-{subject_input}"

def print_directory_tree(directory: Path, prefix: str = "", max_depth: int = 3, current_depth: int = 0) -> List[str]:
    """Generate a tree structure of the directory."""
    if current_depth >= max_depth:
        return []
    
    lines = []
    try:
        items = sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        
        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            current_prefix = "└── " if is_last else "├── "
            lines.append(f"{prefix}{current_prefix}{item.name}")
            
            if item.is_dir() and current_depth < max_depth - 1:
                extension = "    " if is_last else "│   "
                lines.extend(print_directory_tree(item, prefix + extension, max_depth, current_depth + 1))
    except PermissionError:
        pass
    
    return lines


def _extract_run_number(filename: str) -> Optional[str]:
    """
    Extract run number from filename.
    Handles patterns like: _run5, _run-5, _t1_2, _t2_1, etc.
    
    NOTE: Does NOT extract numbers from split file patterns (e.g., -1.fif, -2.fif)
    which indicate file splits, not run numbers.
    """
    # Try explicit _run patterns first
    run_match = re.search(r'_run[_-]?(\d+)', filename, re.IGNORECASE)
    if run_match:
        return run_match.group(1)
    
    # Try trailing numeric patterns like _t1_2 (task 1, run 2) or _1_2
    # Match last two numeric components separated by underscore
    parts_match = re.search(r'_(\d+)_(\d+)\.fif$', filename, re.IGNORECASE)
    if parts_match:
        return parts_match.group(2)  # Return second number as run
    
    # Try single trailing number like _1.fif or _2.fif
    # BUT: exclude split file patterns like -1.fif, -2.fif (those are file splits, not runs)
    single_match = re.search(r'_(\d+)\.fif$', filename, re.IGNORECASE)
    if single_match:
        # Make sure it's not a split pattern (hyphen before number)
        if not re.search(r'-\d+\.fif$', filename, re.IGNORECASE):
            return single_match.group(1)
    
    return None


def check_config_validity(config: BIDSConfig, source_dir: Path, file_patterns: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Check if config is valid and preview how files would be processed.
    
    Returns: (is_valid, list_of_issues)
    """
    issues = []
    
    # Check file patterns exist and are valid
    if not file_patterns:
        issues.append("ERROR: No file patterns defined in config")
        return False, issues
    
    # Check each pattern
    seen_patterns = set()
    for idx, pattern in enumerate(file_patterns, 1):
        pat_str = pattern.get('pattern', '')
        
        if not pat_str:
            issues.append(f"ERROR: Pattern #{idx} has no 'pattern' field")
            continue
        
        if 'task' not in pattern:
            issues.append(f"WARNING: Pattern #{idx} ({pat_str}) has no 'task' field")
        
        if pat_str in seen_patterns:
            issues.append(f"WARNING: Pattern #{idx} ({pat_str}) is duplicate")
        seen_patterns.add(pat_str)
    
    # Preview file matching
    logger.info("\n" + "─"*70)
    logger.info("CONFIG CHECK: File Preview")
    logger.info("─"*70)
    
    sessions = auto_detect_sessions(source_dir)
    if not sessions:
        issues.append(f"ERROR: No session folders found in {source_dir}")
        return False, issues
    
    for folder_name, session_id in sessions:
        sess_dir = source_dir / folder_name
        
        # Display session with ID if multiple sessions
        if session_id:
            logger.info(f"\nSession: {folder_name} → ses-{session_id}")
        else:
            logger.info(f"\nSession: {folder_name}")
        
        all_fif_files = sorted(sess_dir.glob("*.fif"))
        
        if not all_fif_files:
            logger.info("  No FIF files found")
            continue
        
        # Detect split files
        split_file_groups = detect_split_files(all_fif_files)
        
        # Preview ALL files (no truncation)
        for fif_file in all_fif_files:
            # Skip if this file is a split part (will be shown with its primary file)
            is_split_part = any(fif_file in parts[1:] for parts in split_file_groups.values())
            if is_split_part:
                continue
            
            deriv_info = extract_derivative_info(fif_file.name)
            
            if deriv_info:
                base_filename, proc_label = deriv_info
                # Check if this derivative has splits
                if fif_file in split_file_groups:
                    num_splits = len(split_file_groups[fif_file])
                    logger.info(f"  {fif_file.name} → [DERIVATIVE: proc-{proc_label}] ({num_splits} splits)")
                else:
                    logger.info(f"  {fif_file.name} → [DERIVATIVE: proc-{proc_label}]")
            else:
                # Try to match as raw file
                matches = find_matching_patterns(fif_file.name, file_patterns)
                if len(matches) == 0:
                    logger.warning(f"  {fif_file.name} → [NO MATCH - would be skipped]")
                    issues.append(f"WARNING: {fif_file.name} doesn't match any pattern")
                elif len(matches) == 1:
                    task = matches[0][1].get('task', 'unknown')
                    # Extract run number from filename if available
                    run_num = _extract_run_number(fif_file.name)
                    
                    # Check if this file has splits
                    split_info = ""
                    if fif_file in split_file_groups:
                        num_splits = len(split_file_groups[fif_file])
                        split_info = f" ({num_splits} splits)"
                    
                    if run_num:
                        logger.info(f"  {fif_file.name} → task-{task} run-{run_num}{split_info}")
                    else:
                        logger.info(f"  {fif_file.name} → task-{task}{split_info}")
                else:
                    tasks = set(m[1].get('task', 'unknown') for m in matches)
                    if len(tasks) > 1:
                        logger.error(f"  {fif_file.name} → [AMBIGUOUS - multiple tasks]")
                        issues.append(f"ERROR: {fif_file.name} matches multiple patterns with different tasks")
                    else:
                        task = list(tasks)[0]
                        # Extract run number from filename if available
                        run_num = _extract_run_number(fif_file.name)
                        
                        # Check if this file has splits
                        split_info = ""
                        if fif_file in split_file_groups:
                            num_splits = len(split_file_groups[fif_file])
                            split_info = f" ({num_splits} splits)"
                        
                        if run_num:
                            logger.info(f"  {fif_file.name} → task-{task} run-{run_num}{split_info} (matches {len(matches)} patterns)")
                        else:
                            logger.info(f"  {fif_file.name} → task-{task}{split_info} (matches {len(matches)} patterns)")
    
    logger.info("─"*70)
    
    # Summary
    logger.info("\n" + "─"*70)
    logger.info("CONFIG CHECK SUMMARY")
    logger.info("─"*70)
    
    errors = [i for i in issues if i.startswith("ERROR")]
    warnings = [i for i in issues if i.startswith("WARNING")]
    
    if errors:
        logger.error(f"\n✗ Found {len(errors)} error(s):")
        for error in errors:
            logger.error(f"  {error}")
        return False, issues
    
    if warnings:
        logger.warning(f"\n⚠ Found {len(warnings)} warning(s):")
        for warning in warnings:
            logger.warning(f"  {warning}")
        logger.info("\nConfig is usable but review warnings above")
        return True, issues
    
    logger.info("\n✓ Config is valid - no errors or warnings found")
    logger.info("You can now run without --check-config to convert files")
    
    return True, issues


def run_check_config(args) -> int:
    """Run config check mode and exit (no conversion)."""
    logger.info("\n" + "═"*70)
    logger.info("MEG2BIDS CONFIG CHECK")
    logger.info("═"*70)
    logger.info(f"Dataset:       {args.dataset}")
    logger.info(f"Config:        {args.config}")
    logger.info(f"MEG data root: {args.source_meg}")
    logger.info(f"Participants:  {args.participants_file}")
    logger.info("═"*70)
    
    try:
        config = BIDSConfig(args.config)
    except Exception as err:
        logger.error(f"✗ Failed to load config: {err}")
        return 1
    
    # Load participants mapping for multi-subject preview
    try:
        participants_map = load_participants_mapping(args.participants_file)
    except Exception as err:
        logger.error(f"✗ Failed to load participants file: {err}")
        return 1
    
    file_patterns = config.get_file_patterns()
    meg_folders = auto_discover_meg_folders(args.source_meg)
    if not meg_folders:
        logger.warning("⚠ No meg_XXXX folders found in MEG data directory")
        return 1
    
    # Determine subjects to preview
    subjects_to_process = []
    if args.subject:
        subject_arg = normalize_subject_input(args.subject, participants_map)
        if not subject_arg:
            logger.error(f"✗ Subject {args.subject} not found in participants file")
            return 1
        meg_id = lookup_meg_id_from_subject(subject_arg, participants_map)
        if not meg_id:
            logger.error(f"✗ BIDS subject {subject_arg} not found in participants file")
            return 1
        if meg_id not in meg_folders:
            logger.error(f"✗ MEG folder meg_{meg_id} not found in MEG data directory")
            return 1
        subjects_to_process = [(subject_arg, meg_id)]
    else:
        for meg_id in meg_folders:
            subject = lookup_subject_from_meg_id(meg_id, participants_map)
            if subject:
                subjects_to_process.append((subject, meg_id))
            else:
                logger.warning(f"⚠ meg_{meg_id} not found in participants file (skipped)")
    
    if not subjects_to_process:
        logger.warning("⚠ No subjects to process")
        return 1
    
    # If a specific subject is requested, keep detailed per-file preview
    if args.subject:
        overall_valid = True
        overall_issues: List[str] = []
        for bids_subject, meg_id in subjects_to_process:
            meg_folder = args.source_meg / f"meg_{meg_id}"
            logger.info("\n" + "─"*70)
            logger.info(f"Subject: {bids_subject} (meg_{meg_id})")
            logger.info("─"*70)
            is_valid, issues = check_config_validity(config, meg_folder, file_patterns)
            overall_issues.extend(issues)
            if not is_valid:
                overall_valid = False

        logger.info("\n" + "═"*70)
        if overall_valid and not [i for i in overall_issues if i.startswith("WARNING")]:
            logger.info("✓ Config check PASSED - ready to convert")
        elif overall_valid:
            logger.info("⚠ Config check PASSED with warnings")
        else:
            logger.info("✗ Config check FAILED - fix issues before converting")
        logger.info("═"*70 + "\n")
        return 0 if overall_valid else 1

    # Summary mode (no --subject): build and print compact, complete report
    def build_subject_summary(meg_id: str, bids_subject: str) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            'bids_subject': bids_subject,
            'meg_id': meg_id,
            'sessions': 0,
            'raw_count': 0,
            'deriv_count': 0,
            'task_counts': defaultdict(int),
            'unmatched_files': [],
            'ambiguous_files': [],
            'unknown_task_files': [],
        }
        meg_folder = args.source_meg / f"meg_{meg_id}"
        sessions = auto_detect_sessions(meg_folder)
        summary['sessions'] = len(sessions)
        for folder_name, session_id in sessions:
            sess_dir = meg_folder / folder_name
            all_fif_files = sorted(sess_dir.glob("*.fif"))
            raw_files, derivative_files = [], []
            for f in all_fif_files:
                if extract_derivative_info(f.name) is None:
                    raw_files.append(f)
                else:
                    derivative_files.append(f)
            summary['raw_count'] += len(raw_files)
            summary['deriv_count'] += len(derivative_files)

            split_groups = detect_split_files(raw_files)
            split_parts = set()
            for primary, parts in split_groups.items():
                split_parts.update(parts[1:])
            primary_raw_files = [f for f in raw_files if f not in split_parts]

            for f in primary_raw_files:
                matches = find_matching_patterns(f.name, file_patterns)
                if len(matches) == 0:
                    summary['unmatched_files'].append(str(f.relative_to(meg_folder)))
                elif len(matches) == 1:
                    task = matches[0][1].get('task', 'unknown')
                    summary['task_counts'][task] += 1
                else:
                    tasks = set(rule.get('task', 'unknown') for _, rule in matches)
                    if len(tasks) > 1:
                        summary['ambiguous_files'].append({
                            'file': str(f.relative_to(meg_folder)),
                            'patterns': [m[1].get('pattern', 'unknown') for m in matches],
                            'tasks': list(tasks)
                        })
                    else:
                        task = list(tasks)[0]
                        summary['task_counts'][task] += 1

            for df in derivative_files:
                deriv_info = extract_derivative_info(df.name)
                if not deriv_info:
                    continue
                base_filename, _ = deriv_info
                raw_match = find_matching_raw_file(df.name, raw_files, split_groups)
                task = None
                if raw_match and raw_match[0].name in [f.name for f in primary_raw_files]:
                    matches = find_matching_patterns(raw_match[0].name, file_patterns)
                    if matches:
                        task = matches[0][1].get('task', None)
                if task is None:
                    task = infer_task_from_basename(base_filename, file_patterns)
                if task is None:
                    summary['unknown_task_files'].append(str(df.relative_to(meg_folder)))
        return summary

    subject_summaries: List[Dict[str, Any]] = []
    mapped_subjects = 0
    for meg_id in meg_folders:
        bids_subject = lookup_subject_from_meg_id(meg_id, participants_map)
        if bids_subject:
            mapped_subjects += 1
            subject_summaries.append(build_subject_summary(meg_id, bids_subject))

    participants_meg_ids = list(participants_map.keys())
    participants_without_folder = [m for m in participants_meg_ids if m not in meg_folders]

    total_sessions = sum(s['sessions'] for s in subject_summaries)
    total_raw = sum(s['raw_count'] for s in subject_summaries)
    total_deriv = sum(s['deriv_count'] for s in subject_summaries)
    total_unmatched = sum(len(s['unmatched_files']) for s in subject_summaries)
    total_ambiguous = sum(len(s['ambiguous_files']) for s in subject_summaries)

    logger.info("\n" + "═"*70)
    logger.info("DATASET SUMMARY")
    logger.info("═"*70)
    logger.info(f"  Subjects discovered: {len(meg_folders)}")
    logger.info(f"  Subjects mapped:     {mapped_subjects}")
    logger.info(f"  Sessions:            {total_sessions}")
    logger.info(f"  Files:               raw={total_raw}, derivatives={total_deriv}")
    logger.info(f"  Issues:              unmatched={total_unmatched}, ambiguous={total_ambiguous}")

    logger.info("\n" + "─"*70)
    logger.info("MAPPING (meg_XXXX → sub-XX)")
    logger.info("─"*70)
    for meg_id in sorted(meg_folders):
        subj = lookup_subject_from_meg_id(meg_id, participants_map)
        if subj:
            logger.info(f"  meg_{meg_id} → {subj} ✓")
        else:
            logger.info(f"  meg_{meg_id} → (no participants entry) ✗")
    if participants_without_folder:
        logger.info("\nParticipants entries without matching meg folder:")
        for mid in sorted(participants_without_folder):
            logger.info(f"  {participants_map[mid]} → meg_{mid} ✗ (missing folder)")

    logger.info("\n" + "─"*70)
    logger.info("SUBJECTS (sessions, raw, derivatives, unmatched, ambiguous)")
    logger.info("─"*70)
    for s in sorted(subject_summaries, key=lambda x: x['bids_subject']):
        logger.info(f"  {s['bids_subject']} (meg_{s['meg_id']}): sessions={s['sessions']} raw={s['raw_count']} deriv={s['deriv_count']} unmatched={len(s['unmatched_files'])} ambiguous={len(s['ambiguous_files'])}")

    logger.info("\n" + "─"*70)
    logger.info("TASK MATCH (per subject)")
    logger.info("─"*70)
    for s in sorted(subject_summaries, key=lambda x: x['bids_subject']):
        tc = s['task_counts']
        tasks_str = ", ".join([f"{t}={tc[t]}" for t in sorted(tc.keys())]) if tc else "none"
        unknown_deriv = len(s['unknown_task_files'])
        logger.info(f"  {s['bids_subject']}: {tasks_str} | unknown={unknown_deriv}")

    logger.info("\n" + "─"*70)
    logger.info("ISSUES (per subject)")
    logger.info("─"*70)
    for s in sorted(subject_summaries, key=lambda x: x['bids_subject']):
        if s['unmatched_files'] or s['ambiguous_files'] or s['unknown_task_files']:
            logger.info(f"  {s['bids_subject']}:")
            if s['unmatched_files']:
                logger.info("    Unmatched files:")
                for f in s['unmatched_files']:
                    logger.info(f"      - {f}")
            if s['ambiguous_files']:
                logger.info("    Ambiguous patterns:")
                for entry in s['ambiguous_files']:
                    logger.info(f"      - {entry['file']} (tasks={','.join(entry['tasks'])}, patterns={','.join(entry['patterns'])})")
            if s['unknown_task_files']:
                logger.info("    Derivatives with unknown task:")
                for f in s['unknown_task_files']:
                    logger.info(f"      - {f}")

    logger.info("\n" + "═"*70)
    logger.info("✓ Config check summary complete")
    logger.info("═"*70 + "\n")
    has_errors = (total_unmatched > 0) or (total_ambiguous > 0)
    return 1 if has_errors else 0


def run_bids_validator(bids_root: Path) -> None:
    """Run BIDS validator if available."""
    validator = shutil.which("bids-validator")
    if validator:
        cmd = [validator, str(bids_root)]
    else:
        npx = shutil.which("npx")
        if npx:
            cmd = [npx, "--yes", "bids-validator", str(bids_root)]
        else:
            logger.warning("BIDS Validator not found. Install: npm install -g bids-validator")
            return
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        logger.info(proc.stdout)
        if proc.returncode == 0:
            logger.info("✓ BIDS validation passed")
        else:
            logger.warning("⚠ BIDS validation reported issues")
    except Exception as err:
        logger.warning(f"Could not run validator: {err}")


def main() -> int:
    global logger, conversion_stats
    
    logger = setup_logging()
    conversion_stats = ConversionStats()
    
    parser = argparse.ArgumentParser(
        description="Convert MEG FIF to BIDS with automatic MaxFilter derivative handling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
USAGE EXAMPLES:
  python meg2bids.py --dataset mystudy --check-config
  python meg2bids.py --dataset mystudy
  python meg2bids.py --dataset mystudy --subject sub-01 -b

DIRECTORY STRUCTURE:
  sourcedata/
    <dataset>-sourcedata/
      meg/
        meg_XXXX/
          YYMMDD/
            *.fif files
      configs/
        meg2bids.json
      participants_complete.tsv
  
  rawdata/
    <dataset>-rawdata/
      sub-XX/
        meg/
  
  derivatives/
    <dataset>-derivatives/
        maxfilter_v2.2.20/
          sub-XX/

WORKFLOW:
  1. Organize MEG data in sourcedata/<dataset>-sourcedata/meg/
  2. Place config in sourcedata/<dataset>-sourcedata/configs/meg2bids.json
  3. Run --check-config to validate configuration
  4. Convert all subjects or use --subject for single subject conversion
  5. Raw BIDS output: rawdata/<dataset>-rawdata/, Derivatives: derivatives/<dataset>-derivatives/

CALIBRATION FILES:
  - Session date extracted from folder name (YYMMDD format, e.g., 250207)
  - Selects calibration file with date ≤ session date
  - Triux: sss_cal_XXXX_*.dat, VectorView: sss_cal_vectorview.dat

See README_MEG2BIDS.md for complete documentation.
        """
    )
    parser.add_argument("--dataset", type=str, required=True,
                        help="Dataset name (e.g., 'mystudy'). Constructs paths automatically from this name")
    parser.add_argument("--subject", type=str, default=None,
                        help="Process only this subject. Accepts three formats: (1) BIDS subject 'sub-HC01', (2) subject label 'HC01', or (3) meg_id '2473'. If not provided, process all discovered meg_XXXX folders")
    parser.add_argument("-b", "--validate", action="store_true",
                        help="Run BIDS validation after conversion")
    parser.add_argument("--check-config", action="store_true",
                        help="Only validate config and preview how files would be processed (no conversion)")
    args = parser.parse_args()
    
    # Construct paths from dataset name
    # All operations are in current working directory (expected to be project root)
    cwd = Path.cwd()
    args.source_root = cwd / "sourcedata" / f"{args.dataset}-sourcedata"
    args.source_meg = args.source_root / "meg"
    args.config = args.source_root / "configs" / "meg2bids.json"
    args.participants_file = args.source_root / "participants_complete.tsv"
    args.rawdata_root = cwd / "rawdata" / f"{args.dataset}-rawdata"
    args.derivatives_root = cwd / "derivatives" / f"{args.dataset}-derivatives"
    
    # Validate paths exist
    if not args.source_root.exists():
        logger.error(f"✗ Dataset directory not found: {args.source_root}")
        return 1
    
    if not args.source_meg.exists():
        logger.error(f"✗ MEG data directory not found: {args.source_meg}")
        return 1
    
    if not args.config.exists():
        logger.error(f"✗ Config file not found: {args.config}")
        return 1
    
    if not args.participants_file.exists():
        logger.error(f"✗ Participants file not found: {args.participants_file}")
        return 1
    
    # If only checking configuration, stop before any conversion work
    if args.check_config:
        return run_check_config(args)

    try:
        config = BIDSConfig(args.config)
    except Exception as err:
        logger.error(f"✗ Failed to load config: {err}")
        return 1
    
    # Load participants mapping
    try:
        participants_map = load_participants_mapping(args.participants_file)
    except Exception as err:
        logger.error(f"✗ Failed to load participants file: {err}")
        return 1
    
    source_dir = args.source_meg
    bids_root = args.rawdata_root
    bids_root.mkdir(parents=True, exist_ok=True)
    
    # Discover MEG folders
    meg_folders = auto_discover_meg_folders(source_dir)
    if not meg_folders:
        logger.warning("⚠ No meg_XXXX folders found in source directory")
        return 1
    
    # Determine which subjects to process
    subjects_to_process = []
    if args.subject:
        # User specified a subject - normalize and look up meg_id
        subject_arg = normalize_subject_input(args.subject, participants_map)
        if not subject_arg:
            logger.error(f"✗ Subject {args.subject} not found in participants file")
            return 1
        meg_id = lookup_meg_id_from_subject(subject_arg, participants_map)
        if not meg_id:
            logger.error(f"✗ BIDS subject {subject_arg} not found in participants file")
            return 1
        if meg_id not in meg_folders:
            logger.error(f"✗ MEG folder meg_{meg_id} not found in MEG data directory")
            return 1
        subjects_to_process = [(subject_arg, meg_id)]
    else:
        # Auto-discover: process all found meg folders
        for meg_id in meg_folders:
            subject = lookup_subject_from_meg_id(meg_id, participants_map)
            if subject:
                subjects_to_process.append((subject, meg_id))
            else:
                logger.warning(f"⚠ meg_{meg_id} not found in participants file (skipped)")
    
    if not subjects_to_process:
        logger.warning("⚠ No subjects to process")
        return 1
    
    logger.info(f"\n{'═'*70}")
    logger.info("MEG to BIDS Conversion")
    logger.info(f"{'═'*70}")
    logger.info(f"Dataset:            {args.dataset}")
    logger.info(f"Source MEG:         {source_dir}")
    logger.info(f"BIDS rawdata:       {bids_root}")
    logger.info(f"Derivatives:        {args.derivatives_root}")
    logger.info(f"Config:             {args.config}")
    logger.info(f"Participants file:  {args.participants_file}")
    logger.info(f"Subjects to process: {len(subjects_to_process)}")
    logger.info(f"{'═'*70}")
    
    file_patterns = config.get_file_patterns()
    
    created_subject_roots: Set[Path] = set()

    for bids_subject, meg_id in subjects_to_process:
        meg_folder = source_dir / f"meg_{meg_id}"
        
        # Safety: skip if MEG data already exists in BIDS for this subject
        existing_meg_dirs: List[Path] = []
        subject_root = bids_root / bids_subject
        if subject_root.exists():
            for meg_dir in subject_root.glob("**/meg"):
                if meg_dir.is_dir() and any(meg_dir.iterdir()):
                    existing_meg_dirs.append(meg_dir)
        if existing_meg_dirs:
            logger.info("")
            logger.warning(f"⚠ Skipping {bids_subject}: existing MEG BIDS data found (no overwrite).")
            for d in existing_meg_dirs:
                logger.info(f"  Existing: {d.relative_to(bids_root)}")
            logger.info("─"*70)
            conversion_stats.subjects_skipped += 1
            continue

        logger.info(f"\n{'='*70}")
        logger.info(f"Processing: {bids_subject} (meg_{meg_id})")
        logger.info(f"{'='*70}")
        conversion_stats.subjects_processed += 1
        
        # Auto-detect sessions within this meg folder
        sessions = auto_detect_sessions(meg_folder)
        
        if not sessions:
            if has_fif_files_in_folder(meg_folder):
                logger.info(f"  ℹ Found FIF files directly in folder (legacy format without sessions)")
                sessions = [(meg_folder.name, None)]
            else:
                logger.warning(f"  ⚠ No session directories found in {meg_folder}")
                continue
        
        for folder_name, session_id in sessions:
            if folder_name == meg_folder.name and session_id is None:
                sess_dir = meg_folder
            else:
                sess_dir = meg_folder / folder_name
            
            logger.info(f"\n{'─'*70}")
            if session_id:
                logger.info(f"SESSION: {folder_name} (ses-{session_id})")
            else:
                logger.info(f"SESSION: {folder_name}")
            logger.info(f"{'─'*70}")
            
            all_fif_files = sorted(sess_dir.glob("*.fif"))
            if not all_fif_files:
                logger.warning("  ⚠ No FIF files found in this session")
                continue
        
            # Separate raw from derivatives
            raw_files = []
            derivative_files = []
            
            for fif_file in all_fif_files:
                if extract_derivative_info(fif_file.name) is None:
                    raw_files.append(fif_file)  # Raw file (no MaxFilter suffix detected)
                else:
                    derivative_files.append(fif_file)  # Derivative (MaxFilter suffix detected)
            
            logger.info(f"Found {len(all_fif_files)} FIF file(s) ({len(raw_files)} raw, {len(derivative_files)} derivatives)")
            
            # Apply file exclusion patterns
            exclude_patterns = config.get_exclude_patterns()
            if exclude_patterns:
                excluded_raw = []
                kept_raw = []
                for f in raw_files:
                    matched = should_exclude_file(f.name, exclude_patterns)
                    if matched:
                        logger.info(f"  ⊗ Excluded (pattern: {matched}): {f.name}")
                        conversion_stats.add_file('excluded', 'excluded', f.name)
                        excluded_raw.append(f)
                    else:
                        kept_raw.append(f)
                if excluded_raw:
                    logger.info(f"  Excluded {len(excluded_raw)} raw file(s)")
                raw_files = kept_raw

                excluded_deriv = []
                kept_deriv = []
                for f in derivative_files:
                    matched = should_exclude_file(f.name, exclude_patterns)
                    if matched:
                        logger.info(f"  ⊗ Excluded (pattern: {matched}): {f.name}")
                        conversion_stats.add_file('excluded', 'excluded', f.name)
                        excluded_deriv.append(f)
                    else:
                        kept_deriv.append(f)
                if excluded_deriv:
                    logger.info(f"  Excluded {len(excluded_deriv)} derivative file(s)")
                derivative_files = kept_deriv
            
            # Deduplicate raw files based on FIF header fingerprint
            raw_files, split_group_count = identify_primary_files(raw_files, interactive=False)
            if split_group_count > 0:
                logger.info(f"  ℹ Identified {split_group_count} split file group(s) from header deduplication")
            
            # Detect and copy calibration files
            if config.get_calibration_auto_detect():
                logger.info("\nDetecting Neuromag calibration files...")
                # Get calibration system and maxfilter root from config
                calibration_system = config.get_calibration_system()
                meg_maxfilter_root = config.get_maxfilter_root()
                if meg_maxfilter_root:
                    calib_files = detect_calibration_files(meg_folder, folder_name, meg_maxfilter_root, calibration_system, raw_fif_files=all_fif_files)
                else:
                    logger.warning("  ⚠ maxfilter_root not found in config or directory does not exist")
                    calib_files: Dict[str, Optional[Path]] = {'crosstalk': None, 'calibration': None}
                
                if calib_files['crosstalk'] or calib_files['calibration']:
                    copy_calibration_files(calib_files, bids_subject.replace('sub-', ''), session_id, bids_root, config.get_datatype())
                else:
                    logger.info("  ℹ No calibration files found")
        
            # Detect split files
            split_file_groups = detect_split_files(raw_files)
            if split_file_groups:
                logger.info(f"\nDetected {len(split_file_groups)} split file group(s)")
            
            # Get list of primary files only (exclude split parts)
            # Split parts will be processed with their primary file
            split_parts = set()
            for primary_file, parts in split_file_groups.items():
                # Add all parts except the first one (which is the primary)
                split_parts.update(parts[1:])
            
            # Filter raw_files to exclude split parts for validation
            primary_raw_files = [f for f in raw_files if f not in split_parts]
            
            try:
                if not primary_raw_files:
                    logger.warning("  ⚠ No raw FIF files found (skipping session)")
                    continue
            
                file_pattern_map = validate_all_files(primary_raw_files, file_patterns)
                task_files = group_files_by_task(file_pattern_map, meg_id=meg_id)
                file_mapping = assign_run_numbers(task_files)
                
                # Print conversion plan
                logger.info("\n" + "─"*70)
                logger.info("CONVERSION PLAN")
                logger.info("─"*70)
                
                for fif_path in primary_raw_files:
                    if fif_path not in file_mapping:
                        logger.info(f"  ⊘ {fif_path.name}: No matching pattern (skipped)")
                        continue
                    
                    task, run, _ = file_mapping[fif_path]
                    run_str = f" run-{run:02d}" if run else ""
                    logger.info(f"  → {fif_path.name}: task-{task}{run_str} (raw → BIDS)")
                
                for deriv_path in derivative_files:
                    deriv_info = extract_derivative_info(deriv_path.name)
                    if not deriv_info:
                        continue
                    
                    base_filename, proc_label = deriv_info
                    raw_match_result = find_matching_raw_file(deriv_path.name, raw_files, split_file_groups)
                    
                    task = None
                    run = None
                    
                    if raw_match_result and raw_match_result[0] in file_mapping:
                        # Derivative has matching raw file - use its metadata
                        task, run, _ = file_mapping[raw_match_result[0]]
                    else:
                        # No matching raw file - try to infer task from base filename
                        task = infer_task_from_basename(base_filename, file_patterns)
                        if task:
                            logger.debug(f"  Inferred task='{task}' for {deriv_path.name} from base filename {base_filename}")
                    
                    if task and raw_match_result:
                        run_str = f" run-{run:02d}" if run else ""
                        split_str = ""
                        if raw_match_result:
                            split_idx = raw_match_result[1]
                            if split_idx is not None:
                                split_str = f" split-{split_idx+1:02d}"
                        logger.info(f"  → {deriv_path.name}: task-{task}{run_str}{split_str} (MaxFilter → derivatives/proc-{proc_label})")
                
                logger.info("─"*70)
                logger.info("Starting conversion...\n")
                
                # Track EEG channels across all session files for electrodes.tsv
                session_eeg_data = None
                eeg_checked = False
                
                # Convert raw files (only primary files, split parts handled automatically)
                for fif_path in primary_raw_files:
                    if fif_path not in file_mapping:
                        logger.debug(f"  ⊘ No matching pattern for: {fif_path.name}")
                        continue
                    
                    task, run, pattern_rule = file_mapping[fif_path]
                    split_parts_for_file = split_file_groups.get(fif_path, None)
                    
                    # Convert the raw file
                    convert_raw_file(fif_path, bids_subject.replace('sub-', ''), session_id, task, run, config, pattern_rule, bids_root, split_parts_for_file)
                    
                    # Check for EEG only once per session (from first file)
                    if not eeg_checked:
                        try:
                            raw = mne.io.read_raw_fif(fif_path, preload=False, allow_maxshield=config.get_option('allow_maxshield', True), verbose=False)
                            session_eeg_data = extract_eeg_information(raw)
                            eeg_checked = True
                        except Exception as e:
                            logger.debug(f"  Could not check EEG in {fif_path.name}: {e}")
                            eeg_checked = True
                
                # Write electrodes.tsv once per session if EEG was detected
                if session_eeg_data is not None:
                    write_electrodes_tsv(session_eeg_data, bids_subject.replace('sub-', ''), session_id, bids_root, config.get_datatype())
                
                # Convert derivative files (only if pipeline is configured)
                if config.get_pipeline_name():
                    logger.info("\n" + "─"*70)
                    logger.info("Processing MaxFilter derivatives...")
                    logger.info("─"*70)
                    
                    if not derivative_files:
                        logger.info("  ℹ No MaxFilter derivatives found")
                    
                    pipeline_name = config.get_pipeline_name() or 'maxfilter'
                    
                    # Detect split groups among derivatives
                    deriv_split_groups, deriv_split_parts = detect_derivative_split_files(derivative_files)
                    
                    # Process primary derivative files (non-split-part files)
                    primary_deriv_files = [f for f in derivative_files if f not in deriv_split_parts]
                    
                    for deriv_path in primary_deriv_files:
                        deriv_info = extract_derivative_info(deriv_path.name)
                        if not deriv_info:
                            continue
                        
                        # Critical fix (f65e434): match using base_filename, not deriv_path.name
                        base_filename, proc_label = deriv_info
                        matched_pattern = match_file_pattern(base_filename, file_patterns)
                        
                        task = None
                        run = None
                        acq = None
                        
                        if matched_pattern:
                            task = matched_pattern.get('task')
                            run_extraction = matched_pattern.get('run_extraction', 'last_digits')
                            run = extract_run_from_filename(base_filename, run_extraction, meg_id=meg_id)
                            # Extract acq: static string or dynamic method
                            acq_config = matched_pattern.get('acq')
                            if acq_config and acq_config not in ('last_digits', 'first_digits'):
                                acq = acq_config
                            elif acq_config in ('last_digits', 'first_digits'):
                                acq = extract_run_from_filename(base_filename, acq_config, meg_id=meg_id)
                                if acq is not None:
                                    acq = str(acq)
                        else:
                            task = infer_task_from_basename(base_filename, file_patterns)
                            if task:
                                logger.debug(f"  Inferred task='{task}' for {deriv_path.name} from base filename {base_filename}")
                        
                        if task:
                            logger.info(f"  ✓ Converting derivative: {deriv_path.name} → task={task} (proc-{proc_label})")
                            copy_derivative_file_with_proc(
                                deriv_path, bids_subject.replace('sub-', ''), session_id, task, run,
                                proc_label, args.derivatives_root, acq=acq, pipeline_name=pipeline_name
                            )
                            conversion_stats.add_file('success', task, deriv_path.name)
                        else:
                            logger.warning(f"  ✗ {deriv_path.name}: Could not determine task (skipped)")
                            conversion_stats.add_file('skipped', 'unknown', deriv_path.name)
                    
                    # Process split derivative groups
                    for primary_split_path, split_files in deriv_split_groups.items():
                        split_deriv_info = extract_derivative_info(primary_split_path.name)
                        if not split_deriv_info:
                            continue
                        split_base_filename, proc_label = split_deriv_info
                        # Strip any split suffix to get the true base name for pattern matching
                        base_name, _ = _extract_base_name_and_suffix(split_base_filename, with_proc=False)
                        # Match using base_name (without proc suffix) for task lookup
                        matched_pattern = match_file_pattern(base_name + '.fif', file_patterns)
                        
                        task = None
                        run = None
                        acq = None
                        
                        if matched_pattern:
                            task = matched_pattern.get('task')
                            run_extraction = matched_pattern.get('run_extraction', 'last_digits')
                            run = extract_run_from_filename(base_name + '.fif', run_extraction, meg_id=meg_id)
                            acq_config = matched_pattern.get('acq')
                            if acq_config and acq_config not in ('last_digits', 'first_digits'):
                                acq = acq_config
                            elif acq_config in ('last_digits', 'first_digits'):
                                acq = extract_run_from_filename(base_name + '.fif', acq_config, meg_id=meg_id)
                                if acq is not None:
                                    acq = str(acq)
                        else:
                            task = infer_task_from_basename(base_name + '.fif', file_patterns)
                        
                        if task:
                            for split_file in split_files:
                                logger.info(f"  ✓ Converting derivative split: {split_file.name} → task={task} (proc-{proc_label})")
                                copy_derivative_file_with_proc(
                                    split_file, bids_subject.replace('sub-', ''), session_id, task, run,
                                    proc_label, args.derivatives_root, acq=acq, pipeline_name=pipeline_name
                                )
                                conversion_stats.add_file('success', task, split_file.name)
                        else:
                            logger.warning(f"  ✗ Derivative split group {base_name}/{proc_label}: Could not determine task (skipped)")
                else:
                    logger.debug("  ℹ Skipping derivatives (pipeline_name set to 'none' in config)")
            
            except ValidationError as e:
                logger.error(str(e))
                logger.error("\nConversion aborted due to validation errors.")
                continue

# Track subjects that now contain MEG data for focused tree output
        subject_meg_dirs = [d for d in (bids_root / bids_subject).glob("**/meg") if d.is_dir() and any(d.iterdir())]
        if subject_meg_dirs:
            created_subject_roots.add(bids_root / bids_subject)
    
    if args.validate:
        logger.info("\n" + "═"*70)
        logger.info("BIDS VALIDATION")
        logger.info("═"*70)
        run_bids_validator(bids_root)
    
    logger.info(conversion_stats.summary())
    
    if created_subject_roots:
        logger.info("\n" + "═"*70)
        logger.info("BIDS DIRECTORY STRUCTURE (updated subjects)")
        logger.info("═"*70)
        for subject_root in sorted(created_subject_roots):
            logger.info(f"{subject_root.relative_to(bids_root)}/")
            for line in print_directory_tree(subject_root, prefix="", max_depth=4):
                logger.info(line)
            logger.info("─"*70)
        logger.info("═"*70)
    
    if conversion_stats.failed == 0:
        logger.info(f"\n✓ Conversion completed successfully!")
    else:
        logger.info(f"\n⚠ Conversion completed with {conversion_stats.failed} error(s)")
    logger.info("")
    return 0



if __name__ == "__main__":
    sys.exit(main())
