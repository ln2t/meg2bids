#!/usr/bin/env python3
"""Setup script for meg2bids."""

from pathlib import Path
from setuptools import setup, find_packages

# Read long description from README
readme_file = Path(__file__).parent / "README.md"
if readme_file.exists():
    with open(readme_file, "r", encoding="utf-8") as f:
        long_description = f.read()
else:
    long_description = "MEG to BIDS converter for Neuromag/Elekta/MEGIN FIF files"

# Read requirements
requirements_file = Path(__file__).parent / "requirements.txt"
if requirements_file.exists():
    with open(requirements_file, "r", encoding="utf-8") as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]
else:
    requirements = [
        "mne>=1.0",
        "mne-bids>=0.13",
        "numpy>=1.20",
    ]

setup(
    name="meg2bids",
    version="1.1.0",
    description="MEG to BIDS converter for Neuromag/Elekta/MEGIN FIF files",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Vandermiers Quentin",
    author_email="quentin.vandermiers@ulb.be",
    url="https://github.com/ln2t/meg2bids",
    license="GPL-3.0",
    packages=find_packages(),
    py_modules=["meg2bids"],
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=3.0",
            "black>=22.0",
            "flake8>=4.0",
            "pylint>=2.0",
        ],
        "docs": [
            "mkdocs>=1.4",
            "mkdocs-material>=9.0",
        ],
    },
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "meg2bids=meg2bids:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Medical Science Apps.",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="meg bids neuroscience neuroimaging mne fif",
    project_urls={
        "Bug Reports": "https://github.com/ln2t/meg2bids/issues",
        "Documentation": "https://github.com/ln2t/meg2bids/docs",
        "Source": "https://github.com/ln2t/meg2bids",
    },
)
