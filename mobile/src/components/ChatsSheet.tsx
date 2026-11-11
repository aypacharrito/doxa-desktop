import { Modal, Pressable, ScrollView, StyleSheet } from "react-native";
import Animated, { FadeIn, SlideInLeft } from "react-native-reanimated";
import MaterialCommunityIcons from "@expo/vector-icons/MaterialCommunityIcons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { ChatSummary } from "../api";
import { colors, font } from "../theme";
import { AppText as Text } from "./AppText";

function when(iso: string) {
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return "";
  const date = new Date(ms), now = new Date();
  if (date.toDateString() === now.toDateString()) return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

/** Chats like ChatGPT / Claude: start a new one, or open an earlier one. */
export function ChatsSheet({ visible, chats, currentId, onClose, onNew, onOpen }: {
  visible: boolean; chats: ChatSummary[]; currentId: number | null; onClose: () => void; onNew: () => void;
  onOpen: (chat: ChatSummary) => void;
}) {
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="none" onRequestClose={onClose} statusBarTranslucent>
      <Animated.View entering={FadeIn.duration(150)} style={styles.scrim}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Close chats" />
        <Animated.View entering={SlideInLeft.duration(220)} style={[styles.sheet, { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 12 }]}>
          <Text style={styles.brand}>DOXA</Text>
          <Pressable onPress={onNew} style={styles.newChat} android_ripple={{ color: "rgba(255,255,255,0.10)" }}>
            <MaterialCommunityIcons name="square-edit-outline" size={20} color={colors.gold} />
            <Text style={styles.newText}>New chat</Text>
          </Pressable>
          <Text style={styles.section}>Chats</Text>
          <ScrollView contentContainerStyle={{ paddingBottom: 12 }}>
            {chats.length ? chats.map((chat, index) => {
              const current = currentId === null ? index === 0 : chat.id === currentId;
              return (
                <Pressable key={chat.id} onPress={() => onOpen(chat)} android_ripple={{ color: "rgba(255,255,255,0.08)" }}
                  style={[styles.row, current && styles.rowOn]}>
                  <Text numberOfLines={1} style={[styles.title, current && { color: colors.gold }]}>{chat.title}</Text>
                  <Text style={styles.time}>{when(chat.updated)}</Text>
                </Pressable>
              );
            }) : <Text style={styles.empty}>Your chats will show up here.</Text>}
          </ScrollView>
        </Animated.View>
      </Animated.View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)" },
  sheet: { position: "absolute", top: 0, bottom: 0, left: 0, width: "82%", maxWidth: 360, backgroundColor: colors.surface, paddingHorizontal: 14 },
  brand: { color: colors.gold, letterSpacing: 6, fontSize: font.brand, fontWeight: "500", marginLeft: 8, marginBottom: 14 },
  newChat: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 12, paddingVertical: 12, borderRadius: 14, overflow: "hidden", backgroundColor: colors.surface2 },
  newText: { color: colors.text, fontSize: font.body, fontWeight: "600" },
  section: { color: colors.muted, fontSize: font.tiny, letterSpacing: 1.2, marginTop: 20, marginBottom: 6, marginLeft: 12 },
  row: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, paddingVertical: 12, borderRadius: 12, overflow: "hidden" },
  rowOn: { backgroundColor: colors.surface2 },
  title: { flex: 1, color: colors.text, fontSize: font.body },
  time: { color: colors.muted, fontSize: font.tiny },
  empty: { color: colors.muted, fontSize: font.small, marginLeft: 12, marginTop: 8 },
});
