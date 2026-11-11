import * as Notifications from "expo-notifications";
import { AndroidImportance } from "expo-notifications";
import * as Device from "expo-device";
import Constants from "expo-constants";
import { Platform } from "react-native";
import { api, type Connection } from "./api";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false,
  }),
});

/** Ask once, then tell the PC where to send "Doxa needs your OK" alerts. Best-effort. */
export async function registerForPush(c: Connection): Promise<string> {
  if (!Device.isDevice) return "Notifications need a real phone.";
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("doxa", {
      name: "Doxa", importance: AndroidImportance.HIGH, lightColor: "#E8C26A",
    });
  }
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== "granted") status = (await Notifications.requestPermissionsAsync()).status;
  if (status !== "granted") return "Notifications are off for Doxa.";
  const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  try {
    const token = (await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined)).data;
    await api.registerPush(c, token);
    return "";
  } catch {
    return "Notifications aren't available in this build yet.";
  }
}
