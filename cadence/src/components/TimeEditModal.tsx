/**
 * Time-tracking correction modal — opens when you click the ⏱ icon on a
 * completed-task card. Lets you fix the total worked minutes plus the
 * duration and reason of every pause recorded against that task, for when
 * you forgot to hit Start / Done / Resume at the right moment.
 *
 * Wire shape:
 *   • Total time: PATCH /execution-log/{id} with actual_minutes
 *   • Each pause: PATCH /interruptions/{id} with resumed_at recomputed
 *     from (original paused_at + new duration) + the edited reason
 *
 * Editing paused_at moments directly (the actual clock time the pause
 * started) is intentionally out of scope for v1 — what matters for the
 * weekly report is total time and pause durations, not exact moments.
 */

import { useEffect, useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type InterruptionOut, type TaskOut } from '@/src/api';
import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

interface EditablePause {
  id: number;
  paused_at: string;            // ISO — not edited, used to recompute resumed_at
  durationMin: string;          // editable as string (numeric input)
  reason: string;               // editable
  originalDuration: number;     // for change detection
  originalReason: string;       // for change detection
}

function pauseDurationMin(p: InterruptionOut): number {
  if (!p.resumed_at) return 0;
  return Math.max(0, Math.round(
    (new Date(p.resumed_at).getTime() - new Date(p.paused_at).getTime()) / 60_000
  ));
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
  const [actualMin, setActualMin] = useState<string>('');
  const [originalActualMin, setOriginalActualMin] = useState<number>(0);
  const [pauses, setPauses] = useState<EditablePause[]>([]);

  // Hydrate local edit state once the query returns.
  useEffect(() => {
    if (!timing.data) return;
    if (timing.data.execution_log) {
      setActualMin(String(timing.data.execution_log.actual_minutes));
      setOriginalActualMin(timing.data.execution_log.actual_minutes);
    }
    setPauses(timing.data.interruptions.map((p) => {
      const dur = pauseDurationMin(p);
      return {
        id: p.id,
        paused_at: p.paused_at,
        durationMin: String(dur),
        reason: p.reason,
        originalDuration: dur,
        originalReason: p.reason,
      };
    }));
  }, [timing.data]);

  const save = useMutation({
    mutationFn: async () => {
      // 1. Update execution_log if total changed.
      if (log && parseInt(actualMin, 10) !== originalActualMin) {
        const n = parseInt(actualMin, 10);
        if (!Number.isNaN(n) && n >= 0) {
          await api.patchExecutionLog(log.id, { actual_minutes: n });
        }
      }
      // 2. Update each interruption that changed.
      for (const p of pauses) {
        const newDur = parseInt(p.durationMin, 10);
        const durationChanged =
          !Number.isNaN(newDur) && newDur >= 0 && newDur !== p.originalDuration;
        const reasonChanged = p.reason.trim() !== p.originalReason && p.reason.trim() !== '';

        if (!durationChanged && !reasonChanged) continue;

        const fields: { resumed_at?: string; reason?: string } = {};
        if (durationChanged) {
          const newResumed = new Date(
            new Date(p.paused_at).getTime() + newDur * 60_000,
          ).toISOString();
          fields.resumed_at = newResumed;
        }
        if (reasonChanged) fields.reason = p.reason.trim();
        await api.patchInterruption(p.id, fields);
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

  const totalPauseMin = pauses.reduce((sum, p) => sum + (parseInt(p.durationMin, 10) || 0), 0);

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

              {log ? (
                <View style={s.field}>
                  <Text style={s.label}>TOTAL TIME WORKED</Text>
                  <View style={s.row}>
                    <TextInput
                      value={actualMin}
                      onChangeText={(v) => setActualMin(v.replace(/[^0-9]/g, ''))}
                      style={[s.input, { width: 80, textAlign: 'center' }]}
                      inputMode="numeric"
                    />
                    <Text style={s.unit}>min</Text>
                    <Text style={s.hint}>
                      · originally {originalActualMin}m
                    </Text>
                  </View>
                </View>
              ) : (
                <Text style={s.muted}>
                  This task hasn't been marked done yet — no execution record
                  to edit. Mark it done first, then edit the time.
                </Text>
              )}

              <View style={s.field}>
                <Text style={s.label}>
                  PAUSES ({pauses.length}) · total {totalPauseMin}m
                </Text>
                {pauses.length === 0 ? (
                  <Text style={s.muted}>No pauses recorded on this task.</Text>
                ) : (
                  pauses.map((p, i) => (
                    <View key={p.id} style={s.pauseRow}>
                      <TextInput
                        value={p.reason}
                        onChangeText={(v) => updatePause(i, { reason: v })}
                        placeholder="reason"
                        placeholderTextColor={c.textFaint}
                        style={[s.input, { flex: 1 }]}
                      />
                      <TextInput
                        value={p.durationMin}
                        onChangeText={(v) =>
                          updatePause(i, { durationMin: v.replace(/[^0-9]/g, '') })
                        }
                        style={[s.input, { width: 60, textAlign: 'center' }]}
                        inputMode="numeric"
                      />
                      <Text style={s.unit}>min</Text>
                    </View>
                  ))
                )}
              </View>
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
    maxWidth: 560,
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
  row: { flexDirection: 'row', alignItems: 'center', gap: sp.sm },
  unit: { ...t.taskMeta, color: c.textDim },
  hint: { ...t.taskMeta, color: c.textFaint },

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

  pauseRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.sm,
    paddingVertical: 2,
  },

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
