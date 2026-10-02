import sys
from pathlib import Path

# portal_server lives in comercial/portal/, registry_server in relay/
sys.path.insert(0, str(Path(__file__).parents[2] / "comercial" / "portal"))
sys.path.insert(0, str(Path(__file__).parents[2] / "relay"))
