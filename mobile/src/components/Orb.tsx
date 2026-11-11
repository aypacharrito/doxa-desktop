import { useEffect, useState } from "react";
import { Animated, Easing, StyleSheet, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors } from "../theme";

export type OrbState = "idle" | "thinking" | "working" | "waiting" | "offline";

const PALETTE: Record<OrbState, { core: [string, string]; ring: string; glow: string }> = {
  idle: { core: [colors.goldBright, colors.gold], ring: "rgba(232,194,106,0.55)", glow: colors.gold },
  thinking: { core: ["#FFF4D6", colors.goldBright], ring: "rgba(255,227,161,0.85)", glow: colors.goldBright },
  working: { core: ["#FFF4D6", colors.gold], ring: "rgba(232,194,106,0.9)", glow: colors.gold },
  waiting: { core: ["#FFE0B8", colors.amber], ring: "rgba(255,159,67,0.85)", glow: colors.amber },
  offline: { core: ["#3A4350", "#262D36"], ring: "rgba(80,90,104,0.6)", glow: "transparent" },
};

/** Doxa's presence: breathes when idle, quickens while thinking, glows amber when it needs you. */
export function Orb({ state = "idle", size = 176 }: { state?: OrbState; size?: number }) {
  const [breathe] = useState(() => new Animated.Value(0));
  const [spin] = useState(() => new Animated.Value(0));
  const fast = state === "thinking" || state === "working";

  useEffect(() => {
    if (state === "offline") {
      breathe.setValue(0);
      return;
    }
    const period = fast ? 650 : state === "waiting" ? 900 : 2200;
    const b = Animated.loop(Animated.sequence([
      Animated.timing(breathe, { toValue: 1, duration: period, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      Animated.timing(breathe, { toValue: 0, duration: period, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
    ]));
    const s = Animated.loop(Animated.timing(spin, { toValue: 1, duration: fast ? 2400 : 16000, easing: Easing.linear, useNativeDriver: true }));
    b.start();
    s.start();
    return () => { b.stop(); s.stop(); };
  }, [state, fast, breathe, spin]);

  const p = PALETTE[state];
  const coreScale = breathe.interpolate({ inputRange: [0, 1], outputRange: [0.92, 1.06] });
  const haloOpacity = breathe.interpolate({ inputRange: [0, 1], outputRange: [0.18, 0.42] });
  const rotate = spin.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] });
  const counter = spin.interpolate({ inputRange: [0, 1], outputRange: ["360deg", "0deg"] });
  const ring = (inset: number, extra: object = {}) => ({
    position: "absolute" as const, top: size * inset, left: size * inset, right: size * inset, bottom: size * inset,
    borderRadius: size, borderColor: p.ring, ...extra,
  });

  return (
    <View style={{ width: size, height: size }} accessibilityLabel={`Doxa is ${state}`}>
      <Animated.View style={[ring(-0.08, { borderWidth: 0, backgroundColor: p.glow }), { opacity: haloOpacity, transform: [{ scale: coreScale }] }]} />
      <View style={[ring(0, { borderWidth: StyleSheet.hairlineWidth * 3 })]} />
      <Animated.View style={[ring(0.1, { borderWidth: 1.5, borderStyle: "dashed" }), { transform: [{ rotate }] }]} />
      <Animated.View style={[ring(0.22, { borderWidth: 1, opacity: 0.7 }), { transform: [{ rotate: counter }] }]} />
      <Animated.View style={[ring(0.34, { borderWidth: 0, overflow: "hidden" }), { transform: [{ scale: coreScale }] }]}>
        <LinearGradient colors={p.core} start={{ x: 0.3, y: 0.2 }} end={{ x: 0.8, y: 1 }} style={StyleSheet.absoluteFill} />
      </Animated.View>
    </View>
  );
}
