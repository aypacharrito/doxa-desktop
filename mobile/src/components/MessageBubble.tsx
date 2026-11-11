import { memo } from "react";
import { StyleSheet, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { colors, font, radius } from "../theme";
import { AppText as Text } from "./AppText";

export type ChatItem = { id: string; role: "user" | "assistant"; text: string; note?: string; pending?: boolean; error?: boolean; old?: boolean };

/** New messages slide up softly; history loaded at start appears without animation. */
export const MessageBubble = memo(function MessageBubble({ item }: { item: ChatItem }) {
  const mine = item.role === "user";
  return (
    <Animated.View entering={item.old ? undefined : FadeInDown.duration(220)} style={[styles.row, mine ? styles.right : styles.left]}>
      <View style={[styles.bubble, mine ? styles.user : styles.doxa, item.error && styles.error]}>
        <Text selectable style={[styles.text, mine && styles.userText, item.pending && styles.pending]}>
          {item.text || "…"}
        </Text>
        {!!item.note && <Text style={styles.note}>{item.note}</Text>}
      </View>
    </Animated.View>
  );
});

const styles = StyleSheet.create({
  row: { paddingHorizontal: 14, marginVertical: 4, flexDirection: "row" },
  left: { justifyContent: "flex-start" },
  right: { justifyContent: "flex-end" },
  bubble: { maxWidth: "84%", paddingHorizontal: 15, paddingVertical: 10, borderRadius: radius.lg },
  user: { backgroundColor: colors.userBubble, borderBottomRightRadius: 6 },
  doxa: { backgroundColor: colors.surface, borderBottomLeftRadius: 6 },
  error: { borderWidth: 1, borderColor: colors.danger },
  text: { color: colors.text, fontSize: font.body, lineHeight: 23 },
  userText: { color: colors.userText },
  pending: { color: colors.muted },
  note: { color: colors.muted, fontSize: font.tiny, marginTop: 6, letterSpacing: 0.3 },
});
