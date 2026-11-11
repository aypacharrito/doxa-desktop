import { useEffect, useRef, useState } from "react";
import { AppState, Image, Modal, Pressable, StyleSheet, useWindowDimensions, View } from "react-native";
import { Gesture, GestureDetector, GestureHandlerRootView } from "react-native-gesture-handler";
import Animated, { runOnJS, useAnimatedStyle, useSharedValue, withTiming } from "react-native-reanimated";
import MaterialCommunityIcons from "@expo/vector-icons/MaterialCommunityIcons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { Connection } from "../api";
import { colors, font } from "../theme";
import { AppText as Text } from "./AppText";

const MAX_ZOOM = 6;

/** Your PC's screen, live (about one picture a second), view only. Pinch to zoom, drag to move, double-tap to zoom
 * in/out; turn the phone sideways for a bigger picture. Zooming asks the PC for a sharper picture. Two images take
 * turns so the next picture loads behind the current one and the view never flashes. */
export function ScreenView({ connection, visible, onClose }: { connection: Connection; visible: boolean; onClose: () => void }) {
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const landscape = width > height;
  const [zoomLevel, setZoomLevel] = useState(1);
  const [frames, setFrames] = useState<[string, string]>(["", ""]);
  const [front, setFront] = useState(0);
  const [time, setTime] = useState("");
  const [error, setError] = useState("");
  const loading = useRef(false);

  const scale = useSharedValue(1), savedScale = useSharedValue(1);
  const tx = useSharedValue(0), ty = useSharedValue(0), savedTx = useSharedValue(0), savedTy = useSharedValue(0);

  const reset = () => {
    "worklet";
    scale.value = withTiming(1); savedScale.value = 1;
    tx.value = withTiming(0); ty.value = withTiming(0); savedTx.value = 0; savedTy.value = 0;
  };
  const pinch = Gesture.Pinch()
    .onUpdate((e) => { scale.value = Math.min(MAX_ZOOM, Math.max(1, savedScale.value * e.scale)); })
    .onEnd(() => {
      savedScale.value = scale.value;
      if (scale.value <= 1.01) reset();
      runOnJS(setZoomLevel)(Math.round(scale.value * 2) / 2);
    });
  const pan = Gesture.Pan().minPointers(1).maxPointers(2)
    .onUpdate((e) => {
      if (scale.value <= 1) return;
      tx.value = savedTx.value + e.translationX;
      ty.value = savedTy.value + e.translationY;
    })
    .onEnd(() => { savedTx.value = tx.value; savedTy.value = ty.value; });
  const doubleTap = Gesture.Tap().numberOfTaps(2).onEnd((e) => {
    if (scale.value > 1.2) { reset(); runOnJS(setZoomLevel)(1); return; }
    const next = 2.5;
    // zoom towards the tapped point
    tx.value = withTiming((width / 2 - e.x) * (next - 1)); ty.value = withTiming((height / 2 - e.y) * (next - 1));
    savedTx.value = (width / 2 - e.x) * (next - 1); savedTy.value = (height / 2 - e.y) * (next - 1);
    scale.value = withTiming(next); savedScale.value = next;
    runOnJS(setZoomLevel)(next);
  });
  const gestures = Gesture.Exclusive(doubleTap, Gesture.Simultaneous(pinch, pan));
  const zoomStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: tx.value }, { translateY: ty.value }, { scale: scale.value }],
  }));

  const pixels = Math.max(width, height) * 2;
  const url = () => `${connection.base}/api/screen?w=${Math.min(2560, Math.round(pixels * Math.min(zoomLevel, 2)))}&t=${Date.now()}`;

  useEffect(() => {
    if (!visible) return;
    const tick = () => {
      if (loading.current || AppState.currentState !== "active") return;
      loading.current = true;
      setFrames((old) => { const next: [string, string] = [...old] as [string, string]; next[1 - front] = url(); return next; });
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, front, zoomLevel]);

  const loaded = (index: number) => {
    loading.current = false;
    setError("");
    if (index !== front) setFront(index);
    setTime(new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" }));
  };

  const image = (index: number) => frames[index] ? (
    <Image key={index} source={{ uri: frames[index], headers: { Authorization: "Bearer " + connection.key } }} fadeDuration={0}
      onLoad={() => loaded(index)} onError={() => { loading.current = false; setError("Can't reach your PC"); }}
      resizeMode="contain" style={[StyleSheet.absoluteFill, { opacity: index === front ? 1 : 0 }]} />
  ) : null;

  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onClose} statusBarTranslucent supportedOrientations={["portrait", "landscape"]}>
      <GestureHandlerRootView style={styles.wrap}>
        <GestureDetector gesture={gestures}>
          <Animated.View style={[styles.frame, zoomStyle]}>{image(0)}{image(1)}</Animated.View>
        </GestureDetector>
        <View pointerEvents="box-none" style={[styles.bar, { top: landscape ? 8 : insets.top + 6, left: insets.left + 10, right: insets.right + 10 }]}>
          <View style={styles.pill}>
            <View style={[styles.live, { backgroundColor: error ? colors.danger : colors.ok }]} />
            <Text style={styles.meta} numberOfLines={1}>{error || (time ? `Your PC · ${time}` : "Connecting…")}</Text>
          </View>
          <View style={{ flex: 1 }} />
          {zoomLevel > 1 ? (
            <Pressable onPress={() => { reset(); setZoomLevel(1); }} style={styles.round} hitSlop={8} accessibilityLabel="Fit to screen"
              android_ripple={{ color: "rgba(255,255,255,0.15)", borderless: true, radius: 22 }}>
              <MaterialCommunityIcons name="fit-to-screen-outline" size={22} color={colors.text} />
            </Pressable>
          ) : null}
          <Pressable onPress={onClose} style={styles.round} hitSlop={8} accessibilityLabel="Close"
            android_ripple={{ color: "rgba(255,255,255,0.15)", borderless: true, radius: 22 }}>
            <MaterialCommunityIcons name="close" size={22} color={colors.text} />
          </Pressable>
        </View>
        {!landscape && zoomLevel === 1 ? (
          <Text style={[styles.tip, { bottom: insets.bottom + 16 }]}>Pinch to zoom · double-tap · turn your phone sideways</Text>
        ) : null}
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#000" },
  frame: { flex: 1 },
  bar: { position: "absolute", flexDirection: "row", alignItems: "center", gap: 10 },
  pill: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 18, backgroundColor: "rgba(15,20,27,0.82)", maxWidth: "70%" },
  live: { width: 8, height: 8, borderRadius: 4 },
  meta: { color: colors.text, fontSize: font.small },
  round: { width: 42, height: 42, borderRadius: 21, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(15,20,27,0.82)", overflow: "hidden" },
  tip: { position: "absolute", alignSelf: "center", color: colors.muted, fontSize: font.small, backgroundColor: "rgba(15,20,27,0.7)", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 14, overflow: "hidden" },
});
