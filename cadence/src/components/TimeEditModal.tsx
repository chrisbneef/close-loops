/**
 * Time-tracking correction modal — opens when you click the ⏱ icon on a
 * completed-task card. Lets you fix every recorded timestamp on the task:
 * when you Started, when each pause was Paused / Resumed (plus the reason),
 * and when you marked it Completed. The footer shows the derived
 * wall-clock / pauses / focus totals so you can sanity-check your edits.
 *
 * Wire shape:
 *   • Execution log: PATCH /execution-log/{id} with started_at + finished_at
 *     (the handler recomputes actual_minutes from those bounds).
 *   • Each pause:   PATCH /interruptions/{id} with paused_at / resumed_at
 *     and the reason text.
 *
 * Only fields that actually changed are sent — unchanged rows are skipped.
 */

import { useEffect, useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type TaskOut } from '@/src/api';
import { DateTimeField } from '@/src/components/DateTimeField';
import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

interface EditablePause {
  id: number;
  pausedAt: string;
  resumedAt: string;
  reason: string;
  // Originals — used to detect what actually changed and to drive the
  // sparse PATCH payload.
  origPausedAt: string;
  origResumedAt: string;
  origReason: string;
}

function minutesBetween(a: string, b: string): number {
  if (!a || !b) return 0;
  const t1 = new Date(a).getTime();
  const t2 = new Date(b).getTime();
  if (isNaN(t1) || isNaN(t2) || t2 <= t1) return 0;
  return Math.round((t2 - t1) / 60_000);
}

function fmtMins(mins: number): string {
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function TimeEditModal({
  task, onClose,
}: { task: TaskOut; onClose: () => void }) {
  const qc = useQueryClient();
  const timing = useQuery({
    queryKey: ['timing', task.id],
    queryFn: () => api.getTaskTiming(task.id),
  });

  const log = timing.data?.execution_log ?? null;

  // Editable execution-log timestamps.
  const [startedAt, setStartedAt] = useState('');
  const [finishedAt, setFinishedAt] = useState('');
  const [origStartedAt, setOrigStartedAt] = useState('');
  const [origFinishedAt, setOrigFinishedAt] = useState('');

  // Editable pause rows.
  const [pauses, setPauses] = useState<EditablePause[]>([]);

  useEffect(() => {
    if (!timing.data) return;
    if (timing.data.execution_log) {
      setStartedAt(timing.data.execution_log.started_at);
      setFinishedAt(timing.data.execution_log.finished_at);
      setOrigStartedAt(timing.data.execution_log.started_at);
      setOrigFinishedAt(timing.data.execution_log.finished_at);
    }
    setPauses(timing.data.interruptions.map((p) => ({
      id: p.id,
      pausedAt: p.paused_at,
      resumedAt: p.resumed_at ?? '',
      reason: p.reason,
      origPausedAt: p.paused_at,
      origResumedAt: p.resumed_at ?? '',
      origReason: p.reason,
    })));
  }, [timing.data]);

  const save = useMutation({
    mutationFn: async () => {
      // 1. Execution log if either bound moved.
      if (log) {
        const fields: { started_at?: string; finished_at?: string } = {};
        if (startedAt !== origStartedAt) fields.started_at = startedAt;
        if (finishedAt !== origFinishedAt) fields.finished_at = finishedAt;
        if (Object.keys(fields).length > 0) {
          await api.patchExecutionLog(log.id, fields);
        }
      }
      // 2. Each pause: only send the fields that changed.
      for (const p of pauses) {
        const fields: { paused_at?: string; resumed_at?: string; reason?: string } = {};
        if (p.pausedAt !== p.origPausedAt) fields.paused_at = p.pausedAt;
        if (p.resumedAt !== p.origResumedAt && p.resumedAt) fields.resumed_at = p.resumedAt;
        if (p.reason.trim() !== p.origReason && p.reason.trim() !== '') {
          fields.reason = p.reason.trim();
        }
        if (Object.keys(fields).length > 0) {
          await api.patchInterruption(p.id, fields);
        }
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', task.owner_id] });
      qc.invalidateQueries({ queryKey: ['next-action', task.owner_id] });
      qc.invalidateQueries({ queryKey: ['timing', task.id] });
      onClose();
    },
  });

  const updatePause = (idx: number, patch: Partial<EditablePause>) =>
    setPauses((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)));

  // Derived totals. Wall clock = end - start; pauses sum durations; focus =
  // wall clock minus pause total (clamped to non-negative).
  const wallClock = minutesBetween(startedAt, finishedAt);
  const totalPause = pauses.reduce(
    (sum, p) => sum + minutesBetween(p.pausedAt, p.resumedAt), 0,
  );
  const focus = Math.max(0, wallClock - totalPause);

  return (
    <View style={s.backdrop}>
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
      <View style={s.modal}>
        <View style={s.head}>
          <Text style={s.title}>Edit Time</Text>
          <Pressable onPress={onClose} hitSlop={8}>
            <Text style={s.close}>✕</Text>
          </Pressable>
        </View>

        <ScrollView style={s.body} contentContainerStyle={{ gap: sp.md }}>
          {timing.isLoading ? (
            <Text style={s.muted}>Loading…</Text>
          ) : timing.isError ? (
            <Text style={s.muted}>Can't load timing.</Text>
          ) : (
            <>
              <Text style={s.taskLine} numberOfLines={2}>{task.title}</Text>

              {!log ? (
                <Text style={s.muted}>
                  This task hasn't been marked done yet — no execution record
                  to edit. Mark it done first, then edit the time.
                </Text>
              ) : (
                <>
                  <View style={s.field}>
                    <Text style={s.label}>STARTED AT</Text>
                    <DateTimeField value={startedAt} onChange={setStartedAt} />
                  </View>

                  {pauses.map((p, i) => {
                    const dur = minutesBetween(p.pausedAt, p.resumedAt);
                    return (
                      <View key={p.id} style={s.pauseBlock}>
                        <View style={s.pauseHead}>
                          <Text style={s.label}>PAUSE {i + 1}</Text>
                          <Text style={s.pauseDur}>{fmtMins(dur)}</Text>
                        </View>
                        <View style={s.field}>
                          <Text style={s.sublabel}>Reason</Text>
                          <TextInput
                            value={p.reason}
                            onChangeText={(v) => updatePause(i, { reason: v })}
                            placeholder="why did you pause?"
                            placeholderTextColor={c.textFaint}
                            style={s.input}
                          />
                        </View>
                        <View style={s.field}>
                          <Text style={s.sublabel}>Paused at</Text>
                          <DateTimeField
                            value={p.pausedAt}
                            onChange={(v) => updatePause(i, { pausedAt: v })}
                          />
                        </View>
                        <View style={s.field}>
                          <Text style={s.sublabel}>Resumed at</Text>
                          <DateTimeField
                            value={p.resumedAt}
                            onChange={(v) => updatePause(i, { resumedAt: v })}
                          />
                        </View>
                      </View>
                    );
                  })}

                  {pauses.length === 0 && (
                    <Text style={s.muted}>No pauses recorded on this task.</Text>
                  )}

                  <View style={s.field}>
                    <Text style={s.label}>COMPLETED AT</Text>
                    <DateTimeField value={finishedAt} onChange={setFinishedAt} />
                  </View>

                  <View style={s.totals}>
                    <Text style={s.totalRow}>
                      Wall clock <Text style={s.totalNum}>{fmtMins(wallClock)}</Text>
                    </Text>
                    <Text style={s.totalRow}>
                      Pauses <Text style={s.totalNum}>{fmtMins(totalPause)}</Text>
                    </Text>
                    <Text style={[s.totalRow, s.totalFocus]}>
                      Focus <Text style={s.totalNum}>{fmtMins(focus)}</Text>
                    </Text>
                  </View>
                </>
              )}
            </>
          )}
        </ScrollView>

        <View style={s.foot}>
          <Pressable onPress={onClose} style={s.cancel}>
            <Text style={s.cancelText}>Cancel</Text>
          </Pressable>
          <Pressable
            onPress={() => save.mutate()}
            disabled={save.isPending || !log}
            style={({ pressed }) => [
              s.submit,
              (save.isPending || !log) && s.submitDisabled,
              pressed && !save.isPending && log && { opacity: 0.85 },
            ]}
          >
            <Text style={[s.submitText, (save.isPending || !log) && { color: c.textFaint }]}>
              {save.isPending ? 'SAVING…' : 'SAVE'}
            </Text>
          </Pressable>
        </View>
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
    maxWidth: 640,
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
  close: { ...t.subtask, color: c.textDim, fontSize: 18 },
  body: { paddingHorizontal: sp.lg, paddingVertical: sp.md },
  foot: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: sp.sm,
    paddingHorizontal: sp.lg,
    paddingVertical: sp.md,
    borderTopWidth: 1,
    borderTopColor: c.border,
    backgroundColor: c.bg,
  },

  taskLine: { ...t.taskTitle, color: c.text },

  field: { gap: sp.xs },
  label: { ...t.micro, color: c.textFaint },
  sublabel: { ...t.micro, color: c.textFaint, fontSize: 9 },

  input: {
    ...t.subtask,
    color: c.text,
    backgroundColor: c.bg,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: sp.sm,
    paddingVertical: sp.xs,
    outlineStyle: 'none' as any,
  },

  pauseBlock: {
    gap: sp.xs,
    padding: sp.sm,
    borderRadius: r.md,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.bg,
  },
  pauseHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  pauseDur: { ...t.duration, color: c.textDim },

  totals: {
    marginTop: sp.sm,
    paddingTop: sp.sm,
    borderTopWidth: 1,
    borderTopColor: c.border,
    gap: 2,
  },
  totalRow: { ...t.taskMeta, color: c.textDim },
  totalFocus: { ...t.taskTitle, color: c.text, marginTop: sp.xs },
  totalNum: { fontFamily: 'JetBrainsMono_700Bold', color: c.accent },

  cancel: { paddingHorizontal: sp.lg, paddingVertical: sp.sm, borderRadius: r.sm },
  cancelText: { ...t.button, color: c.textDim },
  submit: {
    backgroundColor: c.accent,
    borderRadius: r.sm,
    paddingHorizontal: sp.xl,
    paddingVertical: sp.sm,
  },
  submitDisabled: { backgroundColor: c.surfaceElevated },
  submitText: { ...t.button, color: c.textOnAccent },

  muted: { ...t.taskMeta, color: c.textDim },
});
