# Changelog

All notable changes to meg2bids will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-01-21

### Added
- Initial release of meg2bids
- MEG FIF to BIDS conversion for Neuromag/Elekta/MEGIN systems
- Automatic MaxFilter derivative detection and organization
- Support for multiple derivative suffixes (e.g., `_mc_ave`)
- Split file handling for large MEG files (> 2GB)
- Calibration file auto-detection and management
  - Triux system with date-matched fine-calibration
  - VectorView system support
- Session auto-detection from date-named folders
- Multi-subject batch processing
- Participant mapping from TSV file
- Configuration validation with `--check-config`
- Pattern-based file matching with ambiguity detection
- Run number extraction from filenames
- BIDS validation integration
- Comprehensive documentation and examples

### Features
- JSON-based configuration system
- Three subject input formats: BIDS ID, label, or MEG ID
- Automatic run number assignment
- Single and multi-session support
- Detailed conversion statistics and reporting
- Clear error messages and troubleshooting guidance

### Documentation
- Installation guide
- Tutorial for first steps
- Configuration reference
- Advanced usage guide
- Example configurations
- Contributing guidelines
- Code of conduct

## [Unreleased]

### Planned
- Support for other MEG manufacturers (CTF, BTI/4D, KIT/Yokogawa)
- GUI interface for configuration
- Docker container support
- Additional file format support
- Automated testing suite
- CI/CD integration

---

## Release Notes Format

### Added
New features

### Changed
Changes in existing functionality

### Deprecated
Soon-to-be removed features

### Removed
Removed features

### Fixed
Bug fixes

### Security
Vulnerability fixes
