import { useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import Animated, { FadeIn, LinearTransition } from "react-native-reanimated";
import MaterialCommunityIcons from "@expo/vector-icons/MaterialCommunityIcons";
import * as Haptics from "expo-haptics";
import type { CodeState } from "../api";
import { colors, font, radius } from "../theme";
import { AppText as Text, AppTextInput as TextInput } from "./AppText";

type Props = {
  state: CodeState;
  onSend: (task: string, engine: string, fresh: boolean) => Promise<void>;
  onStop: () => void;
};

const ENGINES: [string, string][] = [["auto", "Automatic"], ["codex", "Codex"], ["claude", "Claude Code"]];

/** Code mode on the PC (Codex / Claude Code): live steps, what the agent says, the result, Stop, and follow-ups
 * that continue the same chat. */
export function CodeCard({ state, onSend, onStop }: Props) {
  const job = state.job;
  const [task, setTask] = useState("");
  const [engine, setEngine] = useState("auto");
  const [fresh, setFresh] = useState(false);
  const [busy, setBusy] = useState(false);
  const running = job?.status === "running";
  const tone = !job ? colors.muted : running ? colors.gold : job.status === "done" ? colors.ok : colors.amber;
  const label = !job ? "Code mode" : `${job.name} · ${({ running: "working", done: "done", failed: "problem", stopped: "stopped" } as Record<string, string>)[job.status] ?? job.status}`;

  const send = async () => {
    const text = task.trim();
    if (!text || busy) return;
    setBusy(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    try { await onSend(text, engine, fresh); setTask(""); setFresh(false); } finally { setBusy(false); }
  };

  return (
    <Animated.View entering={FadeIn.duration(200)} layout={LinearTransition.duration(180)} style={styles.card}>
      <View style={styles.header}>
        <View style={[styles.dot, { backgroundColor: tone, shadowColor: tone }]} />
        <Text style={styles.title}>{label}</Text>
        {running ? (
          <Pressable onPress={onStop} android_ripple={{ color: "rgba(255,255,255,0.12)", borderless: true, radius: 18 }} hitSlop={8}
            accessibilityLabel="Stop Code mode">
            <MaterialCommunityIcons name="stop-circle-outline" size={24} color={colors.danger} />
          </Pressable>
        ) : null}
      </View>
      <Text style={styles.goal} numberOfLines={3}>{job ? job.task : "Give Codex or Claude Code a job on your PC: build, fix, reverse-engineer anything."}</Text>
      {job && job.steps.length ? (
        <View style={styles.log}>
          {job.steps.slice(-12).map((step, index) => {
            const says = step.startsWith(job.name + ": ");
            return <Text key={index} style={says ? styles.says : styles.step} numberOfLines={says ? 6 : 2}>
              {says ? step.slice(job.name.length + 2) : "• " + step}
            </Text>;
          })}
        </View>
      ) : null}
      {job?.report ? <View style={[styles.result, { borderLeftColor: tone }]}><Text selectable style={styles.resultText}>{job.report}</Text></View> : null}
      <View style={styles.engines}>
        {ENGINES.filter(([value]) => value === "auto" || value in state.engines).map(([value, name]) => (
          <Pressable key={value} onPress={() => setEngine(value)} style={[styles.chip, engine === value && styles.chipOn]}
            android_ripple={{ color: "rgba(255,255,255,0.10)" }}>
            <Text style={[styles.chipText, engine === value && styles.chipTextOn]}>{name}</Text>
          </Pressable>
        ))}
        <Pressable onPress={() => setFresh(!fresh)} style={[styles.chip, fresh && styles.chipOn]} android_ripple={{ color: "rgba(255,255,255,0.10)" }}>
          <Text style={[styles.chipText, fresh && styles.chipTextOn]}>{fresh ? "✓ New chat" : "New chat"}</Text>
        </Pressable>
      </View>
      <View style={styles.ask}>
        <TextInput value={task} onChangeText={setTask} placeholder={job ? "Tell it what to do next…" : "Describe the job…"}
          placeholderTextColor={colors.muted} style={styles.input} multiline maxLength={20000} />
        <Pressable onPress={send} disabled={!task.trim() || busy} style={[styles.send, (!task.trim() || busy) && { opacity: 0.4 }]}
          android_ripple={{ color: "rgba(0,0,0,0.15)", borderless: true, radius: 22 }} accessibilityLabel="Send to Code mode">
          <MaterialCommunityIcons name="arrow-up" size={22} color={colors.userText} />
        </Pressable>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  card: { marginHorizontal: 16, marginVertical: 8, padding: 16, borderRadius: radius.lg, backgroundColor: colors.surface, gap: 10 },
  header: { flexDirection: "row", alignItems: "center", gap: 10 },
  dot: { width: 9, height: 9, borderRadius: 5, shadowOpacity: 0.9, shadowRadius: 6, shadowOffset: { width: 0, height: 0 } },
  title: { flex: 1, color: colors.text, fontSize: font.body, fontWeight: "600" },
  goal: { color: colors.muted, fontSize: font.small, lineHeight: 19 },
  log: { gap: 4, paddingVertical: 4 },
  step: { color: colors.muted, fontSize: font.tiny + 1, lineHeight: 17 },
  says: { color: colors.text, fontSize: font.small + 1, lineHeight: 20 },
  result: { borderLeftWidth: 3, paddingLeft: 10, paddingVertical: 4 },
  resultText: { color: colors.text, fontSize: font.small + 1, lineHeight: 20 },
  engines: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderRadius: 14, paddingHorizontal: 12, paddingVertical: 6, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.line, overflow: "hidden" },
  chipOn: { backgroundColor: colors.surface2, borderColor: colors.goldDeep },
  chipText: { color: colors.muted, fontSize: font.small },
  chipTextOn: { color: colors.gold, fontWeight: "600" },
  ask: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  input: { flex: 1, maxHeight: 120, minHeight: 44, color: colors.text, backgroundColor: colors.surface2, borderRadius: 22, paddingHorizontal: 14, paddingTop: 11, paddingBottom: 11, fontSize: font.small + 1 },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.gold, alignItems: "center", justifyContent: "center" },
});
