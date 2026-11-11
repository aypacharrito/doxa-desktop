import { useRef, useState } from "react";
import { Modal, Pressable, StyleSheet, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import MaterialCommunityIcons from "@expo/vector-icons/MaterialCommunityIcons";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { parseAppLink, parseLink, type Connection } from "../api";
import { colors, font } from "../theme";
import { AppText as Text } from "./AppText";

/** Scan the QR code from Doxa → Settings → Phone on the PC (like linking WhatsApp to a computer). The phone's own
 * camera would open that https link in the browser; scanning here connects this app instead. */
export function QrScanner({ visible, onClose, onScanned }: { visible: boolean; onClose: () => void; onScanned: (c: Connection) => void }) {
  const [permission, requestPermission] = useCameraPermissions();
  const [note, setNote] = useState("");
  const done = useRef(false);
  const insets = useSafeAreaInsets();

  const scanned = (data: string) => {
    if (done.current) return;
    const connection = parseLink(data) || parseAppLink(data);
    if (!connection) { setNote("That QR code isn't a Doxa link. Use the one in Doxa → Settings → Phone on your PC."); return; }
    done.current = true;
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    onScanned(connection);
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} onShow={() => { done.current = false; setNote(""); }}
      statusBarTranslucent>
      <View style={[styles.wrap, { paddingTop: insets.top, paddingBottom: insets.bottom + 16 }]}>
        <View style={styles.bar}>
          <Text style={styles.title}>Scan the code on your PC</Text>
          <Pressable onPress={onClose} hitSlop={10} accessibilityLabel="Close"
            android_ripple={{ color: "rgba(255,255,255,0.12)", borderless: true, radius: 20 }}>
            <MaterialCommunityIcons name="close" size={24} color={colors.text} />
          </Pressable>
        </View>
        {permission?.granted ? (
          <View style={styles.cameraBox}>
            <CameraView style={StyleSheet.absoluteFill} facing="back" barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
              onBarcodeScanned={({ data }) => scanned(data)} />
            <View pointerEvents="none" style={styles.frame} />
          </View>
        ) : (
          <View style={styles.ask}>
            <MaterialCommunityIcons name="qrcode-scan" size={56} color={colors.gold} />
            <Text style={styles.help}>{"Doxa needs the camera to read the QR code on your PC. It's used only for this."}</Text>
            <Pressable onPress={requestPermission} style={styles.allow} android_ripple={{ color: "rgba(0,0,0,0.15)" }}>
              <Text style={styles.allowText}>Allow camera</Text>
            </Pressable>
          </View>
        )}
        <Text style={styles.help}>{note || "On your PC open Doxa → Settings → Phone. If there's no QR code, press Create new link."}</Text>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.bg },
  bar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 18, paddingVertical: 14 },
  title: { color: colors.text, fontSize: font.body + 1, fontWeight: "600" },
  cameraBox: { flex: 1, marginHorizontal: 16, borderRadius: 24, overflow: "hidden", backgroundColor: "#000", alignItems: "center", justifyContent: "center" },
  frame: { width: 240, height: 240, borderRadius: 24, borderWidth: 3, borderColor: colors.gold },
  ask: { flex: 1, alignItems: "center", justifyContent: "center", gap: 18, padding: 24 },
  help: { color: colors.muted, fontSize: font.small + 1, lineHeight: 20, textAlign: "center", marginTop: 14, paddingHorizontal: 28 },
  allow: { backgroundColor: colors.gold, borderRadius: 24, paddingHorizontal: 22, paddingVertical: 12, overflow: "hidden" },
  allowText: { color: colors.userText, fontWeight: "600", fontSize: font.body },
});
