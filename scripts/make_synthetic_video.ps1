# Generate a completely synthetic, nonconfidential speech fixture on E:.
. "$PSScriptRoot\use-storage.ps1"
$fixtureRoot = 'E:\HumanitiAI\browser-assets\test'
New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null
$wavePath = Join-Path $fixtureRoot 'synthetic.wav'
if (-not (Test-Path -LiteralPath $wavePath)) {
    Add-Type -AssemblyName System.Speech
    $synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synthesizer.Rate = 0
    $synthesizer.SetOutputToWaveFile($wavePath)
    $synthesizer.Speak('Welcome to our practice class. Today we will compare fractions using a number line. What does the bottom number tell us? Take a moment to explain your answer. A learner says it tells us how many equal parts make one whole. Yes, that is correct. Now compare one half and one quarter. If your answer differs, draw both on the same line. To recap, equal parts must have the same whole. Try two examples after class.')
    $synthesizer.Dispose()
}
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
& $python "$PSScriptRoot\make_synthetic_video.py"
