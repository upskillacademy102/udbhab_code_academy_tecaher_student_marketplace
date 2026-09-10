# Builds the Tailwind stylesheet. Run from the project root:
#   ./tools/build-css.ps1            (one-off, minified — do this before committing)
#   ./tools/build-css.ps1 -Watch     (rebuild on change, during development)
param([switch]$Watch)

# Tailwind prints a harmless "caniuse-lite is outdated" notice to stderr;
# don't let that abort the script.
$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$cliArgs = @(
  "-c", "tailwind.config.js",
  "-i", "static/src/app.css",
  "-o", "static/css/app.css"
)
if ($Watch) { $cliArgs += "--watch" } else { $cliArgs += "--minify" }

& "$PSScriptRoot\tailwindcss.exe" @cliArgs
