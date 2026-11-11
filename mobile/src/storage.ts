import * as SecureStore from "expo-secure-store";
import type { Connection } from "./api";

const KEY = "doxa.connection";

// The private key lives in the phone's secure keychain, never in plain storage.
export async function loadConnection(): Promise<Connection | null> {
  try {
    const raw = await SecureStore.getItemAsync(KEY);
    return raw ? (JSON.parse(raw) as Connection) : null;
  } catch {
    return null;
  }
}

export async function saveConnection(c: Connection) {
  await SecureStore.setItemAsync(KEY, JSON.stringify(c));
}

export async function forgetConnection() {
  await SecureStore.deleteItemAsync(KEY);
}
