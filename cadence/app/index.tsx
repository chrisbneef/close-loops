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

import {
  api,
  type GamificationOut,
  type NextActionResponse,
  type PartnerPresence,
} from '@/src/api';
import { colors, radii, spacing, type } from '@/src/theme';
import { formatTimer, useTimer } from '@/src/timer-store';

// Dev-only owner switcher. In production this is determined by auth (Supabase
// Auth — Phase 8). Two cofounders; pick whichever you're testing as.
const OWNERS = [
  { id: 1, name: 'Michael' },
  { id: 2, name: 'Chris' },
] as const;
const DEFAULT_POMODORO_MIN = 25;

export default function NowScreen() {
  const queryClient = useQueryClient();
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [ownerId, setOwnerId] = useState<1 | 2>(1);
  const timer = useTimer();

  // Poll the brain. 30s staleTime in QueryClient + refetch-on-focus means the
  // card stays current when the scheduler reorders things.
  const nextActionQuery = useQuery({
    queryKey: ['next-action', ownerId],
    queryFn: () => api.getNextAction(ownerId),
    refetchInterval: 30_000,
  });

  const gamificationQuery = useQuery({
    queryKey: ['gamification', ownerId],
    queryFn: () => api.getGamification(ownerId),
  });

  // Body doubling — poll partner's presence every 30s. Ambient, not nagging.
  const partnerQuery = useQuery({
    queryKey: ['partner-presence', ownerId],
    queryFn: () => api.getPartnerPresence(ownerId),
    refetchInterval: 30_000,
  });

  const startMutation = useMutation({
    mutationFn: (taskId: number) => api.startTask(taskId),
    onSuccess: (_, taskId) => {
      timer.start(taskId);
      // +5 points awarded server-side; pull the fresh count.
      queryClient.invalidateQueries({ queryKey: ['gamification', ownerId] });
    },
  });

  const doneMutation = useMutation({
    mutationFn: (taskId: number) => api.completeTask(taskId),
    onSuccess: (next) => {
      timer.reset();
      // The /done endpoint returns the new NextAction inline — push it into
      // the query cache so the UI flips immediately, no extra round-trip.
      queryClient.setQueryData<NextActionResponse>(['next-action', ownerId], next);
      // Streak + points changed; refresh the chip.
      queryClient.invalidateQueries({ queryKey: ['gamification', ownerId] });
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

  // ----- render -----
  // Header + switcher + partner-line are ALWAYS rendered regardless of state
  // so the owner toggle is reachable even when a queue is empty / loading /
  // errored. Only the center body varies.

  const data = nextActionQuery.data;
  const task = data?.current ?? null;
  const durationMin = task ? Math.min(task.est_minutes, DEFAULT_POMODORO_MIN) : DEFAULT_POMODORO_MIN;
  const remainingMs = timer.remainingMs(durationMin, nowMs);

  return (
    <SafeAreaView style={s.root}>
      <View style={s.header}>
        <Text style={s.wordmarkText}>cadence</Text>
        <GameChip data={gamificationQuery.data} />
      </View>

      <OwnerSwitcher active={ownerId} onChange={setOwnerId} />
      <PartnerLine partner={partnerQuery.data} />

      {nextActionQuery.isLoading ? (
        <View style={s.center}>
          <Text style={s.loading}>Loading…</Text>
        </View>
      ) : nextActionQuery.isError ? (
        <View style={s.center}>
          <Text style={s.errorTitle}>Can't reach the brain.</Text>
          <Text style={s.errorBody}>
            Is the backend running on{'\n'}
            {'  '}http://localhost:8000?
          </Text>
          <Text style={s.errorHint}>{String(nextActionQuery.error)}</Text>
        </View>
      ) : !task ? (
        <View style={s.center}>
          <Text style={s.emptyTitle}>You're clear.</Text>
          <Text style={s.emptyBody}>
            Nothing scheduled for this user. Drop a goal into{'\n'}
            POST /ingest, or switch users above.
          </Text>
        </View>
      ) : (
        <>
          <View style={s.center}>
            <Text style={s.meta}>NEXT ACTION</Text>
            <Text style={s.title}>{task.title}</Text>
            {data?.why ? <Text style={s.why}>{data.why}</Text> : null}

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

          {data && data.up_next.length > 0 && (
            <View style={s.upNext}>
              <Text style={s.upNextLabel}>UP NEXT</Text>
              {data.up_next.map((t) => (
                <Text key={t.id} style={s.upNextItem} numberOfLines={1}>
                  · {t.title}
                </Text>
              ))}
            </View>
          )}
        </>
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
 * Dev-only owner switcher. Lets you walk through both cofounders' queues from
 * one browser session. Replace with auth state when Phase 8 lands.
 */
function OwnerSwitcher({
  active, onChange,
}: { active: 1 | 2; onChange: (id: 1 | 2) => void }) {
  return (
    <View style={s.switcher}>
      <Text style={s.switcherLabel}>viewing as</Text>
      {OWNERS.map((o) => (
        <Pressable
          key={o.id}
          onPress={() => onChange(o.id)}
          style={({ pressed }) => [
            s.switcherButton,
            active === o.id && s.switcherButtonActive,
            pressed && { opacity: 0.7 },
          ]}
        >
          <Text style={[s.switcherButtonText, active === o.id && s.switcherButtonTextActive]}>
            {o.name}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

/**
 * Body-doubling presence line. Shows what the OTHER cofounder is doing right
 * now: "chris is heads-down on 'Refactor auth'" or "chris is idle". Hidden
 * when partner is offline / never online / no partner. Ambient awareness,
 * not surveillance — the spec is explicit about this.
 */
function PartnerLine({ partner }: { partner: PartnerPresence | null | undefined }) {
  if (!partner || partner.status === 'offline') return null;
  const name = partner.user_name.toLowerCase();
  if (partner.status === 'focusing' && partner.current_task_title) {
    return (
      <Text style={s.partner} numberOfLines={1}>
        {name} is heads-down on{' '}
        <Text style={s.partnerHighlight}>'{partner.current_task_title}'</Text>
      </Text>
    );
  }
  // status === 'idle' or focusing without a task title
  return (
    <Text style={s.partner} numberOfLines={1}>
      {name} is here
    </Text>
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


// (Centered / Empty wrappers were removed — header + switcher are now always
// rendered inline in NowScreen so the owner toggle stays reachable in every
// state, including loading / error / empty.)

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
  partner: {
    ...type.caption,
    color: colors.textFaint,
    marginBottom: spacing.lg,
  },
  partnerHighlight: {
    color: colors.textDim,
    fontFamily: 'DMSans_500Medium',
  },
  switcher: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.md,
  },
  switcherLabel: {
    ...type.micro,
    color: colors.textFaint,
    marginRight: spacing.sm,
  },
  switcherButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.hairline,
  },
  switcherButtonActive: {
    backgroundColor: colors.surface,
    borderColor: colors.accent,
  },
  switcherButtonText: {
    ...type.micro,
    color: colors.textDim,
  },
  switcherButtonTextActive: {
    color: colors.accent,
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
