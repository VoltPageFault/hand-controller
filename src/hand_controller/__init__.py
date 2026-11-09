"""Hand Controller: mouse e controller Xbox virtuali pilotati dalla mano via webcam."""
import os

# Media Foundation (Windows) con le "trasformazioni hardware" attive può impiegare 30+ secondi ad
# aprire la webcam: disattivate si apre in meno di un secondo. Va impostato prima di importare cv2.
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

__version__ = "0.1.0"
