import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, AppState, FlatList, Linking, Pressable, StyleSheet, View } from "react-native";
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { KeyboardProvider, useReanimatedKeyboardAnimation } from "react-native-keyboard-controller";
import Animated, { useAnimatedStyle } from "react-native-reanimated";
import MaterialCommunityIcons from "@expo/vector-icons/MaterialCommunityIcons";
import { useFonts, Inter_400Regular, Inter_500Medium, Inter_600SemiBold, Inter_700Bold } from "@expo-google-fonts/inter";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import * as Haptics from "expo-haptics";
import * as Notifications from "expo-notifications";
import { api, DoxaError, parseAppLink, streamChat, type BrowserState, type ChatSummary, type CodeState, type Connection, type Status, type Upload } from "./src/api";
import { forgetConnection, loadConnection, saveConnection } from "./src/storage";
import { registerForPush } from "./src/push";
import { colors, font } from "./src/theme";
import { Orb, type OrbState } from "./src/components/Orb";
import { MessageBubble, type ChatItem } from "./src/components/MessageBubble";
import { TaskCard, Btn } from "./src/components/TaskCard";
import { ConnectScreen } from "./src/components/ConnectScreen";
import { CodeCard } from "./src/components/CodeCard";
import { ScreenView } from "./src/components/ScreenView";
import { QrScanner } from "./src/components/QrScanner";
import { ChatsSheet } from "./src/components/ChatsSheet";
import { AudioModule, RecordingPresets, createAudioPlayer, setAudioModeAsync, useAudioRecorder, type AudioPlayer } from "expo-audio";
import * as FileSystem from "expo-file-system/legacy";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";
import { AppText as Text, AppTextInput as TextInput } from "./src/components/AppText";

void SplashScreen.preventAutoHideAsync().catch(() => {});

type Offer = { id: string; task: string };
let nextId = 0;
const newId = () => `m${Date.now()}-${nextId++}`;

export default function App() {
  const [fontsLoaded, fontError] = useFonts({ Inter_400Regular, Inter_500Medium, Inter_600SemiBold, Inter_700Bold });
  const [connection, setConnection] = useState<Connection | null | undefined>(undefined);
  useEffect(() => { loadConnection().then(setConnection); }, []);
  useEffect(() => { if (fontsLoaded || fontError) void SplashScreen.hideAsync(); }, [fontsLoaded, fontError]);

  const connect = useCallback(async (c: Connection) => {
    await saveConnection(c);
    setConnection(c);
  }, []);

  // "Open in the Doxa app" on the phone page (doxa://connect?u=…&k=…) connects this app in one tap.
  useEffect(() => {
    const handle = (url?: string | null) => { const c = url ? parseAppLink(url) : null; if (c) void connect(c); };
    Linking.getInitialURL().then(handle).catch(() => {});
    const sub = Linking.addEventListener("url", ({ url }) => handle(url));
    return () => sub.remove();
  }, [connect]);

  if (!fontsLoaded && !fontError) return null;
  return (
    <KeyboardProvider>
      <SafeAreaProvider>
        <StatusBar style="light" />
        {connection === undefined ? (
          <View style={[styles.fill, styles.centered]}><ActivityIndicator color={colors.gold} /></View>
        ) : connection === null ? (
          <SafeAreaView style={styles.fill}><ConnectScreen onConnected={connect} /></SafeAreaView>
        ) : (
          <Main key={connection.base} connection={connection} onReconnect={connect}
            onDisconnect={async () => { await forgetConnection(); setConnection(null); }} />
        )}
      </SafeAreaProvider>
    </KeyboardProvider>
  );
}

function IconBtn({ name, label, onPress, color = colors.text }: { name: React.ComponentProps<typeof MaterialCommunityIcons>["name"]; label: string; onPress: () => void; color?: string }) {
  return (
    <Pressable onPress={onPress} accessibilityLabel={label} hitSlop={8} style={styles.iconBtn}
      android_ripple={{ color: "rgba(255,255,255,0.14)", borderless: true, radius: 20 }}>
      <MaterialCommunityIcons name={name} size={22} color={color} />
    </Pressable>
  );
}

function Main({ connection, onDisconnect, onReconnect }: { connection: Connection; onDisconnect: () => void; onReconnect: (c: Connection) => void }) {
  const [scanning, setScanning] = useState(false);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [offline, setOffline] = useState(false);
  const [task, setTask] = useState<BrowserState | null>(null);
  const [code, setCode] = useState<CodeState | null>(null);
  const [showCode, setShowCode] = useState(false);
  const [screen, setScreen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [hearing, setHearing] = useState(false);
  const [chatsOpen, setChatsOpen] = useState(false);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [viewing, setViewing] = useState<ChatSummary | null>(null);  // an older chat, read-only
  const [attached, setAttached] = useState<Upload[]>([]);   // photos/documents already on the PC, sent with the next message
  const [uploading, setUploading] = useState(0);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const player = useRef<AudioPlayer | null>(null);
  const list = useRef<FlatList<ChatItem>>(null);
  const abort = useRef<AbortController | null>(null);
  const taskTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const codeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastPending = useRef<string | null>(null);
  const insets = useSafeAreaInsets();
  // The composer rides up with the keyboard frame by frame (Android edge-to-edge no longer resizes the window).
  const { height: keyboard } = useReanimatedKeyboardAnimation();
  const composerPad = useAnimatedStyle(() => ({ paddingBottom: Math.max(insets.bottom, -keyboard.value) + 8 }));

  const loadCurrent = useCallback(() => {
    api.history(connection).then(({ messages }) =>
      setItems(messages.slice(-30).map((m) => ({ id: newId(), role: m.role === "user" ? "user" : "assistant", text: m.content, old: true })))).catch(() => {});
  }, [connection]);

  // --- Status (also warms the connection so the first message is fast) ----------------
  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.status(connection);
      setStatus(s); setOffline(false);
      if (s.browser_running) pollTask();
    } catch (e) {
      setOffline(true);
      if (e instanceof DoxaError && (e.status === 401 || e.status === 429)) {
        Alert.alert("Reconnect Doxa", e.message, [{ text: "Scan new link", onPress: () => setScanning(true) }, { text: "Disconnect", style: "destructive", onPress: onDisconnect }]);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection]);

  // --- Browser task: poll quickly only while one is running ------------------------------
  const pollTask = useCallback(async () => {
    if (taskTimer.current) clearTimeout(taskTimer.current);
    try {
      const s = await api.browser(connection);
      setTask(s.running || s.result ? s : null);
      if (s.pending && s.pending.id !== lastPending.current) {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
      }
      lastPending.current = s.pending?.id ?? null;
      if (s.running) taskTimer.current = setTimeout(pollTask, s.pending ? 2500 : 1200);
    } catch {
      taskTimer.current = setTimeout(pollTask, 5000);
    }
  }, [connection]);

  // --- Code mode: poll every 2 s while a job runs -------------------------------------------
  const pollCode = useCallback(async () => {
    if (codeTimer.current) clearTimeout(codeTimer.current);
    try {
      const s = await api.code(connection);
      setCode(s);
      if (s.running) codeTimer.current = setTimeout(pollCode, 2000);
    } catch { /* PC asleep or an older Doxa: the card just stays as it was */ }
  }, [connection]);

  useEffect(() => {
    refreshStatus();
    loadCurrent();
    pollTask();
    pollCode();
    registerForPush(connection).catch(() => {});
    const interval = setInterval(() => { if (AppState.currentState === "active") refreshStatus(); }, 10000);
    const appState = AppState.addEventListener("change", (s) => { if (s === "active") { refreshStatus(); pollTask(); pollCode(); } });
    const tap = Notifications.addNotificationResponseReceivedListener(() => { pollTask(); pollCode(); });
    return () => {
      clearInterval(interval); appState.remove(); tap.remove();
      if (taskTimer.current) clearTimeout(taskTimer.current);
      if (codeTimer.current) clearTimeout(codeTimer.current);
    };
  }, [connection, refreshStatus, pollTask, pollCode, loadCurrent]);
  useEffect(() => () => { player.current?.remove(); }, []);

  const scrollToEnd = () => requestAnimationFrame(() => list.current?.scrollToEnd({ animated: true }));

  // --- Chat with streaming: words show up as Doxa writes them -----------------------------

  // --- Chats (like ChatGPT): new chat, older chats --------------------------------------------
  const openChats = async () => {
    setChatsOpen(true);
    try { setChats((await api.chats(connection)).chats); } catch { /* list stays as it was */ }
  };
  const newChat = async () => {
    setChatsOpen(false);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    try { await api.newChat(connection); } catch (e) { Alert.alert("New chat", e instanceof Error ? e.message : "Try again."); return; }
    setViewing(null); setItems([]); setOffers([]);
  };
  const openChat = async (chat: ChatSummary) => {
    setChatsOpen(false);
    if (chats[0]?.id === chat.id) { setViewing(null); loadCurrent(); return; }  // the current chat
    try {
      const { messages } = await api.chat(connection, chat.id);
      setViewing(chat);
      setItems(messages.map((m) => ({ id: newId(), role: m.role === "user" ? "user" : "assistant", text: m.content, old: true })));
    } catch (e) { Alert.alert("Couldn't open that chat", e instanceof Error ? e.message : "Try again."); }
  };

  // --- Talk to Doxa: tap the mic, speak, tap again; the answer is read out in Doxa's voice -----------
  const speakReply = async (text: string) => {
    try {
      const { id } = await api.speak(connection, text.slice(0, 1500));
      player.current?.remove();
      await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
      const next = createAudioPlayer({ uri: `${connection.base}/api/speak/${id}`, headers: { Authorization: "Bearer " + connection.key } });
      player.current = next;
      next.play();
    } catch { /* the text answer is already on screen */ }
  };
  const toggleMic = async () => {
    if (hearing) return;
    if (!recording) {
      const permission = await AudioModule.requestRecordingPermissionsAsync();
      if (!permission.granted) { Alert.alert("Microphone", "Allow the microphone in your phone's settings to talk to Doxa."); return; }
      player.current?.pause();
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecording(true);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
      return;
    }
    setRecording(false);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    try {
      await recorder.stop();
      await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
      const uri = recorder.uri;
      if (!uri) return;
      setHearing(true);
      const audio = await FileSystem.readAsStringAsync(uri, { encoding: FileSystem.EncodingType.Base64 });
      const { text } = await api.transcribe(connection, audio, "audio/mp4");
      setHearing(false);
      if (text.trim()) await send(text, true);
      else Alert.alert("Didn't catch that", "Try again a little closer to the phone.");
    } catch (e) {
      setHearing(false);
      Alert.alert("Voice", e instanceof Error ? e.message : "Couldn't hear that. Try again.");
    }
  };

  // --- Photos and documents: picked here, saved on the PC, then Claude looks at them with the message ---------------
  const uploadPicked = async (files: { uri: string; name: string; base64?: string | null }[]) => {
    for (const file of files) {
      setUploading((n) => n + 1);
      try {
        const data = file.base64 || await FileSystem.readAsStringAsync(file.uri, { encoding: FileSystem.EncodingType.Base64 });
        const saved = await api.upload(connection, file.name, data);
        setAttached((prev) => [...prev, saved]);
        Haptics.selectionAsync().catch(() => {});
      } catch (e) {
        Alert.alert("Couldn't send " + file.name, e instanceof Error ? e.message : "Try again.");
      } finally {
        setUploading((n) => n - 1);
      }
    }
  };
  const pickPhotos = async (camera: boolean) => {
    const permission = camera ? await ImagePicker.requestCameraPermissionsAsync() : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) { Alert.alert(camera ? "Camera" : "Photos", "Allow access in your phone's settings to send it to Doxa."); return; }
    const options: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.8, base64: true, allowsMultipleSelection: !camera, selectionLimit: 6 };
    const result = camera ? await ImagePicker.launchCameraAsync(options) : await ImagePicker.launchImageLibraryAsync(options);
    if (result.canceled) return;
    // The picker gives JPEG (HEIC is converted), so the PC can always open it.
    await uploadPicked(result.assets.map((a, i) => ({ uri: a.uri, base64: a.base64, name: (a.fileName || `photo-${i + 1}`).replace(/\.(heic|heif)$/i, "") + (/\.(jpe?g|png|webp|gif)$/i.test(a.fileName || "") ? "" : ".jpg") })));
  };
  const pickDocuments = async () => {
    const result = await DocumentPicker.getDocumentAsync({ multiple: true, copyToCacheDirectory: true });
    if (result.canceled) return;
    const big = result.assets.find((a) => (a.size || 0) > 25_000_000);
    if (big) { Alert.alert("Too big", `${big.name} is over 25 MB.`); return; }
    await uploadPicked(result.assets.map((a) => ({ uri: a.uri, name: a.name })));
  };
  const attach = () => {
    Alert.alert("Send to Doxa", "Doxa saves it on your PC and looks at it with your message.", [
      { text: "Photo library", onPress: () => void pickPhotos(false) },
      { text: "Take a photo", onPress: () => void pickPhotos(true) },
      { text: "File or document", onPress: () => void pickDocuments() },
    ], { cancelable: true });
  };

  const send = async (spokenText?: string, spoken = false) => {
    const typed = (spokenText ?? input).trim();
    if ((!typed && !attached.length) || busy || uploading) return;
    const files = attached;
    const text = files.length
      ? `${typed || "Look at this."}\n\n${files.map((f) => f.tag).join("\n")}`
      : typed;
    const shownText = files.length ? `${typed || "Look at this."}\n${files.map((f) => "📎 " + f.name).join("\n")}` : typed;
    setAttached([]);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    if (viewing) {  // typing in an older chat starts a fresh one (the old one stays in the list)
      try { await api.newChat(connection); } catch { /* still send */ }
      setViewing(null); setItems([]);
    }
    if (!spokenText) setInput("");
    setBusy(true);
    const replyId = newId();
    setItems((prev) => [...prev, { id: newId(), role: "user", text: shownText }, { id: replyId, role: "assistant", text: "", pending: true }]);
    scrollToEnd();
    let shown = "";
    let frame: number | null = null;
    const flush = () => {
      frame = null;
      setItems((prev) => prev.map((m) => (m.id === replyId ? { ...m, text: shown, pending: false } : m)));
    };
    const controller = new AbortController();
    abort.current = controller;
    try {
      await streamChat(connection, text, (event) => {
        if (event.type === "token") {
          if (!shown) Haptics.selectionAsync().catch(() => {});
          shown += event.text;
          if (frame === null) frame = requestAnimationFrame(flush); // at most one repaint per frame
        } else if (event.type === "status" && !shown) {
          setItems((prev) => prev.map((m) => (m.id === replyId ? { ...m, text: event.text } : m)));
        } else if (event.type === "offer") {
          setItems((prev) => prev.map((m) => (m.id === replyId ? { ...m, text: event.reply, pending: false } : m)));
          setOffers((prev) => [...prev, { id: newId(), task: event.task }]);
        } else if (event.type === "done") {
          if (frame !== null) cancelAnimationFrame(frame);
          setItems((prev) => prev.map((m) => (m.id === replyId ? { ...m, text: event.reply, note: event.note, pending: false } : m)));
          if (spoken && event.reply) void speakReply(event.reply);
        }
      }, controller.signal);
    } catch (e) {
      if (!controller.signal.aborted) {
        const message = e instanceof Error ? e.message : "Something went wrong.";
        setItems((prev) => prev.map((m) => (m.id === replyId ? { ...m, text: message, pending: false, error: true } : m)));
      }
    } finally {
      setBusy(false);
      abort.current = null;
      scrollToEnd();
      setTimeout(pollCode, 1500);  // "codex: …" / "ask Claude Code to …" starts a Code job: show its card
    }
  };

  const stopAll = async () => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
    abort.current?.abort();
    try { await api.stop(connection); } catch { /* status shows offline */ }
    pollTask();
  };

  const startTask = async (offer: Offer) => {
    try {
      await api.startTask(connection, offer.task);
      setOffers((prev) => prev.filter((o) => o.id !== offer.id));
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
      pollTask();
    } catch (e) {
      Alert.alert("Couldn't start", e instanceof Error ? e.message : "Try again.");
    }
  };

  const respond = async (id: string, value: unknown) => {
    try { await api.respond(connection, id, value); } catch (e) {
      Alert.alert("Not sent", e instanceof Error ? e.message : "Try again.");
    }
    pollTask();
  };

  const sendCode = async (job: string, engine: string, fresh: boolean) => {
    try { await api.codeStart(connection, job, engine, fresh); } catch (e) {
      Alert.alert("Code mode", e instanceof Error ? e.message : "Try again.");
    }
    setTimeout(pollCode, 600);
  };

  const stopCode = async () => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
    try { await api.codeStop(connection); } catch { /* shown by the next poll */ }
    setTimeout(pollCode, 800);
  };

  const codeVisible = !!code && (showCode || !!code.job);
  const orbState: OrbState = offline ? "offline" : task?.pending ? "waiting" : task?.running || code?.running ? "working" : busy ? "thinking" : "idle";
  const empty = items.length === 0 && offers.length === 0 && !task && !codeVisible;

  return (
    <SafeAreaView style={styles.fill} edges={["top", "left", "right"]}>
      <View style={styles.header}>
        <IconBtn name="menu" label="Chats" onPress={openChats} />
        <Pressable onLongPress={() => Alert.alert("Disconnect this phone?", "You'll need a new link from your PC to reconnect.",
          [{ text: "Cancel", style: "cancel" }, { text: "Disconnect", style: "destructive", onPress: onDisconnect }])}
          style={styles.brandRow} hitSlop={8}>
          {!empty && <Orb state={orbState} size={30} />}
          <Text style={styles.brand}>DOXA</Text>
        </Pressable>
        <Text style={styles.meta} numberOfLines={1}>
          {offline ? "PC unreachable" : status ? (code?.running ? "Code mode working…" : "Ready") : "Connecting…"}
        </Text>
        <IconBtn name="monitor" label="See your PC screen" onPress={() => setScreen(true)} />
        <IconBtn name="code-braces" label="Code mode" color={codeVisible ? colors.gold : colors.text}
          onPress={() => { setShowCode(!showCode || !!code?.job); pollCode(); }} />
        <IconBtn name="stop-circle-outline" label="Stop" color={colors.danger} onPress={stopAll} />
      </View>

      {viewing ? (
        <View style={styles.banner}>
          <MaterialCommunityIcons name="history" size={20} color={colors.muted} />
          <Text style={styles.bannerText} numberOfLines={2}>Older chat: {viewing.title}. Type or talk to start a new chat.</Text>
        </View>
      ) : null}
      {offline ? (
        <Pressable onPress={() => setScanning(true)} style={styles.banner} android_ripple={{ color: "rgba(255,255,255,0.08)" }}>
          <MaterialCommunityIcons name="qrcode-scan" size={20} color={colors.gold} />
          <Text style={styles.bannerText}>Can't reach your PC. Is it on with Doxa open? If you made a new link, tap to scan it.</Text>
        </Pressable>
      ) : null}
      <View style={styles.fill}>
        {empty ? (
          <View style={[styles.fill, styles.centered]}>
            <Orb state={orbState} size={190} />
            <Text style={styles.hello}>{offline ? "Doxa can't reach your PC right now." : "Ask anything, or tell me what to get done."}</Text>
          </View>
        ) : (
          <FlatList
            ref={list}
            data={items}
            keyExtractor={(m) => m.id}
            renderItem={({ item }) => <MessageBubble item={item} />}
            contentContainerStyle={{ paddingVertical: 12 }}
            onContentSizeChange={() => list.current?.scrollToEnd({ animated: false })}
            keyboardDismissMode="on-drag"
            keyboardShouldPersistTaps="handled"
            ListFooterComponent={
              <>
                {offers.map((offer) => (
                  <View key={offer.id} style={styles.offer}>
                    <Text style={styles.offerTitle}>Start a browser task?</Text>
                    <Text style={styles.offerText}>{offer.task}</Text>
                    <Text style={styles.offerHint}>Doxa works in its own browser on your PC, asks you here for details, and waits for your OK before booking or submitting.</Text>
                    <View style={styles.row}>
                      <Btn label="Start" primary onPress={() => startTask(offer)} />
                      <Btn label="Not now" onPress={() => setOffers((prev) => prev.filter((o) => o.id !== offer.id))} />
                    </View>
                  </View>
                ))}
                {task && <TaskCard state={task} onRespond={respond} />}
                {codeVisible && code && <CodeCard state={code} onSend={sendCode} onStop={stopCode} />}
              </>
            }
          />
        )}
        <Animated.View style={[styles.composerWrap, composerPad]}>
          {(attached.length > 0 || uploading > 0) && (
            <View style={styles.chips}>
              {attached.map((f) => (
                <Pressable key={f.path} onPress={() => setAttached((prev) => prev.filter((x) => x.path !== f.path))} style={styles.chip}
                  accessibilityLabel={`Remove ${f.name}`}>
                  <MaterialCommunityIcons name={f.kind === "image" ? "image-outline" : "file-document-outline"} size={16} color={colors.gold} />
                  <Text style={styles.chipText} numberOfLines={1}>{f.name.replace(/^\d{6}(-\d+)? /, "")}</Text>
                  <MaterialCommunityIcons name="close" size={14} color={colors.muted} />
                </Pressable>
              ))}
              {uploading > 0 && <View style={styles.chip}><ActivityIndicator size="small" color={colors.gold} /><Text style={styles.chipText}>Sending to your PC…</Text></View>}
            </View>
          )}
          <View style={styles.composer}>
            <Pressable onPress={attach} disabled={busy} accessibilityLabel="Send a photo or document" hitSlop={6}
              android_ripple={{ color: "rgba(255,255,255,0.14)", borderless: true, radius: 22 }} style={styles.attach}>
              <MaterialCommunityIcons name="paperclip" size={22} color={colors.text} />
            </Pressable>
            <TextInput value={input} onChangeText={setInput} placeholder={recording ? "Listening… tap ■ to send" : hearing ? "Getting your words…" : "Message Doxa…"} placeholderTextColor={colors.muted}
              style={styles.input} multiline maxLength={8000} />
            {input.trim() || attached.length ? (
              <Pressable onPress={() => void send()} disabled={busy || uploading > 0} accessibilityLabel="Send"
                android_ripple={{ color: "rgba(0,0,0,0.15)", borderless: true, radius: 23 }}
                style={({ pressed }) => [styles.send, busy && { opacity: 0.4 }, pressed && { transform: [{ scale: 0.94 }] }]}>
                {busy ? <ActivityIndicator color={colors.userText} size="small" /> : <MaterialCommunityIcons name="arrow-up" size={22} color={colors.userText} />}
              </Pressable>
            ) : (
              <Pressable onPress={() => void toggleMic()} disabled={busy || hearing} accessibilityLabel={recording ? "Stop and send" : "Talk to Doxa"}
                android_ripple={{ color: "rgba(0,0,0,0.15)", borderless: true, radius: 23 }}
                style={({ pressed }) => [styles.send, recording && styles.recording, (busy || hearing) && { opacity: 0.5 }, pressed && { transform: [{ scale: 0.94 }] }]}>
                {hearing ? <ActivityIndicator color={colors.userText} size="small" />
                  : <MaterialCommunityIcons name={recording ? "stop" : "microphone"} size={22} color={recording ? "#fff" : colors.userText} />}
              </Pressable>
            )}
          </View>
        </Animated.View>
      </View>
      <ScreenView connection={connection} visible={screen} onClose={() => setScreen(false)} />
      <ChatsSheet visible={chatsOpen} chats={chats} currentId={viewing ? viewing.id : null} onClose={() => setChatsOpen(false)}
        onNew={() => void newChat()} onOpen={(chat) => void openChat(chat)} />
      <QrScanner visible={scanning} onClose={() => setScanning(false)}
        onScanned={(c) => { setScanning(false); onReconnect(c); }} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: colors.bg },
  centered: { alignItems: "center", justifyContent: "center", padding: 24 },
  header: { flexDirection: "row", alignItems: "center", gap: 6, paddingLeft: 16, paddingRight: 8, paddingVertical: 8 },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  brand: { color: colors.gold, fontSize: font.brand, letterSpacing: 6, fontWeight: "500" },
  meta: { flex: 1, color: colors.muted, fontSize: font.small, marginLeft: 6 },
  iconBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  banner: { flexDirection: "row", alignItems: "center", gap: 12, marginHorizontal: 12, marginBottom: 6, padding: 12, borderRadius: 16, backgroundColor: colors.surface, overflow: "hidden" },
  bannerText: { flex: 1, color: colors.text, fontSize: font.small, lineHeight: 19 },
  hello: { color: colors.muted, fontSize: font.body, textAlign: "center", marginTop: 28, maxWidth: 280, lineHeight: 22 },
  offer: { marginHorizontal: 16, marginVertical: 8, padding: 16, borderRadius: 22, backgroundColor: colors.surface },
  offerTitle: { color: colors.text, fontWeight: "600", fontSize: font.body },
  offerText: { color: colors.text, fontSize: font.body, marginTop: 8, padding: 10, backgroundColor: colors.surface2, borderRadius: 10 },
  offerHint: { color: colors.muted, fontSize: font.small, marginTop: 8, lineHeight: 19 },
  row: { flexDirection: "row", gap: 10, marginTop: 12 },
  composerWrap: { backgroundColor: colors.bg },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: 10, paddingHorizontal: 12, paddingTop: 8 },
  input: { flex: 1, maxHeight: 140, minHeight: 46, color: colors.text, backgroundColor: colors.surface, borderRadius: 23, paddingHorizontal: 18, paddingTop: 13, paddingBottom: 13, fontSize: font.body },
  send: { width: 46, height: 46, borderRadius: 23, backgroundColor: colors.gold, alignItems: "center", justifyContent: "center" },
  recording: { backgroundColor: colors.danger },
  attach: { width: 40, height: 46, alignItems: "center", justifyContent: "center" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, paddingHorizontal: 12, paddingTop: 8 },
  chip: { flexDirection: "row", alignItems: "center", gap: 6, maxWidth: 220, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 14, backgroundColor: colors.surface },
  chipText: { color: colors.text, fontSize: font.small, flexShrink: 1 },
});
