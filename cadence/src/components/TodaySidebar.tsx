/**
 * Dashboard TODAY rail — replaces the old next-action list with a unified
 * day timeline of Google Calendar meetings + Cadence-scheduled task blocks.
 *
 * Behavior:
 *   • Before the user clicks "Start Your Day" today: prominent CTA + (if any)
 *     pre-existing meetings already on the calendar.
 *   • After: the day timeline (time | title | meeting/task pill), with a
 *     small "Re-analyze" link at the bottom to repack around new meetings
 *     or freshly-added tasks.
 *
 * Polls /day-plan every 60s so the local-day rollover at midnight (or 5am,
 * whenever the user is back at the dashboard the next morning) flips the
 * CTA back on automatically.
 */

import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type DayPlanItem } from '@/src/api';
import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function fmtDuration(startIso: string, endIso: string): string {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  const m = Math.max(0, Math.round(ms / 60_000));
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h ${rem}m` : `${h}h`;
}

export function TodaySidebar({ ownerId }: { ownerId: 1 | 2 }) {
  const qc = useQueryClient();
  const plan = useQuery({
    queryKey: ['day-plan', ownerId],
    queryFn: () => api.getDayPlan(ownerId),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });

  const startDay = useMutation({
    mutationFn: () => api.startDay(ownerId),
    onSuccess: (next) => {
      qc.setQueryData(['day-plan', ownerId], next);
      qc.invalidateQueries({ queryKey: ['tasks', ownerId] });
    },
  });

  const data = plan.data;

  return (
    <View style={s.root}>
      <View style={s.head}>
        <Text style={s.heading}>TODAY</Text>
        {data && (
          <Text style={s.dateLine}>
            {new Date(data.date + 'T00:00:00').toLocaleDateString('en-US', {
              weekday: 'short', month: 'short', day: 'numeric',
            })}
          </Text>
        )}
      </View>

      {plan.isLoading ? (
        <Text style={s.muted}>Loading…</Text>
      ) : plan.isError ? (
        <Text style={s.muted}>Can't reach the brain.</Text>
      ) : !data?.has_started ? (
        <View style={s.cta}>
          <Text style={s.ctaLead}>Ready for the day?</Text>
          <Text style={s.ctaBody}>
            Dump everything you plan to work on into Up Next, then hit the
            button. We'll pack your real focus blocks around any meetings
            already on your calendar.
          </Text>
          <Pressable
            onPress={() => startDay.mutate()}
            disabled={startDay.isPending}
            style={({ pressed }) => [
              s.ctaBtn,
              startDay.isPending && s.ctaBtnDisabled,
              pressed && !startDay.isPending && { opacity: 0.85 },
            ]}
          >
            {startDay.isPending ? (
              <ActivityIndicator color={c.textOnAccent} />
            ) : (
              <Text style={s.ctaBtnText}>START YOUR DAY</Text>
            )}
          </Pressable>

          {data && data.items.length > 0 && (
            <>
              <Text style={s.subhead}>Already on the calendar</Text>
              <Timeline items={data.items} />
            </>
          )}
        </View>
      ) : data.items.length === 0 ? (
        <View style={s.cta}>
          <Text style={s.muted}>
            Day's started but nothing's scheduled yet. Add some tasks to Up Next
            and hit re-analyze.
          </Text>
          <Pressable
            onPress={() => startDay.mutate()}
            style={({ pressed }) => [s.reanalyzeBtn, pressed && { opacity: 0.85 }]}
          >
            <Text style={s.reanalyzeBtnText}>↻ RE-ANALYZE</Text>
          </Pressable>
        </View>
      ) : (
        <>
          <ScrollView showsVerticalScrollIndicator={false} style={s.scroll}>
            <Timeline items={data.items} />
          </ScrollView>
          <Pressable
            onPress={() => startDay.mutate()}
            style={({ pressed }) => [s.reanalyzeBtn, pressed && { opacity: 0.85 }]}
          >
            <Text style={s.reanalyzeBtnText}>↻ RE-ANALYZE</Text>
          </Pressable>
        </>
      )}
    </View>
  );
}

function Timeline({ items }: { items: DayPlanItem[] }) {
  return (
    <View style={s.timeline}>
      {items.map((item, idx) => (
        <View
          key={`${item.type}-${item.task_id ?? idx}-${item.start}`}
          style={[s.item, item.type === 'task' && s.itemTask]}
        >
          <View style={s.timeColumn}>
            <Text style={s.startTime}>{fmtTime(item.start)}</Text>
            <Text style={s.dur}>{fmtDuration(item.start, item.end)}</Text>
          </View>
          <View style={s.titleColumn}>
            <Text
              style={[s.title, item.type === 'meeting' && s.titleMeeting]}
              numberOfLines={2}
            >
              {item.title}
            </Text>
            <Text style={s.typeTag}>
              {item.type === 'meeting' ? 'meeting' : `task · imp ${item.importance ?? '?'}`}
            </Text>
          </View>
        </View>
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1 },
  head: { marginBottom: sp.md, gap: 2 },
  heading: { ...t.hud, color: c.accent },
  dateLine: { ...t.taskMeta, color: c.textDim },

  cta: {
    gap: sp.sm,
    padding: sp.md,
    backgroundColor: c.surface,
    borderRadius: r.md,
    borderWidth: 1,
    borderColor: c.border,
  },
  ctaLead: { ...t.taskTitle, color: c.text },
  ctaBody: { ...t.taskMeta, color: c.textDim, marginBottom: sp.xs },
  ctaBtn: {
    backgroundColor: c.accent,
    borderRadius: r.md,
    paddingVertical: sp.md,
    alignItems: 'center',
  },
  ctaBtnDisabled: { backgroundColor: c.surfaceElevated },
  ctaBtnText: { ...t.button, color: c.textOnAccent },
  subhead: {
    ...t.micro, color: c.textFaint,
    marginTop: sp.md,
  },

  scroll: { flex: 1 },
  timeline: { gap: sp.xs },
  item: {
    flexDirection: 'row',
    gap: sp.sm,
    paddingVertical: sp.xs,
    paddingHorizontal: sp.sm,
    backgroundColor: c.surface,
    borderRadius: r.sm,
    borderLeftWidth: 3,
    borderLeftColor: c.border,
  },
  itemTask: { borderLeftColor: c.accent },
  timeColumn: { width: 64, gap: 2 },
  startTime: { ...t.duration, color: c.text },
  dur: { ...t.taskMeta, color: c.textFaint, fontSize: 10 },
  titleColumn: { flex: 1, gap: 2 },
  title: { ...t.subtask, color: c.text },
  titleMeeting: { color: c.textDim },
  typeTag: { ...t.taskMeta, color: c.textFaint, fontSize: 10 },

  reanalyzeBtn: {
    marginTop: sp.sm,
    paddingVertical: sp.xs,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
    alignItems: 'center',
  },
  reanalyzeBtnText: { ...t.duration, color: c.textDim },

  muted: { ...t.taskMeta, color: c.textDim },
});
