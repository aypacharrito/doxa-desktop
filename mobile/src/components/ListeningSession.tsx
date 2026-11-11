import {useState} from 'react';
import {Alert,Text,View} from 'react-native';
import {AudioModule,RecordingPresets,setAudioModeAsync,useAudioRecorder,useAudioRecorderState} from 'expo-audio';
import {File} from 'expo-file-system';
import {Btn} from './TaskCard';
import {colors} from '../theme';

// Capture is explicit and bounded. Nothing uploads or triggers an action here.
export function ListeningSession(){
  const recorder=useAudioRecorder({...RecordingPresets.LOW_QUALITY,directory:'document'});
  const state=useAudioRecorderState(recorder);
  const [busy,setBusy]=useState(false);
  const [saved,setSaved]=useState<string|null>(null);
  const start=async()=>{
    if(busy)return;
    setBusy(true);
    try{
      const p=await AudioModule.requestRecordingPermissionsAsync();
      if(!p.granted)throw new Error('Microphone permission was not granted.');
      await setAudioModeAsync({allowsRecording:true,allowsBackgroundRecording:true,playsInSilentMode:true});
      await recorder.prepareToRecordAsync();
      recorder.record({forDuration:600});
      setSaved(null);
    }catch(e){Alert.alert('Listening did not start',e instanceof Error?e.message:'Try again.');}
    finally{setBusy(false);}
  };
  const stop=async()=>{
    setBusy(true);
    try{await recorder.stop();setSaved(recorder.uri);}
    catch{Alert.alert('Could not finish recording','Use the recording notification to stop the microphone.');}
    finally{setBusy(false);}
  };
  return <View style={{paddingHorizontal:16,paddingVertical:8,gap:8}}>
    <Text style={{color:colors.muted}}>{state.isRecording?'Recording on this phone · up to 10 minutes':'Listening sessions · microphone off'}</Text>
    <Btn label={state.isRecording?'Stop session':busy?'Please wait…':'Start listening session'} onPress={()=>{
      if(busy)return;
      if(state.isRecording){void stop();return;}
      Alert.alert('Start a listening session?','Records nearby speech on this phone for up to 10 minutes, including while locked. Tell other people before recording. This preview saves audio locally; transcription and suggested memories are not connected yet.',[{text:'Cancel',style:'cancel'},{text:'Start',onPress:()=>void start()}]);
    }}/>
    {saved&&<><Text style={{color:colors.muted}}>Session saved on this phone. No audio was uploaded.</Text><Btn label="Delete saved session" onPress={()=>{try{new File(saved).delete();setSaved(null);}catch{Alert.alert('Could not delete','Try again.');}}}/></>}
  </View>;
}
