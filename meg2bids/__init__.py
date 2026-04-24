# meg2bids Package Information

__version__ = "1.1.0"
__author__ = "Quentin Vandermiers"
__email__ = "quentin.vandermiers@ulb.be"
__license__ = "GPL-3.0"
__url__ = "https://github.com/ln2t/meg2bids"
__description__ = "MEG to BIDS converter for Neuromag/Elekta/MEGIN FIF files"

# Import main conversion function for package-level access
from .meg2bids import main

__all__ = ['main', '__version__']
