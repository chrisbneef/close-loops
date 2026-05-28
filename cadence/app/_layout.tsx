/**
 * Root layout. Loads custom fonts + hydrates the auth session behind the splash
 * screen, mounts the QueryClient, and gates every app surface behind login via
 * Stack.Protected: when there's no token the only reachable screen is /login;
 * once a token exists the Now / dashboard / widget screens unlock and the
 * router routes into the app automatically.
 */

import { useEffect } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import * as SplashScreen from 'expo-splash-screen';
import {
  Fraunces_500Medium,
  Fraunces_700Bold,
  useFonts,
} from '@expo-google-fonts/fraunces';
import {
  DMSans_400Regular,
  DMSans_500Medium,
  DMSans_700Bold,
} from '@expo-google-fonts/dm-sans';
import {
  JetBrainsMono_500Medium,
  JetBrainsMono_700Bold,
} from '@expo-google-fonts/jetbrains-mono';
import {
  Sora_400Regular,
  Sora_600SemiBold,
  Sora_700Bold,
} from '@expo-google-fonts/sora';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useAuth } from '@/src/auth-store';
import { registerForPush } from '@/src/notifications';
import { colors } from '@/src/theme';

SplashScreen.preventAutoHideAsync().catch(() => {});

// One QueryClient for the app's lifetime. 30-second stale time matches the
// scheduler tick cadence so the Now screen auto-refreshes the next task
// roughly when the backend re-packs.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, refetchOnWindowFocus: true, retry: 1 },
  },
});

export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    // Mobile Now screen — warm minimalism
    Fraunces_500Medium,
    Fraunces_700Bold,
    DMSans_400Regular,
    DMSans_500Medium,
    DMSans_700Bold,
    // Widget surface — gamer/HUD direction
    JetBrainsMono_500Medium,
    JetBrainsMono_700Bold,
    Sora_400Regular,
    Sora_600SemiBold,
    Sora_700Bold,
  });

  const hydrated = useAuth((s) => s.hydrated);
  const hydrate = useAuth((s) => s.hydrate);
  const userId = useAuth((s) => s.user?.id ?? null);
  const isAuthed = useAuth((s) => !!s.token);

  // Read the stored token back once on launch.
  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  const ready = fontsLoaded && hydrated;
  useEffect(() => {
    if (ready) SplashScreen.hideAsync().catch(() => {});
  }, [ready]);

  // Register for push only once we know who's logged in. Web/simulators bail
  // silently; real devices see one permission prompt.
  useEffect(() => {
    if (userId == null) return;
    registerForPush(userId).catch((e) =>
      console.warn('push registration error:', e),
    );
  }, [userId]);

  if (!ready) return null;

  return (
    <QueryClientProvider client={queryClient}>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.bg },
        }}
      >
        <Stack.Protected guard={isAuthed}>
          <Stack.Screen name="index" />
          <Stack.Screen name="dashboard" />
          <Stack.Screen name="widget" />
        </Stack.Protected>
        <Stack.Protected guard={!isAuthed}>
          <Stack.Screen name="login" />
        </Stack.Protected>
      </Stack>
    </QueryClientProvider>
  );
}
