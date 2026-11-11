param([ValidateSet('listen','speak','probe','recognize-file')][string]$Mode='probe', [int]$OwnerPid=0, [string]$WaveFile='')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding=[System.Text.UTF8Encoding]::new($false)
function Emit($value){[Console]::WriteLine(($value | ConvertTo-Json -Compress));[Console]::Out.Flush()}
try {
    Add-Type -AssemblyName System.Speech
    $voices=@([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | Where-Object {$_.Culture.Name -eq 'en-US'})
    if($Mode -eq 'probe'){Emit @{type='probe';ready=($voices.Count -gt 0);engine='Windows offline speech';language='en-US'};exit 0}
    if($Mode -eq 'speak'){
        $request=[Console]::In.ReadLine() | ConvertFrom-Json
        $speaker=[System.Speech.Synthesis.SpeechSynthesizer]::new()
        $speaker.Rate=0
        if($WaveFile){$speaker.SetOutputToWaveFile($WaveFile)}else{$speaker.SetOutputToDefaultAudioDevice()}
        $speaker.Speak([string]$request.text)
        $speaker.Dispose()
        Emit @{type='spoken'}
        exit 0
    }
    if($voices.Count -eq 0){throw 'No offline English recognizer is installed. Install the English (United States) speech language pack in Windows Settings.'}
    $recognizer=[System.Speech.Recognition.SpeechRecognitionEngine]::new($voices[0])
    $recognizer.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
    $wake=[System.Speech.Recognition.GrammarBuilder]::new()
    $wake.Culture=$voices[0].Culture
    $wake.Append([System.Speech.Recognition.Choices]::new([string[]]@('Hey Doxa','Doxa','Hey Jarvis','Jarvis')))
    $recognizer.LoadGrammar([System.Speech.Recognition.Grammar]::new($wake))
    $recognizer.EndSilenceTimeout=[TimeSpan]::FromMilliseconds(650)
    $recognizer.EndSilenceTimeoutAmbiguous=[TimeSpan]::FromMilliseconds(900)
    $recognizer.BabbleTimeout=[TimeSpan]::FromSeconds(15)
    if($Mode -eq 'recognize-file'){
        $recognizer.SetInputToWaveFile($WaveFile)
        $result=$recognizer.Recognize([TimeSpan]::FromSeconds(10))
        if($result){Emit @{type='recognized';text=$result.Text;confidence=$result.Confidence}}else{Emit @{type='no-match'}}
    }else{
        $recognizer.SetInputToDefaultAudioDevice()
        Emit @{type='ready'}
        while($true){
            if($OwnerPid -gt 0 -and -not (Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue)){break}
            $result=$recognizer.Recognize([TimeSpan]::FromSeconds(2))
            if($result){Emit @{type='recognized';text=$result.Text;confidence=$result.Confidence}}
        }
    }
    $recognizer.Dispose()
}catch{Emit @{type='error';message=$_.Exception.Message};exit 1}
