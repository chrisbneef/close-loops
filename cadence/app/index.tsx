/**
 * Now screen — the keystone. Open the app → see the single next action, hit
 * Start (timer begins) → hit Done (server logs actual_minutes, re-packs,
 * surfaces the next action).
 *
 * Design commitment: refined minimalism with intentional warmth. The display
 * serif (Fraunces) is reserved for the task title — nothing else uses it,
 * so the user's eye always lands on the action first. Everything else is in
 * DM Sans, dim, and visually subordinate.
 *
 * v1 owner_id is hardcoded; auth comes later.
 */

import { useEffect, useState } from 'react';
import {
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type GamificationOut, type NextActionResponse } from '@/src/api';
import { colors, radii, spacing, type } from '@/src/theme';
import { formatTimer, useTimer } from '@/src/timer-store';

const OWNER_ID = 1; // Michael — dev-only constant; replace with auth in Phase 6+
const DEFAULT_POMODORO_MIN = 25;

export default function NowScreen() {
  const queryClient = useQueryClient();
  const [nowMs, setNowMs] = useState(() => Date.now());
  const timer = useTimer();

  // Poll the brain. 30s staleTime in QueryClient + refetch-on-focus means the
  // card stays current when the scheduler reorders things.
  const nextActionQuery = useQuery({
    queryKey: ['next-action', OWNER_ID],
    queryFn: () => api.getNextAction(OWNER_ID),
    refetchInterval: 30_000,
  });

  const gamificationQuery = useQuery({
    queryKey: ['gamification', OWNER_ID],
    queryFn: () => api.getGamification(OWNER_ID),
  });

  const startMutation = useMutation({
    mutationFn: (taskId: number) => api.startTask(taskId),
    onSuccess: (_, taskId) => {
      timer.start(taskId);
      // +5 points awarded server-side; pull the fresh count.
      queryClient.invalidateQueries({ queryKey: ['gamification', OWNER_ID] });
    },
  });

  const doneMutation = useMutation({
    mutationFn: (taskId: number) => api.completeTask(taskId),
    onSuccess: (next) => {
      timer.reset();
      // The /done endpoint returns the new NextAction inline — push it into
      // the query cache so the UI flips immediately, no extra round-trip.
      queryClient.setQueryData<NextActionResponse>(['next-action', OWNER_ID], next);
      // Streak + points changed; refresh the chip.
      queryClient.invalidateQueries({ queryKey: ['gamification', OWNER_ID] });
    },
  });

  // Drive the countdown by re-rendering every 500ms while a task is running.
  // Cheap; cheaper than wiring Reanimated for the digit-style display.
  const taskId = nextActionQuery.data?.current?.id ?? null;
  const isRunning = timer.isRunningFor(taskId);
  useEffect(() => {
    if (!isRunning) return;
    const i = setInterval(() => setNowMs(Date.now()), 500);
    return () => clearInterval(i);
  }, [isRunning]);

  // ----- render branches -----

  if (nextActionQuery.isLoading) {
    return <Centered>Loading…</Centered>;
  }
  if (nextActionQuery.isError) {
    return (
      <Centered>
        <Text style={s.errorTitle}>Can't reach the brain.</Text>
        <Text style={s.errorBody}>
          Is the backend running on{'\n'}
          {'  '}http://localhost:8000?
        </Text>
        <Text style={s.errorHint}>{String(nextActionQuery.error)}</Text>
      </Centered>
    );
  }
  const data = nextActionQuery.data!;
  if (!data.current) {
    return <Empty />;
  }

  const task = data.current;
  const durationMin = Math.min(task.est_minutes, DEFAULT_POMODORO_MIN);
  const remainingMs = timer.remainingMs(durationMin, nowMs);

  return (
    <SafeAreaView style={s.root}>
      <View style={s.header}>
        <Text style={s.wordmarkText}>cadence</Text>
        <GameChip data={gamificationQuery.data} />
      </View>

      <View style={s.center}>
        <Text style={s.meta}>NEXT ACTION</Text>
        <Text style={s.title}>{task.title}</Text>
        {data.why ? <Text style={s.why}>{data.why}</Text> : null}

        <View style={s.timerWrap}>
          <Text style={s.timer}>{formatTimer(remainingMs)}</Text>
          <Text style={s.timerLabel}>
            {isRunning ? 'remaining' : `${durationMin} min`}
          </Text>
        </View>

        {isRunning ? (
          <ActionButton
            label="Done"
            onPress={() => doneMutation.mutate(task.id)}
            disabled={doneMutation.isPending}
            kind="done"
          />
        ) : (
          <ActionButton
            label="Start"
            onPress={() => startMutation.mutate(task.id)}
            disabled={startMutation.isPending}
            kind="start"
          />
        )}
      </View>

      {data.up_next.length > 0 && (
        <View style={s.upNext}>
          <Text style={s.upNextLabel}>UP NEXT</Text>
          {data.up_next.map((t) => (
            <Text key={t.id} style={s.upNextItem} numberOfLines={1}>
              · {t.title}
            </Text>
          ))}
        </View>
      )}
    </SafeAreaView>
  );
}

// ---------- small presentational helpers ----------

function ActionButton({
  label, onPress, disabled, kind,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  kind: 'start' | 'done';
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [
        s.button,
        { backgroundColor: kind === 'done' ? colors.sage : colors.accent },
        pressed && { opacity: 0.85, transform: [{ scale: 0.98 }] },
        disabled && { opacity: 0.5 },
      ]}
    >
      <Text style={s.buttonText}>{label}</Text>
    </Pressable>
  );
}

/**
 * Tiny chip in the header. Two stats only:
 *   ★ N          → total points (lifetime; never decreases)
 *   N-day streak → consecutive days with at least one Done
 *
 * No animation in v1. If the user blinks past it, they still feel the number
 * tick when they look back; we resist the temptation to splash a burst over
 * the action button. Calm, not noisy.
 */
function GameChip({ data }: { data?: GamificationOut }) {
  if (!data || data.points === 0) return null;
  return (
    <View style={s.chip}>
      <Text style={s.chipPoints}>★ {data.points}</Text>
      {data.current_streak > 0 && (
        <>
          <Text style={s.chipDivider}>·</Text>
          <Text style={s.chipStreak}>
            {data.current_streak}-day streak
          </Text>
        </>
      )}
    </View>
  );
}


function Centered({ children }: { children: React.ReactNode }) {
  return (
    <SafeAreaView style={s.root}>
      <View style={[s.center, { gap: spacing.md }]}>
        {typeof children === 'string' ? (
          <Text style={s.loading}>{children}</Text>
        ) : (
          children
        )}
      </View>
    </SafeAreaView>
  );
}

function Empty() {
  return (
    <SafeAreaView style={s.root}>
      <View style={s.header}>
        <Text style={s.wordmarkText}>cadence</Text>
      </View>
      <View style={s.center}>
        <Text style={s.emptyTitle}>You're clear.</Text>
        <Text style={s.emptyBody}>
          Nothing scheduled. Drop a goal into{'\n'}
          POST /ingest and the brain will queue it up.
        </Text>
      </View>
    </SafeAreaView>
  );
}

// ---------- styles ----------

const s = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.bg,
    paddingHorizontal: spacing.lg,
  },
  header: {
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  wordmarkText: {
    ...type.micro,
    color: colors.textFaint,
    textTransform: 'lowercase',
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: colors.surface,
    borderRadius: radii.pill,
  },
  chipPoints: {
    ...type.micro,
    color: colors.accent,
    letterSpacing: 0.5,
  },
  chipDivider: {
    ...type.micro,
    color: colors.textFaint,
  },
  chipStreak: {
    ...type.micro,
    color: colors.text,
    letterSpacing: 0.5,
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'flex-start',
    paddingBottom: spacing.xxl,
  },
  meta: {
    ...type.micro,
    color: colors.accent,
    marginBottom: spacing.md,
  },
  title: {
    ...type.display,
    color: colors.text,
    marginBottom: spacing.md,
  },
  why: {
    ...type.caption,
    color: colors.textDim,
    marginBottom: spacing.xl,
  },
  timerWrap: {
    marginBottom: spacing.xl,
  },
  timer: {
    ...type.timer,
    color: colors.text,
    fontVariant: ['tabular-nums'],
  },
  timerLabel: {
    ...type.micro,
    color: colors.textFaint,
    marginTop: -spacing.sm,
  },
  button: {
    alignSelf: 'stretch',
    paddingVertical: spacing.lg,
    borderRadius: radii.pill,
    alignItems: 'center',
  },
  buttonText: {
    ...type.body,
    color: colors.bg,
    fontFamily: 'DMSans_700Bold',
    letterSpacing: 0.5,
  },
  upNext: {
    paddingBottom: spacing.xl,
    gap: spacing.xs,
  },
  upNextLabel: {
    ...type.micro,
    color: colors.textFaint,
    marginBottom: spacing.sm,
  },
  upNextItem: {
    ...type.caption,
    color: colors.textDim,
  },
  loading: {
    ...type.caption,
    color: colors.textDim,
  },
  errorTitle: {
    ...type.body,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  errorBody: {
    ...type.caption,
    color: colors.textDim,
    marginBottom: spacing.md,
  },
  errorHint: {
    ...type.caption,
    color: colors.textFaint,
    fontStyle: 'italic',
  },
  emptyTitle: {
    ...type.display,
    color: colors.text,
    marginBottom: spacing.md,
  },
  emptyBody: {
    ...type.caption,
    color: colors.textDim,
  },
});
