/**
 * Root layout. Loads custom fonts behind the splash screen, mounts the
 * QueryClient for server state, and renders the single Stack screen
 * (Now is the only screen for Phase 5; Today/Week/Momentum/Together come later).
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
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { registerForPush } from '@/src/notifications';
import { colors } from '@/src/theme';

const OWNER_ID = 1; // matches the Now screen's hardcoded owner; replace with auth later

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
    Fraunces_500Medium,
    Fraunces_700Bold,
    DMSans_400Regular,
    DMSans_500Medium,
    DMSans_700Bold,
  });

  useEffect(() => {
    if (fontsLoaded) SplashScreen.hideAsync().catch(() => {});
  }, [fontsLoaded]);

  // Fire-and-forget push registration. Web/simulators silently bail; real
  // device users see one permission prompt on first launch.
  useEffect(() => {
    registerForPush(OWNER_ID).catch((e) =>
      console.warn('push registration error:', e),
    );
  }, []);

  if (!fontsLoaded) return null;

  return (
    <QueryClientProvider client={queryClient}>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.bg },
        }}
      />
    </QueryClientProvider>
  );
}
