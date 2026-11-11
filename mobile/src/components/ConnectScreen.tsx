import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { AppText as Text, AppTextInput as TextInput } from "./AppText";
import * as Clipboard from "expo-clipboard";
import { api, parseLink, type Connection } from "../api";
import { colors, font, radius } from "../theme";
import { Orb } from "./Orb";
import { Btn } from "./TaskCard";
import { QrScanner } from "./QrScanner";

export function ConnectScreen({ onConnected }: { onConnected: (c: Connection) => void }) {
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [scanning, setScanning] = useState(false);

  const connect = async (value = link) => {
    const c = parseLink(value);
    if (!c) { setError("That doesn't look like a Doxa link. Copy it from Doxa → Phone access on your PC."); return; }
    setBusy(true); setError("");
    try {
      await api.status(c);
      onConnected(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't connect.");
    } finally {
      setBusy(false);
    }
  };

  const paste = async () => {
    const text = await Clipboard.getStringAsync();
    setLink(text);
    if (parseLink(text)) connect(text);
  };

  return (
    <KeyboardAvoidingView style={styles.wrap} behavior="padding">
      <View style={styles.center}>
        <Orb state={busy ? "thinking" : "idle"} size={150} />
        <Text style={styles.brand}>DOXA</Text>
        <Text style={styles.sub}>δόξα · glory</Text>
        <Text style={styles.help}>On your PC open <Text style={styles.strong}>Doxa → Settings → Phone</Text>, then tap <Text style={styles.strong}>Scan QR code</Text> here and point it at the code.</Text>
        <TextInput value={link} onChangeText={setLink} placeholder="https://…#k=…" placeholderTextColor={colors.muted}
          autoCapitalize="none" autoCorrect={false} style={styles.input} onSubmitEditing={() => connect()} />
        {!!error && <Text style={styles.error}>{error}</Text>}
        <View style={styles.row}>
          <Btn label="Scan QR code" primary onPress={() => setScanning(true)} disabled={busy} />
          <Btn label="Paste link" onPress={paste} disabled={busy} />
          <Btn label={busy ? "Connecting…" : "Connect"} onPress={() => connect()} disabled={busy || !link.trim()} />
        </View>
      </View>
      <QrScanner visible={scanning} onClose={() => setScanning(false)}
        onScanned={(c) => { setScanning(false); setLink(""); void connect(c.base + "/#k=" + c.key); }} />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  brand: { color: colors.gold, fontSize: 30, letterSpacing: 12, fontWeight: "300", marginTop: 26 },
  sub: { color: colors.muted, fontSize: font.small, letterSpacing: 2, marginTop: 4 },
  help: { color: colors.muted, textAlign: "center", fontSize: font.body, lineHeight: 22, marginTop: 28, marginBottom: 14, maxWidth: 320 },
  strong: { color: colors.text, fontWeight: "600" },
  input: { alignSelf: "stretch", color: colors.text, backgroundColor: colors.surface, borderColor: colors.line, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 12, fontSize: font.body },
  error: { color: colors.danger, marginTop: 10, textAlign: "center" },
  row: { flexDirection: "row", gap: 10, marginTop: 16 },
});
