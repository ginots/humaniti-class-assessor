# Dot-source this file before Python, dependency downloads, or model work.
# Process-local settings only; this does not modify the installed interpreter.
$storageRoot = 'E:\HumanitiAI'
$freeBytes = [System.IO.DriveInfo]::new('E:\').AvailableFreeSpace
if ($freeBytes -lt 5GB) { throw 'Less than 5 GiB free on E:. Free space before continuing.' }
$storageVariables = @{
    TEMP = "$storageRoot\tmp"
    TMP = "$storageRoot\tmp"
    TMPDIR = "$storageRoot\tmp"
    PIP_CACHE_DIR = "$storageRoot\caches\pip"
    UV_CACHE_DIR = "$storageRoot\caches\uv"
    XDG_CACHE_HOME = "$storageRoot\caches"
    HF_HOME = "$storageRoot\caches\huggingface"
    HF_HUB_CACHE = "$storageRoot\caches\huggingface\hub"
    HUGGINGFACE_HUB_CACHE = "$storageRoot\caches\huggingface\hub"
    TORCH_HOME = "$storageRoot\caches\torch"
    NUMBA_CACHE_DIR = "$storageRoot\caches\numba"
    MPLCONFIGDIR = "$storageRoot\caches\matplotlib"
}
foreach ($entry in $storageVariables.GetEnumerator()) {
    New-Item -ItemType Directory -Path $entry.Value -Force -ErrorAction Stop | Out-Null
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
}
$env:PYTHONDONTWRITEBYTECODE = '1'
# Offline defaults protect later local inference from implicit downloads.
# Explicitly change these only for a deliberate public-model download.
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
Write-Output ('E: storage configured; {0:N1} GiB free. No packages or models installed.' -f ($freeBytes / 1GB))
