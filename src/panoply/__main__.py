# Inject the system trust store (macOS Keychain, Windows cert store, etc.)
# so that corporate proxies like Zscaler work out of the box.
# This MUST run before any other import that might create an SSL context.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from panoply.connector.cli.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
