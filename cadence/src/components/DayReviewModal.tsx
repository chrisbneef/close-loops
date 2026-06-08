/**
 * End-of-Day Review modal — opens automatically when the user clicks
 * "END YOUR DAY" on the TODAY rail. Lays out the day chronologically:
 * completed tasks + resolved pauses + meetings, interleaved with any
 * "gaps" the backend detected (unaccounted stretches ≥ 5 minutes).
 *
 * Each gap renders with an inline form: pick task vs pause, type a label,
 * hit save. Saving posts to /day/gaps/fill which creates a Task+ExecutionLog
 * (task) or a free-standing Interruption (pause). The timeline query
 * invalidates so the just-filled gap disappears and a new event row takes
 * its place.
 *
 * Re-openable: a "Review Day" button on the TODAY rail brings this back up
 * any time after End Day has been clicked.
 */

import { useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type DayTimelineGap } from '@/src/api';
import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function fmtMins(mins: number): string {
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

interface MergedRow {
  start: string;
  end: string;
  key: string;
  kind: 'event' | 'gap';
  event?: {
    kind: 'task' | 'pause' | 'meeting';
    title: string;
  };
  gap?: DayTimelineGap;
}

export function DayReviewModal({
  ownerId, onClose,
}: { ownerId: 1 | 2; onClose: () => void }) {
  const qc = useQueryClient();
  const timeline = useQuery({
    queryKey: ['day-timeline', ownerId],
    queryFn: () => api.getDayTimeline(ownerId),
  });

  const data = timeline.data;

  // Merge events + gaps into one chronologically-sorted list.
  const rows: MergedRow[] = [];
  if (data) {
    for (const ev of data.events) {
      rows.push({
        start: ev.start, end: ev.end,
        key: `e-${ev.kind}-${ev.task_id ?? ev.interruption_id ?? ev.start}`,
        kind: 'event',
        event: { kind: ev.kind, title: ev.title },
      });
    }
    for (const g of data.gaps) {
      rows.push({ start: g.start, end: g.end, key: `g-${g.start}`, kind: 'gap', gap: g });
    }
    rows.sort((a, b) => a.start.localeCompare(b.start));
  }

  const totalGapMinutes = data?.gaps.reduce((s, g) => s + g.duration_minutes, 0) ?? 0;
  const focusMinutes = data?.events.reduce((sum, ev) => {
    if (ev.kind !== 'task') return sum;
    return sum + Math.round(
      (new Date(ev.end).getTime() - new Date(ev.start).getTime()) / 60_000,
    );
  }, 0) ?? 0;

  return (
    <View style={s.backdrop}>
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
      <View style={s.modal}>
        <View style={s.head}>
          <View>
            <Text style={s.title}>Day Review</Text>
            {data && (
              <Text style={s.dateLine}>
                {new Date(data.date + 'T00:00:00').toLocaleDateString('en-US', {
                  weekday: 'long', month: 'short', day: 'numeric',
                })}
              </Text>
            )}
          </View>
          <Pressable onPress={onClose} hitSlop={8}>
            <Text style={s.close}>✕</Text>
          </Pressable>
        </View>

        <ScrollView style={s.body} contentContainerStyle={{ gap: sp.xs }}>
          {timeline.isLoading ? (
            <Text style={s.muted}>Loading…</Text>
          ) : timeline.isError ? (
            <Text style={s.muted}>Can't load the day's timeline.</Text>
          ) : rows.length === 0 ? (
            <Text style={s.muted}>
              Nothing logged for today yet. Once you complete tasks and log
              pauses, they'll show up here with any gaps highlighted.
            </Text>
          ) : (
            rows.map((row) =>
              row.kind === 'event' ? (
                <EventRow key={row.key} start={row.start} end={row.end} event={row.event!} />
              ) : (
                <GapRow
                  key={row.key}
                  gap={row.gap!}
                  ownerId={ownerId}
                  onFilled={() => qc.invalidateQueries({ queryKey: ['day-timeline', ownerId] })}
                />
              ),
            )
          )}
        </ScrollView>

        <View style={s.foot}>
          <View style={s.totals}>
            <Text style={s.totalRow}>Focus <Text style={s.totalNum}>{fmtMins(focusMinutes)}</Text></Text>
            <Text style={s.totalRow}>Unaccounted <Text style={s.totalNum}>{fmtMins(totalGapMinutes)}</Text></Text>
          </View>
          <Pressable onPress={onClose} style={s.doneBtn}>
            <Text style={s.doneBtnText}>DONE</Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}

function EventRow({
  start, end, event,
}: { start: string; end: string; event: { kind: 'task' | 'pause' | 'meeting'; title: string } }) {
  const pillBg = event.kind === 'task' ? c.accent : event.kind === 'meeting' ? c.border : c.surfaceElevated;
  const pillFg = event.kind === 'task' ? c.textOnAccent : c.textDim;
  return (
    <View style={[s.row, s.eventRow]}>
      <Text style={s.timeLabel}>{fmtTime(start)} — {fmtTime(end)}</Text>
      <Text style={s.eventTitle} numberOfLines={2}>{event.title}</Text>
      <View style={[s.pill, { backgroundColor: pillBg }]}>
        <Text style={[s.pillText, { color: pillFg }]}>{event.kind}</Text>
      </View>
    </View>
  );
}

function GapRow({
  gap, ownerId, onFilled,
}: {
  gap: DayTimelineGap;
  ownerId: 1 | 2;
  onFilled: () => void;
}) {
  const [kind, setKind] = useState<'task' | 'pause' | null>(null);
  const [label, setLabel] = useState('');

  const fill = useMutation({
    mutationFn: () => api.fillGap({
      owner_id: ownerId,
      start_at: gap.start,
      end_at: gap.end,
      kind: kind!,
      label: label.trim(),
    }),
    onSuccess: () => onFilled(),
  });

  const canSubmit = kind !== null && label.trim().length > 0 && !fill.isPending;

  return (
    <View style={[s.row, s.gapRow]}>
      <Text style={s.timeLabel}>{fmtTime(gap.start)} — {fmtTime(gap.end)}</Text>
      <Text style={s.gapHint}>⚠ {fmtMins(gap.duration_minutes)} unaccounted — what were you doing?</Text>
      <View style={s.gapForm}>
        <View style={s.kindRow}>
          <Pressable
            onPress={() => setKind('task')}
            style={[s.kindBtn, kind === 'task' && s.kindBtnOn]}
          >
            <Text style={[s.kindText, kind === 'task' && s.kindTextOn]}>Task</Text>
          </Pressable>
          <Pressable
            onPress={() => setKind('pause')}
            style={[s.kindBtn, kind === 'pause' && s.kindBtnOn]}
          >
            <Text style={[s.kindText, kind === 'pause' && s.kindTextOn]}>Pause</Text>
          </Pressable>
        </View>
        <TextInput
          value={label}
          onChangeText={setLabel}
          placeholder={kind === 'pause' ? 'pause reason (lunch, kid, slack)' : kind === 'task' ? 'task you did' : 'pick task or pause'}
          placeholderTextColor={c.textFaint}
          style={s.gapInput}
          editable={kind !== null}
          onSubmitEditing={() => canSubmit && fill.mutate()}
        />
        <Pressable
          onPress={() => fill.mutate()}
          disabled={!canSubmit}
          style={({ pressed }) => [
            s.gapSave,
            !canSubmit && s.gapSaveDisabled,
            pressed && canSubmit && { opacity: 0.85 },
          ]}
        >
          <Text style={[s.gapSaveText, !canSubmit && { color: c.textFaint }]}>
            {fill.isPending ? '…' : 'SAVE'}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.55)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: sp.lg,
    zIndex: 100,
  },
  modal: {
    width: '100%',
    maxWidth: 720,
    maxHeight: '90%',
    backgroundColor: c.surface,
    borderRadius: r.lg,
    borderWidth: 1,
    borderColor: c.border,
    overflow: 'hidden',
  },
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: sp.lg,
    paddingVertical: sp.md,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  title: { ...t.hud, color: c.accent, fontSize: 14 },
  dateLine: { ...t.taskMeta, color: c.textDim, marginTop: 2 },
  close: { ...t.subtask, color: c.textDim, fontSize: 18 },
  body: { paddingHorizontal: sp.lg, paddingVertical: sp.md },
  foot: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: sp.sm,
    paddingHorizontal: sp.lg,
    paddingVertical: sp.md,
    borderTopWidth: 1,
    borderTopColor: c.border,
    backgroundColor: c.bg,
  },

  row: {
    paddingVertical: sp.xs,
    paddingHorizontal: sp.sm,
    borderRadius: r.sm,
    gap: sp.xs,
  },
  eventRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.sm,
    backgroundColor: c.bg,
    borderLeftWidth: 3,
    borderLeftColor: c.border,
  },
  timeLabel: { ...t.duration, color: c.textDim, width: 140 },
  eventTitle: { ...t.subtask, color: c.text, flex: 1 },
  pill: {
    paddingHorizontal: sp.sm,
    paddingVertical: 2,
    borderRadius: r.pill,
  },
  pillText: { ...t.micro, fontSize: 9 },

  gapRow: {
    backgroundColor: '#231a0e',
    borderLeftWidth: 3,
    borderLeftColor: c.warning,
  },
  gapHint: { ...t.taskMeta, color: c.warning },
  gapForm: { flexDirection: 'row', gap: sp.xs, alignItems: 'center', flexWrap: 'wrap' },
  kindRow: { flexDirection: 'row', gap: 2 },
  kindBtn: {
    paddingHorizontal: sp.sm,
    paddingVertical: sp.xs,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
  },
  kindBtnOn: { backgroundColor: c.accent, borderColor: c.accent },
  kindText: { ...t.duration, color: c.textDim },
  kindTextOn: { color: c.textOnAccent },
  gapInput: {
    ...t.subtask,
    color: c.text,
    backgroundColor: c.bg,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: sp.sm,
    paddingVertical: sp.xs,
    outlineStyle: 'none' as any,
    flex: 1,
    minWidth: 180,
  },
  gapSave: {
    backgroundColor: c.accent,
    borderRadius: r.sm,
    paddingHorizontal: sp.md,
    paddingVertical: sp.xs,
  },
  gapSaveDisabled: { backgroundColor: c.surfaceElevated },
  gapSaveText: { ...t.button, color: c.textOnAccent },

  totals: { flexDirection: 'row', gap: sp.lg },
  totalRow: { ...t.taskMeta, color: c.textDim },
  totalNum: { fontFamily: 'JetBrainsMono_700Bold', color: c.accent },

  doneBtn: {
    backgroundColor: c.accent,
    borderRadius: r.sm,
    paddingHorizontal: sp.xl,
    paddingVertical: sp.sm,
  },
  doneBtnText: { ...t.button, color: c.textOnAccent },

  muted: { ...t.taskMeta, color: c.textDim },
});
