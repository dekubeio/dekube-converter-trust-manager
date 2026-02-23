"""h2c operator: trust-manager — Bundle.

Assembles CA trust bundles from cert-manager Secrets, ConfigMaps, inline PEM,
and (optionally) system default CAs. Injects the result as a synthetic
ConfigMap into ctx.configmaps.

Optional: certifi (for useDefaultCAs). Falls back to system CA paths.
"""

import sys

from h2c import ConverterResult, Converter


def _get_default_cas():
    """Get system CA bundle — try certifi, then common system paths."""
    try:
        import certifi  # pylint: disable=import-outside-toplevel
        with open(certifi.where(), encoding="utf-8") as f:
            return f.read()
    except ImportError:
        pass
    # macOS, Debian/Ubuntu, Alpine, RHEL/Fedora
    for path in ("/etc/ssl/cert.pem",
                 "/etc/ssl/certs/ca-certificates.crt",
                 "/etc/ssl/certs/ca-bundle.crt"):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            continue
    return None


def _collect_source(source, ctx, bundle_name):  # pylint: disable=too-many-return-statements
    """Resolve a single Bundle source entry. Returns (pem_str, warning)."""
    if source.get("useDefaultCAs"):
        cas = _get_default_cas()
        if cas:
            return cas, None
        return None, (f"Bundle '{bundle_name}': useDefaultCAs requested but "
                      f"no system CA bundle found (install certifi)")

    secret_src = source.get("secret")
    if secret_src:
        name = secret_src.get("name", "")
        key = secret_src.get("key", "")
        sec = ctx.secrets.get(name, {})
        # K8s Secret format: stringData (plain) or data (base64)
        val = sec.get("stringData", {}).get(key)
        if val is None:
            raw = sec.get("data", {}).get(key)
            if raw is not None:
                try:
                    import base64 as b64  # pylint: disable=import-outside-toplevel
                    val = b64.b64decode(raw).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    val = raw
        if val is not None:
            return val, None
        return None, (f"Bundle '{bundle_name}': secret '{name}' "
                      f"key '{key}' not found")

    cm_src = source.get("configMap")
    if cm_src:
        name = cm_src.get("name", "")
        key = cm_src.get("key", "")
        cm = ctx.configmaps.get(name, {})
        val = cm.get("data", {}).get(key) if "data" in cm else cm.get(key)
        if val is not None:
            return val, None
        return None, (f"Bundle '{bundle_name}': configMap '{name}' "
                      f"key '{key}' not found")

    inline = source.get("inLine")
    if inline:
        return inline, None

    return None, None  # empty/unknown source type — skip silently


class TrustManagerConverter(Converter):
    """Convert trust-manager Bundle to synthetic ConfigMap."""

    name = "trust-manager"
    kinds = ["Bundle"]
    priority = 200  # after cert-manager (needs secrets), before keycloak (produces configmaps)

    def convert(self, _kind, manifests, ctx):
        """Process Bundle manifests into synthetic ConfigMaps."""
        for m in manifests:
            name = m.get("metadata", {}).get("name", "?")
            spec = m.get("spec", {})
            target_key = (spec.get("target", {})
                          .get("configMap", {})
                          .get("key", "ca-certificates.crt"))

            pem_parts = []
            for source in spec.get("sources", []):
                pem, warning = _collect_source(source, ctx, name)
                if pem:
                    pem_parts.append(pem)
                if warning:
                    ctx.warnings.append(warning)

            if pem_parts:
                bundle = "\n".join(p.rstrip("\n") for p in pem_parts) + "\n"
                # Inject as K8s ConfigMap format
                ctx.configmaps[name] = {
                    "metadata": {"name": name},
                    "data": {target_key: bundle},
                }
                print(f"  trust-manager: generated bundle '{name}' "
                      f"({len(pem_parts)} source(s))", file=sys.stderr)
            else:
                ctx.warnings.append(
                    f"Bundle '{name}': no sources resolved — skipped")

        return ConverterResult()
