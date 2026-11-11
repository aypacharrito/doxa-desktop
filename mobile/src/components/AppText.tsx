import React from "react";
import { StyleSheet, Text as RNText, TextInput as RNTextInput } from "react-native";

/** Inter is bundled with the app (loaded in App.tsx). One known font everywhere: the same look on every phone, and no
 * cut-off bold labels on phones whose system font makes React Native measure text wrong. Android needs a separate
 * font file per weight, so weights map to families. (React 19: `ref` arrives as an ordinary prop.) */
export const FONT = {
  regular: "Inter_400Regular",
  medium: "Inter_500Medium",
  semibold: "Inter_600SemiBold",
  bold: "Inter_700Bold",
} as const;

export function fontFor(weight: unknown): string {
  const value = weight === "bold" ? 700 : weight === "normal" || weight === undefined ? 400 : Number(weight);
  if (value >= 700) return FONT.bold;
  if (value >= 600) return FONT.semibold;
  if (value >= 500) return FONT.medium;
  return FONT.regular;
}

export function AppText({ style, ...props }: React.ComponentProps<typeof RNText>) {
  const flat = StyleSheet.flatten(style) || {};
  if (flat.fontFamily) return <RNText {...props} style={style} />;
  return <RNText {...props} style={[style, { fontFamily: fontFor(flat.fontWeight), fontWeight: "normal" }]} />;
}

export function AppTextInput({ style, ...props }: React.ComponentProps<typeof RNTextInput>) {
  const flat = StyleSheet.flatten(style) || {};
  return <RNTextInput {...props} style={[style, flat.fontFamily ? null : { fontFamily: fontFor(flat.fontWeight), fontWeight: "normal" }]} />;
}
