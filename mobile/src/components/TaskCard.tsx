import { useState } from "react";
import { Pressable, StyleSheet, Switch, View } from "react-native";
import { AppText as Text, AppTextInput as TextInput } from "./AppText";
import * as Haptics from "expo-haptics";
import type { BrowserState } from "../api";
import { colors, font, radius } from "../theme";

type Props = { state: BrowserState; onRespond: (id: string, value: unknown) => Promise<void> };

/** Live browser task: progress, plus Doxa's questions and approval requests. */
export function TaskCard({ state, onRespond }: Props) {
  const p = state.pending;
  const [answer, setAnswer] = useState("");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  // A new request clears the form (adjusting state during render, per React docs).
  const [shownId, setShownId] = useState(p?.id);
  if (shownId !== p?.id) { setShownId(p?.id); setAnswer(""); setRemember(false); setBusy(false); }

  const send = async (value: unknown) => {
    if (!p || busy) return;
    setBusy(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    try { await onRespond(p.id, value); } finally { setBusy(false); }
  };

  const status = state.running
    ? p ? "Needs you" : state.paused ? "Paused" : "Working"
    : state.result ? ({ completed: "Done", needs_input: "Needs you", stopped: "Stopped", error: "Couldn't finish" } as Record<string, string>)[state.result.status] ?? state.result.status
    : "";
  const tone = state.running ? (p ? colors.amber : colors.gold) : state.result?.status === "completed" ? colors.ok : colors.amber;

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <View style={[styles.dot, { backgroundColor: tone, shadowColor: tone }]} />
        <Text style={styles.title}>Browser task · {status}</Text>
      </View>
      <Text style={styles.goal} numberOfLines={3}>{state.task}</Text>
      {state.result?.message ? (
        <View style={[styles.result, { borderLeftColor: tone }]}><Text selectable style={styles.resultText}>{state.result.message}</Text></View>
      ) : null}
      {state.log.slice(-3).map((line, i) => <Text key={i} style={styles.log} numberOfLines={2}>{line}</Text>)}

      {p && (
        <View style={styles.pending}>
          {p.kind === "ask" && (
            <>
              <Text style={styles.prompt}>{p.text}</Text>
              <TextInput value={answer} onChangeText={setAnswer} placeholder="Your answer" placeholderTextColor={colors.muted}
                style={styles.input} autoFocus returnKeyType="send" onSubmitEditing={() => answer.trim() && send([answer.trim(), remember])} />
              <View style={styles.rememberRow}>
                <Switch value={remember} onValueChange={setRemember} trackColor={{ true: colors.goldDeep, false: colors.line }} thumbColor={remember ? colors.gold : colors.muted} />
                <Text style={styles.muted}>Remember for next time</Text>
              </View>
              <Row>
                <Btn label="Answer" primary disabled={!answer.trim() || busy} onPress={() => send([answer.trim(), remember])} />
                <Btn label="Skip" onPress={() => send(null)} disabled={busy} />
              </Row>
            </>
          )}
          {p.kind === "confirm" && (
            <>
              <Text style={styles.prompt}>Approve? {p.title}</Text>
              <Text selectable style={styles.details}>{p.body}</Text>
              <Row>
                <Btn label="Approve" primary disabled={busy} onPress={() => send(true)} />
                <Btn label="Decline" danger disabled={busy} onPress={() => send(false)} />
              </Row>
            </>
          )}
          {p.kind === "hand_off" && (
            <>
              <Text style={styles.prompt}>Your turn at the PC</Text>
              <Text style={styles.details}>{p.text}</Text>
              <Row>
                <Btn label="Done — continue" primary disabled={busy} onPress={() => send(true)} />
                <Btn label="Stop task" disabled={busy} onPress={() => send(false)} />
              </Row>
            </>
          )}
        </View>
      )}
    </View>
  );
}

const Row = ({ children }: { children: React.ReactNode }) => <View style={styles.row}>{children}</View>;

export function Btn({ label, onPress, primary, danger, disabled }: { label: string; onPress: () => void; primary?: boolean; danger?: boolean; disabled?: boolean }) {
  return (
    <Pressable onPress={onPress} disabled={disabled} hitSlop={6}
      style={({ pressed }) => [styles.btn, primary && styles.btnPrimary, danger && styles.btnDanger, (pressed || disabled) && { opacity: disabled ? 0.45 : 0.8 }]}>
      <Text style={[styles.btnText, primary && styles.btnPrimaryText, danger && { color: colors.danger }]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { marginHorizontal: 16, marginVertical: 8, padding: 16, borderRadius: radius.lg, backgroundColor: colors.surface, borderColor: colors.line, borderWidth: StyleSheet.hairlineWidth },
  header: { flexDirection: "row", alignItems: "center", gap: 8 },
  dot: { width: 9, height: 9, borderRadius: 5, shadowOpacity: 0.9, shadowRadius: 6, shadowOffset: { width: 0, height: 0 } },
  title: { color: colors.text, fontWeight: "600", fontSize: font.body },
  goal: { color: colors.muted, fontSize: font.small, marginTop: 6, marginBottom: 6 },
  result: { backgroundColor: colors.surface2, borderRadius: radius.sm, padding: 10, borderLeftWidth: 3, marginVertical: 6 },
  resultText: { color: colors.text, fontSize: font.body },
  log: { color: colors.muted, fontSize: font.small, marginTop: 2 },
  pending: { marginTop: 12, paddingTop: 12, borderTopColor: colors.line, borderTopWidth: StyleSheet.hairlineWidth },
  prompt: { color: colors.text, fontWeight: "600", fontSize: font.body, marginBottom: 8 },
  details: { color: colors.muted, fontSize: font.small, lineHeight: 19, backgroundColor: colors.surface2, padding: 10, borderRadius: radius.sm },
  input: { color: colors.text, backgroundColor: colors.surface2, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10, fontSize: font.body, borderColor: colors.line, borderWidth: StyleSheet.hairlineWidth },
  rememberRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8 },
  muted: { color: colors.muted, fontSize: font.small },
  row: { flexDirection: "row", gap: 10, marginTop: 12, flexWrap: "wrap" },
  btn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm, borderColor: colors.line, borderWidth: 1, backgroundColor: colors.surface2 },
  btnPrimary: { backgroundColor: colors.gold, borderColor: colors.gold },
  btnDanger: { borderColor: "rgba(255,95,87,0.5)" },
  btnText: { color: colors.text, fontWeight: "600" },
  btnPrimaryText: { color: colors.userText },
});
