"""dekube converter: trust-manager — Bundle.

Assembles CA trust bundles from cert-manager Secrets, ConfigMaps, inline PEM,
and (optionally) system default CAs. Injects the result as a synthetic
ConfigMap into ctx.configmaps.

Optional: certifi (for useDefaultCAs). Falls back to system CA paths.
"""

import sys

from dekube import ConverterResult, Converter  # pylint: disable=import-error  # h2c resolves at runtime

# Bundle.spec.target.secret has the same shape as target.configMap — a TargetTemplate
# with a "key" field (cert-manager/trust-manager pkg/apis/trust/v1alpha1: BundleTarget{
# ConfigMap *TargetTemplate, Secret *TargetTemplate}, TargetTemplate{Key string}).
_DEFAULT_TARGET_KEY = "ca-certificates.crt"


class TrustManagerConverter(Converter):  # pylint: disable=too-few-public-methods  # contract: one class, one method
    """Convert trust-manager Bundle to synthetic ConfigMap."""

    name = "trust-manager"
    kinds = ["Bundle"]
    priority = 200  # after cert-manager (needs secrets), before keycloak (produces configmaps)

    @staticmethod
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

    @staticmethod
    def _collect_source(source, ctx, bundle_name):  # pylint: disable=too-many-return-statements
        """Resolve a single Bundle source entry. Returns (pem_str, warning)."""
        if source.get("useDefaultCAs"):
            cas = TrustManagerConverter._get_default_cas()
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
            val = (sec.get("stringData") or {}).get(key)
            if val is None:
                raw = (sec.get("data") or {}).get(key)
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
            val = (cm.get("data") or {}).get(key) if "data" in cm else cm.get(key)
            if val is not None:
                return val, None
            return None, (f"Bundle '{bundle_name}': configMap '{name}' "
                          f"key '{key}' not found")

        inline = source.get("inLine")
        if inline:
            return inline, None

        return None, None  # empty/unknown source type — skip silently

    def convert(self, _kind, manifests, ctx):
        """Process Bundle manifests into synthetic ConfigMaps/Secrets."""
        for m in manifests:
            name = (m.get("metadata") or {}).get("name", "?")
            spec = m.get("spec") or {}
            target = spec.get("target") or {}
            cm_target = target.get("configMap") or {}
            secret_target = target.get("secret") or {}

            pem_parts = []
            for source in (spec.get("sources") or []):
                if not source:  # null list item (Helm conditional inside sources)
                    continue
                pem, warning = self._collect_source(source, ctx, name)
                if pem:
                    pem_parts.append(pem)
                if warning:
                    ctx.warnings.append(warning)

            if not pem_parts:
                ctx.warnings.append(
                    f"Bundle '{name}': no sources resolved — skipped")
                continue

            bundle = "\n".join(p.rstrip("\n") for p in pem_parts) + "\n"
            written = []

            if cm_target:
                cm_key = cm_target.get("key", _DEFAULT_TARGET_KEY)
                ctx.configmaps[name] = {
                    "metadata": {"name": name},
                    "data": {cm_key: bundle},
                }
                written.append(f"ConfigMap '{name}'")

            if secret_target:
                sec_key = secret_target.get("key", _DEFAULT_TARGET_KEY)
                # stringData (plain), not data — avoids double base64-encoding, see
                # write_secret_files()/the synthetic-secret convention used elsewhere.
                ctx.secrets[name] = {
                    "metadata": {"name": name},
                    "stringData": {sec_key: bundle},
                }
                written.append(f"Secret '{name}'")

            if not written:
                ctx.warnings.append(
                    f"Bundle '{name}': no target.configMap or target.secret — skipped")
                continue

            print(f"  trust-manager: generated bundle '{name}' -> {', '.join(written)} "
                  f"({len(pem_parts)} source(s))", file=sys.stderr)

        return ConverterResult()
