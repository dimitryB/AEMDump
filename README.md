# AEMDump

AEMDump is a CLI utility that exports files from Adobe Experience Manager (AEM) WebDAV into a local folder while preserving remote modified timestamps. It talks to AEM WebDAV directly over HTTP and does not require mapping/mounting a WebDAV drive.
This is usefull when exporting original assets from AEM DAM.

## Features

- Recursive export from a configurable repository root (default: `/content/dam`)
- Streams downloads in chunks for large files
- Skips unchanged files by comparing remote and local size
- Applies `getlastmodified` timestamp to local files
- Avoids OS-level WebDAV drive mapping; uses direct WebDAV API calls instead
- Supports secure password handling via environment variable or interactive prompt

## Requirements

- Python 3.10+
- Network access to your AEM WebDAV endpoint

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### macOS / Linux

```bash
python3 aem_export.py \
  --base-url "https://aem.example.com/crx/repository/crx.default" \
  --username "your-username" \
  --remote-root "/content/dam" \
  --local-root "./exports"
```

### Windows (PowerShell)

```powershell
py aem_export.py `
  --base-url "https://aem.example.com/crx/repository/crx.default" `
  --username "your-username" `
  --remote-root "/content/dam" `
  --local-root ".\\exports"
```

Password resolution order:

1. `--password` argument
2. environment variable from `--password-env` (defaults to `AEM_PASSWORD`)
3. interactive terminal prompt (unless `--no-password-prompt`)

Example using environment variable (macOS / Linux):

```bash
export AEM_PASSWORD='your-password'
python3 aem_export.py \
  --base-url "https://aem.example.com/crx/repository/crx.default" \
  --username "your-username" \
  --local-root "./exports"
```

Example using environment variable (Windows PowerShell):

```powershell
$env:AEM_PASSWORD = "your-password"
py aem_export.py `
  --base-url "https://aem.example.com/crx/repository/crx.default" `
  --username "your-username" `
  --local-root ".\\exports"
```

## Notes

- Use `--insecure` only in trusted environments; it disables TLS certificate verification.
- This utility uses WebDAV `PROPFIND` and `GET` requests directly (no mapped WebDAV drive required).

## Development

```bash
python3 -m py_compile aem_export.py
python3 aem_export.py --help
python3 -m unittest discover -s tests -v
```

## License

MIT. See [LICENSE](LICENSE).
