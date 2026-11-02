"""Optional workaround for broken IPv6 routing, scoped to pip and its children."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

# Pip can spawn build helpers. sitecustomize applies this workaround to those
# Python children too, without changing any system network configuration.
with tempfile.TemporaryDirectory(prefix="bee-install-") as directory:
    Path(directory, "sitecustomize.py").write_text('''import socket
original = socket.getaddrinfo
def ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return original(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = ipv4
''')
    environment = dict(os.environ)
    environment["PYTHONPATH"] = directory + os.pathsep + environment.get("PYTHONPATH", "")
    requirements = Path(__file__).resolve().parent.parent / "requirements.txt"
    result = subprocess.run([sys.executable, "-m", "pip", "install", "--prefer-binary",
                             "--timeout", "60", "-r", str(requirements)], env=environment)
    sys.exit(result.returncode)
