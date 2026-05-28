/**
 * Phase 6c — register for Expo push notifications, send the token back to
 * the brain.
 *
 * Called once on app load. Idempotent: if the user already granted permission
 * and we already have the token, this is just a re-POST (cheap).
 *
 * Behavior by environment:
 *   - Real device + Expo Go: gets an ExponentPushToken[...] back, POSTs it.
 *   - iOS Simulator / Android emulator: getExpoPushTokenAsync returns null
 *     (no push hardware); we silently bail.
 *   - Web: expo-notifications has no push support; we silently bail.
 *   - Permission denied: bail. The user can grant later via system settings.
 */

import { Platform } from 'react-native';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';

import { api } from '@/src/api';

// Show notifications in-foreground too (otherwise iOS swallows them silently
// when the app is open). Set once at module load.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

export async function registerForPush(ownerId: number): Promise<string | null> {
  if (Platform.OS === 'web') return null;            // no web push via Expo
  if (!Device.isDevice) return null;                 // simulators get no token

  const existing = await Notifications.getPermissionsAsync();
  let status = existing.status;
  if (status !== 'granted') {
    const requested = await Notifications.requestPermissionsAsync();
    status = requested.status;
  }
  if (status !== 'granted') return null;

  // Expo Go does not require a projectId; standalone builds do. Try without
  // first — works for the common Expo Go dev path. If it fails for standalone,
  // pass { projectId: Constants.expoConfig?.extra?.eas?.projectId }.
  const tokenResult = await Notifications.getExpoPushTokenAsync();
  const token = tokenResult.data;
  if (!token) return null;

  try {
    // Goes through the api wrapper so it carries the auth token (the /users
    // route is gated). Called post-login, so the token is present.
    await api.setPushToken(ownerId, token);
  } catch (e) {
    // Brain unreachable — phone still has the token; we'll re-POST on next launch.
    console.warn('failed to register push token with brain:', e);
  }
  return token;
}
