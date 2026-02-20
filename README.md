# h2c-converter-trust-manager

![vibe coded](https://img.shields.io/badge/vibe-coded-ff69b4)
![python 3](https://img.shields.io/badge/python-3-3776AB)
![heresy: 4/10](https://img.shields.io/badge/heresy-4%2F10-yellow)
![public domain](https://img.shields.io/badge/license-public%20domain-brightgreen)

trust-manager Bundle CRD converter for [helmfile2compose](https://github.com/helmfile2compose/helmfile2compose).

## Handled kinds

- `Bundle` -- assembles CA trust bundles and injects them as synthetic ConfigMaps

## What it does

Replaces trust-manager's Bundle reconciliation with local assembly at conversion time. Collects PEM certificates from multiple sources and concatenates them into a single trust bundle ConfigMap.

Supported Bundle sources:
- **Secret** -- reads a key from a K8s Secret in `ctx.secrets` (supports both `stringData` and base64-encoded `data`)
- **ConfigMap** -- reads a key from a K8s ConfigMap in `ctx.configmaps`
- **Inline PEM** -- uses the literal PEM string from `spec.sources[].inLine`
- **System default CAs** -- when `useDefaultCAs: true`, reads system CA certificates (tries `certifi` first, then falls back to common system paths: `/etc/ssl/cert.pem`, `/etc/ssl/certs/ca-certificates.crt`, `/etc/ssl/certs/ca-bundle.crt`)

The assembled bundle is injected into `ctx.configmaps` under the Bundle's name, with the key specified by `spec.target.configMap.key` (defaults to `ca-certificates.crt`). Workloads that mount this ConfigMap pick it up through the existing volume-mount machinery.

## Priority

`20` -- runs after cert-manager (priority 10, generates the Secrets this converter reads), before keycloak (priority 50, mounts the ConfigMaps this converter produces).

## Depends on

- **h2c-converter-cert-manager** -- needs its generated Secrets as input for Secret-type sources. When using h2c-manager, cert-manager is auto-resolved as a dependency.

## Dependencies

- `certifi` (optional) -- used for `useDefaultCAs` source resolution. Falls back to system CA paths if not installed.

## Usage

Via h2c-manager (recommended -- auto-resolves cert-manager dependency):

```bash
python3 h2c-manager.py trust-manager
```

Manual (both extensions must be in the same directory — `--extensions-dir` scans `.py` files and one-level subdirectories):

```bash
mkdir -p extensions
cp h2c-converter-cert-manager/cert_manager.py extensions/
cp h2c-converter-trust-manager/trust_manager.py extensions/

python3 helmfile2compose.py \
  --extensions-dir ./extensions \
  --helmfile-dir ~/my-platform -e local --output-dir .
```

## License

Public domain.
