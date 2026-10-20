"""What identifies analyze-spectrum's releases to the shared auto-update client."""

from analyze_common.update import UpdateConfig

from analyze_spectrum import __version__

# base64 of the raw Ed25519 public key.  Its private half is the repository
# secret UPDATE_SIGNING_KEY, which release.yaml signs latest.json with.
PUBLIC_KEY = "BXJXGjeQuBlOeEMkcfwiWMXqWAEtTS+Y5KTkbTMKqzk="

UPDATE_CONFIG = UpdateConfig(
    product="analyze-spectrum",
    repo="semnil/analyze-spectrum",
    current_version=__version__,
    public_key=PUBLIC_KEY,
    temp_prefix="spectrum_update_",
    # Held by the running app; build.py hands it to installer.iss as MyAppMutex.
    mutex_name="com.semnil.spectrum-analyzer",
)
