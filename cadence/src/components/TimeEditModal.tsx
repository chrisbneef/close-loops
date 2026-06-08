/**
 * Time-tracking correction modal — the dashboard's ⏱ icon (now on every
 * Done / In Progress / Paused card) opens this. Acts as a full daily
 * time-card for the task:
 *
 *   STARTED AT      [calendar pill] [HH:MM]
 *   PAUSE 1 · 12m   [reason]
 *     Paused / Resumed timestamps
 *   PAUSE 2 · 18m   …
 *   COMPLETED AT    [calendar pill] [HH:MM]   ← only when task is done
 *
 *   [+ Add a pause]                            ← retroactive punch
 *
 *   Wall clock / Pauses / Focus                ← computed totals
 *
 * Wire shape:
 *   • Existing pauses: PATCH /interruptions/{id}
 *   • New pauses:      POST  /tasks/{taskId}/interruptions
 *   • Execution log:   PATCH /execution-log/{id}   (when done)
 *   • Task start time: PATCH /tasks/{id}           (when in-progress/paused)
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

interface ExistingPause {
  kind: 'existing';
  id: number;
  pausedAt: string;
  resumedAt: string;
  reason: string;
  origPausedAt: string;
  origResumedAt: string;
  origReason: string;
}

interface NewPause {
  kind: 'new';
  // Local key used only for React's list reconciliation.
  localKey: number;
  pausedAt: string;
  resumedAt: string;
  reason: string;
}

type EditablePause = ExistingPause | NewPause;

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

let nextLocalKey = 1;

export function TimeEditModal({
  task, onClose,
}: { task: TaskOut; onClose: () => void }) {
  const qc = useQueryClient();
  const timing = useQuery({
    queryKey: ['timing', task.id],
    queryFn: () => api.getTaskTiming(task.id),
  });

  const log = timing.data?.execution_log ?? null;
  const isDone = !!log;

  const [startedAt, setStartedAt] = useState('');
  const [finishedAt, setFinishedAt] = useState('');
  const [origStartedAt, setOrigStartedAt] = useState('');
  const [origFinishedAt, setOrigFinishedAt] = useState('');
  const [pauses, setPauses] = useState<EditablePause[]>([]);

  useEffect(() => {
    if (!timing.data) return;
    const initialStart = timing.data.execution_log?.started_at
      ?? timing.data.task_started_at
      ?? '';
    const initialEnd = timing.data.execution_log?.finished_at ?? '';
    setStartedAt(initialStart);
    setFinishedAt(initialEnd);
    setOrigStartedAt(initialStart);
    setOrigFinishedAt(initialEnd);
    setPauses(timing.data.interruptions.map<ExistingPause>((p) => ({
      kind: 'existing',
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
      // 1. Save the start/end timestamps. Path depends on whether the task
      //    is done (has an execution_log) or still in-progress/paused.
      if (log) {
        const fields: { started_at?: string; finished_at?: string } = {};
        if (startedAt !== origStartedAt) fields.started_at = startedAt;
        if (finishedAt !== origFinishedAt) fields.finished_at = finishedAt;
        if (Object.keys(fields).length > 0) {
          await api.patchExecutionLog(log.id, fields);
        }
      } else if (startedAt && startedAt !== origStartedAt) {
        // In-progress / paused task — write to Task.started_at directly.
        await api.patchTask(task.id, { started_at: startedAt });
      }

      // 2. Pauses. Existing → PATCH if anything changed. New → POST.
      for (const p of pauses) {
        if (p.kind === 'existing') {
          const fields: { paused_at?: string; resumed_at?: string; reason?: string } = {};
          if (p.pausedAt !== p.origPausedAt) fields.paused_at = p.pausedAt;
          if (p.resumedAt !== p.origResumedAt && p.resumedAt) fields.resumed_at = p.resumedAt;
          if (p.reason.trim() !== p.origReason && p.reason.trim() !== '') {
            fields.reason = p.reason.trim();
          }
          if (Object.keys(fields).length > 0) {
            await api.patchInterruption(p.id, fields);
          }
        } else {
          // New pause — needs both paused_at + reason at minimum.
          if (!p.pausedAt || !p.reason.trim()) continue;
          await api.addInterruption(task.id, {
            paused_at: p.pausedAt,
            ...(p.resumedAt ? { resumed_at: p.resumedAt } : {}),
            reason: p.reason.trim(),
          });
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
    setPauses((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } as EditablePause : p)));

  const addBlankPause = () =>
    setPauses((prev) => [
      ...prev,
      {
        kind: 'new',
        localKey: nextLocalKey++,
        pausedAt: '',
        resumedAt: '',
        reason: '',
      },
    ]);

  // Totals.
  const wallClock = minutesBetween(startedAt, finishedAt || new Date().toISOString());
  const totalPause = pauses.reduce(
    (sum, p) => sum + minutesBetween(p.pausedAt, p.resumedAt), 0,
  );
  const focus = Math.max(0, wallClock - totalPause);

  // Friendly badge.
  const statusBadge = isDone
    ? 'DONE'
    : task.status === 'in_progress'
      ? 'IN PROGRESS'
      : task.status === 'paused'
        ? 'PAUSED'
        : task.status.toUpperCase();

  return (
    <View style={s.backdrop}>
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
      <View style={s.modal}>
        <View style={s.head}>
          <View>
            <Text style={s.title}>Edit Time</Text>
            <Text style={s.statusBadge}>{statusBadge}</Text>
          </View>
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

              <View style={s.field}>
                <Text style={s.label}>STARTED AT</Text>
                <DateTimeField value={startedAt} onChange={setStartedAt} />
              </View>

              {pauses.map((p, i) => {
                const dur = minutesBetween(p.pausedAt, p.resumedAt);
                return (
                  <View
                    key={p.kind === 'existing' ? `e-${p.id}` : `n-${p.localKey}`}
                    style={s.pauseBlock}
                  >
                    <View style={s.pauseHead}>
                      <Text style={s.label}>
                        PAUSE {i + 1}{p.kind === 'new' ? ' · new' : ''}
                      </Text>
                      <Text style={s.pauseDur}>{p.resumedAt ? fmtMins(dur) : 'still open'}</Text>
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
                      <Text style={s.sublabel}>Resumed at (leave blank if still paused)</Text>
                      <DateTimeField
                        value={p.resumedAt}
                        onChange={(v) => updatePause(i, { resumedAt: v })}
                      />
                    </View>
                  </View>
                );
              })}

              <Pressable
                onPress={addBlankPause}
                style={({ pressed }) => [s.addPauseBtn, pressed && { opacity: 0.85 }]}
              >
                <Text style={s.addPauseBtnText}>+ ADD A PAUSE / PUNCH</Text>
              </Pressable>

              {isDone && (
                <View style={s.field}>
                  <Text style={s.label}>COMPLETED AT</Text>
                  <DateTimeField value={finishedAt} onChange={setFinishedAt} />
                </View>
              )}

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
        </ScrollView>

        <View style={s.foot}>
          <Pressable onPress={onClose} style={s.cancel}>
            <Text style={s.cancelText}>Cancel</Text>
          </Pressable>
          <Pressable
            onPress={() => save.mutate()}
            disabled={save.isPending || timing.isLoading || timing.isError}
            style={({ pressed }) => [
              s.submit,
              (save.isPending || timing.isLoading || timing.isError) && s.submitDisabled,
              pressed && !save.isPending && !timing.isLoading && !timing.isError && { opacity: 0.85 },
            ]}
          >
            <Text style={[s.submitText, (save.isPending || timing.isLoading || timing.isError) && { color: c.textFaint }]}>
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
  statusBadge: { ...t.micro, color: c.textFaint, fontSize: 9, marginTop: 2 },
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

  addPauseBtn: {
    paddingVertical: sp.sm,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.accent,
    borderStyle: 'dashed' as any,
    alignItems: 'center',
    backgroundColor: c.bg,
  },
  addPauseBtnText: { ...t.duration, color: c.accent },

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
